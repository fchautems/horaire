"""Fresh 600-second CP-SAT search after the independent-review fixes."""

from __future__ import annotations

import hashlib
import json
import platform
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
OUT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "src"))

from creche_planning import solver  # noqa: E402


OPTIONS = dict(
    min_daily_hours=2.0,
    enforce_min_daily_hours=False,
    max_split_gap_minutes=None,
    weekly_hours_tolerance_percent=5.0,
    weekly_hours_tolerance_step_minutes=15,
    enforce_absolute_max_weekly_hours=True,
    absolute_max_weekly_hours=40.0,
    the_enabled=True,
    the_percent=10.0,
    the_colloques_count=True,
    half_day_split_time="12:30",
    max_weekly_group_exception_days=1,
    hard_max_work_days=True,
)
VERIFICATION_OPTIONS = {
    key: value
    for key, value in OPTIONS.items()
    if key not in {"min_daily_hours", "enforce_min_daily_hours"}
}


def save(name: str, value: object) -> None:
    solver.save_json(OUT / name, value)


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def protected_hashes() -> dict[str, str]:
    paths = [
        *sorted((ROOT / "src").rglob("*.py")),
        ROOT / "data" / "gwendo.json",
        ROOT / "config" / "solveur_config.json",
        *sorted(path for path in (ROOT / "outputs").rglob("*") if path.is_file()),
    ]
    return {str(path.relative_to(ROOT)): sha256(path) for path in paths}


def git_head() -> str:
    return subprocess.check_output(
        ["git", "rev-parse", "HEAD"], cwd=ROOT, text=True
    ).strip()


started_at = datetime.now(timezone.utc)
before = protected_hashes()
data = json.loads((ROOT / "data" / "gwendo.json").read_text(encoding="utf-8"))

try:
    import ortools

    ortools_version = ortools.__version__
except Exception:
    ortools_version = None

save(
    "conditions.json",
    {
        "started_at": started_at.isoformat(),
        "time_limit_seconds": 600,
        "hint_payload": None,
        "fixed_schedule": None,
        "options": OPTIONS,
        "git_head": git_head(),
        "python": platform.python_version(),
        "ortools": ortools_version,
        "protected_hashes_before": before,
    },
)

started = time.monotonic()


def progress(percent: int, message: str) -> None:
    print(f"PROGRESS {time.monotonic() - started:.3f}|{percent}|{message}", flush=True)


def checkpoint(payload: dict, _bundle: object) -> None:
    elapsed = round(time.monotonic() - started, 3)
    save("checkpoint.json", payload)
    save(
        "checkpoint-metadata.json",
        {
            "elapsed_seconds": elapsed,
            "status": payload.get("status"),
            "score": solver.planning_quality_score(payload),
        },
    )
    print(
        f"CHECKPOINT {elapsed:.3f} score={solver.planning_quality_score(payload)}",
        flush=True,
    )


result, bundle = solver.make_ortools_slot_payload(
    data,
    time_limit=600,
    hint_payload=None,
    fixed_schedule=None,
    debug_log_path=OUT / "cp_sat.log",
    progress_callback=progress,
    candidate_callback=checkpoint,
    **OPTIONS,
)
elapsed = round(time.monotonic() - started, 3)
save("result.json", result)

validation = None
selected = None
if result.get("schedule"):
    validation = solver.verify_solution(
        bundle,
        result["schedule"],
        primary_groups_by_educator=result.get("checks", {}).get(
            "primary_groups_by_educator", {}
        ),
        **VERIFICATION_OPTIONS,
    )
    save("validation.json", validation)
    if result.get("status") == "ok" and not validation["errors"]:
        selected = "new_candidate"
        save("selected.json", result)

after = protected_hashes()
integrity = {
    "protected_hashes_before": before,
    "protected_hashes_after": after,
    "unchanged": before == after,
    "changed": sorted(key for key in before.keys() | after.keys() if before.get(key) != after.get(key)),
}
save("integrity.json", integrity)

summary = {
    "started_at": started_at.isoformat(),
    "finished_at": datetime.now(timezone.utc).isoformat(),
    "elapsed_seconds": elapsed,
    "status": result.get("status"),
    "solver_message": result.get("solver_message"),
    "statistics": result.get("cp_sat_statistics"),
    "schedule_present": bool(result.get("schedule")),
    "independent_errors": None if validation is None else validation["errors"],
    "score": None if not result.get("schedule") else solver.planning_quality_score(result),
    "selected": selected,
    "protected_files_unchanged": integrity["unchanged"],
}
save("summary.json", summary)
print("SUMMARY " + json.dumps(summary, ensure_ascii=False), flush=True)
