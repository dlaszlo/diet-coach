#!/usr/bin/env python3
"""Health / weight-loss diary CLI.

Uses only the Python 3 standard library. The diary files stay human-readable
markdown; this script only speeds up data entry and computes trends / ideas.

Commands:
    weight <kg> [--date YYYY-MM-DD]
    day  [--date YYYY-MM-DD]                   create the daily template
    meal "<desc>" <kcal> [--time HH:MM] [--protein] [--date ...]
    exercise <activity> <km> <minutes> [--met M] [--date ...]
    report [--date YYYY-MM-DD]                 weekly summary

The fixed structure baked into this script (section headers, output strings,
day names, CSV columns) is English. Only free-form content the user enters
(meal descriptions, coach notes, the config checklist items) is in the user's
own language.
"""
from __future__ import annotations

import argparse
import csv
import datetime as dt
import json
import os
import re
import sys
from pathlib import Path

# Open Food Facts lives in a sibling module. Resolve THIS file's real directory
# (./t is a symlink, so __file__ may be the symlink) so the import works no
# matter how track.py was invoked.
sys.path.insert(0, str(Path(__file__).resolve().parent))
import off  # noqa: E402

# This script is bundled inside the diet-coach skill, so it must NOT locate the
# data relative to its own file. The user's data lives in their project: the
# directory given by $HEALTH_TRACKER_DIR, or the current working directory
# (where ./t is run from — the SessionStart hook cd's to the project root).
PROJECT = Path(os.environ.get("HEALTH_TRACKER_DIR") or Path.cwd()).resolve()
DATA = PROJECT / "data"
DIARY = DATA / "diary"
REPORTS = DATA / "reports"
WEIGHT_CSV = DATA / "weight.csv"
KCAL_REF = DATA / "kcal_reference.md"
PREFS = DATA / "preferences.md"
PLANS = DATA / "plans"
SHOPPING = DATA / "shopping"

# The concrete personal values live in the (gitignored) data/config.json; the
# code only carries generic, impersonal defaults so a fresh clone still runs.
CONFIG_PATH = DATA / "config.json"
PROFILE = DATA / "profile.md"

_CONFIG_DEFAULTS = {
    "kcal_min": 1800,
    "kcal_max": 2200,
    "default_weight_kg": 70.0,
    "water_target_label": "2–3 l",
    "water_min_l": 2.0,
    "checklist": [
        "Protein at every main meal",
        "1–2 snacks",
        "Fluids to the daily target",
        "Got some movement",
        "Went to bed on time",
    ],
}


def load_config() -> dict:
    cfg = dict(_CONFIG_DEFAULTS)
    if CONFIG_PATH.exists():
        try:
            cfg.update(json.loads(CONFIG_PATH.read_text(encoding="utf-8")))
        except (json.JSONDecodeError, OSError):
            pass
    return cfg


CFG = load_config()
KCAL_MIN = CFG["kcal_min"]
KCAL_MAX = CFG["kcal_max"]
DEFAULT_WEIGHT = CFG["default_weight_kg"]
WATER_TARGET_LABEL = CFG["water_target_label"]
WATER_MIN = CFG["water_min_l"]
CHECKLIST = CFG["checklist"]

DAYS = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #
def today(args) -> str:
    return getattr(args, "date", None) or dt.date.today().isoformat()


def parse_date(s: str) -> dt.date:
    return dt.date.fromisoformat(s)


def diary_path(date: str) -> Path:
    return DIARY / f"{date}.md"


def latest_weight(on_or_before: str | None = None) -> float:
    """Most recent measured weight (up to the given date, if provided)."""
    if not WEIGHT_CSV.exists():
        return DEFAULT_WEIGHT
    rows = sorted(read_weights().items())
    if on_or_before:
        rows = [(d, kg) for d, kg in rows if d <= on_or_before]
    return rows[-1][1] if rows else DEFAULT_WEIGHT


def read_weights() -> dict[str, float]:
    out: dict[str, float] = {}
    if not WEIGHT_CSV.exists():
        return out
    with WEIGHT_CSV.open(newline="") as f:
        for row in csv.DictReader(f):
            try:
                out[row["date"]] = float(row["kg"])
            except (KeyError, ValueError):
                continue
    return out


def cells(line: str) -> list[str]:
    return [c.strip() for c in line.strip().strip("|").split("|")]


def is_separator(line: str) -> bool:
    return bool(re.fullmatch(r"\|[\s\-:|]+\|", line.strip()))


def first_number(text: str) -> float | None:
    m = re.search(r"-?\d+(?:[.,]\d+)?", text)
    return float(m.group().replace(",", ".")) if m else None


