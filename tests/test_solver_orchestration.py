from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from creche_planning import solver  # noqa: E402


class SolverOrchestrationTests(unittest.TestCase):
    def test_cached_candidate_is_revalidated_before_reuse(self) -> None:
        data = {
            "sites": [{"name": "bas", "open": "08:00", "close": "10:00"}],
            "groups": [{"name": "Nurserie", "site": "bas"}],
            "educators": [{"name": "A", "type": "EDE", "percentage": 0}],
            "educator_types": [{"name": "EDE"}],
            "rules_global": {"max_weekly_hours": 40, "max_daily_hours": 8.5},
            "rules_group": [],
            "rules_time": [],
            "rules_percentage": [],
            "rules_site_schedule": [],
            "rules_colloques": [],
        }
        payload = {
            "status": "ok",
            "schedule": {
                "A": {
                    "lundi": [],
                    "mardi": [],
                    "mercredi": [],
                    "jeudi": [],
                    "vendredi": [],
                }
            },
            "checks": {},
        }
        result = solver.revalidate_cached_payload(data, payload)
        self.assertIsNotNone(result)
        candidate, _bundle = result
        self.assertEqual(candidate["status"], "ok")
        self.assertEqual(candidate["checks"]["errors"], [])
        self.assertEqual(
            candidate["diagnostics"],
            ["Planning en cache revalide avec les donnees et regles actuelles."],
        )

    def test_explicit_latest_candidate_is_preferred_over_newer_debug_output(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            output_directory = Path(temporary_directory)
            latest_path = output_directory / "planning_gwendo_latest.json"
            debug_path = output_directory / "cp_sat_candidate_test.json"
            latest_path.write_text(
                json.dumps({"status": "ok", "schedule": {}, "source": "latest"}),
                encoding="utf-8",
            )
            debug_path.write_text(
                json.dumps({"status": "ok", "schedule": {}, "source": "debug"}),
                encoding="utf-8",
            )

            payload = solver.load_latest_valid_payload(latest_path)

        self.assertIsNotNone(payload)
        self.assertEqual(payload["source"], "latest")

    def test_cached_candidate_is_rejected_when_current_rules_fail(self) -> None:
        data = {
            "sites": [{"name": "bas", "open": "08:00", "close": "10:00"}],
            "groups": [{"name": "Nurserie", "site": "bas"}],
            "educators": [{"name": "A", "type": "EDE", "percentage": 0}],
            "educator_types": [{"name": "EDE"}],
            "rules_global": {"max_weekly_hours": 40, "max_daily_hours": 8.5},
            "rules_group": [],
            "rules_time": [["positif", "hard", "A", "lundi", "08:00", "09:00"]],
            "rules_percentage": [],
            "rules_site_schedule": [],
            "rules_colloques": [],
        }
        payload = {
            "status": "ok",
            "schedule": {
                "A": {
                    "lundi": [],
                    "mardi": [],
                    "mercredi": [],
                    "jeudi": [],
                    "vendredi": [],
                }
            },
            "checks": {},
        }
        result = solver.revalidate_cached_payload(data, payload)
        self.assertIsNotNone(result)
        candidate, _bundle = result
        self.assertEqual(candidate["status"], "invalid")
        self.assertTrue(candidate["checks"]["errors"])

    def test_valid_candidate_is_kept_when_quality_improvement_times_out(self) -> None:
        config = {
            "solver_engine": "pattern_mip",
            "time_limit_seconds": 1000,
            "compact_candidate_first": False,
            "pattern_fallback_time_seconds": 180,
            "fix_primary_groups_from_latest": True,
            "hard_max_work_days": True,
            "relax_work_days_if_infeasible": False,
            "write_latest_outputs": False,
            "timestamp_outputs": False,
        }
        data = {
            "educators": [{"name": "A"}],
            "groups": [],
            "sites": [],
            "rules_global": {},
        }
        latest = {
            "schedule": {},
            "checks": {
                "worked_days_by_educator": {"A": 1},
                "max_work_days": {"A": 1},
            },
        }
        bundle = SimpleNamespace(data=data, horizon=None, groups=[], educators=[], sites=[])
        candidate = {
            "status": "ok",
            "objective": 0.0,
            "solver_message": "Feasible",
            "warnings": [],
            "schedule": {},
            "checks": {"errors": [], "hard_errors": []},
        }
        timeout = {
            "status": "infeasible_or_not_solved",
            "solver_message": "Time limit reached.",
            "warnings": [],
            "diagnostics": [],
        }
        reported: list[dict] = []

        with (
            patch.object(solver, "load_run_config", return_value=(config, Path("."))),
            patch.object(
                solver,
                "select_quality_profile",
                return_value=("equilibre", "Equilibre", {}, []),
            ),
            patch.object(solver, "load_json", return_value=data),
            patch.object(solver, "load_latest_valid_payload", return_value=latest),
            patch.object(
                solver,
                "infer_majority_primary_groups_from_payload",
                return_value={0: 0},
            ),
            patch.object(
                solver,
                "make_pattern_mip_payload",
                side_effect=[(candidate, bundle), (timeout, bundle)],
            ),
            patch.object(solver, "attach_quality_profile"),
            patch.object(solver, "build_rule_summary", return_value={}),
            patch.object(solver, "print_report", side_effect=lambda payload: reported.append(payload)),
            patch.object(sys, "argv", ["solveur_v2.py", "dummy.json"]),
        ):
            return_code = solver.main()

        self.assertEqual(return_code, 0)
        self.assertEqual(reported[-1]["status"], "ok")
        self.assertEqual(reported[-1]["solver_message"], "Feasible")
        self.assertTrue(
            any("candidat hard-valide conserve" in warning for warning in reported[-1]["warnings"])
        )


if __name__ == "__main__":
    unittest.main()
