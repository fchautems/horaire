from __future__ import annotations

import copy
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from creche_planning.solver import planning_quality_score


def block(start, end, group="Nurserie", activity="children"):
    return {"start": start, "end": end, "group": group,
            "site": "bas", "activity": activity}


def payload(blocks):
    return {"status": "ok", "checks": {"errors": []},
            "schedule": {"A": {"mardi": blocks}}}


class PlanningQualityScoreTests(unittest.TestCase):
    def test_fragmented_replacement_counts_as_two_presence_periods(self):
        fragmented = payload([
            block("08:30", "12:00"), block("13:00", "13:15"),
            block("13:15", "14:00", "Grands", "remplacement_colloque"),
            block("14:00", "18:00"),
        ])
        self.assertEqual(planning_quality_score(fragmented), 1000)

    def test_adjacent_colloque_has_same_score_as_continuous_presence(self):
        continuous = payload([block("08:00", "12:00")])
        fragmented = payload([
            block("08:00", "09:00"),
            block("09:00", "09:45", activity="colloque"),
            block("09:45", "10:00"), block("10:00", "12:00"),
        ])
        self.assertEqual(planning_quality_score(fragmented),
                         planning_quality_score(continuous))

    def test_real_gap_is_still_penalized(self):
        self.assertEqual(planning_quality_score(payload([
            block("08:00", "12:00"), block("13:00", "18:00")
        ])), 100)

    def test_four_real_periods_keep_large_penalty(self):
        self.assertEqual(planning_quality_score(payload([
            block("08:00", "09:00"), block("10:00", "11:00"),
            block("12:00", "13:00"), block("14:00", "15:00"),
        ])), 10280)

    def test_unsorted_nested_intervals_are_merged_without_mutation(self):
        candidate = payload([
            block("10:00", "11:00"), block("08:00", "12:00"),
            block("09:00", "09:30"), block("12:00", "13:00"),
        ])
        original = copy.deepcopy(candidate)
        self.assertEqual(planning_quality_score(candidate), 10)
        self.assertEqual(candidate, original)

    def test_empty_day_and_validation_errors(self):
        candidate = payload([])
        self.assertEqual(planning_quality_score(candidate), 0)
        candidate["checks"]["errors"] = ["invalid"]
        self.assertEqual(planning_quality_score(candidate), 1000000)
        candidate["status"] = "invalid"
        self.assertEqual(planning_quality_score(candidate), 1000000000)