# --------------------------------------------------------------------------- #
# Daily markdown handling
# --------------------------------------------------------------------------- #
TEMPLATE = """# {date} ({day_name})

## Weight
{weight}

## Meals
| time | meal | est. kcal | protein? |
|------|------|----------:|:--------:|
**Estimated intake: ~0 kcal**

## Exercise
| type | dist (km) | time (min) | est. kcal |
|------|----------:|-----------:|----------:|

## Fluids
**So far: 0 l** / target {water_label}

## Sleep
(not recorded yet)

## Checklist
{checklist}

## Coach notes
"""


def ensure_day(date: str) -> Path:
    p = diary_path(date)
    if not p.exists():
        DIARY.mkdir(parents=True, exist_ok=True)
        day_name = DAYS[parse_date(date).weekday()]
        weight = read_weights().get(date)
        p.write_text(
            TEMPLATE.format(
                date=date, day_name=day_name,
                weight=f"{weight:.1f} kg" if weight is not None else "(no measurement)",
                water_label=WATER_TARGET_LABEL,
                checklist="\n".join(f"- [ ] {x}" for x in CHECKLIST),
            ),
            encoding="utf-8",
        )
    return p


def section_span(lines: list[str], heading: str) -> tuple[int, int, int]:
    """Locate a '## heading' section. Returns (header_idx, body_start, body_end),
    where the body is lines[body_start:body_end]. If the heading is absent,
    header_idx is -1 and an empty range at EOF is returned, so callers degrade
    gracefully (reads see nothing) instead of crashing on a malformed file."""
    hi = find_heading(lines, heading)
    if hi == -1:
        return -1, len(lines), len(lines)
    end = hi + 1
    while end < len(lines) and not lines[end].startswith("## "):
        end += 1
    return hi, hi + 1, end


def section_bounds(lines: list[str], header: str) -> tuple[int, int]:
    """The [start, end) body range of the given '## header' section."""
    _, start, end = section_span(lines, header)
    return start, end


def table_data_rows(lines: list[str], start: int, end: int) -> list[int]:
    """Indices of the table data rows (without header and separator)."""
    rows = [i for i in range(start, end)
            if lines[i].strip().startswith("|") and not is_separator(lines[i])]
    return rows[1:] if rows else []          # the first one is the header


def add_meal(date: str, desc: str, kcal: int, time: str, protein: bool) -> None:
    p = ensure_day(date)
    lines = p.read_text(encoding="utf-8").splitlines()
    start, end = section_bounds(lines, "## Meals")
    data = table_data_rows(lines, start, end)
    mark = "✓" if protein else "-"
    row = f"| {time} | {desc} | {kcal} | {mark} |"
    insert = (data[-1] + 1) if data else _after_separator(lines, start, end)
    lines.insert(insert, row)
    _rewrite_intake_total(lines)              # refresh the total
    p.write_text("\n".join(lines) + "\n", encoding="utf-8")


def add_exercise(date: str, activity: str, km: float, minutes: int, kcal: int) -> None:
    p = ensure_day(date)
    lines = p.read_text(encoding="utf-8").splitlines()
    start, end = section_bounds(lines, "## Exercise")
    data = table_data_rows(lines, start, end)
    row = f"| {activity} | {km:g} | {minutes} | ~{kcal} |"
    insert = (data[-1] + 1) if data else _after_separator(lines, start, end)
    lines.insert(insert, row)
    p.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _after_separator(lines: list[str], start: int, end: int) -> int:
    for i in range(start, end):
        if is_separator(lines[i]):
            return i + 1
    return end


def _sum_meal_kcal(lines: list[str]) -> int:
    """Total estimated kcal from the '## Meals' table (the est. kcal column)."""
    start, end = section_bounds(lines, "## Meals")
    total = 0
    for i in table_data_rows(lines, start, end):
        c = cells(lines[i])
        if len(c) >= 3 and (n := first_number(c[2])) is not None:
            total += int(n)
    return total


def _rewrite_intake_total(lines: list[str]) -> None:
    start, end = section_bounds(lines, "## Meals")
    new = f"**Estimated intake: ~{_sum_meal_kcal(lines)} kcal**"
    for i in range(start, end):
        if lines[i].startswith("**Estimated intake"):
            lines[i] = new
            return
    lines.insert(end, new)


def intake_total(date: str) -> int | None:
    p = diary_path(date)
    if not p.exists():
        return None
    return _sum_meal_kcal(p.read_text(encoding="utf-8").splitlines())


CHECKBOX_RE = re.compile(r"- \[[ xX]\]")
CHECKED_RE = re.compile(r"- \[[xX]\]")


def checklist_item_indices(lines: list[str]) -> list[int]:
    """Line indices of the checkbox items inside the '## Checklist' section only
    (so coach notes or stray checkboxes elsewhere are never miscounted)."""
    _, start, end = section_span(lines, "## Checklist")
    return [i for i in range(start, end) if CHECKBOX_RE.match(lines[i].strip())]


