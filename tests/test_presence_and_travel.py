"""Business decisions of 18 October: partial presence windows and real intersite journeys."""
import unittest
from test_audit_regressions import p
from creche_planning import solver


class PresenceAndTravelTests(unittest.TestCase):
    def test_required_window_means_work_during_day_not_full_window(self):
        result = p.partial_required()
        self.assertEqual(result['validator_errors'], [])
        self.assertEqual(result['cp_status'], 'ok', result)

    def travel_case(self, gap):
        d = p.data(2, groups=('A', 'B'))
        d['sites'].append(dict(name='haut', open='08:00', close='18:00'))
        d['groups'][1]['site'] = 'haut'
        start = 12*60 + 30 + gap
        s = p.schedule([p.block('11:30','12:30'),
                        p.block(p.domain.format_time(start), p.domain.format_time(start+60), group='B',site='haut')])
        return d, s

    def test_cross_site_adjacent_blocks_are_rejected_by_both(self):
        d,s = self.travel_case(0)
        r = p.compare(d,s)
        self.assertTrue(any('Deplacement' in e for e in r['validator_errors']))
        self.assertEqual(r['cp_message'], 'INFEASIBLE')

    def test_cross_site_one_free_grid_slot_is_valid(self):
        d,s = self.travel_case(15)
        r = p.compare(d,s)
        self.assertEqual(r['validator_errors'], [])
        self.assertEqual(r['cp_status'], 'ok', r)

    def test_journey_is_required_even_for_visible_meeting(self):
        d,s = self.travel_case(0)
        d['educators'][0]['attends_colloque'] = True
        d['rules_group'] = [['positif', 'hard', 'Lea', 'B']]
        d['rules_colloques'] = [dict(group='B',day='lundi',start='12:30',end='13:15')]
        s['Lea']['lundi'][0]['activity']='remplacement_colloque'
        # Direct journey helper includes every activity, even if other rules fail.
        s['Lea']['lundi'][1]['activity']='colloque'
        self.assertTrue(solver.hard_site_travel_errors(s))
        r=p.compare(d,s,primary={'Lea':'B'})
        self.assertEqual(r['cp_message'], 'INFEASIBLE')

    def test_minute_exact_journey_boundary(self):
        for gap in [0,5,9,10,15]:
            d,s = self.travel_case(gap)
            with self.subTest(gap=gap):
                self.assertEqual(bool(solver.hard_site_travel_errors(s)),gap<10)

    def test_pattern_site_sequence_preserves_full_slot_duration(self):
        for step in [5,10,15]:
            for distance in range(1,5):
                with self.subTest(step=step,distance=distance):
                    self.assertEqual(solver.site_sequence_has_travel_time([(0,'bas'),(distance,'haut')],step),
                                     (distance-1)*step>=10)
        self.assertTrue(solver.site_sequence_has_travel_time([(0,'bas'),(1,'bas')],15))

    def test_missing_required_day_is_rejected(self):
        d=p.data(1)
        d['rules_time']=[['positif','hard','Lea','mardi','08:00','09:00']]
        r=p.compare(d,p.schedule([p.block()]))
        self.assertTrue(r['validator_errors'])
        self.assertEqual(r['cp_message'],'INFEASIBLE')

    def test_same_site_group_change_at_half_day_needs_no_gap(self):
        d,s=self.travel_case(0)
        d['groups'][1]['site']='bas'
        s['Lea']['lundi'][1]['site']='bas'
        result=p.compare(d,s)
        self.assertEqual(result['validator_errors'],[])
        self.assertEqual(result['cp_status'],'ok',result)

    def test_pattern_engine_filters_only_journeys_without_enough_time(self):
        from creche_planning.pattern_mip import solve_pattern_mip
        for gap in (0,15):
            d,s=self.travel_case(gap)
            for site in d['sites']:
                site.update(open='11:30',close='14:00')
            with self.subTest(gap=gap):
                result,_=solve_pattern_mip(d,time_limit=15,the_enabled=False,min_daily_hours=0,
                    fixed_daily_schedules=s,fixed_primary_groups={0:0},max_split_gap_minutes=None,
                    weekly_hours_tolerance_percent=0)
                self.assertEqual(result['status']=='ok',gap>=10,result)
                if gap>=10:
                    self.assertEqual(result['checks']['errors'],[])
                else:
                    self.assertIn('Aucun patron possible',result['solver_message'])

    def test_compact_engine_locates_visible_meetings_and_real_replacements(self):
        for gap in (0,15):
            d=p.data(2.25,groups=('A','B'),attends=True)
            d['sites'].append(dict(name='haut',open='08:00',close='18:00'))
            d['groups'][1]['site']='haut'
            d['rules_group']=[['positif','hard','Lea','B']]
            meeting_start=12*60+30+gap
            meeting_end=meeting_start+45
            d['rules_colloques']=[dict(group='A',day='lundi',start='11:45',end='12:30'),
                dict(group='B',day='lundi',start=p.domain.format_time(meeting_start),end=p.domain.format_time(meeting_end))]
            s=p.schedule([p.block('11:45','12:30',activity='remplacement_colloque'),
                p.block(p.domain.format_time(meeting_start),p.domain.format_time(meeting_end),group='B',site='haut',activity='colloque'),
                p.block(p.domain.format_time(meeting_end),p.domain.format_time(meeting_end+45),group='B',site='haut')])
            with self.subTest(gap=gap):
                result=p.compare(d,s,primary={'Lea':'B'})
                self.assertEqual(result['cp_status']=='ok',gap>=10,result)
                if gap>=10:
                    self.assertEqual(result['validator_errors'],[])
                else:
                    self.assertTrue(any('Deplacement' in e for e in result['validator_errors']))
