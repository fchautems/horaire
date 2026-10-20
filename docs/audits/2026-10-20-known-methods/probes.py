"""Small observations of existing APIs; no production behavior is modified."""
from __future__ import annotations
import copy
import hashlib
import json
import platform
import subprocess
import sys
import time
from pathlib import Path
ROOT = Path(__file__).resolve().parents[3]
OUT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / 'src'))
from creche_planning import domain, solver
import ortools

def protected_hashes():
    paths = [*sorted((ROOT/'src').rglob('*.py')), ROOT/'data/gwendo.json', ROOT/'config/solveur_config.json', *sorted((ROOT/'outputs').rglob('*'))]
    return {str(p.relative_to(ROOT)):hashlib.sha256(p.read_bytes()).hexdigest() for p in paths if p.is_file()}

before=protected_hashes()
data=dict(sites=[dict(name='S',open='08:00',close='10:00')], groups=[dict(name='G',site='S')],
          educators=[dict(name='A',type='EDE',percentage=5,attends_colloque=False,max_work_days=5)],
          educator_types=[dict(name='EDE')], rules_global=dict(max_weekly_hours=40,max_daily_hours=8.5),
          rules_time=[['negatif','hard','A',d,'08:00','10:00'] for d,_ in domain.DAYS if d!='lundi'],
          rules_group=[],rules_percentage=[],rules_site_schedule=[],rules_colloques=[])
options=dict(time_limit=2,the_enabled=False,the_colloques_count=False,min_daily_hours=0,
             weekly_hours_tolerance_percent=0,weekly_hours_tolerance_step_minutes=15,
             max_split_gap_minutes=90,hard_max_work_days=True)

def schedule(end):
    return {'A':{d:[dict(start='08:00',end=end,site='S',group='G',hours=(domain.parse_time(end)-480)/60)] if d=='lundi' else [] for d,_ in domain.DAYS}}

results={}
def call(label,**extra):
    started=time.monotonic()
    payload,_=solver.make_ortools_slot_payload(copy.deepcopy(data),**options,**extra)
    results[label]={'elapsed_seconds':round(time.monotonic()-started,4),'payload':payload}
    return payload

full=call('strict_full_schedule',fixed_schedule=schedule('10:00'))
assert full['status']=='ok' and not full['checks']['errors']
partial=call('compact_fixed_schedule_is_total_not_partial',fixed_schedule=schedule('09:00'))
assert partial['solver_message']=='INFEASIBLE'
checkpoints=[]
relaxed=call('disabled_weekly_constraint_does_not_repair',fixed_schedule=schedule('09:00'),enforce_weekly_hours=False,accept_invalid_for_hint=True,candidate_callback=lambda p,b:checkpoints.append(p))
assert relaxed['status']=='invalid' and relaxed['checks']['errors'] and not checkpoints
assert sum(b['hours'] for days in relaxed['schedule'].values() for blocks in days.values() for b in blocks)==1
repaired=call('strict_solver_can_use_invalid_hint_on_easy_case',hint_payload=relaxed)
assert repaired['status']=='ok' and not repaired['checks']['errors']
assert sum(b['hours'] for days in repaired['schedule'].values() for blocks in days.values() for b in blocks)==2
assert protected_hashes()==before
report={'base_commit':subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip(),
        'python':platform.python_version(),'ortools':ortools.__version__,
        'synthetic_data':data,'options':options,'observations':results,
        'all_assertions_passed':True,'protected_files_unchanged':True,'protected_hashes':before,
        'limits':'Single educator, two-hour horizon, no coverage/qualification/THE/colloque requirements. API characterization only; no global performance inference.'}
(OUT/'results.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')
print(json.dumps({k:{'seconds':v['elapsed_seconds'],'status':v['payload']['status'],'message':v['payload'].get('solver_message'),'errors':v['payload'].get('checks',{}).get('errors')} for k,v in results.items()},ensure_ascii=False,indent=2))