def checklist_status(date: str) -> tuple[int, int]:
    p = diary_path(date)
    if not p.exists():
        return 0, 0
    lines = p.read_text(encoding="utf-8").splitlines()
    items = checklist_item_indices(lines)
    done = sum(1 for i in items if CHECKED_RE.match(lines[i].strip()))
    return done, len(items)


def exercise_total(date: str) -> int:
    p = diary_path(date)
    if not p.exists():
        return 0
    lines = p.read_text(encoding="utf-8").splitlines()
    start, end = section_bounds(lines, "## Exercise")
    total = 0
    for i in table_data_rows(lines, start, end):
        c = cells(lines[i])
        if c and (n := first_number(c[-1])) is not None:
            total += int(n)
    return total


# --------------------------------------------------------------------------- #
# Fluids / sleep / note / daily status
# --------------------------------------------------------------------------- #
def find_heading(lines: list[str], heading: str) -> int:
    for i, l in enumerate(lines):
        if l.strip() == heading:
            return i
    return -1


def _item_text(line: str) -> str:
    return line.split("]", 1)[-1].strip()


def resolve_check(lines: list[str], target: str):
    """Locate a checklist item by 1-based index or substring (case-insensitive).
    Returns one of:
      ("ok", line_index)
      ("none", None)
      ("ambiguous", [(1based_index, text), ...])  # >1 substring match
    Index is positional, so it can shift if the config checklist changes — prefer
    a substring; the index is a disambiguation fallback."""
    items = checklist_item_indices(lines)
    if target.isdigit():
        n = int(target)
        return ("ok", items[n - 1]) if 1 <= n <= len(items) else ("none", None)
    matches = [i for i in items if target.lower() in lines[i].lower()]
    if not matches:
        return ("none", None)
    if len(matches) > 1:
        return ("ambiguous", [(items.index(i) + 1, _item_text(lines[i])) for i in matches])
    return ("ok", matches[0])


def apply_check(lines: list[str], idx: int, checked: bool) -> str:
    if checked:
        lines[idx] = lines[idx].replace("[ ]", "[x]", 1)
    else:
        lines[idx] = re.sub(r"\[[xX]\]", "[ ]", lines[idx], count=1)
    return _item_text(lines[idx])


def set_section_body(lines: list[str], heading: str, body: list[str]) -> None:
    """Replace the section body; create it at the end if missing."""
    hi, start, end = section_span(lines, heading)
    if hi == -1:
        if lines and lines[-1].strip():
            lines.append("")
        lines += [heading] + body + [""]
        return
    lines[start:end] = body + [""]


def _read_water(lines: list[str]) -> float:
    _, start, end = section_span(lines, "## Fluids")
    for i in range(start, end):
        m = re.search(r"So far:\s*([\d.,]+)", lines[i])
        if m:
            return float(m.group(1).replace(",", "."))
    return 0.0


def add_water(date: str, liters: float) -> float:
    p = ensure_day(date)
    lines = p.read_text(encoding="utf-8").splitlines()
    total = round(_read_water(lines) + liters, 2)
    set_section_body(lines, "## Fluids", [f"**So far: {total:g} l** / target {WATER_TARGET_LABEL}"])
    p.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return total


def water_total(date: str) -> float:
    p = diary_path(date)
    return _read_water(p.read_text(encoding="utf-8").splitlines()) if p.exists() else 0.0


def add_sleep(date: str, hours: float, bed: str | None, wake: str | None, remark: str) -> None:
    p = ensure_day(date)
    lines = p.read_text(encoding="utf-8").splitlines()
    body = f"Last night: {hours:g} h"
    if bed and wake:
        body += f" ({bed}–{wake})"
    if remark:
        body += f" — {remark}"
    set_section_body(lines, "## Sleep", [body])
    p.write_text("\n".join(lines) + "\n", encoding="utf-8")


def add_note(date: str, text: str, by: str) -> None:
    ensure_day(date)
    ts = dt.datetime.now().strftime("%H:%M")
    append_to_section(diary_path(date), "## Coach notes",
                      [f"[{ts}, {by}] {text}"])


