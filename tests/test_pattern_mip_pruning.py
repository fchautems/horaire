from __future__ import annotations

import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from creche_planning.pattern_mip import (  # noqa: E402
    PatternTimeLimitError,
    highs_solve_budget,
    pattern_hours_can_reach_week,
    weekly_pattern_bounds,
)
from creche_planning.solver import make_pattern_mip_payload  # noqa: E402


class PatternMipPruningTests(unittest.TestCase):
    def test_weekly_bounds_match_solver_hour_model(self) -> None:
        self.assertEqual(
            weekly_pattern_bounds(
                target_slots=56,
                tolerance_slots=2,
                the_slots=6,
                max_work_days=2,
                max_daily_slots=34,
                absolute_max_slots=160,
            ),
            (48, 52, 58, 14),
        )

    def test_short_worked_day_is_removed_only_when_week_cannot_be_completed(self) -> None:
        common = {
            "lower_child_slots": 48,
            "upper_child_slots": 52,
            "upper_visible_slots": 58,
            "max_work_days": 2,
            "max_daily_slots": 34,
        }
        self.assertFalse(
            pattern_hours_can_reach_week(
                child_slots=13,
                visible_slots=13,
                **common,
            )
        )
        self.assertTrue(
            pattern_hours_can_reach_week(
                child_slots=14,
                visible_slots=14,
                **common,
            )
        )

    def test_off_day_is_kept_when_remaining_days_can_reach_target(self) -> None:
        self.assertTrue(
            pattern_hours_can_reach_week(
                child_slots=0,
                visible_slots=0,
                lower_child_slots=48,
                upper_child_slots=52,
                upper_visible_slots=58,
                max_work_days=2,
                max_daily_slots=34,
            )
        )

    def test_pattern_above_weekly_upper_bound_is_removed(self) -> None:
        self.assertFalse(
            pattern_hours_can_reach_week(
                child_slots=53,
                visible_slots=53,
                lower_child_slots=48,
                upper_child_slots=52,
                upper_visible_slots=58,
                max_work_days=2,
                max_daily_slots=34,
            )
        )

    def test_work_pattern_is_removed_when_no_work_day_is_available(self) -> None:
        self.assertFalse(
            pattern_hours_can_reach_week(
                child_slots=1,
                visible_slots=1,
                lower_child_slots=0,
                upper_child_slots=0,
                upper_visible_slots=0,
                max_work_days=0,
                max_daily_slots=34,
            )
        )

    def test_pattern_timeout_is_returned_as_normal_payload(self) -> None:
        payload = {
            "status": "infeasible_or_not_solved",
            "solver_message": "Temps limite atteint pendant la construction du modele.",
        }
        bundle = SimpleNamespace()
        with patch(
            "creche_planning.pattern_mip.solve_pattern_mip",
            side_effect=PatternTimeLimitError(payload, bundle),
        ):
            actual_payload, actual_bundle = make_pattern_mip_payload({})
        self.assertIs(actual_payload, payload)
        self.assertIs(actual_bundle, bundle)

    def test_large_native_model_keeps_time_for_highs_setup(self) -> None:
        self.assertEqual(highs_solve_budget(60.0, 717_582), 0.0)
        self.assertAlmostEqual(highs_solve_budget(200.0, 717_582), 128.2418)
        self.assertEqual(highs_solve_budget(10.0, 50_000), 5.0)


if __name__ == "__main__":
    unittest.main()
