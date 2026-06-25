#!/usr/bin/env python3
"""Characterization tests for track.py.

Pins the CURRENT behaviour before refactoring, so a refactor that changes
behaviour fails loudly. Stdlib only (unittest). Runs against an isolated
throwaway data dir via $HEALTH_TRACKER_DIR, so it never touches real data.

Run:  python3 scripts/test_track.py
"""
from __future__ import annotations

import contextlib
import io
import os
import tempfile
import unittest
from pathlib import Path

# Isolated data dir BEFORE importing track (it reads paths/config at import).
_TMP = tempfile.mkdtemp(prefix="track-test-")
os.environ["HEALTH_TRACKER_DIR"] = _TMP
import sys
sys.path.insert(0, str(Path(__file__).resolve().parent))
import track  # noqa: E402
import off  # noqa: E402


def run(*argv: str) -> str:
    """Invoke the CLI, return captured stdout."""
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        track.main(list(argv))
    return buf.getvalue()


class MealIntake(unittest.TestCase):
    D = "2030-01-01"

    def test_intake_sums_and_band(self):
        run("meal", "eggs", "400", "--date", self.D, "--protein")
        run("meal", "rice", "300", "--date", self.D)
        self.assertEqual(track.intake_total(self.D), 700)

    def test_band_classification(self):
        d = "2030-01-02"
        out = run("meal", "big", "2500", "--date", d)
        self.assertIn("above band", out)            # > KCAL_MAX
        self.assertLess(track.KCAL_MAX, 2500)


class WaterSleepWeight(unittest.TestCase):
    def test_water_accumulates(self):
        d = "2030-02-01"
        run("water", "1", "--date", d)
        run("water", "5", "--dl", "--date", d)      # +0.5
        self.assertAlmostEqual(track.water_total(d), 1.5)

    def test_sleep_recorded(self):
        d = "2030-02-02"
        run("sleep", "7.5", "--bed", "23:00", "--wake", "06:30", "--date", d)
        text = track.diary_path(d).read_text()
        self.assertIn("7.5 h", text)

    def test_weight_writes_csv_and_diary(self):
        d = "2030-02-03"
        run("day", "--date", d)
        run("weight", "80.4", "--date", d)
        self.assertAlmostEqual(track.latest_weight(d), 80.4)
        self.assertIn("80.4 kg", track.diary_path(d).read_text())


class Checklist(unittest.TestCase):
    D = "2030-03-01"

    def setUp(self):
        track.ensure_day(self.D)

    def _lines(self):
        return track.diary_path(self.D).read_text().splitlines()

    def test_template_has_five_items(self):
        _, total = track.checklist_status(self.D)
        self.assertEqual(total, len(track.CHECKLIST))

    def test_resolve_by_index_and_substring(self):
        lines = self._lines()
        kind, _ = track.resolve_check(lines, "1")
        self.assertEqual(kind, "ok")
        kind, _ = track.resolve_check(lines, "Protein")
        self.assertEqual(kind, "ok")

    def test_resolve_none_and_ambiguous(self):
        lines = self._lines()
        self.assertEqual(track.resolve_check(lines, "zzzznope")[0], "none")
        # "e" appears in several default items -> ambiguous
        self.assertEqual(track.resolve_check(lines, "e")[0], "ambiguous")

    def test_check_and_uncheck_roundtrip(self):
        run("check", "Protein", "--date", self.D)
        done, _ = track.checklist_status(self.D)
        self.assertEqual(done, 1)
        run("uncheck", "Protein", "--date", self.D)
        done, _ = track.checklist_status(self.D)
        self.assertEqual(done, 0)

    def test_coach_notes_are_not_checklist_items(self):
        run("note", "ate a big lunch", "--by", "me", "--date", self.D)
        # a coach note line ("- [HH:MM, me] ...") must not count as a checkbox
        _, total = track.checklist_status(self.D)
        self.assertEqual(total, len(track.CHECKLIST))


class ExerciseReportBrief(unittest.TestCase):
    def test_exercise_positive_kcal(self):
        d = "2030-04-01"
        run("exercise", "walk", "3", "45", "--date", d)
        self.assertGreater(track.exercise_total(d), 0)

    def test_report_runs(self):
        run("weight", "79.0", "--date", "2030-04-02")
        text = track.report("2030-04-02")
        self.assertIn("Weekly summary", text)

    def test_brief_runs(self):
        text = track.build_brief("2030-05-01", 3)
        self.assertIn("Planning brief", text)
        self.assertIn(str(track.KCAL_MIN), text)


class Robustness(unittest.TestCase):
    def test_section_bounds_missing_header_is_graceful(self):
        # previously raised StopIteration -> uncaught crash
        s, e = track.section_bounds(["# x", "## Foo", "a"], "## Meals")
        self.assertEqual((s, e), (3, 3))

    def test_intake_total_on_malformed_file_does_not_crash(self):
        d = "2030-06-01"
        track.diary_path(d).parent.mkdir(parents=True, exist_ok=True)
        track.diary_path(d).write_text("# broken\n(no sections)\n")
        self.assertEqual(track.intake_total(d), 0)

    def test_checklist_is_section_scoped(self):
        # a checkbox in coach notes must NOT be counted as a checklist item
        d = "2030-06-02"
        track.ensure_day(d)
        lines = track.diary_path(d).read_text().splitlines()
        lines.append("## Coach notes")
        lines.append("- [x] this is a note, not a checklist item")
        track.diary_path(d).write_text("\n".join(lines) + "\n")
        _, total = track.checklist_status(d)
        self.assertEqual(total, len(track.CHECKLIST))


class OpenFoodFacts(unittest.TestCase):
    PROD = {"code": "123", "product_name": "Skyr", "brands": "Milbona, x",
            "nutriments": {"energy-kcal_100g": 60, "proteins_100g": 11, "fat_100g": 0.2}}

    def test_product_label(self):
        self.assertEqual(off.product_label(self.PROD), "Skyr — Milbona")
        self.assertEqual(off.product_label({"product_name": "Plain"}), "Plain")
        self.assertEqual(off.product_label({}), "(unnamed)")

    def test_nutriment_accessors(self):
        self.assertEqual(off.energy_100g(self.PROD), 60.0)
        self.assertEqual(off.protein_100g(self.PROD), 11.0)
        self.assertIsNone(off.energy_100g({"nutriments": {}}))

    def test_fmt_portion(self):
        self.assertIn("150 g", off.fmt_portion(self.PROD, 150))
        self.assertIsNone(off.fmt_portion({"nutriments": {}}, 150))

    def test_resolve_off_meal_wiring(self):
        # monkeypatch the network call — no real HTTP in tests
        orig = off.off_product
        off.off_product = lambda code: self.PROD
        try:
            desc, kcal, protein, info = track.resolve_off_meal("123", 200, "snack", False)
        finally:
            off.off_product = orig
        self.assertEqual(kcal, 120)               # 60 kcal/100g * 200 g
        self.assertTrue(protein)                  # 11*2 = 22 g >= flag
        self.assertIn("Skyr", desc)
        self.assertIn("OFF:", info)

    def test_resolve_off_meal_no_hit_raises(self):
        orig = off.off_product
        off.off_product = lambda code: None
        try:
            with self.assertRaises(ValueError):
                track.resolve_off_meal("000", 100, "x", False)
        finally:
            off.off_product = orig


if __name__ == "__main__":
    unittest.main(verbosity=2)