def status_today(date: str) -> str:
    kc = intake_total(date) or 0
    band = ("⬇️ below band" if kc < KCAL_MIN
            else "⬆️ above band" if kc > KCAL_MAX else "✅ in band")
    water = water_total(date)
    done, tot = checklist_status(date)
    out = [f"# Status — {date}",
           f"- Intake: ~{kc} kcal ({band}, target {KCAL_MIN}–{KCAL_MAX})",
           f"- Exercise: ~{exercise_total(date)} kcal",
           f"- Fluids: {water:g} l / target {WATER_TARGET_LABEL}{'  ✅' if water >= WATER_MIN else ''}",
           f"- Checklist: {done}/{tot}"]
    p = diary_path(date)
    if p.exists():
        lines = p.read_text(encoding="utf-8").splitlines()
        _, start, end = section_span(lines, "## Coach notes")
        notes = [lines[i].strip() for i in range(start, end)
                 if lines[i].strip().startswith("-")]
        if notes:
            out.append("- Notes:")
            out += [f"    {n}" for n in notes]
    return "\n".join(out) + "\n"


def status_line(date: str) -> str:
    """Compact one-line status for the Claude Code statusline."""
    kc = intake_total(date) or 0
    pct = round(kc / KCAL_MIN * 100) if KCAL_MIN else 0
    band = "✅" if KCAL_MIN <= kc <= KCAL_MAX else ("⬇️" if kc < KCAL_MIN else "⬆️")
    water = water_total(date)
    water_mark = "✅" if water >= WATER_MIN else ""
    done, tot = checklist_status(date)
    w = latest_weight(date)
    return (f"🍽 {kc}/{KCAL_MIN} ({pct}%){band}  "
            f"💧 {water:g}l{water_mark}  ☑ {done}/{tot}  ⚖ {w:g}kg")


# --------------------------------------------------------------------------- #
# Exercise → kcal estimate (body-weight based, NET, rough)
# --------------------------------------------------------------------------- #
def met_value(activity: str, speed_kmh: float) -> float:
    t = activity.lower()
    if t in ("seta", "séta", "walk", "gyaloglas", "gyaloglás"):
        for limit, met in [(3.2, 2.0), (4.0, 2.8), (4.8, 3.0),
                            (5.5, 3.5), (6.4, 4.3)]:
            if speed_kmh < limit:
                return met
        return 5.0
    if t in ("futas", "futás", "run", "kocogas", "kocogás"):
        return max(6.0, speed_kmh)                       # ~6–12 MET
    if t in ("kerekpar", "kerékpár", "bringa", "bike"):
        for limit, met in [(16, 6.0), (19, 8.0), (22, 10.0)]:
            if speed_kmh < limit:
                return met
        return 12.0
    return 3.5                                           # unknown: moderate


def estimate_kcal(activity: str, km: float, minutes: int, met_override: float | None) -> int:
    hours = minutes / 60.0
    speed = km / hours if hours else 0.0
    met = met_override if met_override else met_value(activity, speed)
    weight = latest_weight()
    # NET burn: subtract resting metabolism (1 MET) -> more realistic "extra"
    kcal = max(0.0, (met - 1.0)) * weight * hours
    return round(kcal)


# --------------------------------------------------------------------------- #
# Weekly report
# --------------------------------------------------------------------------- #
def moving_average(series: list[tuple[str, float]], window: int = 7) -> list[tuple[str, float]]:
    out = []
    for i in range(len(series)):
        lo = max(0, i - window + 1)
        chunk = [kg for _, kg in series[lo:i + 1]]
        out.append((series[i][0], sum(chunk) / len(chunk)))
    return out


def report(date: str) -> str:
    d = parse_date(date)
    monday = d - dt.timedelta(days=d.weekday())
    week_days = [monday + dt.timedelta(days=i) for i in range(7)]
    iso_year, iso_week, _ = monday.isocalendar()

    lines = [f"# Weekly summary — {iso_year}-W{iso_week:02d}",
             f"_{week_days[0].isoformat()} … {week_days[-1].isoformat()}_", ""]

    # --- Weight trend (7-day moving average) ---
    weights = sorted(read_weights().items())
    lines.append("## Weight")
    if weights:
        ma = dict(moving_average(weights))
        latest_d, latest_kg = weights[-1]
        lines.append(f"- Latest measurement: **{latest_kg:.1f} kg** ({latest_d})")
        lines.append(f"- 7-day moving average: **{ma[latest_d]:.1f} kg**")
        # change from start vs end of week (on the moving average)
        wk = [(dd, ma[dd]) for dd, _ in weights
              if week_days[0].isoformat() <= dd <= week_days[-1].isoformat()]
        if len(wk) >= 2:
            delta = wk[-1][1] - wk[0][1]
            arrow = "📉" if delta < 0 else ("📈" if delta > 0 else "➡️")
            lines.append(f"- Weekly trend (moving avg): {arrow} **{delta:+.1f} kg**")
        # total from baseline
        lines.append(f"- From baseline (oldest measurement): "
                     f"**{latest_kg - weights[0][1]:+.1f} kg**")
    else:
        lines.append("- (no data)")
    lines.append("")

    # --- Intake + checklist + exercise per day ---
    lines.append("## Days")
    lines.append("| day | intake | band | exercise | checklist |")
    lines.append("|-----|-------:|------|---------:|-----------|")
    intakes = []
    for wd in week_days:
        ds = wd.isoformat()
        kc = intake_total(ds)
        mv = exercise_total(ds)
        done, tot = checklist_status(ds)
        if kc is None:
            lines.append(f"| {ds} | – | – | – | – |")
            continue
        intakes.append(kc)
        if kc < KCAL_MIN:
            band = "⬇️ below"
        elif kc > KCAL_MAX:
            band = "⬆️ above"
        else:
            band = "✅ in band"
        lines.append(f"| {ds} | {kc} | {band} | {mv} | {done}/{tot} |")
    lines.append("")

    # --- Summary ---
    lines.append("## Summary")
    if intakes:
        avg = sum(intakes) / len(intakes)
        lines.append(f"- Logged days: **{len(intakes)}/7**")
        lines.append(f"- Average daily intake: **~{avg:.0f} kcal** "
                     f"(target {KCAL_MIN}–{KCAL_MAX})")
        under = sum(1 for k in intakes if k < KCAL_MIN)
        if under:
            lines.append(f"- ⚠️ Below the band on {under} day(s) — don't starve.")
    else:
        lines.append("- (no logged day)")
    lines.append("")
    lines.append("> Reminder: daily fluctuation is noise — the weekly moving-average trend matters.")
    return "\n".join(lines) + "\n"


