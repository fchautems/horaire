"""Run a bounded guided CP-SAT search for fewer classic split days."""

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
from creche_planning.reports import write_csv, write_html  # noqa: E402


TIME_LIMIT = 120.0
OPTIONS = dict(
    min_daily_hours=2.0,
    enforce_min_daily_hours=False,
    max_split_gap_minutes=90,
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
    split_shift_weight=1000.0,
    split_gap_weight=4.0,
)
VERIFY_OPTIONS = {
    key: value
    for key, value in OPTIONS.items()
    if key not in {"min_daily_hours", "enforce_min_daily_hours", "split_shift_weight", "split_gap_weight"}
}


def save(name: str, value: object) -> None:
    solver.save_json(OUT / name, value)


def protected_hashes() -> dict[str, str]:
    paths = [
        *sorted((ROOT / "src").rglob("*.py")),
        ROOT / "data" / "gwendo.json",
        ROOT / "config" / "solveur_config.json",
        *sorted(path for path in (ROOT / "outputs").rglob("*") if path.is_file()),
    ]
    return {
        str(path.relative_to(ROOT)): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in paths
    }


def quality_key(payload: dict) -> tuple[int, int, int, float]:
    metrics = payload["checks"]["quality_summary"]["metrics"]
    return (
        int(metrics["split_days_count"]),
        int(round(float(metrics["total_split_gap_hours"]) * 60)),
        int(metrics["max_split_gap_minutes_found"]),
        float(solver.planning_quality_score(payload)),
    )


started = time.monotonic()
before_hashes = protected_hashes()
data = json.loads((ROOT / "data/gwendo.json").read_text(encoding="utf-8"))
source = json.loads(
    (ROOT / "docs/experiments/2026-10-19-hard-90-minute-repair/candidate.json").read_text(
        encoding="utf-8"
    )
)
context = solver.compact_quality_context(data)
source, source_bundle = solver.revalidate_cached_payload(
    data, source, quality_context=context, **VERIFY_OPTIONS
)
assert source["status"] == "ok" and not source["checks"]["errors"]

best = source
best_bundle = source_bundle
incumbents: list[dict] = []


def checkpoint(candidate: dict, bundle: object) -> None:
    global best, best_bundle
    checked, checked_bundle = solver.revalidate_cached_payload(
        data, candidate, quality_context=context, **VERIFY_OPTIONS
    )
    if checked["status"] != "ok" or checked["checks"]["errors"]:
        return
    entry = {
        "elapsed_seconds": round(time.monotonic() - started, 3),
        "quality_key": quality_key(checked),
        "score": solver.planning_quality_score(checked),
    }
    incumbents.append(entry)
    if quality_key(checked) < quality_key(best):
        best, best_bundle = checked, checked_bundle
        save("checkpoint-best.json", best)


conditions = {
    "started_at": datetime.now(timezone.utc).isoformat(),
    "git_head": subprocess.check_output(
        ["git", "rev-parse", "HEAD"], cwd=ROOT, text=True
    ).strip(),
    "python": platform.python_version(),
    "time_limit_seconds": TIME_LIMIT,
    "hint_source": "docs/experiments/2026-10-19-hard-90-minute-repair/candidate.json",
    "fixed_schedule": None,
    "selection_order": [
        "split_days_count",
        "total_split_gap_minutes",
        "max_split_gap_minutes",
        "planning_quality_score",
    ],
    "search_weights": {
        "split_shift_weight": OPTIONS["split_shift_weight"],
        "split_gap_weight": OPTIONS["split_gap_weight"],
    },
    "hard_max_split_gap_minutes": 90,
    "protected_hashes_before": before_hashes,
}
save("conditions.json", conditions)

payload, bundle = solver.make_ortools_slot_payload(
    data,
    time_limit=TIME_LIMIT,
    hint_payload=source,
    debug_log_path=OUT / "cp-sat.log",
    candidate_callback=checkpoint,
    **OPTIONS,
)
if payload.get("status") == "ok":
    checkpoint(payload, bundle)

selected = best
selected_bundle = best_bundle
save("raw-result.json", payload)
save("result.json", selected)
write_csv(OUT / "result.csv", selected)
write_html(OUT / "result.html", selected, selected_bundle)

after_hashes = protected_hashes()
source_metrics = source["checks"]["quality_summary"]["metrics"]
result_metrics = selected["checks"]["quality_summary"]["metrics"]
summary = {
    "elapsed_seconds": round(time.monotonic() - started, 3),
    "raw_status": payload.get("status"),
    "raw_message": payload.get("solver_message"),
    "source": {
        "quality_key": quality_key(source),
        "split_days_count": source_metrics["split_days_count"],
        "total_split_gap_hours": source_metrics["total_split_gap_hours"],
        "max_split_gap_minutes": source_metrics["max_split_gap_minutes_found"],
        "score": solver.planning_quality_score(source),
    },
    "selected": {
        "is_improvement": quality_key(selected) < quality_key(source),
        "quality_key": quality_key(selected),
        "split_days_count": result_metrics["split_days_count"],
        "total_split_gap_hours": result_metrics["total_split_gap_hours"],
        "max_split_gap_minutes": result_metrics["max_split_gap_minutes_found"],
        "score": solver.planning_quality_score(selected),
        "errors": selected["checks"]["errors"],
    },
    "incumbents_checked": incumbents,
    "cp_sat_statistics": payload.get("cp_sat_statistics"),
    "protected_files_unchanged": before_hashes == after_hashes,
    "protected_files_changed": sorted(
        key
        for key in before_hashes.keys() | after_hashes.keys()
        if before_hashes.get(key) != after_hashes.get(key)
    ),
    "active_planning_replaced": False,
}
assert summary["selected"]["errors"] == []
assert summary["selected"]["max_split_gap_minutes"] <= 90
assert summary["protected_files_unchanged"]
save("summary.json", summary)
save(
    "integrity.json",
    {
        "protected_hashes_before": before_hashes,
        "protected_hashes_after": after_hashes,
        "unchanged": before_hashes == after_hashes,
        "changed": summary["protected_files_changed"],
    },
)
print(json.dumps(summary, ensure_ascii=False, indent=2))
