"""Desired behavior for the independently reproduced second-review defects."""
import copy
import importlib.util
from pathlib import Path
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('second_review_probes',
    ROOT / 'docs/audits/2026-10-19-second-review/probes.py')
p = importlib.util.module_from_spec(spec)
spec.loader.exec_module(p)


def assignments(schedule):
    return {(name,day,slot):(b['group'],b['site'],b.get('activity') or 'children')
        for name,days in schedule.items() for day,blocks in days.items()
        for b in blocks for slot in range(p.domain.parse_time(b['start']),p.domain.parse_time(b['end']),15)}


class SecondReviewRegressions(unittest.TestCase):
    def assertValid(self, result):
        self.assertEqual(result['status'], 'ok', result)
        self.assertEqual(result['checks']['errors'], [])

    def test_free_round_trip_respects_both_forbidden_journey_slots(self):
        d,s=p.round_trip(); p.require_coverage(d,s)
        d['rules_time'] += [['negatif','hard','Lea','lundi',a,z]
            for a,z in [('13:00','13:15'),('14:00','14:15')]]
        result=p.patterns(d)
        self.assertValid(result)
        self.assertEqual(assignments(result['schedule']), assignments(s))

    def test_empty_journeys_do_not_incur_time_preference_costs(self):
        d,s=p.round_trip(); p.require_coverage(d,s)
        base=p.patterns(d)
        self.assertValid(base)
        for preference in ['negatif','positif']:
            with self.subTest(preference=preference):
                changed=copy.deepcopy(d)
                changed['rules_time'] += [[preference,'soft','Lea','lundi',a,z]
                    for a,z in [('13:00','13:15'),('14:00','14:15')]]
                result=p.patterns(changed)
                self.assertValid(result)
                self.assertEqual(assignments(result['schedule']),assignments(s))
                self.assertEqual(result['objective'],base['objective'])

    def extended_replacement(self):
        return p.make_case([p.block('12:45','13:00'),
            p.block('13:00','14:30','B','bas','remplacement_colloque'),
            p.block('14:30','14:45')],two_sites=False)

    def test_fixed_replacement_keeps_its_entire_window(self):
        d,s=self.extended_replacement()
        result=p.patterns(d,s)
        self.assertValid(result)
        self.assertEqual(assignments(result['schedule']),assignments(s))

    def test_free_replacement_covers_authorized_margins(self):
        d,s=self.extended_replacement(); p.require_coverage(d,s)
        result=p.patterns(d)
        self.assertValid(result)
        self.assertEqual(assignments(result['schedule']),assignments(s))

    def test_fixed_replacement_covers_authorized_margins(self):
        d,s=self.extended_replacement(); p.require_coverage(d,s)
        result=p.patterns(d,s)
        self.assertValid(result)
        self.assertEqual(assignments(result['schedule']),assignments(s))

    def test_partial_replacement_without_full_meeting_is_generated(self):
        d,s=p.make_case([p.block('12:45','13:00'),
            p.block('13:00','13:30','B','bas','remplacement_colloque'),
            p.block('13:30','13:45')],two_sites=False)
        p.require_coverage(d,s)
        for fixed in [None,s]:
            with self.subTest(fixed=bool(fixed)):
                result=p.patterns(d,fixed)
                self.assertValid(result)
                self.assertEqual(assignments(result['schedule']),assignments(s))

    def test_journeys_are_not_reported_as_classic_gap_violations(self):
        d,s=p.round_trip()
        result=p.validate(d,s,max_split_gap_minutes=0)
        self.assertEqual(result['errors'],[])
        metrics=result['quality_summary']['metrics']
        self.assertEqual(metrics['split_gap_violations'],0)
        self.assertEqual(metrics['split_gaps_count'],0)
        self.assertEqual(metrics['travel_gaps_count'],2)
        self.assertEqual(metrics['total_travel_gap_hours'],.5)
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'report.html'
            p.reports.write_html(path,dict(status='ok',schedule=s,checks=result),p.bundle(d))
            self.assertIn('<td>Coupures</td><td>0 jour(s), plus grande 0 min</td><td>OK</td>',path.read_text())

    def test_real_break_is_still_reported_beside_journeys(self):
        d,s=p.round_trip()
        s['Lea']['lundi'][0:1]=[p.block('11:45','12:00'),p.block('12:15','13:00')]
        d['educators'][0]['percentage']=2.25/40*100
        result=p.validate(d,s,max_split_gap_minutes=0)
        metrics=result['quality_summary']['metrics']
        self.assertEqual(metrics['split_gap_violations'],1)
        self.assertEqual(metrics['split_gaps_count'],1)
        self.assertEqual(metrics['travel_gaps_count'],2)
        self.assertTrue(any('coupure de 15' in error for error in result['errors']))

    def test_rule_summary_describes_actual_replacement_rule(self):
        d,_=p.round_trip()
        rule=next(r['rule'] for r in p.reports.build_rule_summary(d,{})['hard'] if r['code']=='colloques')
        self.assertNotIn('une personne de chaque',rule)
        self.assertIn('couverture',rule)
        self.assertIn('quinze minutes avant',rule)
        self.assertIn('trente minutes apres',rule)

    def test_hard_presence_on_empty_travel_is_not_satisfied(self):
        d,s=p.round_trip(); p.require_coverage(d,s)
        d['rules_time'].append(['positif','hard','Lea','lundi','13:00','13:15'])
        result=p.patterns(d)
        self.assertNotEqual(result['status'],'ok')
        self.assertIn('Infeasible',result['solver_message'])

    def test_forbidden_actual_work_remains_forbidden(self):
        d,s=p.round_trip(); p.require_coverage(d,s)
        d['rules_time'].append(['negatif','hard','Lea','lundi','12:45','13:00'])
        result=p.patterns(d)
        self.assertNotEqual(result['status'],'ok')
        self.assertIn('Infeasible',result['solver_message'])

    def test_contract_and_coverage_still_exclude_journeys(self):
        d,s=p.round_trip(); p.require_coverage(d,s)
        d['educators'][0]['percentage']=3.25/40*100
        # Isolate accounting from the search budget. Free travel generation is
        # exercised by the dedicated round-trip and replacement tests above.
        result=p.patterns(d,s,the_percent=25)
        self.assertValid(result)
        self.assertEqual(result['checks']['hours_by_educator']['Lea'],3.25)
        self.assertEqual(result['checks']['child_hours_by_educator']['Lea'],2.5)
        self.assertEqual(result['checks']['invisible_the_hours_by_educator']['Lea'],.75)

    def test_capacity_diagnostic_has_no_quota_by_source_group(self):
        d,_=p.round_trip()
        d['educators'][0]['percentage']=0
        errors=p.solver.diagnose_the_capacity(d,p.domain.make_horizon(d),the_percent=0,
                                              weekly_hours_tolerance_percent=0)
        self.assertEqual(errors,[])
        d['rules_site_schedule']=[dict(site='bas',days=['lundi'],time_intervals=[
            dict(group='A',start='12:00',end='13:00',min_staff=1)])]
        errors=p.solver.diagnose_the_capacity(d,p.domain.make_horizon(d),the_percent=0,
                                              weekly_hours_tolerance_percent=0)
        self.assertTrue(any(e.startswith('Capacite enfants insuffisante') for e in errors))

    def test_fixed_replacement_outside_window_is_rejected_not_shortened(self):
        d,s=self.extended_replacement()
        s['Lea']['lundi']=[p.block('12:45','14:45','B','bas','remplacement_colloque')]
        result=p.patterns(d,s)
        self.assertNotEqual(result['status'],'ok')
        self.assertIn('Aucun patron possible',result['solver_message'])

    def test_group_prohibition_does_not_block_authentic_replacement(self):
        d,s=self.extended_replacement(); p.require_coverage(d,s)
        d['rules_group'].append(['negatif','hard','Lea','B'])
        result=p.patterns(d)
        self.assertValid(result)
        self.assertEqual(assignments(result['schedule']),assignments(s))

    def test_fixed_multiple_replacements_are_not_overwritten(self):
        d,s=self.extended_replacement()
        d['groups'].append(dict(name='C',site='bas'))
        d['rules_colloques'].append(dict(group='C',day='lundi',start='14:15',end='14:45'))
        s['Lea']['lundi']=[p.block('12:45','13:00'),
            p.block('13:00','13:45','B','bas','remplacement_colloque'),
            p.block('13:45','14:00'),
            p.block('14:00','14:45','C','bas','remplacement_colloque')]
        p.require_coverage(d,s)
        result=p.patterns(d,s)
        self.assertValid(result)
        self.assertEqual(assignments(result['schedule']),assignments(s))
