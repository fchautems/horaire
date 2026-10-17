from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from creche_planning.solver import make_ortools_slot_payload, verify_solution


class CpSatTheWorkDayTests(unittest.TestCase):
    def solve(self, blocks, *, contract=9, the_enabled=True, tolerance=0,
              colloque=False):
        data = {
            "sites": [{"name": "bas", "open": "08:00", "close": "18:00"}],
            "groups": [{"name": "A", "site": "bas"}],
            "educators": [{"name": "Lea", "type": "EDE",
                           "percentage": contract / 40 * 100,
                           "attends_colloque": colloque}],
            "educator_types": [{"name": "EDE"}],
            "rules_global": {"max_weekly_hours": 40, "max_daily_hours": 8.5},
            "rules_colloques": [["A", "mardi", "08:00", "08:45"]] if colloque else [],
        }
        schedule = {"Lea": {day: blocks.get(day, []) for day in
                            ("lundi", "mardi", "mercredi", "jeudi", "vendredi")}}
        options = dict(the_enabled=the_enabled, the_percent=10,
                       weekly_hours_tolerance_percent=tolerance,
                       max_split_gap_minutes=None, hard_max_work_days=True)
        payload, bundle = make_ortools_slot_payload(
            data, time_limit=5, fixed_schedule=schedule, **options,
        )
        checks = verify_solution(
            bundle, schedule, primary_groups_by_educator={"Lea": "A"}, **options,
        )
        return payload, checks

    @staticmethod
    def block(end, hours, activity=None):
        result = dict(group="A", site="bas", start="08:00", end=end, hours=hours)
        if activity:
            result["activity"] = activity
        return result

    def assert_valid(self, payload, checks):
        self.assertEqual(checks["errors"], [])
        self.assertEqual(payload["status"], "ok", payload)
        self.assertEqual(payload["checks"]["errors"], [])

    def assert_infeasible(self, payload):
        self.assertEqual(payload["cp_sat_statistics"]["feasibility"]["status"],
                         "INFEASIBLE")

    def test_invisible_the_does_not_require_a_second_presence_day(self):
        self.assert_valid(*self.solve({"lundi": [self.block("16:00", 8)]}))

    def test_weekly_tolerance_is_applied_before_counting_presence_days(self):
        self.assert_valid(*self.solve(
            {"lundi": [self.block("16:30", 8.5)]}, contract=10, tolerance=5,
        ))

    def test_without_the_nine_hours_still_need_two_days(self):
        payload, checks = self.solve(
            {"lundi": [self.block("16:00", 8)]}, the_enabled=False,
        )
        self.assertTrue(checks["errors"])
        self.assert_infeasible(payload)
        self.assert_valid(*self.solve(
            {"lundi": [self.block("16:00", 8)],
             "mardi": [self.block("09:00", 1)]}, the_enabled=False,
        ))

    def test_daily_presence_limit_is_still_enforced(self):
        payload, checks = self.solve(
            {"lundi": [self.block("17:00", 9)]}, contract=10,
        )
        self.assertTrue(checks["errors"])
        self.assert_infeasible(payload)

    def test_visible_colloque_still_requires_presence_on_its_day(self):
        self.assert_valid(*self.solve(
            {"lundi": [self.block("16:00", 8)],
             "mardi": [self.block("08:45", .75, "colloque")]}, colloque=True,
        ))
        payload, checks = self.solve(
            {"lundi": [self.block("16:00", 8)]}, colloque=True,
        )
        self.assertTrue(checks["errors"])
        self.assert_infeasible(payload)


if __name__ == "__main__":
    unittest.main()
