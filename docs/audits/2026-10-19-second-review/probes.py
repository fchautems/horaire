"""Independent short audit probes. No production data/configuration is written.
Run from repository root: python docs/audits/2026-10-19-second-review/probes.py
Assertions characterize observed defects, not desired regression expectations.
"""
from __future__ import annotations
import copy
import hashlib
import json
from pathlib import Path
import platform
import subprocess
import sys
import time
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[3]
OUT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / 'src'))
from creche_planning import solver, domain, reports
from creche_planning.pattern_mip import solve_pattern_mip
from creche_planning.scoring import compact_quality_breakdown

DAYS = [d for d, _ in domain.DAYS]
OPTIONS = dict(the_enabled=True, the_percent=0, weekly_hours_tolerance_percent=0,
               min_daily_hours=0, max_split_gap_minutes=None)
RESULTS = {}

def block(start, end, group='A', site='bas', activity=None):
    b = dict(start=start, end=end, group=group, site=site,
             hours=(domain.parse_time(end)-domain.parse_time(start))/60)
    if activity: b['activity'] = activity
    return b

def make_case(blocks, *, two_sites=True, meeting=True):
    hours = sum(b['hours'] for b in blocks)
    d = dict(sites=[dict(name='bas', open='11:45', close='14:45')],
             groups=[dict(name='A', site='bas'), dict(name='B', site='haut' if two_sites else 'bas')],
             educators=[dict(name='Lea', type='EDE', percentage=hours/40*100,
                             attends_colloque=False, max_work_days=5)],
             educator_types=[dict(name='EDE')],
             rules_global=dict(max_weekly_hours=40, max_daily_hours=8.5),
             rules_time=[['negatif','hard','Lea',day,'11:45','14:45'] for day in DAYS if day != 'lundi'],
             rules_group=[['positif','hard','Lea','A']], rules_percentage=[],
             rules_site_schedule=[],
             rules_colloques=[dict(group='B',day='lundi',start='13:15',end='14:00')] if meeting else [])
    if two_sites: d['sites'].append(dict(name='haut',open='11:45',close='14:45'))
    s = {'Lea': {day: copy.deepcopy(blocks) if day=='lundi' else [] for day in DAYS}}
    return d,s

def round_trip():
    return make_case([block('11:45','13:00'),
        block('13:15','14:00','B','haut','remplacement_colloque'), block('14:15','14:45')])

def bundle(d):
    return SimpleNamespace(data=d,horizon=domain.make_horizon(d),groups=d['groups'],
                          educators=d['educators'],sites=[s['name'] for s in d['sites']])

def validate(d,s,**options):
    opts = OPTIONS | options
    opts.pop('min_daily_hours',None)
    return solver.verify_solution(bundle(d), s, primary_groups_by_educator={'Lea':'A'}, **opts)

def brief(payload):
    return {k:payload[k] for k in ['status','solver_message','objective','solver_objective',
              'quality_score','pattern_statistics','schedule','checks','quality_scoring'] if k in payload}

def cp(d,s,**options):
    t=time.monotonic()
    payload,_=solver.make_ortools_slot_payload(d,fixed_schedule=s,time_limit=3,**(OPTIONS|options))
    return brief(payload)|{'elapsed_seconds':round(time.monotonic()-t,4)}

def patterns(d,s=None,**options):
    t=time.monotonic()
    payload,_=solve_pattern_mip(d,time_limit=12,fixed_primary_groups={0:0},
        fixed_daily_schedules=s,**(OPTIONS|options))
    return brief(payload)|{'elapsed_seconds':round(time.monotonic()-t,4)}

def require_coverage(d,s):
    # Demand the exact witness's productive intervals; journeys have zero demand.
    d['rules_site_schedule']=[dict(site=b['site'],days=['lundi'],time_intervals=[
        dict(group=b['group'],start=b['start'],end=b['end'],min_staff=1)])
        for b in s['Lea']['lundi'] if b.get('activity')!='colloque']

def travel_prefilter():
    d,s=round_trip(); require_coverage(d,s)
    results={}
    for label,intervals in [('none',[]),('outbound',[('13:00','13:15')]),
          ('inbound',[('14:00','14:15')]),('both',[('13:00','13:15'),('14:00','14:15')])]:
        case=copy.deepcopy(d)
        case['rules_time'] += [['negatif','hard','Lea','lundi',a,z] for a,z in intervals]
        results[label]=dict(data=case,witness=s,validator=validate(case,s),cp=cp(case,s),
                           patterns_free=patterns(case),patterns_fixed=patterns(case,s))
    return results

def replacement_window():
    # The meeting's -15/+30 window is explicitly authorized by the business rules.
    d,s=make_case([block('12:45','13:00'),
        block('13:00','14:30','B','bas','remplacement_colloque'),block('14:30','14:45')],two_sites=False)
    unforced=dict(data=copy.deepcopy(d),witness=s,validator=validate(d,s),cp=cp(d,s),patterns_fixed=patterns(d,s))
    require_coverage(d,s)
    forced=dict(data=d,witness=s,validator=validate(d,s),cp=cp(d,s),patterns_free=patterns(d),patterns_fixed=patterns(d,s))
    return dict(no_coverage=unforced,with_coverage=forced)

