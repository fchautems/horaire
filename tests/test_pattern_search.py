from __future__ import annotations

import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from creche_planning.pattern_search import (  # noqa: E402
    attempt_budget,
    build_candidate_attempts,
    choose_valid_payload,
    ensure_verified_status,
    payload_is_hard_valid,
    payload_is_retryable,
    release_over_limit_primary_groups,
)


def valid_payload(objective: float = 10.0) -> dict:
    return {
        "status": "ok",
        "objective": objective,
        "schedule": {},
        "checks": {"errors": [], "hard_errors": []},
    }


class PatternSearchTests(unittest.TestCase):
    def test_hard_valid_requires_final_checks(self) -> None:
        self.assertTrue(payload_is_hard_valid(valid_payload()))
        self.assertFalse(payload_is_hard_valid({"status": "ok", "schedule": {}}))
        self.assertFalse(
            payload_is_hard_valid(
                {
                    "status": "ok",
                    "schedule": {},
                    "checks": {"errors": ["staffing"], "hard_errors": ["staffing"]},
                }
            )
        )

    def test_unverified_ok_payload_is_downgraded(self) -> None:
        payload = {"status": "ok", "schedule": {}, "checks": {"errors": ["THE"]}}
        ensure_verified_status(payload)
        self.assertEqual(payload["status"], "invalid")
        self.assertTrue(
            any("Planning refuse" in error for error in payload["checks"]["errors"])
        )

    def test_retryable_status_distinguishes_timeout_and_infeasible(self) -> None:
        self.assertTrue(
            payload_is_retryable(
                {"status": "infeasible_or_not_solved", "solver_message": "Time limit reached."}
            )
        )
        self.assertTrue(
            payload_is_retryable(
                {"status": "infeasible_or_not_solved", "solver_message": "Model is infeasible."}
            )
        )
        self.assertFalse(payload_is_retryable(valid_payload()))

    def test_only_over_limit_primary_groups_are_released(self) -> None:
        data = {"educators": [{"name": "A"}, {"name": "B"}, {"name": "C"}]}
        latest = {
            "checks": {
                "worked_days_by_educator": {"A": 5, "B": 3, "C": 2},
                "max_work_days": {"A": 4, "B": 3, "C": 2},
            }
        }
        fixed, names = release_over_limit_primary_groups(data, latest, {0: 0, 1: 1, 2: 2})
        self.assertEqual(fixed, {1: 1, 2: 2})
        self.assertEqual(names, ["A"])

    def test_attempts_expand_without_permanently_excluding_patterns(self) -> None:
        attempts = build_candidate_attempts(
            fixed_primary_groups={0: 0, 1: 1},
            targeted_primary_groups={1: 1},
            max_split_gap_minutes=120,
        )
        self.assertEqual(
            attempts[0].fixed_primary_groups,
            {1: 1},
        )
        self.assertEqual(attempts[0].generation_max_split_gap_minutes, 60)
        self.assertEqual(attempts[0].generation_time_step_minutes, 60)
        self.assertEqual(attempts[0].fine_generation_time_step_minutes, 30)
        self.assertTrue(attempts[0].restricted_patterns)
        self.assertEqual(attempts[0].restricted_pattern_mode, "continuous_halfday_groups")
        self.assertEqual(attempts[-1].fixed_primary_groups, None)
        self.assertFalse(attempts[-1].restricted_patterns)
        self.assertEqual(attempts[-1].generation_max_split_gap_minutes, 120)
        self.assertEqual(attempts[-1].generation_time_step_minutes, 15)
        self.assertIsNone(attempts[-1].fine_generation_time_step_minutes)

    def test_budget_reserves_time_for_improvement(self) -> None:
        attempts = build_candidate_attempts(
            fixed_primary_groups=None,
            targeted_primary_groups=None,
            max_split_gap_minutes=120,
        )
        budget = attempt_budget(1000.0, attempts, 0)
        self.assertGreater(budget, 0)
        self.assertLessEqual(budget, 750.0)

    def test_short_budget_runs_first_useful_attempt_instead_of_full_diagnostic(self) -> None:
        attempts = build_candidate_attempts(
            fixed_primary_groups={0: 0},
            targeted_primary_groups={0: 0},
            max_split_gap_minutes=120,
        )
        self.assertEqual(attempt_budget(180.0, attempts, 0, reserve_fraction=0.10), 162.0)

    def test_valid_candidate_is_never_replaced_by_invalid_improvement(self) -> None:
        current = valid_payload(20.0)
        invalid = {
            "status": "invalid",
            "objective": 1.0,
            "schedule": {},
            "checks": {"errors": ["jours"], "hard_errors": ["jours"]},
        }
        self.assertIs(choose_valid_payload(current, invalid), current)
        better = valid_payload(10.0)
        self.assertIs(choose_valid_payload(current, better), better)


if __name__ == "__main__":
    unittest.main()
