from __future__ import annotations

import sys
import unittest
from pathlib import Path

SRC = Path(__file__).resolve().parents[1] / 'src'
sys.path.insert(0, str(SRC))
from creche_planning.solver import revalidate_cached_payload


class ValidatorPresenceTests(unittest.TestCase):
    def check_blocks(self, blocks):
        data = {
            'sites': [{'name': 'bas', 'open': '08:00', 'close': '18:00'}],
            'groups': [{'name': 'A', 'site': 'bas'}],
            'educators': [{'name': 'Lea', 'type': 'EDE', 'percentage': 7.5,
                           'attends_colloque': False}],
            'educator_types': [{'name': 'EDE'}],
            'rules_global': {'max_weekly_hours': 40, 'max_daily_hours': 8.5},
        }
        schedule = {'Lea': {day: [] for day in
                           ('lundi', 'mardi', 'mercredi', 'jeudi', 'vendredi')}}
        schedule['Lea']['lundi'] = blocks
        candidate, _ = revalidate_cached_payload(
            data, {'schedule': schedule}, the_enabled=False,
            weekly_hours_tolerance_percent=0, max_split_gap_minutes=None,
        )
        return candidate['checks']['errors']

    def block(self, start, end, hours, **extra):
        return dict(group='A', site='bas', start=start, end=end, hours=hours, **extra)

    def test_three_separate_periods_are_rejected(self):
        errors = self.check_blocks([self.block('08:00', '09:00', 1),
                                   self.block('10:00', '11:00', 1),
                                   self.block('13:00', '14:00', 1)])
        self.assertTrue(any('periodes de presence' in error for error in errors), errors)

    def test_overlapping_periods_are_rejected(self):
        errors = self.check_blocks([self.block('08:00', '10:00', 2),
                                   self.block('09:00', '10:00', 1)])
        self.assertTrue(any('chevauchement' in error for error in errors), errors)

    def test_inconsistent_duration_is_rejected(self):
        errors = self.check_blocks([self.block('08:00', '12:00', 3)])
        self.assertTrue(any('duree incoherente' in error for error in errors), errors)

    def test_adjacent_records_form_one_presence_period(self):
        blocks = [self.block('08:00', '09:00', 1),
                  self.block('09:00', '10:00', 1),
                  self.block('10:00', '11:00', 1)]
        self.assertEqual(self.check_blocks(list(reversed(blocks))), [])

    def test_two_separate_periods_are_allowed(self):
        self.assertEqual(self.check_blocks([self.block('08:00', '09:00', 1),
                                           self.block('13:00', '15:00', 2)]), [])

    def test_colloque_record_does_not_split_continuous_presence(self):
        errors = self.check_blocks([self.block('08:00', '09:00', 1),
                                   self.block('09:00', '09:45', .75, activity='colloque'),
                                   self.block('09:45', '10:45', 1),
                                   self.block('13:00', '14:00', 1)])
        self.assertFalse(any('periodes de presence' in error for error in errors), errors)

    def test_reversed_time_range_is_rejected(self):
        errors = self.check_blocks([self.block('09:00', '08:00', 3)])
        self.assertTrue(any('plage horaire invalide' in error for error in errors), errors)
