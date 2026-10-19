"""Repair the historical candidate under the hard 90-minute pause limit."""

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
sys.path.insert(0, str(ROOT / "src"))

from creche_planning import domain, solver  # noqa: E402
from creche_planning.pattern_mip import solve_pattern_mip  # noqa: E402
from creche_planning.reports import write_csv, write_html  # noqa: E402


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
)
VERIFY_OPTIONS = {
    key: value
    for key, value in OPTIONS.items()
    if key not in {"min_daily_hours", "enforce_min_daily_hours"}
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


def block(
    start: str,
    end: str,
    group: str,
    site: str,
    activity: str = "children",
) -> dict:
    return {
        "start": start,
        "end": end,
        "group": group,
        "site": site,
        "activity": activity,
        "hours": round((domain.parse_time(end) - domain.parse_time(start)) / 60, 2),
    }


def slot_assignments(schedule: dict) -> set[tuple[str, str, int, str, str, str]]:
    horizon = domain.make_horizon(data)
    result = set()
    for educator, days in schedule.items():
        for day, blocks in days.items():
            for item in blocks:
                activity = item.get("activity") or "children"
                for slot in domain.slot_range(horizon, item["start"], item["end"]):
                    result.add(
                        (educator, day, slot, item["group"], item["site"], activity)
                    )
    return result


started = time.monotonic()
before_hashes = protected_hashes()
data = json.loads((ROOT / "data" / "gwendo.json").read_text(encoding="utf-8"))
base = json.loads(
    (
        ROOT
        / "docs/experiments/2026-10-19-five-slot-local-repair/candidate.json"
    ).read_text(encoding="utf-8")
)
primary_groups = base["checks"]["primary_groups_by_educator"]
quality_context = solver.compact_quality_context(data)

base_checked, _ = solver.revalidate_cached_payload(
    data,
    base,
    quality_context=quality_context,
    **VERIFY_OPTIONS,
)
assert base_checked["checks"]["errors"] == [
    "Tara jeudi: coupure de 135 minutes > 90 minutes (10:45-13:00)",
    "Léa jeudi: coupure de 180 minutes > 90 minutes (10:00-13:00)",
    "Emilie vendredi: coupure de 135 minutes > 90 minutes (12:00-14:15)",
]

schedule = copy.deepcopy(base["schedule"])
changes = {
    "Tara jeudi": {
        "before": copy.deepcopy(schedule["Tara"]["jeudi"]),
        "after": [
            block("08:00", "10:45", "Grands", "haut"),
            block("12:15", "18:00", "Grands", "haut"),
        ],
    },
    "Fanny jeudi": {
        "before": copy.deepcopy(schedule["Fanny"]["jeudi"]),
        "after": [block("10:45", "18:45", "Grands", "haut")],
    },
    "Léa jeudi": {
        "before": copy.deepcopy(schedule["Léa"]["jeudi"]),
        "after": [
            block("08:45", "10:45", "Trotteur", "bas"),
            block("12:15", "18:45", "Trotteur", "bas"),
        ],
    },
    "Céline jeudi": {
        "before": copy.deepcopy(schedule["Céline"]["jeudi"]),
        "after": [
            block("08:00", "09:15", "Trotteur", "bas"),
            block("10:45", "13:15", "Trotteur", "bas"),
            block(
                "13:15", "14:00", "Nurserie", "bas", "remplacement_colloque"
            ),
            block("14:00", "18:00", "Trotteur", "bas"),
        ],
    },
    "Emilie vendredi": {
        "before": copy.deepcopy(schedule["Emilie"]["vendredi"]),
        "after": [
            block("08:30", "12:45", "Nurserie", "bas"),
            block("14:15", "18:00", "Nurserie", "bas"),
        ],
    },
}
for key, value in changes.items():
    educator, day = key.split(" ", 1)
    schedule[educator][day] = value["after"]

candidate, candidate_bundle = solver.revalidate_cached_payload(
    data,
    {
        "status": "ok",
        "schedule": schedule,
        "checks": {"primary_groups_by_educator": primary_groups},
    },
    quality_context=quality_context,
    **VERIFY_OPTIONS,
)
assert candidate["status"] == "ok", candidate["checks"]["errors"]
assert candidate["checks"]["errors"] == []
assert solver.hard_site_travel_errors(schedule) == []

cp_started = time.monotonic()
cp_payload, _ = solver.make_ortools_slot_payload(
    data, fixed_schedule=schedule, time_limit=20, **OPTIONS
)
cp_elapsed = round(time.monotonic() - cp_started, 4)
assert cp_payload["status"] == "ok", cp_payload
assert cp_payload["checks"]["errors"] == []
assert slot_assignments(cp_payload["schedule"]) == slot_assignments(schedule)

educator_index = {item["name"]: index for index, item in enumerate(data["educators"])}
group_index = {item["name"]: index for index, item in enumerate(data["groups"])}
fixed_primary_groups = {
    educator_index[name]: group_index[group]
    for name, group in primary_groups.items()
}
pattern_started = time.monotonic()
pattern_payload, _ = solve_pattern_mip(
    data,
    time_limit=30,
    fixed_daily_schedules=schedule,
    fixed_primary_groups=fixed_primary_groups,
    **OPTIONS,
)
pattern_elapsed = round(time.monotonic() - pattern_started, 4)
assert pattern_payload["status"] == "ok", pattern_payload
assert pattern_payload["checks"]["errors"] == []
assert slot_assignments(pattern_payload["schedule"]) == slot_assignments(schedule)

cp_checked, _ = solver.revalidate_cached_payload(
    data,
    dict(cp_payload, checks={"primary_groups_by_educator": primary_groups}),
    quality_context=quality_context,
    **VERIFY_OPTIONS,
)
pattern_checked, _ = solver.revalidate_cached_payload(
    data,
    dict(pattern_payload, checks={"primary_groups_by_educator": primary_groups}),
    quality_context=quality_context,
    **VERIFY_OPTIONS,
)
scores = {
    "candidate": solver.planning_quality_score(candidate),
    "cp_sat_fixed": solver.planning_quality_score(cp_checked),
    "patterns_fixed": solver.planning_quality_score(pattern_checked),
}
assert len(set(scores.values())) == 1, scores

write_csv(OUT / "candidate.csv", candidate)
write_html(OUT / "candidate.html", candidate, candidate_bundle)
for exported in (OUT / "candidate.csv", OUT / "candidate.html"):
    exported.write_text(
        "\n".join(line.rstrip() for line in exported.read_text(encoding="utf-8").splitlines())
        + "\n",
        encoding="utf-8",
    )
save("candidate.json", candidate)
save("changes.json", changes)
save("cp-fixed.json", cp_checked)
save("patterns-fixed.json", pattern_checked)

after_hashes = protected_hashes()
conditions = {
    "git_head": subprocess.check_output(
        ["git", "rev-parse", "HEAD"], cwd=ROOT, text=True
    ).strip(),
    "python": platform.python_version(),
    "options": OPTIONS,
    "source_candidate": "docs/experiments/2026-10-19-five-slot-local-repair/candidate.json",
    "scope": "Réparation locale sous maximum hard de 90 minutes.",
    "protected_hashes_before": before_hashes,
}
save("conditions.json", conditions)
save(
    "integrity.json",
    {
        "protected_hashes_before": before_hashes,
        "protected_hashes_after": after_hashes,
        "unchanged": before_hashes == after_hashes,
        "changed": sorted(
            key
            for key in before_hashes.keys() | after_hashes.keys()
            if before_hashes.get(key) != after_hashes.get(key)
        ),
    },
)
summary = {
    "elapsed_seconds": round(time.monotonic() - started, 4),
    "base_errors_under_90_minutes": base_checked["checks"]["errors"],
    "candidate_status": candidate["status"],
    "candidate_errors": candidate["checks"]["errors"],
    "travel_errors": solver.hard_site_travel_errors(schedule),
    "changed_days": list(changes),
    "cp_sat_fixed": {
        "status": cp_payload["status"],
        "message": cp_payload.get("solver_message"),
        "elapsed_seconds": cp_elapsed,
        "same_slot_assignments": True,
    },
    "patterns_fixed": {
        "status": pattern_payload["status"],
        "message": pattern_payload.get("solver_message"),
        "elapsed_seconds": pattern_elapsed,
        "same_slot_assignments": True,
    },
    "scores": scores,
    "protected_files_unchanged": before_hashes == after_hashes,
    "protected_files_changed": [],
    "active_planning_replaced": False,
}
assert summary["protected_files_unchanged"]
save("summary.json", summary)
print(json.dumps(summary, ensure_ascii=False, indent=2))
