from __future__ import annotations

import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from creche_planning.domain import make_horizon  # noqa: E402
from creche_planning.solver import (  # noqa: E402
    hard_half_day_group_errors,
    hard_primary_group_rule_errors,
)


class SolverRuleTests(unittest.TestCase):
    def test_positive_hard_group_rule_constrains_primary_group_only(self) -> None:
        data = {
            "rules_group": [
                ["positif", "hard", "Emilie", "Nurserie"],
            ]
        }
        self.assertEqual(
            hard_primary_group_rule_errors(data, {"Emilie": "Nurserie"}),
            [],
        )
        errors = hard_primary_group_rule_errors(data, {"Emilie": "Trotteur"})
        self.assertEqual(len(errors), 1)
        self.assertIn("groupe principal", errors[0])

    def test_negative_hard_group_rule_rejects_forbidden_primary_group(self) -> None:
        data = {
            "rules_group": [
                ["negatif", "hard", "Natacha", "Grands"],
            ]
        }
        self.assertEqual(
            hard_primary_group_rule_errors(data, {"Natacha": "Trotteur"}),
            [],
        )
        self.assertEqual(
            len(hard_primary_group_rule_errors(data, {"Natacha": "Grands"})),
            1,
        )

    def test_ordinary_group_change_inside_half_day_is_rejected(self) -> None:
        horizon = make_horizon(
            {"sites": [{"name": "bas", "open": "06:45", "close": "18:45"}]}
        )
        schedule = {
            "Emilie": {
                "lundi": [
                    {"group": "Nurserie", "start": "08:00", "end": "10:00"},
                    {"group": "Trotteur", "start": "10:00", "end": "12:00"},
                ]
            }
        }
        errors = hard_half_day_group_errors(schedule, horizon)
        self.assertEqual(len(errors), 1)
        self.assertIn("interdit le matin", errors[0])

    def test_cut_day_can_change_group_between_half_days(self) -> None:
        horizon = make_horizon(
            {
                "sites": [
                    {"name": "bas", "open": "06:45", "close": "18:45"},
                    {"name": "haut", "open": "06:45", "close": "18:45"},
                ]
            }
        )
        schedule = {
            "Emilie": {
                "lundi": [
                    {
                        "group": "Nurserie",
                        "site": "bas",
                        "start": "08:00",
                        "end": "12:00",
                    },
                    {
                        "group": "Grands",
                        "site": "haut",
                        "start": "14:00",
                        "end": "17:00",
                    },
                ]
            }
        }
        self.assertEqual(hard_half_day_group_errors(schedule, horizon), [])

    def test_colloque_replacement_is_not_an_ordinary_group_change(self) -> None:
        horizon = make_horizon(
            {
                "sites": [
                    {"name": "bas", "open": "06:45", "close": "18:45"},
                    {"name": "haut", "open": "06:45", "close": "18:45"},
                ]
            }
        )
        schedule = {
            "Emilie": {
                "mardi": [
                    {
                        "group": "Nurserie",
                        "site": "bas",
                        "start": "13:00",
                        "end": "15:00",
                    },
                    {
                        "group": "Grands",
                        "site": "haut",
                        "start": "13:15",
                        "end": "14:00",
                        "activity": "remplacement_colloque",
                    },
                ]
            }
        }
        self.assertEqual(hard_half_day_group_errors(schedule, horizon), [])

if __name__ == "__main__":
    unittest.main()
