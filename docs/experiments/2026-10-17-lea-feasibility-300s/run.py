import hashlib,json,sys,time
from pathlib import Path
ROOT=Path(__file__).resolve().parents[3]
OUT=Path(__file__).resolve().parent
sys.path.insert(0,str(ROOT/'src'))
from creche_planning import solver

def save(name,value):
 (OUT/name).write_text(json.dumps(value,ensure_ascii=False,indent=2),encoding='utf-8')
source_path=ROOT/'src/creche_planning/solver.py'
source=source_path.read_text(encoding='utf-8-sig')
anchor='    model.Minimize(sum(objective_terms) if objective_terms else 0)\n'
prefix, marker, body = source.partition('def make_ortools_slot_payload(')
assert marker and body.count(anchor)==1
injection='''    # Experimental restriction only: Lea works one continuous period on Thursday.
    target_e = educator_by_name['Léa']
    target_d = next(i for i, (day, _) in enumerate(DAYS) if day == 'jeudi')
    model.Add(sum(start_var[(target_e, target_d, t)] for t in range(horizon.slots)) == 1)
    debug('EXPERIMENT: Lea Thursday one presence period; no score bound; stop at first solution')
'''
# Execute isolated instrumentation in the imported module; production source stays unchanged.
exec(compile(prefix+marker+body.replace(anchor,injection+anchor).replace('    if fixed_schedule is None and remaining_for_optimization >= 1.0:', '    if False: # experiment: feasibility only'),str(source_path),'exec'),solver.__dict__)
data=json.loads((ROOT/'data/gwendo.json').read_text())
reference=json.loads((ROOT/'docs/experiments/2026-10-17-aligned-300s/result.json').read_text())
options=dict(min_daily_hours=2.0,enforce_min_daily_hours=False,max_split_gap_minutes=None,
 weekly_hours_tolerance_percent=5.0,weekly_hours_tolerance_step_minutes=15,
 enforce_absolute_max_weekly_hours=True,absolute_max_weekly_hours=40.0,
 the_enabled=True,the_percent=10.0,the_colloques_count=True,
 half_day_split_time='12:30',max_weekly_group_exception_days=1,hard_max_work_days=True)
verification={k:v for k,v in options.items() if k not in ('min_daily_hours','enforce_min_daily_hours')}
reference,bundle=solver.revalidate_cached_payload(data,reference,**verification)
assert reference['status']=='ok'
assert solver.planning_quality_score(reference)==631977
save('conditions.json',dict(time_limit=300,options=options,target='Léa jeudi: exactly one presence period',
 score_upper_bound=None,stop_after_first_solution=True,optimization=False,fixed_schedule=None,reference_score=631977,
 instrumentation=injection,hashes={str(p.relative_to(ROOT)):hashlib.sha256(p.read_bytes()).hexdigest()
 for p in [source_path,ROOT/'src/creche_planning/scoring.py',ROOT/'data/gwendo.json']}))
started=time.monotonic()
def progress(percent,message):print(f'{time.monotonic()-started:.3f}|{percent}|{message}',flush=True)
def checkpoint(payload,bundle):
 save('checkpoint.json',payload)
 print('CHECKPOINT',solver.planning_quality_score(payload),flush=True)
try:
 payload,bundle=solver.make_ortools_slot_payload(data,time_limit=300,hint_payload=reference,
  fixed_schedule=None,debug_log_path=OUT/'cp_sat.log',progress_callback=progress,
  candidate_callback=checkpoint,**options)
 save('result.json',payload)
 valid=payload.get('status')=='ok'
 checks=solver.verify_solution(bundle,payload.get('schedule',{}),
  primary_groups_by_educator=payload.get('checks',{}).get('primary_groups_by_educator',{}),**verification) if valid else None
 score=solver.planning_quality_score(payload) if valid else None
 accepted=bool(valid and not checks['errors'] and score<631977)
 if accepted:
  assert score==payload['objective']
  save('selected.json',payload)
 else:save('selected.json',reference)
 summary=dict(elapsed_seconds=round(time.monotonic()-started,3),status=payload.get('status'),
 solver_message=payload.get('solver_message'),statistics=payload.get('cp_sat_statistics'),
 reference_score=631977,candidate_score=score,independent_errors=checks['errors'] if checks else None,
 accepted=accepted,active_schedule_replaced=False)
 if valid:
  assert not checks['errors'], checks['errors']
  summary['lea_thursday']=payload['schedule']['Léa']['jeudi']
  summary['breakdown']=solver.compact_quality_breakdown(payload,payload['quality_scoring'])
 save('summary.json',summary)
 print('SUMMARY '+json.dumps(summary,ensure_ascii=False),flush=True)
except Exception as exc:
 save('error.json',dict(error=repr(exc),elapsed_seconds=time.monotonic()-started))
 raise
assert hashlib.sha256(source_path.read_bytes()).hexdigest()==json.loads((OUT/'conditions.json').read_text())['hashes']['src/creche_planning/solver.py']
