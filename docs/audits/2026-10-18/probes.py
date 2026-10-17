"""Reproductions de l'audit, sans modifier le moteur ni les données métier.

Exécuter depuis la racine : python docs/audits/2026-10-18/probes.py
Les sorties décrivent le comportement observé, pas le comportement souhaité.
"""
from __future__ import annotations

import contextlib
import copy
import io
import json
import inspect
import math
import os
from pathlib import Path
import sys
import tempfile
import time
from types import SimpleNamespace
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / 'src'))
from creche_planning import domain, editor, solver
from creche_planning.pattern_search import payload_is_hard_valid
from creche_planning.scoring import compact_quality_context, compact_quality_breakdown

DAYS = [day for day, _ in domain.DAYS]
OPTIONS = dict(the_enabled=False, weekly_hours_tolerance_percent=0,
               max_split_gap_minutes=None)
RESULTS = {}


def data(contract=1, groups=('A',), *, attends=False):
    return dict(
        sites=[dict(name='bas', open='08:00', close='18:00')],
        groups=[dict(name=g, site='bas') for g in groups],
        educators=[dict(name='Lea', type='EDE', percentage=contract / 40 * 100,
                        attends_colloque=attends, max_work_days=5)],
        educator_types=[dict(name='EDE'), dict(name='ASE')],
        rules_global=dict(max_weekly_hours=40, max_daily_hours=8.5),
        rules_time=[], rules_group=[], rules_percentage=[],
        rules_site_schedule=[], rules_colloques=[])


def block(start='08:00', end='09:00', *, group='A', site='bas', activity=None):
    result = dict(start=start, end=end, group=group, site=site,
                  hours=round((domain.parse_time(end) - domain.parse_time(start))/60, 2))
    if activity:
        result['activity'] = activity
    return result


def schedule(blocks=(), day='lundi'):
    return {'Lea': {key: list(blocks) if key == day else [] for key in DAYS}}


def bundle(d):
    return SimpleNamespace(data=d, horizon=domain.make_horizon(d), groups=d['groups'],
                           educators=d['educators'], sites=[s['name'] for s in d['sites']])


def check(d, s, primary=None, **options):
    return solver.verify_solution(bundle(d), s,
        primary_groups_by_educator={'Lea': 'A'} if primary is None else primary,
        **(OPTIONS | options))


def compare(d, s, primary=None, **options):
    checks = check(d, s, primary, **options)
    payload, _ = solver.make_ortools_slot_payload(d, fixed_schedule=s,
                    time_limit=3, **(OPTIONS | options))
    return dict(validator_errors=checks['errors'], cp_status=payload['status'],
                cp_message=payload.get('solver_message'),
                cp_errors=payload.get('checks', {}).get('errors', []))


def record(name, fn):
    try:
        RESULTS[name] = fn()
    except Exception as exc:
        RESULTS[name] = dict(exception=type(exc).__name__, message=str(exc))


def ordinary_forbidden():
    d = data(groups=('A', 'B'))
    d['rules_group'] = [['negatif', 'hard', 'Lea', 'A']]
    return compare(d, schedule([block()]), primary={'Lea': 'B'})


def partial_required():
    d = data()
    d['rules_time'] = [['positif', 'hard', 'Lea', 'lundi', '08:00', '12:00']]
    return compare(d, schedule([block()]))


def fake_activity(activity):
    d = data(2 if activity == 'remplacement_colloque' else 1, groups=('A', 'B'))
    blocks = [block()]
    if activity == 'remplacement_colloque':
        blocks += [block('09:00', '10:00', group='B', activity=activity)]
    else:
        blocks = [block(activity=activity)]
    return compare(d, schedule(blocks))


def unknown_educator():
    d = data(0)
    d['rules_site_schedule'] = [dict(site='bas', days=['lundi'],
        time_intervals=[dict(start='08:00', end='09:00', group='A', min_staff=1)])]
    s = schedule()
    s['Ancienne employée'] = {key: [block()] if key == 'lundi' else [] for key in DAYS}
    payload, _ = solver.revalidate_cached_payload(d, dict(status='ok', schedule=s,
        checks={'primary_groups_by_educator': {'Lea': 'A'}}), **OPTIONS)
    return dict(cache_status=payload['status'], errors=payload['checks']['errors'])