# --------------------------------------------------------------------------- #
# Weight entry
# --------------------------------------------------------------------------- #
def add_weight(date: str, kg: float) -> None:
    data = read_weights()
    data[date] = kg
    WEIGHT_CSV.parent.mkdir(parents=True, exist_ok=True)
    with WEIGHT_CSV.open("w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["date", "kg"])
        for d in sorted(data):
            w.writerow([d, f"{data[d]:g}"])
    # if the daily file exists, refresh the weight line in it too
    p = diary_path(date)
    if p.exists():
        lines = p.read_text(encoding="utf-8").splitlines()
        s, e = section_bounds(lines, "## Weight")
        if s < e:
            lines[s] = f"{kg:.1f} kg"
            p.write_text("\n".join(lines) + "\n", encoding="utf-8")


# --------------------------------------------------------------------------- #
# Meal planning: brief, shopping list, purchase feedback
# --------------------------------------------------------------------------- #
def _append_line(path: Path, line: str) -> None:
    text = path.read_text(encoding="utf-8") if path.exists() else ""
    if text and not text.endswith("\n"):
        text += "\n"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text + line + "\n", encoding="utf-8")


def read_sections(path: Path) -> list[tuple[str, list[str]]]:
    """(## heading, [bullet lines]) pairs from a markdown file."""
    if not path.exists():
        return []
    out: list[tuple[str, list[str]]] = []
    heading = None
    bullets: list[str] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.startswith("## "):
            if heading is not None:
                out.append((heading, bullets))
            heading, bullets = line[3:].strip(), []
        else:
            m = re.match(r"\s*-\s+(.*)", line)
            if m and heading is not None:
                bullets.append(m.group(1).strip())
    if heading is not None:
        out.append((heading, bullets))
    return out


def diary_meals(date: str) -> list[str]:
    p = diary_path(date)
    if not p.exists():
        return []
    lines = p.read_text(encoding="utf-8").splitlines()
    start, end = section_bounds(lines, "## Meals")
    out = []
    for i in table_data_rows(lines, start, end):
        c = cells(lines[i])
        if len(c) >= 2 and c[1]:
            out.append(c[1])
    return out


def recent_meals(start: str, days: int = 10) -> list[tuple[str, list[str]]]:
    """Meals from the days before the start (the most recent 'days' existing days)."""
    d0 = parse_date(start)
    out = []
    for offset in range(1, 21):
        ds = (d0 - dt.timedelta(days=offset)).isoformat()
        meals = diary_meals(ds)
        if meals:
            out.append((ds, meals))
        if len(out) >= days:
            break
    return out


def read_profile() -> str:
    """Contents of the private data/profile.md (personal constraints), if present."""
    if PROFILE.exists():
        return PROFILE.read_text(encoding="utf-8").strip()
    return ""


