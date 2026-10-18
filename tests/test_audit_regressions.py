"""Regression expectations for the independently reproduced audit defects."""
import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
spec = importlib.util.spec_from_file_location('audit_probes', ROOT / 'docs/audits/2026-10-18/probes.py')
p = importlib.util.module_from_spec(spec)
spec.loader.exec_module(p)
from creche_planning import domain, solver, editor
from creche_planning.pattern_search import payload_is_hard_valid


class AuditRegressionTests(unittest.TestCase):
    def test_forbidden_ordinary_group_is_rejected_by_both(self):
        r = p.ordinary_forbidden()
        self.assertTrue(r['validator_errors'])
        self.assertEqual(r['cp_message'], 'INFEASIBLE')

    def test_deleted_educator_cannot_cover_children(self):
        self.assertEqual(p.unknown_educator()['cache_status'], 'invalid')

    def test_fake_activities_are_rejected(self):
        for activity in ['colloque', 'remplacement_colloque']:
            with self.subTest(activity=activity):
                self.assertTrue(p.fake_activity(activity)['validator_errors'])

    def test_missing_primary_does_not_hide_missing_meeting(self):
        self.assertTrue(p.missing_primary())

    def test_bad_site_and_grid_are_rejected(self):
        self.assertTrue(p.wrong_site())
        r = p.off_grid()
        self.assertTrue(r['validator_errors'])
        self.assertNotEqual(r['cp_status'], 'ok')

    def test_nan_hours_are_rejected_before_totals(self):
        b = p.block(); b['hours'] = float('nan')
        self.assertTrue(p.check(p.data(), p.schedule([b]))['errors'])

    def test_malformed_cache_is_invalid_without_exception(self):
        candidate, _ = p.malformed_cache()
        self.assertEqual(candidate['status'], 'invalid')

    def test_every_meeting_is_mandatory(self):
        r = p.multiple_meetings()
        self.assertTrue(r['validator_errors'])
        self.assertNotEqual(r['cp_status'], 'ok')

    def test_simultaneous_meetings_do_not_overwrite_each_other(self):
        r = p.simultaneous_meetings()
        self.assertEqual(r['validator_errors'], [])
        self.assertEqual(r['cp_status'], 'ok', r)

    def test_visible_the_cannot_exceed_the_budget(self):
        self.assertTrue(p.the_budget()['validator_errors'])

    def test_qualification_alias_reaches_validation(self):
        self.assertEqual(p.aliases()['status'], 'ok')

    def test_max_staff_is_applied(self):
        r = p.staffing_max()
        self.assertTrue(r['validator_errors'])
        self.assertEqual(r['cp_message'], 'INFEASIBLE')

    def test_other_engine_never_replaces_better_reference(self):
        r = p.fallback_or_protection('ortools', True)
        self.assertEqual(r['returned_score'], r['reference_score'])

    def test_empty_checks_do_not_certify_validity(self):
        self.assertFalse(payload_is_hard_valid(dict(status='ok', schedule={}, checks={})))

    def test_deferred_error_callback_keeps_message(self):
        r = p.ui_error_callback()
        self.assertIsNone(r)

    def test_unknown_day_is_not_silently_all_days(self):
        with self.assertRaises(ValueError):
            p.typo_day_roundtrip()

    def test_null_report_cap_does_not_crash(self):
        self.assertNotIn('exception', p.null_report_cap())

    def test_legacy_fallback_receives_actual_day(self):
        self.assertEqual(p.legacy_wrong_day()['received_day_indices'], [0, 1])

    def test_atomic_failure_preserves_previous_json(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'cache.json'
            path.write_text('{"old": true}')
            with patch.object(domain.os, 'replace', side_effect=OSError('disk failure')):
                with self.assertRaises(OSError):
                    domain.save_json(path, {'new': True})
            self.assertEqual(json.loads(path.read_text()), {'old': True})
            self.assertEqual(list(Path(folder).glob('*.tmp')), [])

    def test_morning_split_exists_in_full_pattern_domain(self):
        # A short horizon isolates the missing split without enumerating tens
        # of thousands of irrelevant whole-week patterns.
        d = p.data(2)
        d['sites'][0]['close'] = '11:00'
        d['rules_time'] = [['negatif', 'hard', 'Lea', 'lundi', '09:00', '10:00']]
        d['rules_site_schedule'] = [dict(site='bas', days=['lundi'], time_intervals=[
            dict(group='A', start='08:00', end='09:00', min_staff=1),
            dict(group='A', start='10:00', end='11:00', min_staff=1)])]
        result, _ = solver.make_pattern_mip_payload(d, time_limit=15, **p.OPTIONS)
        self.assertEqual(result['status'], 'ok', result)

    def test_no_unnecessary_replacements_by_source_group(self):
        r = p.impossible_replacement_count()
        self.assertEqual(r['cp'], 'ok')
        self.assertEqual(r['patterns'], 'ok', r)

    def test_gap_duration_has_an_independent_penalty(self):
        r = p.gap_score()
        self.assertLess(sum(r['gap_60'].values()), sum(r['gap_180'].values()))

    def test_profile_weights_change_the_scoring_policy(self):
        d = p.data()
        from creche_planning.scoring import compact_quality_context
        a = compact_quality_context(d, soft_time_rule_weight=1)
        b = compact_quality_context(d, soft_time_rule_weight=2.5)
        self.assertNotEqual(a['weights'], b['weights'])

    def test_latest_button_revalidates_and_prefers_latest(self):
        with tempfile.TemporaryDirectory() as folder:
            t = Path(folder); data_path = t / 'data.json'
            domain.save_json(data_path, p.data())
            good = dict(status='ok', schedule=p.schedule([p.block()]), checks={})
            domain.save_json(t/'latest.json', good)
            domain.save_json(t/'out_2026.json', dict(status='invalid'))
            cfg = dict(latest_output_json='latest.json', output_json='out.json', the_enabled=False,
                       weekly_hours_tolerance_percent=0)
            with patch.object(editor, 'find_solver_config', return_value=t/'config.json'), patch.object(editor, 'load_solver_config', return_value=cfg):
                self.assertEqual(editor.find_latest_planning(data_path), t/'latest.json')

    def test_nan_json_and_duplicate_identities_are_rejected(self):
        from creche_planning.validation import data_errors
        d = p.data(); d['educators'] *= 2
        self.assertTrue(data_errors(d))
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'bad.json'; path.write_text('{"value": NaN}')
            with self.assertRaises(ValueError):
                domain.load_json(path)

    def test_primary_hint_enumeration_is_bounded(self):
        d = p.data(0, groups=('A', 'B', 'C'))
        d['sites'][0]['close'] = '08:15'
        d['educators'] = [dict(d['educators'][0], name=f'E{i}') for i in range(12)]
        original = solver.itertools.product
        visited = []
        def product(*args):
            for item in original(*args):
                visited.append(1)
                yield item
        with patch.object(solver.itertools, 'product', product):
            result, _ = solver.make_ortools_slot_payload(d, time_limit=2, **p.OPTIONS)
        self.assertLessEqual(len(visited), 512)
        self.assertIn(result['status'], ['ok', 'infeasible_or_not_solved'])

    def test_fallback_is_attempted_with_a_hundred_second_budget(self):
        import contextlib, io
        d = p.data(2)
        failure = dict(status='infeasible_or_not_solved', solver_message='UNKNOWN', warnings=[])
        config = dict(solver_engine='pattern_mip', time_limit_seconds=100,
                      pattern_fallback_time_seconds=60, write_latest_outputs=False,
                      timestamp_outputs=False, the_enabled=False)
        with contextlib.redirect_stdout(io.StringIO()), \
             patch.object(solver, 'load_run_config', return_value=(config, ROOT)), \
             patch.object(solver, 'load_json', return_value=d), \
             patch.object(solver, 'load_latest_valid_payload', return_value=None), \
             patch.object(solver, 'make_ortools_slot_payload', return_value=(failure, p.bundle(d))), \
             patch.object(solver, 'make_pattern_mip_payload', return_value=(failure, p.bundle(d))) as mip, \
             patch.object(solver, 'print_report'), \
             patch.object(sys, 'argv', ['solveur_v2.py', 'dummy.json']):
            solver.main()
        self.assertGreater(mip.call_count, 0)

    def test_meetings_excluded_from_the_do_not_consume_invisible_the(self):
        d = p.data(3, attends=True)
        d['rules_colloques'] = [['A','lundi','08:00','08:45']]
        s = p.schedule([p.block('08:00','08:45',activity='colloque'), p.block('08:45','11:00')])
        result, _ = solver.make_ortools_slot_payload(d, time_limit=3, fixed_schedule=s,
                    the_enabled=True, the_percent=25, the_colloques_count=False,
                    weekly_hours_tolerance_percent=0, max_split_gap_minutes=None)
        self.assertEqual(result['status'], 'ok', result)

    def test_meetings_count_as_work_when_the_is_disabled(self):
        d = p.data(3, attends=True)
        d['rules_colloques'] = [['A','lundi','08:00','08:45']]
        s = p.schedule([p.block('08:00','08:45',activity='colloque'), p.block('08:45','11:00')])
        result, _ = solver.make_ortools_slot_payload(d, time_limit=3, fixed_schedule=s, **p.OPTIONS)
        self.assertEqual(result['status'], 'ok', result)

    def test_single_period_configuration_is_enforced(self):
        d = p.data(2)
        schedule = p.schedule([p.block(), p.block('10:00', '11:00')])
        result, bundle = solver.make_ortools_slot_payload(d, time_limit=3, fixed_schedule=schedule,
                                                         max_blocks_per_day=1, **p.OPTIONS)
        self.assertEqual(result['solver_message'], 'INFEASIBLE')
        checks = solver.verify_solution(bundle, schedule, max_blocks_per_day=1, **p.OPTIONS)
        self.assertTrue(checks['errors'])

    def test_empty_primary_map_cannot_hide_a_meeting_with_no_work(self):
        d = p.data(0, attends=True)
        d['rules_colloques'] = [['A', 'lundi', '08:00', '08:45']]
        self.assertTrue(p.check(d, p.schedule(), primary={})['errors'])