def wrong_site():
    d = data()
    d['sites'].append(dict(name='haut', open='08:00', close='18:00'))
    return check(d, schedule([block(site='haut')]))['errors']


def off_grid():
    return compare(data(), schedule([block('08:01', '09:01')]))


def nan_hours():
    b = block()
    b['hours'] = float('nan')
    c = check(data(), schedule([b]))
    return dict(errors=c['errors'], nan_total=str(c['hours_by_educator']['Lea']),
                worked_days=c['worked_days_by_educator']['Lea'])


def missing_primary():
    d = data(1, attends=True)
    d['rules_colloques'] = [['A', 'mardi', '08:00', '08:45']]
    return check(d, schedule([block()]), primary={})['errors']


def multiple_meetings():
    d = data(4, attends=True)
    d['rules_colloques'] = [['A', 'lundi', '08:00', '08:45'],
                            ['A', 'mardi', '08:00', '08:45']]
    s = schedule([block('09:00', '12:00')])
    s['Lea']['mardi'] = [block('08:00', '08:45', activity='colloque')]
    return compare(d, s, the_enabled=True, the_percent=25)


def simultaneous_meetings():
    d = data(4, groups=('A', 'B'), attends=True)
    d['rules_group'] = [['positif', 'hard', 'Lea', 'A']]
    d['rules_colloques'] = [['A', 'lundi', '08:00', '08:45'],
                            ['B', 'lundi', '08:00', '08:45']]
    return compare(d, schedule([block('08:00', '08:45', activity='colloque'),
                               block('09:00', '12:00')]),
                   the_enabled=True, the_percent=25)


def the_budget():
    d = data(1, attends=True)
    d['rules_colloques'] = [['A', 'lundi', '08:00', '08:45']]
    s = schedule([block('08:00', '08:45', activity='colloque'),
                  block('08:45', '09:00')])
    c = check(d, s, the_enabled=True)
    return compare(d, s, the_enabled=True) | dict(
        target_the=c['weekly_the_targets'], actual_the=c['total_the_hours_by_educator'])


def aliases():
    d = data()
    d['rules_percentage'] = [[['ancien'], 'min', 100, 'bas']]
    p, _ = solver.make_ortools_slot_payload(d, fixed_schedule=schedule([block()]),
        time_limit=3, type_aliases={'ancien': 'EDE'}, **OPTIONS)
    return dict(status=p['status'], errors=p.get('checks', {}).get('errors', []),
                model_status=p.get('cp_sat_statistics', {}).get('feasibility', {}).get('status'))


def staffing_max():
    d = data()
    d['educators'].append(dict(d['educators'][0], name='Emilie'))
    s = schedule([block()])
    s['Emilie'] = copy.deepcopy(s['Lea'])
    d['rules_site_schedule'] = [dict(site='bas', days=['lundi'],
        time_intervals=[dict(start='08:00', end='09:00', group='A', min_staff=0, max_staff=1)])]
    return compare(d, s, primary={'Lea': 'A', 'Emilie': 'A'})


def opening_hours():
    d = data()
    d['sites'][0]['close'] = '12:00'
    d['sites'].append(dict(name='haut', open='08:00', close='18:00'))
    return compare(d, schedule([block('14:00', '15:00')]))


def gap_score():
    d = data(2)
    context = compact_quality_context(d, the_enabled=False)
    def score(end):
        p = dict(schedule=schedule([block(), block(end, domain.format_time(domain.parse_time(end)+60))]),
                 checks={'primary_groups_by_educator': {'Lea': 'A'}})
        return compact_quality_breakdown(p, context)
    return dict(gap_60=score('10:00'), gap_180=score('12:00'))