def travel_report():
    d,s=round_trip()
    result=cp(d,s,max_split_gap_minutes=0)
    payload={k:v for k,v in result.items() if k!='elapsed_seconds'}
    payload['rule_summary'] = reports.build_rule_summary(d, dict(the_percent=0, max_pause_between_blocks_minutes=0, enforce_max_pause_between_blocks=True))
    reports.write_html(OUT/'travel-report.html',payload,bundle(d))
    reports.write_csv(OUT/'travel-report.csv',payload)
    return dict(data=d,witness=s,cp=result,
        score_breakdown=compact_quality_breakdown(payload,payload['quality_scoring']),
        recomputed_score=solver.planning_quality_score(payload),
        html_file='travel-report.html', rule_summary=payload['rule_summary'])


def travel_soft_cost():
    d,s=round_trip(); require_coverage(d,s)
    result={}
    for label,weight in [('no_preference',0),('ordinary_weight',1),('large_weight',1000)]:
        case=copy.deepcopy(d)
        if weight:
            case['rules_time'] += [['negatif','soft','Lea','lundi',a,z]
                for a,z in [('13:00','13:15'),('14:00','14:15')]]
        result[label]=dict(data=case,witness=s,cp=cp(case,s,soft_time_rule_weight=weight),
            patterns_free=patterns(case,soft_time_rule_weight=weight))
    return result

def contract_and_coverage():
    d,s=round_trip(); require_coverage(d,s)
    d['educators'][0]['percentage']=3.25/40*100
    opts=dict(the_percent=25)
    checks=validate(d,s,**opts)
    good=dict(data=copy.deepcopy(d),witness=s,validator=checks,cp=cp(d,s,**opts),
              patterns_free=patterns(d,**opts),patterns_fixed=patterns(d,s,**opts))
    d['rules_site_schedule'].append(dict(site='bas',days=['lundi'],time_intervals=[
        dict(group='A',start='13:00',end='13:15',min_staff=1)]))
    bad=dict(data=d,witness=s,validator=validate(d,s,**opts),cp=cp(d,s,**opts),patterns_fixed=patterns(d,s,**opts))
    return dict(nonzero_the=good,demand_during_travel=bad)

def assert_observations():
    r=RESULTS
    for label,v in r['travel_prefilter'].items():
        assert v['validator']['errors']==[]
        assert v['cp']['status']=='ok'
        assert v['patterns_fixed']['status']=='ok'
        if label=='both':
            assert 'Infeasible' in v['patterns_free']['solver_message']
        else:
            assert v['patterns_free']['status']=='ok'
    for v in r['replacement_window'].values():
        assert v['validator']['errors']==[] and v['cp']['status']=='ok'
    v=r['replacement_window']['no_coverage']
    assert v['patterns_fixed']['status']=='ok'
    assert v['patterns_fixed']['schedule']!=v['witness']
    for mode in ['patterns_fixed','patterns_free']:
        assert 'Infeasible' in r['replacement_window']['with_coverage'][mode]['solver_message']
    v=r['travel_report']
    assert v['cp']['checks']['errors']==[]
    assert v['cp']['checks']['quality_summary']['metrics']['split_gap_violations']==2
    assert v['cp']['objective']==v['recomputed_score']
    assert any('une personne de chaque' in rule['rule'] for rule in v['rule_summary']['hard'])
    costs=RESULTS['travel_soft_cost']
    base=costs['no_preference']['patterns_free']
    weighted=costs['ordinary_weight']['patterns_free']
    assert base['schedule']==weighted['schedule']==costs['no_preference']['witness']
    assert weighted['checks']['quality_summary']['metrics']['soft_time_rules']['violated']==0
    assert weighted['objective']-base['objective']==90
    assert costs['no_preference']['cp']['objective']==costs['ordinary_weight']['cp']['objective']
    r=r['contract_and_coverage']
    for name in ['cp','patterns_free','patterns_fixed']:
        checks=r['nonzero_the'][name]['checks']
        assert checks['errors']==[]
        assert checks['hours_by_educator']['Lea']==3.25
        assert checks['child_hours_by_educator']['Lea']==2.5
        assert checks['invisible_the_hours_by_educator']['Lea']==.75
    assert any('13:00' in err for err in r['demand_during_travel']['validator']['errors'])
    assert r['demand_during_travel']['cp']['solver_message']=='INFEASIBLE'
    assert r['demand_during_travel']['patterns_fixed']['status']!='ok'

def fingerprints():
    return {str(f.relative_to(ROOT)):hashlib.sha256(f.read_bytes()).hexdigest()
        for folder in ['src','config','data','tests/fixtures','outputs']
        for f in sorted((ROOT/folder).rglob('*')) if f.is_file() and '__pycache__' not in f.parts}

def main():
    before=fingerprints()
    for name,fn in [('travel_prefilter',travel_prefilter),('replacement_window',replacement_window),
                    ('travel_report',travel_report),('travel_soft_cost',travel_soft_cost),
                    ('contract_and_coverage',contract_and_coverage)]:
        start=time.monotonic()
        RESULTS[name]=fn()
        print(name,round(time.monotonic()-start,3),'seconds',flush=True)
        (OUT/'results.json').write_text(json.dumps(RESULTS,indent=2,ensure_ascii=False)+'\n')
    assert_observations()
    print("Observed-behavior assertions: PASS",flush=True)
    after=fingerprints()
    assert before==after,'Protected files changed'
    import ortools,numpy,scipy
    (OUT/'environment.json').write_text(json.dumps(dict(
        base_commit=subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip(),
        default_probe_options=OPTIONS, cp_time_limit_seconds=3, patterns_time_limit_seconds=12,
        python=platform.python_version(),ortools=ortools.__version__,numpy=numpy.__version__,scipy=scipy.__version__,
        protected_files_before=before,protected_files_after=after,protected_files_unchanged=before==after),indent=2)+'\n')

if __name__=='__main__': main()
