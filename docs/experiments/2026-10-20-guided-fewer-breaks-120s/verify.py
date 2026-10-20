"""Cross-check the selected candidate with the fixed pattern engine."""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
OUT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "src"))

from creche_planning import domain, solver  # noqa: E402
from creche_planning.pattern_mip import solve_pattern_mip  # noqa: E402


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


def assignments(schedule: dict, data: dict) -> set[tuple]:
    horizon = domain.make_horizon(data)
    return {
        (name, day, slot, block["group"], block["site"], block.get("activity", "children"))
        for name, days in schedule.items()
        for day, blocks in days.items()
        for block in blocks
        for slot in domain.slot_range(horizon, block["start"], block["end"])
    }


data = json.loads((ROOT / "data/gwendo.json").read_text(encoding="utf-8"))
candidate = json.loads((OUT / "result.json").read_text(encoding="utf-8"))
primary = candidate["checks"]["primary_groups_by_educator"]
educator_index = {item["name"]: i for i, item in enumerate(data["educators"])}
group_index = {item["name"]: i for i, item in enumerate(data["groups"])}
fixed_primary = {
    educator_index[name]: group_index[group] for name, group in primary.items()
}

started = time.monotonic()
payload, _bundle = solve_pattern_mip(
    data,
    time_limit=30,
    fixed_daily_schedules=candidate["schedule"],
    fixed_primary_groups=fixed_primary,
    **OPTIONS,
)
elapsed = round(time.monotonic() - started, 4)
assert payload["status"] == "ok", payload
assert payload["checks"]["errors"] == []
same = assignments(payload["schedule"], data) == assignments(candidate["schedule"], data)
assert same
checked, _checked_bundle = solver.revalidate_cached_payload(
    data,
    dict(payload, checks={"primary_groups_by_educator": primary}),
    quality_context=solver.compact_quality_context(data),
    weekly_hours_tolerance_percent=5.0,
    weekly_hours_tolerance_step_minutes=15,
    enforce_absolute_max_weekly_hours=True,
    absolute_max_weekly_hours=40.0,
    the_enabled=True,
    the_percent=10.0,
    the_colloques_count=True,
    half_day_split_time="12:30",
    max_weekly_group_exception_days=1,
    max_split_gap_minutes=90,
    hard_max_work_days=True,
)
assert checked["status"] == "ok" and checked["checks"]["errors"] == []
solver.save_json(OUT / "patterns-fixed.json", checked)
solver.save_json(
    OUT / "cross-check.json",
    {
        "status": payload["status"],
        "message": payload.get("solver_message"),
        "elapsed_seconds": elapsed,
        "errors": payload["checks"]["errors"],
        "same_slot_assignments": same,
        "score": solver.planning_quality_score(checked),
    },
)
print((OUT / "cross-check.json").read_text(encoding="utf-8"))