def impossible_replacement_count():
    d = data(1, groups=('A', 'B', 'C'), attends=True)
    d['rules_group'] = [['positif', 'hard', 'Lea', 'A']]
    d['rules_colloques'] = [['A', 'lundi', '08:00', '08:45']]
    # No children need coverage at this colloque: forcing two replacements
    # contradicts the rule "only actual lost coverage".
    # Minimal genuine model with 3 h contract / .75 THE.
    d['educators'][0]['percentage'] = 3 / 40 * 100
    s = schedule([block('08:00', '08:45', activity='colloque'), block('08:45', '11:00')])
    cp, _ = solver.make_ortools_slot_payload(d, fixed_schedule=s, time_limit=3,
        the_enabled=True, the_percent=25, weekly_hours_tolerance_percent=0,
        max_split_gap_minutes=None)
    mip, _ = solver.make_pattern_mip_payload(d, time_limit=10,
        fixed_primary_groups={0: 0}, fixed_daily_schedules=s,
        the_enabled=True, the_percent=25, weekly_hours_tolerance_percent=0,
        max_split_gap_minutes=None)
    return dict(cp=cp['status'], patterns=mip['status'], pattern_message=mip['solver_message'])


def fallback_or_protection(engine='pattern_mip', valid=False):
    d = data(2)
    good_s = schedule([block('08:00', '10:00')])
    bad_s = schedule([block(), block('10:00', '11:00')])
    ctx = compact_quality_context(d, the_enabled=False, work_day_weight=45)
    def payload(s):
        return dict(status='ok', schedule=s, checks=check(d, s), quality_scoring=ctx,
                    objective=0, solver_message='probe', warnings=[])
    good, worse = payload(good_s), payload(bad_s)
    failure = dict(status='infeasible_or_not_solved', solver_message='UNKNOWN', warnings=[])
    cfg = dict(solver_engine=engine, time_limit_seconds=100, pattern_fallback_time_seconds=60,
        compact_candidate_first=True, write_latest_outputs=False,
        timestamp_outputs=False, the_enabled=False, weekly_hours_tolerance_percent=0)
    captured = []
    with contextlib.redirect_stdout(io.StringIO()), \
         patch.object(solver, 'load_run_config', return_value=(cfg, ROOT)), \
         patch.object(solver, 'load_json', return_value=d), \
         patch.object(solver, 'load_latest_valid_payload', return_value=good if valid else None), \
         patch.object(solver, 'make_ortools_slot_payload', return_value=(worse if valid else failure, bundle(d))) as cp, \
         patch.object(solver, 'make_pattern_mip_payload') as mip, \
         patch.object(solver, 'print_report', side_effect=captured.append), \
         patch.object(sys, 'argv', ['solveur_v2.py', 'dummy.json']):
        code = solver.main()
    return dict(return_code=code, compact_calls=cp.call_count, pattern_calls=mip.call_count,
                returned_status=captured[-1]['status'],
                reference_score=solver.planning_quality_score(good, context=ctx),
                returned_score=solver.planning_quality_score(captured[-1], context=ctx),
                warnings=captured[-1].get('warnings'))


def ui_error_callback():
    callbacks = []
    dummy = SimpleNamespace(after=lambda delay, fn: callbacks.append(fn))
    with patch.object(editor.subprocess, 'Popen', side_effect=OSError('probe')):
        dialog = SimpleNamespace(finish=lambda *args: None)
        editor.CrecheEditor._run_solver_thread(dummy, [], Path('unused'), dialog, ROOT, 1)
    try:
        callbacks[0]()
    except Exception as exc:
        return dict(callbacks=len(callbacks), exception=type(exc).__name__, message=str(exc))


def editor_latest():
    with tempfile.TemporaryDirectory() as temp:
        t = Path(temp)
        latest, diagnostic = t/'latest.json', t/'out_2026.json'
        latest.write_text('{"status":"ok"}')
        diagnostic.write_text('{"status":"invalid"}')
        os.utime(latest, (1, 1)); os.utime(diagnostic, (2, 2))
        cfg = t/'cfg.json'; cfg.write_text('{}')
        with patch.object(editor, 'find_solver_config', return_value=cfg), \
             patch.object(editor, 'load_solver_config', return_value={
                 'latest_output_json': str(latest), 'output_json': str(t/'out.json')}):
            return dict(selected=editor.find_latest_planning(t/'data.json').name,
                        valid_latest_exists=latest.exists())


