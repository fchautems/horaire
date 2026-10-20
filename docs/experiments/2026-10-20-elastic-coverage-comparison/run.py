"""Bounded matched screening: 3 seeds x strict/elastic x 60 seconds, sequential.

No prior schedule/hint is loaded. Each trial uses its own process and outputs.
The parent caps each process at 80 seconds and records failures explicitly.
"""
from __future__ import annotations
import argparse
import hashlib
import json
import os
import platform
import resource
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
ROOT=Path(__file__).resolve().parents[3]
OUT=Path(__file__).resolve().parent
sys.path.insert(0,str(ROOT/'src'))
from creche_planning import solver
from creche_planning.pattern_search import payload_is_hard_valid
from creche_planning.reports import write_csv,write_html
import ortools

BUDGET=60.0
SEEDS=(1,17,43)
OPTIONS=dict(min_daily_hours=2.0,enforce_min_daily_hours=False,max_split_gap_minutes=90,
    weekly_hours_tolerance_percent=5.0,weekly_hours_tolerance_step_minutes=15,
    enforce_absolute_max_weekly_hours=True,absolute_max_weekly_hours=40.0,
    the_enabled=True,the_percent=10.0,the_colloques_count=True,
    half_day_split_time='12:30',max_weekly_group_exception_days=1,hard_max_work_days=True)
VERIFY_OPTIONS={k:v for k,v in OPTIONS.items() if k not in {'min_daily_hours','enforce_min_daily_hours'}}

def save(path,value):
    solver.save_json(path,value)

def hashes():
    paths=[*sorted((ROOT/'src').rglob('*.py')),ROOT/'data/gwendo.json',
           ROOT/'config/solveur_config.json',ROOT/'tests/fixtures/planning_gwendo_reference_valid.json',
           *sorted((ROOT/'outputs').rglob('*'))]
    return {str(p.relative_to(ROOT)):hashlib.sha256(p.read_bytes()).hexdigest() for p in paths if p.is_file()}

def child(mode,seed):
    dest=OUT/f'{mode}-{seed}'; dest.mkdir(exist_ok=True)
    before=hashes(); data=json.loads((ROOT/'data/gwendo.json').read_text())
    start=time.monotonic(); cpu=time.process_time(); first_valid=None; checkpoints=[]; progress=[]
    def on_progress(percent,message):
        item=dict(elapsed_seconds=round(time.monotonic()-start,4),percent=percent,message=message)
        progress.append(item); print(json.dumps(item,ensure_ascii=False),flush=True)
    def on_candidate(payload,bundle):
        nonlocal first_valid
        assert payload_is_hard_valid(payload)
        errors=solver.verify_solution(bundle,payload['schedule'],
            primary_groups_by_educator=payload['checks']['primary_groups_by_educator'],**VERIFY_OPTIONS)['errors']
        assert not errors, errors
        elapsed=round(time.monotonic()-start,4)
        if first_valid is None: first_valid=elapsed
        checkpoints.append(dict(elapsed_seconds=elapsed,score=solver.planning_quality_score(payload)))
        save(dest/'checkpoint.json',payload)
    payload,bundle=solver.make_ortools_slot_payload(data,time_limit=BUDGET,
        hint_payload=None,fixed_schedule=None,experimental_elastic_coverage=mode=='elastic',
        search_seed=seed,debug_log_path=dest/'cp-sat.log',
        progress_callback=on_progress,candidate_callback=on_candidate,**OPTIONS)
    solve_seconds=time.monotonic()-start
    save(dest/'result.json',payload)
    independent=None
    if payload.get('schedule') is not None:
        independent=solver.verify_solution(bundle,payload['schedule'],
            primary_groups_by_educator=payload['checks']['primary_groups_by_educator'],**VERIFY_OPTIONS)
        save(dest/'validation.json',independent)
    valid=payload_is_hard_valid(payload)
    if valid: assert independent is not None and not independent['errors']
    info=payload.get('elastic_coverage',{})
    if info.get('total_deficit_slots',0)>0: assert not valid and not checkpoints
    write_csv(dest/'result.csv',payload); write_html(dest/'result.html',payload,bundle)
    after=hashes(); assert before==after
    summary=dict(mode=mode,seed=seed,status=payload['status'],message=payload.get('solver_message'),
        solve_seconds=round(solve_seconds,4),total_seconds=round(time.monotonic()-start,4),
        cpu_seconds=round(time.process_time()-cpu,4),peak_rss_kib=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
        model_ready_seconds=next((p['elapsed_seconds'] for p in progress if p['message'].startswith('CP-SAT: ')),None),
        hard_valid=valid,first_valid_seconds=first_valid,
        independent_errors=None if independent is None else independent['errors'],
        score=solver.planning_quality_score(payload) if valid else None,
        elastic_coverage=info or None,checkpoints=checkpoints,
        cp_sat_statistics=payload.get('cp_sat_statistics'),
        protected_files_unchanged=before==after,active_planning_replaced=False)
    save(dest/'summary.json',summary); save(dest/'progress.json',progress)
    print('SUMMARY '+json.dumps(summary,ensure_ascii=False),flush=True)

