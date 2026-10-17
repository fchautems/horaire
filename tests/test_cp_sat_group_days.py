from __future__ import annotations

import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from creche_planning.solver import make_ortools_slot_payload, verify_solution


class CpSatGroupDayTests(unittest.TestCase):
    def block(self, group, start, end, hours):
        return dict(group=group, site="bas", start=start, end=end, hours=hours)

    def check_schedule(self, monday, tuesday, *, limit=1, attends_colloque=True):
        data = {
            "sites": [{"name": "bas", "open": "08:00", "close": "18:00"}],
            "groups": [{"name": group, "site": "bas"} for group in ("A", "B")],
            "educators": [{"name": "Lea", "type": "EDE", "percentage": 25,
                           "attends_colloque": attends_colloque}],
            "educator_types": [{"name": "EDE"}],
            "rules_group": [["positif", "hard", "Lea", "A"]],
            "rules_global": {"max_weekly_hours": 40, "max_daily_hours": 8.5},
        }
        schedule = {"Lea": {day: [] for day in
                            ("lundi", "mardi", "mercredi", "jeudi", "vendredi")}}
        schedule["Lea"]["lundi"] = monday
        schedule["Lea"]["mardi"] = tuesday
        options = dict(the_enabled=False, weekly_hours_tolerance_percent=0,
                       max_split_gap_minutes=None, max_weekly_group_exception_days=limit)
        payload, bundle = make_ortools_slot_payload(
            data, fixed_schedule=schedule, time_limit=5, **options,
        )
        checks = verify_solution(
            bundle, schedule, primary_groups_by_educator={"Lea": "A"}, **options,
        )
        return payload, checks

    def whole_day(self):
        return [self.block("B", "08:00", "13:00", 5)]

    def mixed_day(self):
        return [self.block("A", "08:00", "10:00", 2),
                self.block("B", "13:00", "16:00", 3)]

    def assert_accepted(self, payload, checks):
        self.assertEqual(checks["errors"], [])
        self.assertEqual(payload["status"], "ok", payload)
        self.assertEqual(payload["checks"]["errors"], [])
        self.assertEqual(payload["checks"]["primary_groups_by_educator"]["Lea"], "A")

    def assert_rejected(self, payload, checks, expected_error):
        self.assertTrue(any(expected_error in error for error in checks["errors"]), checks)
        self.assertEqual(payload["cp_sat_statistics"]["feasibility"]["status"], "INFEASIBLE")

    def test_two_whole_days_outside_primary_do_not_use_exception_days(self):
        for limit in (0, 1):
            with self.subTest(limit=limit):
                self.assert_accepted(*self.check_schedule(
                    self.whole_day(), self.whole_day(), limit=limit,
                ))

    def test_whole_day_outside_primary_plus_one_mixed_day_is_allowed(self):
        self.assert_accepted(*self.check_schedule(self.mixed_day(), self.whole_day()))

    def test_two_mixed_days_still_exceed_limit_one(self):
        self.assert_rejected(
            *self.check_schedule(self.mixed_day(), self.mixed_day()),
            "Trop de jours avec changement de groupe",
        )

    def test_mixed_day_is_rejected_when_limit_is_zero(self):
        self.assert_rejected(
            *self.check_schedule(self.mixed_day(), self.whole_day(), limit=0),
            "Trop de jours avec changement de groupe",
        )

    def test_ordinary_change_within_half_day_stays_forbidden(self):
        self.assert_rejected(
            *self.check_schedule([
                self.block("A", "08:00", "10:00", 2),
                self.block("B", "10:00", "13:00", 3),
            ], self.whole_day()),
            "Changement de groupe interdit le matin",
        )

    def test_non_participant_keeps_existing_weekly_exception(self):
        self.assert_accepted(*self.check_schedule(
            self.mixed_day(), self.mixed_day(), attends_colloque=False,
        ))


if __name__ == "__main__":
    unittest.main()