def build_brief(start: str, days: int) -> str:
    end = (parse_date(start) + dt.timedelta(days=days - 1)).isoformat()
    L = [f"# Planning brief — {days} day(s) from {start} (… {end})", ""]

    L += ["## Rules (REQUIRED)",
          f"- Daily **{KCAL_MIN}–{KCAL_MAX} kcal**, NEVER below it (not starvation).",
          "- Honor the **Profile** section constraints (fat / sensitivity / goal).",
          "- High protein at every main meal; fiber **gradually**.",
          "- **Do not repeat** the same main dish within 3–4 days.",
          "- **Variety is mandatory:** every few days at least 1 NEW / rarely-eaten idea.",
          "- Prefer liked / proven foods (preferences, notes), but not exclusively.", ""]

    prof = read_profile()
    if prof:
        L += ["## Profile (personal constraints — data/profile.md)", prof, ""]

    L.append("## Recent main dishes (avoid quick repeats)")
    rec = recent_meals(start)
    if rec:
        for ds, meals in rec:
            L.append(f"- {ds}: {', '.join(meals)}")
    else:
        L.append("- (no logged day yet)")
    L.append("")

    L.append("## Preferences / sensitivities")
    secs = read_sections(PREFS)
    if secs:
        for h, items in secs:
            if items:
                L.append(f"- **{h}:** {', '.join(items)}")
    else:
        L.append("- (empty)")
    L.append("")

    L.append("## At home now (build on this)")
    L.append("- (at planning time the user says what's at home — ask them)")
    L.append("")

    days_list = ", ".join(
        (parse_date(start) + dt.timedelta(days=i)).isoformat() for i in range(days)
    )
    L += ["## Requested output",
          f"Make a {days}-day plan with the rules above, and save it into "
          "**one file per day**: `data/plans/<day>.md` "
          f"(i.e.: {days_list}).",
          "Per file: Breakfast/Lunch/(Snack)/Dinner/(Snack) + estimated kcal, the "
          f"day's total within {KCAL_MIN}–{KCAL_MAX}, plus that day's ingredients and "
          "recipe. The multi-day shopping is covered by `data/shopping/<start-date>.md`.", ""]
    return "\n".join(L) + "\n"


def append_to_section(path: Path, heading: str, bullets: list[str]) -> None:
    lines = path.read_text(encoding="utf-8").splitlines() if path.exists() else []
    hi, start, end = section_span(lines, heading)
    if hi == -1:
        if lines and lines[-1].strip():
            lines.append("")
        lines += [heading] + [f"- {b}" for b in bullets]
    else:
        ins = end
        while ins > start and not lines[ins - 1].strip():
            ins -= 1
        for b in reversed(bullets):
            lines.insert(ins, f"- {b}")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def process_bought(file: str) -> str:
    path = Path(file)
    if not path.is_absolute():
        path = PROJECT / file
    if not path.exists():
        return f"No such file: {file}\n"
    bought, missing = [], []
    for line in path.read_text(encoding="utf-8").splitlines():
        m = re.match(r"\s*-\s*\[(.)\]\s*(.*)", line)
        if not m:
            continue
        (bought if m.group(1).lower() == "x" else missing).append(m.group(2).strip())

    out = [f"✓ Acquired: {len(bought)} item(s)."]
    if missing:
        out.append("\n⚠️ NOT acquired — adjust the plan to these:")
        out += [f"  - {b}" for b in missing]
        out.append("\n→ Ask the AI: \"adjust the plan to the items not acquired\".")
    return "\n".join(out) + "\n"


# --------------------------------------------------------------------------- #
# Saving Open Food Facts hits into the local kcal_reference.md (offline cache).
# The network/parsing lives in off.py; this only persists a row locally.
# --------------------------------------------------------------------------- #
REF_HIGH_PROTEIN_PER_100G = 8     # mark a product as a good protein source
REF_HIGH_FAT_PER_100G = 17        # ★ = fatty (relevant for the gallbladder rule)
MEAL_PROTEIN_FLAG_G = 10          # a portion above this counts as a protein meal


def save_to_ref(p: dict) -> None:
    kcal = off.energy_100g(p)
    prot = off.protein_100g(p)
    fat = off.fat_100g(p)
    protein_mark = "✓" if prot is not None and prot >= REF_HIGH_PROTEIN_PER_100G else "-"
    star = " ★" if fat is not None and fat >= REF_HIGH_FAT_PER_100G else ""
    kcal_s = f"{kcal:g}" if kcal is not None else "n/a"
    note = f"OFF {p.get('code', '')}".strip()
    if p.get("serving_size"):
        note += f", serving {p['serving_size']}"
    _append_line(KCAL_REF, f"| {off.product_label(p)}{star} | {kcal_s} | {protein_mark} | {note} |")


def ref_has_barcode(code: str) -> bool:
    """True if the product (by barcode) is already in kcal_reference.md."""
    if not code or not KCAL_REF.exists():
        return False
    return f"OFF {code}" in KCAL_REF.read_text(encoding="utf-8")