def typo_day_roundtrip():
    d = data()
    d['rules_site_schedule'] = [dict(site='bas', time_intervals=[dict(
        start='08:00', end='09:00', group='A', min_staff=1, days=['lunddi'])])]
    rows = editor.rows_from_data(d, 'rules_site_schedule')
    editor.rows_to_data(d, 'rules_site_schedule', rows)
    demands, _ = domain.build_demands_by_day(d, d['groups'], domain.make_horizon(d))
    return dict(serialized=d['rules_site_schedule'], demanded_days=[DAYS[i] for i in range(5)
        if any(v for (day, _, _), v in demands.items() if day == i)])


def weak_validity():
    return dict(empty_checks_accepted=payload_is_hard_valid(dict(status='ok', schedule={}, checks={})))


def null_report_cap():
    from creche_planning.reports import build_rule_summary
    return build_rule_summary(data(), {'absolute_max_weekly_hours': None,
                                      'enforce_absolute_max_weekly_hours': False})


def profiles():
    from creche_planning.quality import select_quality_profile
    contexts = {}
    for profile in ('equilibre', 'preferences_horaires'):
        _, _, weights, _ = select_quality_profile({}, profile)
        contexts[profile] = dict(declared_time_weight=weights['soft_time_rule_weight'],
            context=compact_quality_context(data(),
                split_shift_weight=weights['smooth_split_shift_weight'],
                group_switch_day_weight=weights['smooth_group_switch_day_weight'],
                same_group_week_weight=weights['smooth_same_group_week_weight']))
    return contexts


def generation_budget():
    d = data(0, groups=('A', 'B', 'C'))
    d['sites'][0]['close'] = '08:15'
    d['educators'] = [dict(d['educators'][0], name=f'E{i}') for i in range(12)]
    start = time.monotonic()
    p, _ = solver.make_ortools_slot_payload(d, time_limit=2, **OPTIONS)
    return dict(requested_seconds=2, elapsed_seconds=round(time.monotonic()-start, 3),
                combinations=3**12, status=p['status'])


def legacy_wrong_day():
    import ast
    tree = ast.parse(inspect.getsource(solver.smooth_schedule))
    target = next(node for node in ast.walk(tree) if isinstance(node, ast.For) and any(
        isinstance(child, ast.Call) and isinstance(child.func, ast.Name)
        and child.func.id == 'solve_group_assignment' for child in ast.walk(node))
        and isinstance(node.target, ast.Tuple) and len(node.target.elts) == 2
        and isinstance(node.target.elts[0], ast.Name) and node.target.elts[0].id == 'task_i')
    received = []
    namespace = dict(task_records=[(0,'lundi','bas','bas',[(0,4)],{0:((0,4),)}),
                                   (1,'mardi','bas','bas',[(0,4)],{0:((0,4),)})],
                     d_i=4, solve_group_assignment=lambda people,site,day,work: received.append(day))
    # Execute the original fallback loop; returning None skips schedule rebuilding.
    exec(compile(ast.fix_missing_locations(ast.Module(body=[target], type_ignores=[])),
                 'original_legacy_fallback', 'exec'), namespace)
    return dict(expected_day_indices=[0,1], received_day_indices=received,
                evidence='Exécution isolée de la boucle AST originale, pas de calcul natif.')


def morning_split():
    d = data(2)
    d['rules_time'] = [['negatif','hard','Lea','lundi','09:00','10:00'],
                       ['negatif','hard','Lea','lundi','11:00','18:00']]
    d['rules_site_schedule'] = [dict(site='bas',days=['lundi'],time_intervals=[
        dict(group='A', start='08:00',end='09:00', min_staff=1),
        dict(group='A', start='10:00',end='11:00', min_staff=1)])]
    s = schedule([block(), block('10:00','11:00')])
    cp, _ = solver.make_ortools_slot_payload(d, time_limit=3, fixed_schedule=s, **OPTIONS)
    mip, _ = solver.make_pattern_mip_payload(d, time_limit=10, **OPTIONS)
    return dict(cp_status=cp['status'], validator_errors=check(d,s)['errors'],
                pattern_status=mip['status'], pattern_message=mip['solver_message'])


