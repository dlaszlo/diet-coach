# Health / weight-loss diary + meal planner

A long-term, hand-kept, **plain text** diary. No dependency on external apps,
versionable with git. The scripts only help (faster entry, trends, planning
brief); the creative planning is done by **Claude** following the behavior layer
of the `diet-coach` skill.

> ⚠️ This is a supplement, **not a replacement for a doctor**.

## Public solution vs private data (IMPORTANT)

The repo has two sharply separated layers:

- **Committable solution (abstract, ZERO personal data):** the **self-contained
  `diet-coach` skill** (`.claude/skills/diet-coach/` — `SKILL.md` + bundled
  `scripts/` + `data.example/` templates), plus this repo-root `README.md`, the
  thin root `CLAUDE.md` (auto-load entry) and `IDEAS.md`. Safe to commit. (Per
  the skill-authoring guidelines the human README lives **outside** the skill
  folder.)
- **Private personal data (the whole `data/` is gitignored, never committed):**
  config, profile, preferences, kcal reference, weight, diary, plans, shopping,
  reports.

The concrete values (body data, calorie band, sensitivities, daily checklist)
live in `data/profile.md` (human-readable) and `data/config.json` (machine); the
code and the skill only **reference** them.

> Note: the **fixed structure** (section headers, CLI output, day names,
> file/folder names, code) is English. Only **free-form content you enter** —
> meal descriptions, coach notes, and the config checklist items — stays in your
> own language. So a diary file is mixed: English headers, your-language content.

## First run (setup)

Run from your project root (the dir that will hold `data/`):

```bash
SKILL=.claude/skills/diet-coach
chmod +x "$SKILL/scripts/track.py"
ln -s "$SKILL/scripts/track.py" t   # ./t ... wrapper

mkdir -p data
cp "$SKILL"/data.example/config.json        data/config.json      # band, default weight, checklist, language
cp "$SKILL"/data.example/profile.md         data/profile.md       # fill in with your own data
cp "$SKILL"/data.example/preferences.md     data/preferences.md
cp "$SKILL"/data.example/kcal_reference.md  data/kcal_reference.md
```

The script finds the data in `<cwd>/data/` (or `$HEALTH_TRACKER_DIR/data/`), so
run `./t` from the project root. The `diary/`, `plans/`, `shopping/`, `reports/`
folders under `data/` are created automatically on first use. In Claude Code the
root `CLAUDE.md` activates the `diet-coach` skill at the start of every session.

## Claude Code integration (hook + statusline)

`.claude/settings.json` enables two things (portable, via `$CLAUDE_PROJECT_DIR`):