def resolve_off_meal(barcode: str, grams: float, desc: str, protein: bool):
    """Turn an OFF barcode + portion into (desc, kcal, protein, info_line).
    Raises ValueError with a user-facing message if the product/data is missing;
    network errors propagate to the caller. Caches the product locally."""
    prod = off.off_product(barcode.strip())
    if not prod:
        raise ValueError(f"No hit for this barcode: {barcode}")
    e100 = off.energy_100g(prod)
    if e100 is None:
        raise ValueError("This product has no kcal data in OFF — enter it manually.")
    kcal = round(e100 * grams / 100)
    prot = off.protein_100g(prod)
    if prot is not None and prot * grams / 100 >= MEAL_PROTEIN_FLAG_G:
        protein = True
    desc = f"{desc} ({off.product_label(prod)}, {grams:g} g)"
    if not ref_has_barcode(prod.get("code", "")):
        save_to_ref(prod)            # offline cache if not present yet
    info = f"  OFF: {off.product_label(prod)} — {e100:g} kcal/100g → {grams:g} g = {kcal} kcal"
    return desc, kcal, protein, info


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #
def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description="Health / weight-loss diary")
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("weight", help="record a weight measurement")
    p.add_argument("kg", type=float)
    p.add_argument("--date")

    p = sub.add_parser("day", help="create the daily template")
    p.add_argument("--date")

    p = sub.add_parser("meal", help="add a meal")
    p.add_argument("desc")
    p.add_argument("kcal", type=int, nargs="?", default=None,
                   help="kcal manually (optional if --off + --grams given)")
    p.add_argument("--time", default="--:--")
    p.add_argument("--protein", action="store_true")
    p.add_argument("--off", help="OFF barcode — compute kcal from it using --grams")
    p.add_argument("--grams", type=float, help="portion in grams (for --off)")
    p.add_argument("--date")

    p = sub.add_parser("exercise", help="add exercise")
    p.add_argument("activity")
    p.add_argument("km", type=float)
    p.add_argument("minutes", type=int)
    p.add_argument("--met", type=float, default=None)
    p.add_argument("--date")

    p = sub.add_parser("report", help="weekly summary")
    p.add_argument("--date")

    p = sub.add_parser("plan", help="meal planning")
    p.add_argument("subcommand", choices=["brief"])
    p.add_argument("--days", type=int, default=7)
    p.add_argument("--date")

    p = sub.add_parser("bought", help="purchase feedback from the shopping list")
    p.add_argument("file")

    p = sub.add_parser("search", help="nutrition lookup from Open Food Facts")
    p.add_argument("query", help="barcode or product name")
    p.add_argument("--grams", type=float, default=None,
                   help="preview of kcal computed for the given grams")
    p.add_argument("--save", action="store_true",
                   help="save the hit into kcal_reference.md (barcode lookup)")
    p.add_argument("--n", type=int, default=5, help="how many name-search hits")

    p = sub.add_parser("water", help="add fluids to the daily total")
    p.add_argument("amount", type=float, help="liters (or dl with --dl)")
    p.add_argument("--dl", action="store_true", help="amount is in dl")
    p.add_argument("--date")

    p = sub.add_parser("sleep", help="record last night's sleep")
    p.add_argument("hours", type=float, help="sleep in hours (e.g. 7.5)")
    p.add_argument("--bed", help="bedtime HH:MM")
    p.add_argument("--wake", help="wake time HH:MM")
    p.add_argument("--remark", default="")
    p.add_argument("--date")

    p = sub.add_parser("note", help="note for the day (coach status)")
    p.add_argument("text")
    p.add_argument("--by", default="me", help="who wrote it (e.g. me / Claude)")
    p.add_argument("--date")

    p = sub.add_parser("check", help="tick a checklist item (by index or text)")
    p.add_argument("item", help="1-based index, or a substring of the item")
    p.add_argument("--date")

    p = sub.add_parser("uncheck", help="untick a checklist item (by index or text)")
    p.add_argument("item", help="1-based index, or a substring of the item")
    p.add_argument("--date")

    p = sub.add_parser("today", help="daily status summary")
    p.add_argument("--date")

    p = sub.add_parser("statusline", help="compact one-line status (Claude Code statusline)")
    p.add_argument("--date")

    args = ap.parse_args(argv)

    if args.cmd == "weight":
        d = today(args)
        add_weight(d, args.kg)
        print(f"✓ Weight recorded: {args.kg:g} kg ({d})")

    elif args.cmd == "day":
        d = today(args)
        p = ensure_day(d)
        print(f"✓ Daily file: {p}")

    elif args.cmd == "meal":
        d = today(args)
        desc, kcal, protein = args.desc, args.kcal, args.protein
        if args.off:
            if args.grams is None:
                print("⚠️ With --off, provide the portion: --grams N")
                return 2
            try:
                desc, kcal, protein, info = resolve_off_meal(
                    args.off, args.grams, desc, protein)
            except ValueError as e:
                print(f"⚠️ {e}")
                return 1
            except Exception as e:
                print(f"⚠️ Open Food Facts request failed: {e}\n"
                      "(Needs network; enter the kcal manually.)")
                return 1
            print(info)
        elif kcal is None:
            print("⚠️ Provide the kcal, or use: --off <barcode> --grams N")
            return 2
        add_meal(d, desc, kcal, args.time, protein)
        tot = intake_total(d)
        band = ("⬇️ below band" if tot < KCAL_MIN
                else "⬆️ above band" if tot > KCAL_MAX else "✅ in band")
        print(f"✓ Meal added ({d}). Daily total: ~{tot} kcal — {band}")

    elif args.cmd == "exercise":
        d = today(args)
        kcal = estimate_kcal(args.activity, args.km, args.minutes, args.met)
        add_exercise(d, args.activity, args.km, args.minutes, kcal)
        w = latest_weight()
        print(f"✓ Exercise added ({d}): {args.activity} {args.km:g} km / "
              f"{args.minutes} min → ~{kcal} kcal (body weight {w:g} kg)")

    elif args.cmd == "report":
        d = today(args)
        text = report(d)
        REPORTS.mkdir(parents=True, exist_ok=True)
        mon = parse_date(d) - dt.timedelta(days=parse_date(d).weekday())
        y, w, _ = mon.isocalendar()
        out = REPORTS / f"{y}-W{w:02d}.md"
        out.write_text(text, encoding="utf-8")
        print(text)
        print(f"(saved: {out})")

    elif args.cmd == "plan" and args.subcommand == "brief":
        start = today(args)
        text = build_brief(start, args.days)
        PLANS.mkdir(parents=True, exist_ok=True)
        out = PLANS / f"brief_{start}.md"
        out.write_text(text, encoding="utf-8")
        print(text)
        print(f"(saved: {out})")
        print("→ Now ask the AI (Claude Code): \"plan based on the brief\".")

    elif args.cmd == "bought":
        print(process_bought(args.file))

    elif args.cmd == "search":
        q = args.query.strip()
        try:
            if q.isdigit():
                p = off.off_product(q)
                if not p:
                    print(f"No hit for this barcode: {q}")
                else:
                    print(off.fmt_product(p))
                    if args.grams:
                        line = off.fmt_portion(p, args.grams)
                        if line:
                            print(line)
                    if args.save:
                        save_to_ref(p)
                        print(f"\n✓ Saved to {KCAL_REF.name}.")
            else:
                res = off.off_search(q, args.n)
                if not res:
                    print(f"No hits: {q}")
                else:
                    for i, p in enumerate(res, 1):
                        print(f"[{i}] " + off.fmt_product(p).replace("\n", "\n    "))
                        if args.grams:
                            line = off.fmt_portion(p, args.grams)
                            if line:
                                print("  " + line.strip())
                    print("\nTo save, use the chosen product's barcode: "
                          "./t search <barcode> --save")
        except Exception as e:
            print(f"⚠️ Open Food Facts request failed: {e}\n"
                  "(Needs network; offline only the local kcal_reference.md is available.)")
            return 1

    elif args.cmd == "water":
        d = today(args)
        liters = args.amount / 10 if args.dl else args.amount
        total = add_water(d, liters)
        mark = "  ✅ target reached" if total >= WATER_MIN else ""
        print(f"✓ Fluids +{liters:g} l → today total {total:g} l / target {WATER_TARGET_LABEL}{mark}")

    elif args.cmd == "sleep":
        d = today(args)
        add_sleep(d, args.hours, args.bed, args.wake, args.remark)
        print(f"✓ Sleep recorded ({d}): {args.hours:g} h")

    elif args.cmd == "note":
        d = today(args)
        add_note(d, args.text, args.by)
        print(f"✓ Note added ({d}).")

    elif args.cmd in ("check", "uncheck"):
        d = today(args)
        p = ensure_day(d)
        lines = p.read_text(encoding="utf-8").splitlines()
        kind, data = resolve_check(lines, args.item)
        if kind == "none":
            print(f"⚠️ No checklist item matched: {args.item!r}")
            return 1
        if kind == "ambiguous":
            print(f"⚠️ {len(data)} checklist items match {args.item!r} — "
                  "be more specific, or use the index:")
            for n, text in data:
                print(f"  {n}. {text}")
            return 1
        matched = apply_check(lines, data, checked=args.cmd == "check")
        p.write_text("\n".join(lines) + "\n", encoding="utf-8")
        done, tot = checklist_status(d)
        mark = "☑" if args.cmd == "check" else "☐"
        print(f"✓ {mark} {matched}  ({done}/{tot})")

    elif args.cmd == "today":
        print(status_today(today(args)))

    elif args.cmd == "statusline":
        print(status_line(today(args)))

    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
