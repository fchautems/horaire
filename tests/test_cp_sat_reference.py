from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from creche_planning.solver import make_ortools_slot_payload  # noqa: E402


class CpSatReferenceTests(unittest.TestCase):
    def test_valid_reference_schedule_is_feasible_in_cp_sat(self) -> None:
        data = json.loads((ROOT / "data" / "gwendo.json").read_text(encoding="utf-8"))
        reference = json.loads(
            (ROOT / "tests" / "fixtures" / "planning_gwendo_reference_valid.json").read_text(
                encoding="utf-8"
            )
        )
        progress_messages: list[str] = []
        checkpoints: list[dict] = []
        with tempfile.TemporaryDirectory() as directory:
            payload, _bundle = make_ortools_slot_payload(
                data,
                time_limit=30.0,
                min_daily_hours=2.0,
                enforce_min_daily_hours=False,
                max_split_gap_minutes=None,
                weekly_hours_tolerance_percent=5.0,
                weekly_hours_tolerance_step_minutes=15,
                enforce_absolute_max_weekly_hours=True,
                absolute_max_weekly_hours=40.0,
                the_enabled=True,
                the_percent=10.0,
                the_colloques_count=True,
                hard_max_work_days=True,
                hint_payload=reference,
                fixed_schedule=reference["schedule"],
                debug_log_path=Path(directory) / "cp_sat.log",
                progress_callback=lambda _percent, message: progress_messages.append(message),
                candidate_callback=lambda candidate, _bundle: checkpoints.append(candidate),
            )

        self.assertEqual(payload["status"], "ok")
        self.assertEqual(payload["checks"]["errors"], [])
        self.assertEqual(payload["cp_sat_statistics"]["feasibility"]["status"], "OPTIMAL")
        self.assertEqual(len(checkpoints), 1)
        self.assertTrue(
            any("Solution hard-valide trouvee - note" in message for message in progress_messages)
        )

        schedule = payload["schedule"]
        self.assertEqual(
            {block["site"] for block in schedule["Léa"]["mardi"]},
            {"bas", "haut"},
        )
        self.assertTrue(
            any(
                block.get("activity") == "remplacement_colloque"
                for by_day in schedule.values()
                for blocks in by_day.values()
                for block in blocks
            )
        )
        self.assertTrue(
            any(
                block.get("activity") == "colloque"
                for by_day in schedule.values()
                for blocks in by_day.values()
                for block in blocks
            )
        )

    def test_primary_groups_and_colloques_are_resolved_without_hint(self) -> None:
        data = json.loads((ROOT / "data" / "gwendo.json").read_text(encoding="utf-8"))
        reference = json.loads(
            (ROOT / "tests" / "fixtures" / "planning_gwendo_reference_valid.json").read_text(
                encoding="utf-8"
            )
        )
        with tempfile.TemporaryDirectory() as directory:
            payload, _bundle = make_ortools_slot_payload(
                data,
                time_limit=30.0,
                min_daily_hours=2.0,
                enforce_min_daily_hours=False,
                max_split_gap_minutes=None,
                weekly_hours_tolerance_percent=5.0,
                weekly_hours_tolerance_step_minutes=15,
                enforce_absolute_max_weekly_hours=True,
                absolute_max_weekly_hours=40.0,
                the_enabled=True,
                the_percent=10.0,
                the_colloques_count=True,
                hard_max_work_days=True,
                hint_payload=None,
                fixed_schedule=reference["schedule"],
                debug_log_path=Path(directory) / "cp_sat_no_hint.log",
            )

        self.assertEqual(payload["status"], "ok")
        self.assertEqual(payload["checks"]["errors"], [])
        primary_groups = payload["checks"]["primary_groups_by_educator"]
        self.assertEqual(len(primary_groups), len(data["educators"]))
        self.assertEqual(primary_groups["Emilie"], "Nurserie")
        self.assertEqual(primary_groups["Priscila"], "Nurserie")
        self.assertEqual(primary_groups["Natacha"], "Trotteur")
        self.assertTrue(
            any(
                block.get("activity") == "remplacement_colloque"
                for by_day in payload["schedule"].values()
                for blocks in by_day.values()
                for block in blocks
            )
        )


if __name__ == "__main__":
    unittest.main()