def parent():
    before=hashes()
    order=[(mode,seed) for i,seed in enumerate(SEEDS)
           for mode in (('strict','elastic') if i%2==0 else ('elastic','strict'))]
    conditions=dict(started_at=datetime.now(timezone.utc).isoformat(),
        git_head=subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip(),
        python=platform.python_version(),ortools=ortools.__version__,platform=platform.platform(),
        cpu_count=os.cpu_count(),search_workers=min(8,os.cpu_count() or 1),
        time_limit_seconds=BUDGET,seeds=SEEDS,trial_order=order,options=OPTIONS,
        hint_payload=None,fixed_schedule=None,protected_hashes_before=before,
        scope='Direct compact API; matched screening, not a 600-second comparison or a full CLI/GUI run.')
    save(OUT/'conditions.json',conditions)
    summaries=[]
    for mode,seed in order:
        dest=OUT/f'{mode}-{seed}'; dest.mkdir(exist_ok=True)
        print(f'START {mode} seed={seed} budget={BUDGET}',flush=True)
        with (dest/'run.log').open('w') as log:
            process=subprocess.Popen([sys.executable,str(Path(__file__).resolve()),'--mode',mode,'--seed',str(seed)],
                cwd=ROOT,stdout=log,stderr=subprocess.STDOUT)
            timed_out=False
            try: code=process.wait(timeout=80)
            except subprocess.TimeoutExpired:
                timed_out=True; process.kill(); code=process.wait()
        process_info=dict(exit_code=code,timed_out=timed_out)
        save(dest/'process_status.json',process_info)
        if code!=0 or timed_out:
            print(f'ERROR {mode} seed={seed}: {process_info}',flush=True)
            save(OUT/'failure.json',dict(mode=mode,seed=seed,**process_info))
            raise RuntimeError('Trial failed; inspect its log before continuing.')
        summary=json.loads((dest/'summary.json').read_text()); summaries.append(summary)
        save(OUT/'partial-summary.json',summaries)
        print(f"FINISH {mode} seed={seed} valid={summary['hard_valid']} deficit="
              f"{(summary['elastic_coverage'] or {}).get('total_deficit_slots')}",flush=True)
    after=hashes(); assert before==after
    aggregate={mode:dict(trials=sum(s['mode']==mode for s in summaries),
        hard_valid=sum(s['mode']==mode and s['hard_valid'] for s in summaries),
        first_valid_seconds=[s['first_valid_seconds'] for s in summaries if s['mode']==mode and s['hard_valid']],
        scores=[s['score'] for s in summaries if s['mode']==mode and s['hard_valid']]) for mode in ('strict','elastic')}
    save(OUT/'summary.json',dict(finished_at=datetime.now(timezone.utc).isoformat(),
        aggregate=aggregate,trials=summaries,protected_files_unchanged=True,active_planning_replaced=False))
    save(OUT/'integrity.json',dict(before=before,after=after,unchanged=before==after))
    print('COMPLETED '+json.dumps(aggregate),flush=True)

if __name__=='__main__':
    parser=argparse.ArgumentParser(); parser.add_argument('--mode',choices=['strict','elastic']); parser.add_argument('--seed',type=int)
    args=parser.parse_args()
    if args.mode: child(args.mode,args.seed)
    else: parent()
