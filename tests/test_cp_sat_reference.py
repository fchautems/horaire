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
    def test_historical_reference_with_instant_site_moves_is_rejected(self) -> None:
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

        self.assertEqual(payload["solver_message"], "INFEASIBLE")
        self.assertEqual(len(checkpoints), 0)
        # The immutable historical reference has instantaneous intersite moves.
        from creche_planning.solver import revalidate_cached_payload
        checked, _ = revalidate_cached_payload(data, reference,
            weekly_hours_tolerance_percent=5, max_split_gap_minutes=None)
        self.assertEqual(checked["status"], "invalid")
        self.assertTrue(any("Deplacement intersites" in e for e in checked["checks"]["errors"]))

    def test_instant_site_moves_are_rejected_without_hint_too(self) -> None:
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

        self.assertEqual(payload["solver_message"], "INFEASIBLE")
        self.assertNotEqual(payload["status"], "ok")


if __name__ == "__main__":
    unittest.main()
