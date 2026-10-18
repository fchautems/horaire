from __future__ import annotations
import copy
import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
from creche_planning import solver
from creche_planning.scoring import compact_quality_context, compact_quality_breakdown


class QualityAlignmentTests(unittest.TestCase):
    def test_saved_candidates_have_same_cp_sat_and_selection_score(self):
        data = json.loads((ROOT / 'data/gwendo.json').read_text())
        paths = ['tests/fixtures/planning_gwendo_reference_valid.json',
                 'docs/experiments/2026-10-17-group-days-300s/optimized_candidate.json',
                 'docs/experiments/2026-10-17-score-fixed-300s/evaluated_candidate_2.json']
        scores = []
        for path in paths:
            reference = json.loads((ROOT / path).read_text())
            with self.subTest(path=path):
                result, _ = solver.make_ortools_slot_payload(
                    data, time_limit=10, hint_payload=reference,
                    fixed_schedule=reference['schedule'],
                    weekly_hours_tolerance_percent=5, max_split_gap_minutes=None,
                    split_gap_weight=0, short_day_penalty_weight=0,
                )
                self.assertEqual(result['status'], 'ok')
                # Independent recomputation from the JSON schedule, not objective.
                self.assertEqual(result['objective'], solver.planning_quality_score(result))
                scores.append(solver.planning_quality_score(result))
        self.assertEqual(scores, [809618, 650975, 631977])
        self.assertLess(scores[2], scores[1])

    def microcase(self, **weights):
        data = {
            'sites': [{'name': 'bas', 'open': '08:00', 'close': '18:00'}],
            'groups': [{'name': g, 'site': 'bas'} for g in ['A', 'B']],
            'educators': [{'name': 'Lea', 'type': 'EDE', 'percentage': 25,
                           'attends_colloque': False}],
            'educator_types': [{'name': 'EDE'}],
            'rules_global': {'max_weekly_hours': 40, 'max_daily_hours': 8.5},
            'rules_group': [['positif', 'hard', 'Lea', 'A'],
                            ['positif', 'soft', 'Lea', 'A'],
                            ['positif', 'soft', 'Lea', 'B'],
                            ['negatif', 'soft', 'Lea', 'B']],
            'rules_time': [['positif', 'soft', 'Lea', 'lundi', '07:00', '10:00'],
                           ['negatif', 'soft', 'Lea', 'lundi', '09:00', '11:00']],
        }
        def block(g, start, end, hours):
            return dict(group=g, site='bas', start=start, end=end, hours=hours)
        schedule = {'Lea': {day: [] for day in ['lundi','mardi','mercredi','jeudi','vendredi']}}
        schedule['Lea']['lundi'] = [block('A','08:00','10:00',2), block('B','13:00','16:00',3)]
        schedule['Lea']['mardi'] = [block('B','08:00','12:45',4.75)]
        result, _ = solver.make_ortools_slot_payload(
            data, time_limit=5, fixed_schedule=schedule, the_enabled=False,
            weekly_hours_tolerance_percent=5, max_split_gap_minutes=None, **weights,
        )
        self.assertEqual(result['status'], 'ok', result)
        return data, result

    def test_custom_weights_and_all_soft_preferences_match(self):
        data, result = self.microcase(split_shift_weight=3.125, group_switch_day_weight=2.25,
                                      same_group_week_weight=0.125, work_day_weight=7)
        self.assertEqual(result['objective'], solver.planning_quality_score(result))
        parts = compact_quality_breakdown(result, result['quality_scoring'])
        self.assertEqual(parts['hour_deviation_slots'], 2500)
        self.assertEqual(parts['preferred_primary'], -500)
        self.assertEqual(parts['negative_time_slots'], 180)
        self.assertEqual(parts['positive_time_slots'], -280)
        self.assertEqual(parts['outside_group_days'], 24)
        self.assertEqual(parts['mixed_days'], 225)
        self.assertEqual(parts['presence_starts'], 936)
        self.assertGreater(parts['group_rule_slots'], 0)

    def test_fragmenting_activity_does_not_change_shared_score(self):
        _, result = self.microcase()
        altered = copy.deepcopy(result)
        first = altered['schedule']['Lea']['lundi'][0]
        first['end'] = '09:00'; first['hours'] = 1
        altered['schedule']['Lea']['lundi'].append(
            dict(first, start='09:00', end='10:00', hours=1))
        self.assertEqual(solver.planning_quality_score(altered), solver.planning_quality_score(result))

    def test_gap_short_day_and_profile_coefficients_match_model(self):
        _, result = self.microcase(split_gap_weight=7, short_day_penalty_weight=19,
                                  min_daily_hours=6, soft_time_rule_weight=2.5,
                                  soft_group_rule_weight=3, compact_part_time_priority=True,
                                  main_group_day_weight=17, main_group_slot_weight=2,
                                  main_site_day_weight=11, work_day_weight=3)
        parts = compact_quality_breakdown(result, result['quality_scoring'])
        self.assertEqual(result['objective'], sum(parts.values()))
        self.assertGreater(parts['gap_slots'], 0)
        self.assertGreater(parts['short_day_slots'], 0)
        self.assertEqual(parts['negative_time_slots'], 4 * round(45 * 2.5))

    def test_primary_site_penalty_matches_model(self):
        from test_audit_regressions import p
        d = p.data(1, groups=('A', 'B'))
        d['sites'].append(dict(name='haut', open='08:00', close='18:00'))
        d['groups'][1]['site'] = 'haut'
        d['rules_group'] = [['positif', 'hard', 'Lea', 'A']]
        schedule = p.schedule([p.block(group='B', site='haut')])
        result, _ = solver.make_ortools_slot_payload(d, time_limit=3, fixed_schedule=schedule,
                                                    main_site_day_weight=9, **p.OPTIONS)
        self.assertEqual(result['status'], 'ok', result)
        parts = compact_quality_breakdown(result, result['quality_scoring'])
        self.assertEqual(parts['outside_site_days'], 900)
        self.assertEqual(sum(parts.values()), result['objective'])

    def test_cache_uses_current_policy_and_ignores_stale_objective(self):
        data, result = self.microcase()
        result['objective'] = -999999
        result['quality_scoring']['weights']['presence_starts'] = -999999
        current = compact_quality_context(data, the_enabled=False, work_day_weight=12)
        validated, _ = solver.revalidate_cached_payload(
            data, result, quality_context=current, the_enabled=False,
            weekly_hours_tolerance_percent=5, max_split_gap_minutes=None,
        )
        self.assertEqual(validated['status'], 'ok')
        self.assertEqual(validated['quality_scoring'], current)
        self.assertEqual(solver.planning_quality_score(validated),
                         solver.planning_quality_score(result, context=current))
        self.assertNotEqual(solver.planning_quality_score(validated), -999999)
        validated['checks']['errors'] = ['hard error']
        self.assertEqual(solver.planning_quality_score(validated), float('inf'))

    def test_free_search_and_callbacks_use_same_score(self):
        data, reference = self.microcase(work_day_weight=11)
        checkpoints = []
        result, _ = solver.make_ortools_slot_payload(
            data, time_limit=3, hint_payload=reference, fixed_schedule=None,
            the_enabled=False, weekly_hours_tolerance_percent=5,
            max_split_gap_minutes=None, work_day_weight=11,
            candidate_callback=lambda candidate, bundle: checkpoints.append(candidate),
        )
        self.assertEqual(result['status'], 'ok')
        self.assertTrue(checkpoints)
        for candidate in [*checkpoints, result]:
            self.assertEqual(candidate['objective'], solver.planning_quality_score(candidate))
        self.assertLessEqual(solver.planning_quality_score(result),
                             solver.planning_quality_score(checkpoints[0]))
