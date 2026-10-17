import hashlib
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
OUT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / 'src'))
from creche_planning import solver

def save(name, value):
    (OUT / name).write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding='utf-8')

data = json.loads((ROOT / 'data/gwendo.json').read_text())
reference = json.loads((ROOT / 'docs/experiments/2026-10-17-score-fixed-300s/evaluated_candidate_2.json').read_text())
options = dict(
    min_daily_hours=2.0, enforce_min_daily_hours=False, max_split_gap_minutes=None,
    weekly_hours_tolerance_percent=5.0, weekly_hours_tolerance_step_minutes=15,
    enforce_absolute_max_weekly_hours=True, absolute_max_weekly_hours=40.0,
    the_enabled=True, the_percent=10.0, the_colloques_count=True,
    half_day_split_time='12:30', max_weekly_group_exception_days=1,
    hard_max_work_days=True,
)
verification = {k:v for k,v in options.items()
                if k not in ('min_daily_hours','enforce_min_daily_hours')}
validated, _ = solver.revalidate_cached_payload(data, reference, **verification)
assert validated['status'] == 'ok', validated['checks']['errors']
score = solver.planning_quality_score
reference_score = score(validated)
assert reference_score == 631977, reference_score
reference = validated
started = time.monotonic()
evaluations = []
checkpoints = []

def progress(percent, message):
    print(f'{time.monotonic()-started:.3f}|{percent}|{message}', flush=True)

def observe_score(payload, **kwargs):
    result = score(payload, **kwargs)
    entry = dict(elapsed=round(time.monotonic()-started,3), score=result,
                 internal_objective=payload.get('objective'), status=payload.get('status'),
                 errors=payload.get('checks',{}).get('errors'),
                 same_schedule_as_reference=payload.get('schedule') == reference['schedule'])
    evaluations.append(entry)
    save(f'evaluated_candidate_{len(evaluations)}.json', payload)
    save('evaluations.json', evaluations)
    print('EVALUATED '+json.dumps(entry,ensure_ascii=False), flush=True)
    return result

def checkpoint(payload, bundle):
    entry = dict(elapsed=round(time.monotonic()-started,3), score=score(payload),
                 errors=payload['checks']['errors'])
    checkpoints.append(entry)
    save('checkpoint.json',payload)
    print('CHECKPOINT '+json.dumps(entry,ensure_ascii=False), flush=True)

save('conditions.json', dict(
    source_commit='68acb55d6b7f0e57e171e818debb47469fbd6979', time_limit=300,
    options=options, fixed_schedule=None, hint='evaluated_candidate_2.json (score commun 631977)',
    weights=dict(split_shift_weight=120.0, split_gap_weight=4.0,
                 group_switch_day_weight=8.0, same_group_week_weight=0.4, work_day_weight=0.0),
    hashes={p:hashlib.sha256((ROOT/p).read_bytes()).hexdigest() for p in (
        'src/creche_planning/solver.py','src/creche_planning/scoring.py','data/gwendo.json','config/solveur_config.json',
        'docs/experiments/2026-10-17-score-fixed-300s/evaluated_candidate_2.json')},
))
solver.planning_quality_score = observe_score
try:
    payload, bundle = solver.make_ortools_slot_payload(
        data, time_limit=300, hint_payload=reference, fixed_schedule=None,
        debug_log_path=OUT/'cp_sat.log', progress_callback=progress,
        candidate_callback=checkpoint, **options,
    )
finally:
    solver.planning_quality_score = score
elapsed = time.monotonic()-started
save('result.json',payload)
checks = solver.verify_solution(
    bundle, payload['schedule'],
    primary_groups_by_educator=payload['checks']['primary_groups_by_educator'],
    **verification,
)
summary = dict(elapsed_seconds=round(elapsed,3), status=payload['status'],
               solver_message=payload['solver_message'], statistics=payload.get('cp_sat_statistics'),
               reference_score=reference_score, reference_errors=validated['checks']['errors'],
               checkpoints=checkpoints, score_evaluations=evaluations,
               independent_errors=checks['errors'], candidate_score=score(payload),
               same_schedule_as_reference=payload['schedule']==reference['schedule'],
               retain_candidate=payload['status']=='ok' and not checks['errors']
                                and score(payload)<=reference_score)
summary['score_matches_internal_objective'] = score(payload) == payload.get('objective')
summary['reference_breakdown'] = solver.compact_quality_breakdown(reference, reference['quality_scoring'])
summary['result_breakdown'] = solver.compact_quality_breakdown(payload, payload['quality_scoring'])
assert not checks['errors'], checks['errors']
assert score(payload) <= reference_score
assert summary['score_matches_internal_objective'], summary
save('summary.json',summary)
print('SUMMARY '+json.dumps(summary,ensure_ascii=False), flush=True)