- **SessionStart hook** — at every session start it runs `./t day` (create
  today's diary file if missing) + `./t today`, and **injects the output into
  context**. So the AI immediately knows **today's date** and the status
  (intake/band, water, checklist, notes) — with no manual entry.
- **Statusline** — the compact one-line status from `./t statusline` at the
  bottom of the prompt: `🍽 1400/1800 (78%)⬇️  💧 1.4l  ☑ 0/6  ⚖ 152.3kg`.

Both take effect from the next session start.

## Folders

```
.claude/skills/diet-coach/     # the self-contained, portable skill (committed)
  SKILL.md                     # the abstract instruction layer
  scripts/track.py             # CLI tool (generic; reads from <cwd>/data)
  scripts/off.py               # Open Food Facts lookup (network; imported by track.py)
  scripts/test_track.py        # characterization tests (python3 scripts/test_track.py)
  data.example/                # committed templates (no personal data)
    config.json  profile.md  preferences.md  kcal_reference.md
README.md                      # this file (human docs — outside the skill folder)
CLAUDE.md                      # thin auto-load entry → activates the skill
IDEAS.md                       # development ideas
t                              # symlink → the skill's scripts/track.py
data/                          # PRIVATE — the whole folder is gitignored
  config.json                  # machine config (band, default weight, water target, checklist, language)
  profile.md                   # personal health context, constraints
  preferences.md               # likes / dislikes / sensitivities
  kcal_reference.md            # kcal estimates + products saved from OFF
  weight.csv                   # time series (the single source of weight)
  diary/YYYY-MM-DD.md          # daily entry (meals, exercise, checklist, notes)
  plans/YYYY-MM-DD.md          # daily meal plan (one day = one file)
  shopping/YYYY-MM-DD.md       # shopping lists (the missing items)
  reports/                     # generated weekly summaries
```

## Daily routine (short)

| when       | command                                              | what it does |
|------------|------------------------------------------------------|--------------|
| morning    | `./t weight 80.0`                                    | weight into the CSV (today's date) |
| (once)     | `./t day`                                            | create today's diary file from the template (with config checklist) |
| at a meal  | `./t meal "chicken + rice (450 g)" 550 --time 12:30 --protein` | row into the daily meal table, total refreshed |
| after exercise | `./t exercise walk 4.5 75`                       | kcal estimated from body weight, written |
| evening    | `./t check "<item>"` (or by index) to tick the checklist; `./t uncheck …` to undo | — |
| weekly     | `./t report`                                         | weekly summary under data/reports/ |

### Water, sleep, status, notes

| command | what it does |
|---------|--------------|
| `./t water 0.5` (or `./t water 5 --dl`) | add fluids to the daily total |
| `./t sleep 7.5 --bed 23:00 --wake 06:30` | record last night's sleep |
| `./t note "..."` | note for the day (coach status); `--by Claude` if the AI writes it |
| `./t today` | quick daily status: intake/band, exercise, water, checklist, notes |

**Continuity:** the day's memory is the file `data/diary/<day>.md`. At the start
of a new conversation `./t today` (or the file) shows where you left off.

## Meal planning (AI + script)

The creative planning is done by **Claude** (see the `diet-coach` skill); the
script prepares the context. The rules (band, sensitivity constraint, high
protein, variety, no repeats) live in the skill and in `data/profile.md`.

| step | command / task | what it does |
|------|----------------|--------------|
| 1. request a plan | `./t plan brief --days 7` then ask Claude | brief (history + profile + preferences) → Claude writes **one file per day**: `data/plans/<day>.md` |
| 2. shopping | Claude asks what's at home, writes the missing items into `data/shopping/<start-date>.md` | — |
| 3. after shopping | tick the items, then `./t bought data/shopping/<date>.md` | reports what could **not** be acquired |
| 4. adjust | ask Claude: "adjust the plan to the items not acquired" | the plan adapts to what was bought |

### Nutrition lookup (Open Food Facts)

An optional helper for more accurate estimates (needs network):

- `./t search "product name"` — searches by name, shows the top hits' nutrition (per 100 g).
- `./t search <barcode> --save` — fetches one product and **writes it into
  `data/kcal_reference.md`**, so it's available offline from then on.
- `./t search <barcode|name> --grams 140` — preview of the kcal (and protein)
  computed for the given portion, not just the per-100 g value.

**Logging from OFF, with a portion (exact kcal, no manual math):**

- `./t meal "<product>" --off <barcode> --grams 140` — fetches the OFF per-100 g
  value, **computes the portion kcal**, sets the protein flag from the OFF
  protein value (≥10 g per portion), **caches** the product into the reference
  (if not present yet), and logs it. The `kcal` positional argument can be
  omitted in this case.

> OFF is accurate for **packaged, barcoded** products. For raw/generic/home-made
> food (an apple, home-made oatmeal, stew) stick to a manual estimate or the
> local `data/kcal_reference.md`.

## Philosophy

- A **rough (±20–30%) kcal estimate is enough** — the **trend and the habit** matter.
- For weight, the **weekly direction** is what counts, not daily fluctuation (the
  report shows a 7-day moving average).
- For richer meal ideas and plans, talk to Claude; keep your preferences in
  `data/preferences.md` and your constant context in `data/profile.md` up to date.
