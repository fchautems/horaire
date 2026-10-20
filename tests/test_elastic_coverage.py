from __future__ import annotations

import copy
import io
import json
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
from creche_planning import domain, solver
from creche_planning.pattern_search import payload_is_hard_valid


class ElasticCoverageTests(unittest.TestCase):
    def data(self, required_end='09:00'):
        return dict(
            sites=[dict(name='S', open='08:00', close='10:00')],
            groups=[dict(name='G', site='S')],
            educators=[dict(name='A', type='EDE', percentage=2.5,
                            attends_colloque=False, max_work_days=5)],
            educator_types=[dict(name='EDE'), dict(name='ASE')],
            rules_global=dict(max_weekly_hours=40, max_daily_hours=8.5),
            rules_group=[], rules_percentage=[], rules_colloques=[],
            rules_time=[['negatif', 'hard', 'A', d, '08:00', '10:00']
                        for d, _ in domain.DAYS if d != 'lundi'],
            rules_site_schedule=[dict(site='S', days=['lundi'], time_intervals=[
                dict(group='G', start='08:00', end=required_end, min_staff=1)])],
        )

    def block(self, start='08:00', end='09:00', group='G', site='S', **extra):
        return dict(start=start, end=end, group=group, site=site,
                    hours=(domain.parse_time(end)-domain.parse_time(start))/60, **extra)

    def schedule(self, *blocks):
        return {'A': {d: list(blocks) if d == 'lundi' else [] for d, _ in domain.DAYS}}

    def solve(self, data, **options):
        parameters = dict(time_limit=2, the_enabled=False, the_colloques_count=False,
            weekly_hours_tolerance_percent=0, min_daily_hours=0,
            max_split_gap_minutes=90, experimental_elastic_coverage=True, search_seed=7)
        parameters.update(options)
        return solver.make_ortools_slot_payload(copy.deepcopy(data), **parameters)[0]

    def test_positive_deficit_is_exact_diagnostic_and_never_checkpointed(self):
        checkpoints = []
        result = self.solve(self.data('10:00'), fixed_schedule=self.schedule(self.block()),
            candidate_callback=lambda p, b: checkpoints.append(p))
        self.assertEqual(result['status'], 'invalid')
        self.assertTrue(result['diagnostic_only'])
        self.assertFalse(payload_is_hard_valid(result))
        self.assertEqual(result['elastic_coverage']['total_deficit_slots'], 4)
        self.assertEqual(result['elastic_coverage']['deficit_requirement_minutes'], 60)
        self.assertEqual(len(result['elastic_coverage']['deficits']), 4)
        self.assertFalse(result['elastic_coverage']['quality_phase_started'])
        self.assertEqual(checkpoints, [])
        self.assertTrue(result['checks']['errors'])

    def test_default_remains_strict_and_feature_is_disabled_in_configuration(self):
        result = self.solve(self.data('10:00'), experimental_elastic_coverage=False)
        self.assertEqual(result['solver_message'], 'INFEASIBLE')
        self.assertNotIn('elastic_coverage', result)
        config = json.loads((ROOT/'config/solveur_config.json').read_text())
        for settings in (config, domain.DEFAULT_RUN_CONFIG):
            self.assertIs(settings['experimental_elastic_coverage'], False)

    def test_zero_then_quality_never_trades_coverage_for_soft_preferences(self):
        data = self.data()
        data['rules_time'].append(['negatif', 'soft', 'A', 'lundi', '08:00', '09:00'])
        hint = dict(schedule=self.schedule(self.block('09:00', '10:00')))
        checkpoints = []
        result = self.solve(data, hint_payload=hint, soft_time_rule_weight=1_000_000,
            candidate_callback=lambda p, b: checkpoints.append(copy.deepcopy(p)))
        self.assertTrue(payload_is_hard_valid(result))
        self.assertTrue(result['elastic_coverage']['zero_reached'])
        self.assertTrue(result['elastic_coverage']['quality_phase_started'])
        self.assertEqual(result['elastic_coverage']['total_deficit_slots'], 0)
        self.assertEqual(result['schedule']['A']['lundi'][0]['start'], '08:00')
        self.assertTrue(checkpoints)
        self.assertTrue(all(payload_is_hard_valid(p) for p in checkpoints))
        self.assertTrue(all(p['elastic_coverage']['total_deficit_slots'] == 0 for p in checkpoints))

    def test_site_and_group_deficits_stay_separate(self):
        data = self.data('10:00')
        data['rules_site_schedule'][0]['time_intervals'].append(
            dict(group='tous', start='08:00', end='10:00', min_staff=1))
        result = self.solve(data, fixed_schedule=self.schedule(self.block()))
        rows = result['elastic_coverage']['deficits']
        self.assertEqual({r['scope'] for r in rows}, {'site', 'group'})
        self.assertEqual(sum(r['missing'] for r in rows), 8)
        self.assertEqual(result['elastic_coverage']['total_deficit_slots'], 8)

    def test_contract_daily_cap_qualifications_and_hard_availability_stay_strict(self):
        cases = []
        data = self.data(); cases.append(('contract', data, self.schedule(self.block(end='10:00'))))
        data = self.data(); data['rules_global']['max_daily_hours'] = .5
        cases.append(('daily_cap', data, self.schedule(self.block())))
        data = self.data(); data['rules_percentage'] = [[['ASE'], 'min', 50, 'S']]
        cases.append(('qualification', data, self.schedule(self.block())))
        data = self.data(); data['rules_time'].append(['negatif', 'hard', 'A', 'lundi', '08:00', '09:00'])
        cases.append(('availability', data, self.schedule(self.block())))
        for label, data, schedule in cases:
            with self.subTest(label=label):
                result = self.solve(data, fixed_schedule=schedule)
                self.assertEqual(result['solver_message'], 'INFEASIBLE')
                self.assertFalse(payload_is_hard_valid(result))

    def test_maximum_classic_break_is_not_relaxed(self):
        data = self.data()
        data['sites'][0]['close'] = '12:00'
        data['rules_time'] = [['negatif', 'hard', 'A', d, '08:00', '12:00']
                              for d, _ in domain.DAYS if d != 'lundi']
        result = self.solve(data, fixed_schedule=self.schedule(
            self.block(end='08:30'), self.block('11:00', '11:30')))
        self.assertEqual(result['solver_message'], 'INFEASIBLE')

    def test_group_staffing_upper_bound_is_not_relaxed(self):
        data = self.data()
        data['educators'].append(dict(data['educators'][0], name='B'))
        data['rules_time'] += [r[:2] + ['B'] + r[3:] for r in list(data['rules_time'])]
        data['rules_site_schedule'][0]['time_intervals'][0]['max_staff'] = 1
        fixed = self.schedule(self.block())
        fixed['B'] = copy.deepcopy(fixed['A'])
        result = self.solve(data, fixed_schedule=fixed)
        self.assertEqual(result['solver_message'], 'INFEASIBLE')

    def test_weekly_absolute_cap_remains_strict_with_contract_tolerance(self):
        data = self.data()
        data['educators'][0]['percentage'] = 100
        data['sites'][0]['close'] = '17:00'
        data['rules_time'] = []
        fixed = {'A': {d: [self.block(end='16:15')] for d, _ in domain.DAYS}}
        result = self.solve(data, weekly_hours_tolerance_percent=5, fixed_schedule=fixed)
        self.assertEqual(result['solver_message'], 'INFEASIBLE')

    def test_maximum_work_days_is_not_relaxed(self):
        data = self.data()
        data['educators'][0].update(percentage=5, max_work_days=1)
        data['rules_time'] = [r for r in data['rules_time'] if r[3] != 'mardi']
        fixed = self.schedule(self.block())
        fixed['A']['mardi'] = [self.block()]
        result = self.solve(data, fixed_schedule=fixed)
        self.assertEqual(result['solver_message'], 'INFEASIBLE')

    def test_instant_site_transfer_is_not_relaxed(self):
        data = self.data()
        data['sites'].append(dict(name='T', open='08:00', close='10:00'))
        data['groups'].append(dict(name='H', site='T'))
        result = self.solve(data, fixed_schedule=self.schedule(
            self.block(end='08:30'), self.block('08:30', '09:00', site='T', group='H')))
        self.assertEqual(result['solver_message'], 'INFEASIBLE')

    def test_colloque_and_invisible_the_do_not_cover_children(self):
        data = self.data()
        data['educators'][0]['attends_colloque'] = True
        data['rules_group'] = [['positif', 'hard', 'A', 'G']]
        data['rules_colloques'] = [dict(group='G', day='lundi', start='08:00', end='08:30')]
        result = self.solve(data, the_enabled=True, the_colloques_count=True, the_percent=50,
            fixed_schedule=self.schedule(self.block(end='08:30', activity='colloque'),
                                         self.block('08:30', '09:00')))
        self.assertEqual(result['elastic_coverage']['total_deficit_slots'], 2)
        self.assertEqual(result['checks']['hours_by_educator']['A'], 1)
        self.assertEqual(result['checks']['colloque_the_hours_by_educator']['A'], .5)
        self.assertEqual(result['checks']['child_hours_by_educator']['A'], .5)
        self.assertEqual(result['status'], 'invalid')

    def test_zero_still_requires_independent_strict_validation(self):
        original = solver.verify_solution
        def reject(*args, **kwargs):
            checks = original(*args, **kwargs)
            checks['errors'].append('Independent rejection')
            checks['hard_errors'] = checks['errors']
            return checks
        checkpoints = []
        with patch.object(solver, 'verify_solution', side_effect=reject):
            result = self.solve(self.data(), candidate_callback=lambda p, b: checkpoints.append(p))
        self.assertTrue(result['elastic_coverage']['zero_reached'])
        self.assertEqual(result['status'], 'invalid')
        self.assertEqual(checkpoints, [])
        self.assertFalse(result['elastic_coverage']['quality_phase_started'])

    def test_other_diagnostic_relaxations_cannot_be_combined(self):
        for option in ('enforce_daily_block_structure', 'enforce_half_day_group_structure',
                       'enforce_percentage_rules', 'enforce_daily_hours', 'enforce_weekly_hours'):
            with self.subTest(option=option), self.assertRaises(ValueError):
                self.solve(self.data(), **{option: False})
        with self.assertRaises(ValueError):
            self.solve(self.data(), accept_invalid_for_hint=True)

    def test_cli_opt_in_diagnostic_preserves_latest_outputs(self):
        with tempfile.TemporaryDirectory() as directory:
            folder = Path(directory)
            (folder/'data.json').write_text(json.dumps(self.data('10:00')))
            sentinel = '{"sentinel": "previous output"}\n'
            (folder/'latest.json').write_text(sentinel)
            config = dict(input_json='data.json', output_json='diagnostic.json',
                html_output='diagnostic.html', csv_output='diagnostic.csv',
                latest_output_json='latest.json', latest_csv_output='latest.csv',
                latest_html_output='latest.html', initial_solution_json=None,
                write_latest_outputs=True, timestamp_outputs=False, solver_engine='cp-sat',
                time_limit_seconds=2, experimental_elastic_coverage=False,
                the_enabled=False, the_colloques_count=False, weekly_hours_tolerance_percent=0,
                enforce_max_pause_between_blocks=True, max_pause_between_blocks_minutes=90)
            (folder/'config.json').write_text(json.dumps(config))
            with patch.object(sys, 'argv', ['solver', '--config', str(folder/'config.json'),
                    '--experimental-elastic-coverage', '--search-seed', '23']), redirect_stdout(io.StringIO()):
                code = solver.main()
            result = json.loads((folder/'diagnostic.json').read_text())
            self.assertEqual(code, 2)
            self.assertEqual(result['status'], 'invalid')
            self.assertGreater(result['elastic_coverage']['total_deficit_slots'], 0)
            self.assertEqual((folder/'latest.json').read_text(), sentinel)
            self.assertFalse((folder/'latest.csv').exists())
            self.assertFalse((folder/'latest.html').exists())
            self.assertIn('Planning invalide', (folder/'diagnostic.html').read_text())

    def test_real_known_valid_schedule_has_zero_and_identical_assignments(self):
        data = json.loads((ROOT/'data/gwendo.json').read_text())
        candidate = json.loads((ROOT/'docs/experiments/2026-10-20-guided-fewer-breaks-120s/result.json').read_text())
        options = dict(time_limit=5, fixed_schedule=candidate['schedule'], the_enabled=True,
            the_colloques_count=True, the_percent=10, weekly_hours_tolerance_percent=5,
            max_split_gap_minutes=90, search_seed=7)
        strict, _ = solver.make_ortools_slot_payload(data, **options)
        elastic, _ = solver.make_ortools_slot_payload(data, **options, experimental_elastic_coverage=True)
        self.assertTrue(payload_is_hard_valid(strict), strict)
        self.assertTrue(payload_is_hard_valid(elastic), elastic)
        self.assertEqual(elastic['elastic_coverage']['total_deficit_slots'], 0)
        self.assertEqual(strict['schedule'], elastic['schedule'])
        self.assertEqual(strict['objective'], elastic['objective'])


if __name__ == '__main__':
    unittest.main()