def malformed_cache():
    b = block(); del b['group']
    return solver.revalidate_cached_payload(data(), dict(status='ok', schedule=schedule([b]),
        checks={'primary_groups_by_educator': {'Lea':'A'}}), **OPTIONS)


def non_atomic_write():
    with tempfile.TemporaryDirectory() as tmp:
        p = Path(tmp)/'latest.json'; p.write_text('{"old_valid":true}')
        def disk_failure(payload, handle, **kwargs):
            handle.write('{'); raise OSError('simulated disk failure')
        with patch.object(domain.json, 'dump', side_effect=disk_failure):
            try:
                domain.save_json(p, {'new':'candidate'})
            except OSError:
                pass
        return dict(contents_after_failure=p.read_text(), old_content_lost=True,
                    fault='Erreur d’écriture injectée; aucune panne réelle revendiquée.')


def current_candidate():
    e = json.loads((ROOT/'docs/experiments/2026-10-17-global-restart-300s/evidence.json').read_text())
    p, cond = json.loads(e['result.json']), json.loads(e['conditions.json'])
    d = json.loads((ROOT/'data/gwendo.json').read_text())
    allowed = inspect.signature(solver.verify_solution).parameters
    opts = {k:v for k,v in cond['options'].items() if k in allowed}
    c = solver.verify_solution(bundle(d), p['schedule'],
          primary_groups_by_educator=p['checks']['primary_groups_by_educator'], **opts)
    schema_errors, replacement_outside = [], []
    groups = {g['name']:g for g in d['groups']}
    meetings = domain.parse_colloques(d, domain.make_horizon(d), d['groups'])
    slots_by_meeting = {(m['group'],m['day']): set(m['slots']) for m in meetings}
    h = domain.make_horizon(d)
    expected_names = {x['name'] for x in d['educators']}
    if set(p['schedule']) != expected_names:
        schema_errors.append('educator identities')
    for name, by_day in p['schedule'].items():
        if set(by_day) != set(DAYS):
            schema_errors.append(f'days: {name}')
        for day, blocks in by_day.items():
            previous_end = None
            for b in sorted(blocks, key=lambda b: domain.parse_time(b['start'])):
                start, end = domain.parse_time(b['start']), domain.parse_time(b['end'])
                if (not math.isfinite(b['hours']) or end <= start or
                    not h.start <= start < end <= h.end or
                    (start-h.start)%h.step or (end-h.start)%h.step or
                    abs(b['hours']-(end-start)/60)>1e-6 or
                    b['site'] != groups[b['group']]['site'] or
                    previous_end is not None and start < previous_end):
                    schema_errors.append(f'{name} {day} {b}')
                previous_end = max(previous_end or end, end)
                if b.get('activity') == 'remplacement_colloque':
                    bslots = set(range((start-h.start)//h.step,(end-h.start)//h.step))
                    outside = bslots - slots_by_meeting.get((b['group'],day),set())
                    if outside:
                        replacement_outside.append(dict(name=name,day=day,group=b['group'],
                            start=b['start'],end=b['end'],minutes_outside=len(outside)*h.step))
    experiments = compact_quality_context(d, **{k:v for k,v in cond['weights'].items()
                            if k in inspect.signature(compact_quality_context).parameters})
    configured = dict(experiments, weights=dict(experiments['weights'], worked_days=4500))
    return dict(validator_errors=c['errors'], structural_errors=schema_errors,
        experimental_score=sum(compact_quality_breakdown(p, experiments).values()),
        config_workday_score=sum(compact_quality_breakdown(p, configured).values()),
        replacements_outside_exact_meeting=replacement_outside,
        note='La tolérance -15/+30 min des remplacements est modélisée dans CP-SAT; sa validation métier reste à préciser.')


if __name__ == '__main__':
    for name, fn in [
        ('ordinary_forbidden', ordinary_forbidden), ('partial_required', partial_required),
        ('fake_replacement', lambda: fake_activity('remplacement_colloque')),
        ('fake_meeting', lambda: fake_activity('colloque')), ('unknown_educator', unknown_educator),
        ('wrong_site', wrong_site), ('off_grid', off_grid), ('nan_hours', nan_hours),
        ('missing_primary', missing_primary), ('multiple_meetings', multiple_meetings),
        ('simultaneous_meetings', simultaneous_meetings), ('the_budget', the_budget),
        ('aliases', aliases), ('staffing_max', staffing_max), ('opening_hours', opening_hours),
        ('gap_score', gap_score), ('replacement_engines', impossible_replacement_count),
        ('fallback_100_seconds', fallback_or_protection),
        ('ortools_protection', lambda: fallback_or_protection('ortools', True)),
        ('ui_error_callback', ui_error_callback), ('editor_latest', editor_latest),
        ('typo_day_roundtrip', typo_day_roundtrip), ('weak_validity', weak_validity),
        ('null_report_cap', null_report_cap), ('profiles', profiles),
        ('generation_budget', generation_budget), ('current_candidate', current_candidate),
        ('morning_split', morning_split), ('malformed_cache', malformed_cache),
        ('non_atomic_write', non_atomic_write),
        ('legacy_wrong_day', legacy_wrong_day),
    ]:
        record(name, fn)
    # These assertions certify the observed audit evidence. They intentionally
    # characterize defects; invert the expectations when making regression tests.
    assert RESULTS['ordinary_forbidden']['cp_status'] == 'ok'
    assert RESULTS['ordinary_forbidden']['validator_errors'] == []
    assert RESULTS['unknown_educator']['cache_status'] == 'ok'
    assert RESULTS['fake_replacement']['validator_errors'] == []
    assert RESULTS['fake_meeting']['validator_errors'] == []
    assert RESULTS['missing_primary'] == []
    assert RESULTS['off_grid']['validator_errors'] == []
    assert RESULTS['wrong_site'] == []
    assert RESULTS['nan_hours']['errors'] == []
    assert RESULTS['nan_hours']['nan_total'] == 'nan'
    assert RESULTS['multiple_meetings']['cp_status'] == 'ok'
    assert RESULTS['simultaneous_meetings']['cp_message'] == 'INFEASIBLE'
    assert RESULTS['the_budget']['validator_errors'] == []
    assert RESULTS['aliases']['status'] == 'invalid'
    assert RESULTS['aliases']['model_status'] == 'OPTIMAL'
    assert RESULTS['staffing_max']['cp_status'] == 'ok'
    assert RESULTS['opening_hours']['cp_status'] == 'ok'
    assert RESULTS['gap_score']['gap_60'] == RESULTS['gap_score']['gap_180']
    assert RESULTS['replacement_engines']['cp'] == 'ok'
    assert RESULTS['replacement_engines']['patterns'] == 'infeasible_or_not_solved'
    assert RESULTS['fallback_100_seconds']['pattern_calls'] == 0
    assert RESULTS['ortools_protection']['returned_score'] > RESULTS['ortools_protection']['reference_score']
    assert RESULTS['ui_error_callback']['exception'] == 'NameError'
    assert RESULTS['editor_latest']['selected'] == 'out_2026.json'
    assert RESULTS['typo_day_roundtrip']['demanded_days'] == DAYS
    assert RESULTS['weak_validity']['empty_checks_accepted']
    assert RESULTS['null_report_cap']['exception'] == 'TypeError'
    assert RESULTS['profiles']['equilibre']['context'] == RESULTS['profiles']['preferences_horaires']['context']
    assert RESULTS['current_candidate']['validator_errors'] == []
    assert RESULTS['current_candidate']['structural_errors'] == []
    assert RESULTS['current_candidate']['experimental_score'] == 626975
    assert RESULTS['current_candidate']['config_workday_score'] == 829475
    assert RESULTS['morning_split']['cp_status'] == 'ok'
    assert RESULTS['morning_split']['pattern_status'] == 'infeasible_or_not_solved'
    assert RESULTS['malformed_cache']['exception'] == 'KeyError'
    assert RESULTS['non_atomic_write']['contents_after_failure'] == '{'
    assert RESULTS['legacy_wrong_day']['received_day_indices'] == [4,4]
    destination = Path(__file__).with_name('results.json')
    destination.write_text(json.dumps(RESULTS, ensure_ascii=False, indent=2, allow_nan=False)+'\n')
    print(json.dumps(RESULTS, ensure_ascii=False, indent=2, allow_nan=False))
