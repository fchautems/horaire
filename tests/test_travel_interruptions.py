"""Short necessary journeys do not consume an ordinary daily break."""
import unittest

from test_audit_regressions import p
from creche_planning import solver
from creche_planning.domain import is_short_site_transfer
from creche_planning.pattern_mip import solve_pattern_mip


class TravelInterruptionTests(unittest.TestCase):
    def case(self, gaps=(15, 15), same_site=False):
        # A -> replacement B -> A; the real 13:15–14:00 meeting is retained.
        before_end = 13 * 60 + 15 - gaps[0]
        after_start = 14 * 60 + gaps[1]
        blocks = [p.block('11:45', p.domain.format_time(before_end)),
                  p.block('13:15', '14:00', group='B', site='haut', activity='remplacement_colloque'),
                  p.block(p.domain.format_time(after_start), '14:30')]
        if same_site:
            blocks[1]['site'] = 'bas'
        hours = sum(b['hours'] for b in blocks)
        data = p.data(hours, groups=('A', 'B'))
        data['sites'][0].update(open='11:45', close='14:30')
        data['sites'].append(dict(name='haut', open='11:45', close='14:30'))
        data['groups'][1]['site'] = 'bas' if same_site else 'haut'
        data['rules_group'] = [['positif', 'hard', 'Lea', 'A']]
        data['rules_colloques'] = [dict(group='B', day='lundi', start='13:15', end='14:00')]
        return data, p.schedule(blocks)

    def compare(self, data, schedule, **options):
        return p.compare(data, schedule, **options)

    def test_round_trip_does_not_consume_a_break(self):
        data, schedule = self.case()
        result = self.compare(data, schedule, max_blocks_per_day=1)
        self.assertEqual(result['validator_errors'], [])
        self.assertEqual(result['cp_status'], 'ok', result)

    def test_same_site_interruptions_are_still_breaks(self):
        data, schedule = self.case(same_site=True)
        result = self.compare(data, schedule)
        self.assertTrue(any('3 periodes' in e for e in result['validator_errors']))
        self.assertEqual(result['cp_message'], 'INFEASIBLE')

    def test_longer_gaps_do_not_get_a_travel_exemption(self):
        data, schedule = self.case(gaps=(30, 30))
        schedule['Lea']['lundi'][-1].update(end='14:45', hours=.25)
        for site in data['sites']:
            site['close'] = '14:45'
        data['educators'][0]['percentage'] += .25 / 40 * 100
        result = self.compare(data, schedule)
        self.assertTrue(any('3 periodes' in e for e in result['validator_errors']))
        self.assertEqual(result['cp_message'], 'INFEASIBLE')

    def test_minimum_journey_is_still_required(self):
        data, schedule = self.case(gaps=(0, 15))
        result = self.compare(data, schedule)
        self.assertTrue(any('Deplacement' in e for e in result['validator_errors']))
        self.assertEqual(result['cp_message'], 'INFEASIBLE')

    def test_travel_is_allowed_when_classic_breaks_are_disabled(self):
        data, schedule = self.case()
        result = self.compare(data, schedule, max_split_gap_minutes=0)
        self.assertEqual(result['validator_errors'], [])
        self.assertEqual(result['cp_status'], 'ok', result)

    def test_one_real_break_plus_two_journeys_is_allowed(self):
        data, schedule = self.case()
        schedule['Lea']['lundi'][0]['start'] = '12:15'
        schedule['Lea']['lundi'][0]['hours'] -= .5
        schedule['Lea']['lundi'].insert(0, p.block('11:45', '12:00'))
        data['educators'][0]['percentage'] -= .25 / 40 * 100
        result = self.compare(data, schedule)
        self.assertEqual(result['validator_errors'], [])
        self.assertEqual(result['cp_status'], 'ok', result)
        stricter = self.compare(data, schedule, max_blocks_per_day=1)
        self.assertTrue(stricter['validator_errors'])
        self.assertEqual(stricter['cp_message'], 'INFEASIBLE')

    def test_two_real_breaks_remain_forbidden_even_with_journeys(self):
        data, schedule = self.case()
        schedule['Lea']['lundi'][:1] = [p.block('11:45', '12:00'),
            p.block('12:15', '12:30'), p.block('12:45', '13:00')]
        data['educators'][0]['percentage'] -= .5 / 40 * 100
        result = self.compare(data, schedule)
        self.assertTrue(any('3 periodes' in e for e in result['validator_errors']))
        self.assertEqual(result['cp_message'], 'INFEASIBLE')

    def test_journeys_to_and_from_a_visible_meeting_are_exempt(self):
        data = p.data(1.5, groups=('A', 'B', 'C'), attends=True)
        data['sites'].append(dict(name='haut', open='08:00', close='18:00'))
        data['groups'][1]['site'] = 'haut'
        data['rules_group'] = [['positif', 'hard', 'Lea', 'B']]
        data['rules_colloques'] = [dict(group=g, day='lundi', start=a, end=z)
            for g,a,z in [('A','12:30','13:00'), ('B','13:15','14:00'), ('C','14:15','14:30')]]
        schedule = p.schedule([p.block('12:30','13:00', activity='remplacement_colloque'),
            p.block('13:15','14:00', group='B', site='haut', activity='colloque'),
            p.block('14:15','14:30', group='C', activity='remplacement_colloque')])
        result = p.compare(data, schedule, primary={'Lea':'B'}, the_enabled=True,
            the_percent=50, max_blocks_per_day=1)
        self.assertEqual(result['validator_errors'], [])
        self.assertEqual(result['cp_status'], 'ok', result)

    def test_travel_time_never_covers_children(self):
        data, schedule = self.case()
        data['rules_site_schedule'] = [dict(site='bas', days=['lundi'], time_intervals=[
            dict(group='A', start='13:00', end='13:15', min_staff=1)])]
        result = self.compare(data, schedule)
        self.assertTrue(any('13:00' in e for e in result['validator_errors']))
        self.assertEqual(result['cp_message'], 'INFEASIBLE')

    def test_grid_boundary_only_exempts_the_necessary_duration(self):
        previous = p.block('11:00', '12:00')
        for step, accepted in [(5, {10}), (10, {10}), (15, {10, 15})]:
            for gap in [0, 5, 10, 15, 20, 30]:
                current = p.block(p.domain.format_time(12*60+gap), '13:00', site='haut')
                self.assertEqual(is_short_site_transfer(previous, current, step), gap in accepted)

    def test_pattern_engine_preserves_fixed_journey_gaps(self):
        data, schedule = self.case()
        result, _ = solve_pattern_mip(data, time_limit=15, fixed_daily_schedules=schedule,
            fixed_primary_groups={0:0}, the_percent=0, weekly_hours_tolerance_percent=0,
            min_daily_hours=0, max_split_gap_minutes=None)
        self.assertEqual(result['status'], 'ok', result)
        self.assertEqual(result['checks']['errors'], [])
        self.assertEqual(result['schedule'], schedule)

    def test_pattern_engine_can_generate_a_round_trip(self):
        data, _ = self.case()
        data['rules_global']['max_daily_hours'] = 2.25
        data['rules_time'] = [['negatif', 'hard', 'Lea', day, '11:45', '14:30']
                              for day in p.DAYS if day != 'lundi']
        data['rules_site_schedule'] = [
            dict(site='bas', days=['lundi'], time_intervals=[
                dict(group='A', start='11:45', end='13:00', min_staff=1),
                dict(group='A', start='14:15', end='14:30', min_staff=1)]),
            dict(site='haut', days=['lundi'], time_intervals=[
                dict(group='B', start='13:15', end='14:00', min_staff=1)])]
        result, _ = solve_pattern_mip(data, time_limit=15, fixed_primary_groups={0:0},
            the_percent=0, weekly_hours_tolerance_percent=0, min_daily_hours=0,
            max_split_gap_minutes=None)
        self.assertEqual(result['status'], 'ok', result)
        self.assertEqual(result['checks']['errors'], [])
        self.assertEqual(len(result['schedule']['Lea']['lundi']), 3)

    def test_pattern_minimum_daily_hours_excludes_travel(self):
        data, schedule = self.case()
        result, _ = solve_pattern_mip(data, time_limit=15, fixed_daily_schedules=schedule,
            fixed_primary_groups={0:0}, the_percent=0, weekly_hours_tolerance_percent=0,
            min_daily_hours=2.5, enforce_min_daily_hours=True, max_split_gap_minutes=None)
        self.assertNotEqual(result['status'], 'ok')

    def test_pattern_can_generate_an_ordinary_site_change_without_classic_breaks(self):
        data = p.data(1.75, groups=('A', 'B'))
        data['sites'][0].update(open='11:30', close='13:30')
        data['sites'].append(dict(name='haut', open='11:30', close='13:30'))
        data['groups'][1]['site'] = 'haut'
        data['rules_group'] = [['positif','hard','Lea','A']]
        data['rules_time'] = [['negatif','hard','Lea',day,'11:30','13:30']
                              for day in p.DAYS if day != 'lundi']
        data['rules_site_schedule'] = [
            dict(site='bas', days=['lundi'], time_intervals=[
                dict(group='A',start='11:30',end='12:30',min_staff=1)]),
            dict(site='haut', days=['lundi'], time_intervals=[
                dict(group='B',start='12:45',end='13:30',min_staff=1)])]
        result, _ = solve_pattern_mip(data, time_limit=15, fixed_primary_groups={0:0},
            the_enabled=False, weekly_hours_tolerance_percent=0, min_daily_hours=0,
            max_split_gap_minutes=0)
        self.assertEqual(result['status'], 'ok', result)
        self.assertEqual(result['checks']['errors'], [])

