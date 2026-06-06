from __future__ import annotations

import json
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Any


DAYS = [
    ("lundi", "Lundi"),
    ("mardi", "Mardi"),
    ("mercredi", "Mercredi"),
    ("jeudi", "Jeudi"),
    ("vendredi", "Vendredi"),
]

DEFAULT_TYPE_ALIASES: dict[str, str] = {}

DEFAULT_QUALITY_PROFILES = {
    "equilibre": {
        "label": "Equilibre",
        "description": "Compromis entre journees continues, stabilite des groupes et preferences soft.",
        "weights": {
            "smooth_split_shift_weight": 120.0,
            "smooth_split_gap_weight": 4.0,
            "smooth_group_switch_day_weight": 8.0,
            "smooth_same_group_week_weight": 0.4,
            "main_group_day_weight": 80.0,
            "main_group_slot_weight": 3.0,
            "main_site_day_weight": 100.0,
            "soft_time_rule_weight": 1.0,
            "soft_group_rule_weight": 1.0,
        },
    },
    "journees_continues": {
        "label": "Journees continues",
        "description": "Priorite aux journees sans coupure, puis aux coupures les plus courtes.",
        "weights": {
            "smooth_split_shift_weight": 220.0,
            "smooth_split_gap_weight": 10.0,
            "smooth_group_switch_day_weight": 8.0,
            "smooth_same_group_week_weight": 0.4,
            "main_group_day_weight": 80.0,
            "main_group_slot_weight": 3.0,
            "main_site_day_weight": 100.0,
            "soft_time_rule_weight": 1.0,
            "soft_group_rule_weight": 1.0,
        },
    },
    "groupes_stables": {
        "label": "Groupes stables",
        "description": "Priorite a garder chaque personne dans son groupe principal.",
        "weights": {
            "smooth_split_shift_weight": 120.0,
            "smooth_split_gap_weight": 4.0,
            "smooth_group_switch_day_weight": 22.0,
            "smooth_same_group_week_weight": 1.2,
            "main_group_day_weight": 150.0,
            "main_group_slot_weight": 7.0,
            "main_site_day_weight": 120.0,
            "soft_time_rule_weight": 1.0,
            "soft_group_rule_weight": 1.4,
        },
    },
    "preferences_horaires": {
        "label": "Preferences horaires",
        "description": "Priorite aux regles horaires soft, apres les contraintes hard.",
        "weights": {
            "smooth_split_shift_weight": 120.0,
            "smooth_split_gap_weight": 4.0,
            "smooth_group_switch_day_weight": 8.0,
            "smooth_same_group_week_weight": 0.4,
            "main_group_day_weight": 80.0,
            "main_group_slot_weight": 3.0,
            "main_site_day_weight": 100.0,
            "soft_time_rule_weight": 2.5,
            "soft_group_rule_weight": 1.0,
        },
    },
    "preferences_groupes": {
        "label": "Preferences groupes",
        "description": "Priorite aux regles de groupe soft, apres les contraintes hard.",
        "weights": {
            "smooth_split_shift_weight": 120.0,
            "smooth_split_gap_weight": 4.0,
            "smooth_group_switch_day_weight": 12.0,
            "smooth_same_group_week_weight": 0.8,
            "main_group_day_weight": 120.0,
            "main_group_slot_weight": 5.0,
            "main_site_day_weight": 100.0,
            "soft_time_rule_weight": 1.0,
            "soft_group_rule_weight": 2.5,
        },
    },
}

DEFAULT_RUN_CONFIG = {
    "input_json": "gwendo.json",
    "output_json": "planning_gwendo_smooth.json",
    "csv_output": "planning_gwendo_smooth.csv",
    "html_output": "planning_gwendo_visuel.html",
    "write_latest_outputs": True,
    "latest_output_json": "planning_gwendo_latest.json",
    "latest_csv_output": "planning_gwendo_latest.csv",
    "latest_html_output": "planning_gwendo_latest.html",
    "rules_documentation": "REGLES_METIER.md",
    "solver_engine": "pattern_mip",
    "timestamp_outputs": True,
    "timestamp_format": "%Y-%m-%d_%H-%M-%S",
    "time_limit_seconds": 300.0,
    "quality_gap": 0.05,
    "weekly_mode": "exact",
    "quality_profile": "equilibre",
    "quality_profiles": DEFAULT_QUALITY_PROFILES,
    "fast_feasible": False,
    "smooth": True,
    "smooth_time_limit_seconds": 30.0,
    "smooth_split_shift_weight": 120.0,
    "smooth_split_gap_weight": 4.0,
    "max_pause_between_blocks_minutes": 90,
    "enforce_max_pause_between_blocks": False,
    "smooth_max_split_gap_minutes": 90,
    "smooth_group_switch_day_weight": 8.0,
    "smooth_same_group_week_weight": 0.4,
    "soft_time_rule_weight": 1.0,
    "soft_group_rule_weight": 1.0,
    "compact_work_days": True,
    "compact_work_day_weight": 45.0,
    "compact_part_time_priority": True,
    "hard_max_work_days": True,
    "relax_work_days_if_infeasible": True,
    "relaxed_work_day_weight": 500.0,
    "enforce_absolute_max_weekly_hours": True,
    "absolute_max_weekly_hours": 40.0,
    "weekly_hours_tolerance_percent": 3.0,
    "weekly_hours_tolerance_minutes": None,
    "weekly_hours_tolerance_step_minutes": 15,
    "the_enabled": True,
    "the_percent": 10.0,
    "the_colloques_count": True,
    "the_regular_is_invisible": True,
    "fix_primary_groups_from_latest": False,
    "weekly_stability": True,
    "primary_group": {
        "report_enabled": True,
        "warning_outside_hours": 4.0,
        "warning_outside_days": 1,
        "day_weight": 80.0,
        "slot_weight": 3.0,
        "site_day_weight": 100.0,
    },
    "main_group_day_weight": 80.0,
    "main_group_slot_weight": 3.0,
    "main_site_day_weight": 100.0,
    "half_day_split_time": "12:30",
    "max_weekly_group_exception_days": 1,
    "restricted_patterns": False,
    "restricted_pattern_mode": "continuous_halfday_groups",
    "structured": False,
    "max_blocks_per_day": 2,
    "min_daily_hours": 2.0,
    "enforce_min_daily_hours": False,
    "short_day_penalty_weight": 30.0,
    "type_aliases": {},
}


@dataclass(frozen=True)
class Horizon:
    start: int
    end: int
    step: int = 15

    @property
    def slots(self) -> int:
        return (self.end - self.start) // self.step


@dataclass
class SolverIndexes:
    x: dict[tuple[int, int, int, int], int]
    work_start: dict[tuple[int, int, int], int]
    group_start: dict[tuple[int, int, int, int], int]
    site_day: dict[tuple[int, int, int], int]
    group_day: dict[tuple[int, int, int], int]
    half_group: dict[tuple[int, int, int, int], int]
    mixed_group_day: dict[tuple[int, int], int]
    primary_group: dict[tuple[int, int], int]
    outside_group_slot: dict[tuple[int, int, int, int], int]
    outside_group_day: dict[tuple[int, int], int]
    primary_site: dict[tuple[int, int], int]
    outside_site_day: dict[tuple[int, int], int]
    var_count: int


@dataclass
class SolveBundle:
    result: Any
    data: dict[str, Any]
    horizon: Horizon
    indexes: SolverIndexes
    groups: list[dict[str, Any]]
    educators: list[dict[str, Any]]
    sites: list[str]
    warnings: list[str]
    objective_offset: float = 0.0


@dataclass(frozen=True)
class Pattern:
    site: str
    group_index: int
    start_slot: int
    end_slot: int

    @property
    def duration_slots(self) -> int:
        return self.end_slot - self.start_slot


@dataclass
class PatternSolveBundle:
    result: Any
    data: dict[str, Any]
    horizon: Horizon
    patterns: list[Pattern]
    variables: list[tuple[int, int, int]]
    groups: list[dict[str, Any]]
    educators: list[dict[str, Any]]
    sites: list[str]
    warnings: list[str]


def parse_time(value: str) -> int:
    hour, minute = value.split(":")
    return int(hour) * 60 + int(minute)


def format_time(minutes: int) -> str:
    return f"{minutes // 60:02d}:{minutes % 60:02d}"


def normalize_day(value: str) -> str:
    return value.strip().lower()


def day_index_by_key() -> dict[str, int]:
    return {key: index for index, (key, _label) in enumerate(DAYS)}


def normalize_day_list(value: Any) -> list[int]:
    if value is None:
        return list(range(len(DAYS)))
    if isinstance(value, (list, tuple)):
        raw_items = [str(item).strip() for item in value if str(item).strip()]
    else:
        text = str(value).strip().lower()
        if text in {"", "tous", "tout", "all", "*"}:
            return list(range(len(DAYS)))
        for separator in ("+", ";", "|", "/"):
            text = text.replace(separator, ",")
        raw_items = [item.strip() for item in text.split(",") if item.strip()]
    if not raw_items:
        return list(range(len(DAYS)))

    aliases = {
        "lundi": "lundi",
        "lun": "lundi",
        "mardi": "mardi",
        "mar": "mardi",
        "mercredi": "mercredi",
        "mer": "mercredi",
        "jeudi": "jeudi",
        "jeu": "jeudi",
        "vendredi": "vendredi",
        "ven": "vendredi",
    }
    day_by_name = day_index_by_key()
    result: list[int] = []
    for raw_item in raw_items:
        lowered = raw_item.lower()
        if lowered in {"tous", "tout", "all", "*"}:
            return list(range(len(DAYS)))
        day_key = aliases.get(lowered, lowered)
        if day_key not in day_by_name:
            raise ValueError(f"Jour inconnu dans rules_site_schedule: {raw_item}.")
        day_i = day_by_name[day_key]
        if day_i not in result:
            result.append(day_i)
    return result


def normalize_flag(value: str) -> str:
    return value.strip().lower().replace("Ã©", "e")


def load_json(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def save_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=2, ensure_ascii=False)
        handle.write("\n")


def weekly_tolerance_slots(
    target_hours: float,
    horizon: Horizon,
    *,
    percent: float = 3.0,
    minutes: int | None = None,
    step_minutes: int | None = 15,
) -> int:
    if minutes is not None:
        tolerance_minutes = max(0, int(minutes))
    else:
        tolerance_minutes = max(0.0, target_hours * 60.0 * max(0.0, float(percent)) / 100.0)
        if step_minutes:
            step = max(1, int(step_minutes))
            tolerance_minutes = math.floor((tolerance_minutes + 1e-9) / step) * step
    return int(round(float(tolerance_minutes) / horizon.step))


def absolute_weekly_max_slots(
    horizon: Horizon,
    absolute_max_weekly_hours: float | None,
) -> int | None:
    if absolute_max_weekly_hours is None:
        return None
    return int(math.floor(float(absolute_max_weekly_hours) / (horizon.step / 60.0) + 1e-9))


def the_target_slots(
    contract_target_slots: int,
    the_percent: float = 10.0,
    *,
    enabled: bool = True,
) -> int:
    if not enabled:
        return 0
    return int(round(max(0, contract_target_slots) * max(0.0, float(the_percent)) / 100.0))


def split_types(raw_types: list[Any], aliases: dict[str, str], known: set[str]) -> tuple[set[str], list[str]]:
    values: list[str] = []
    warnings: list[str] = []
    for item in raw_types:
        for chunk in str(item).replace("+", ",").replace(";", ",").split(","):
            value = chunk.strip()
            if value:
                values.append(value)

    normalized: set[str] = set()
    for value in values:
        mapped = aliases.get(value, value)
        if mapped != value:
            warnings.append(f"Alias type applique: {value} -> {mapped}.")
        if mapped not in known:
            warnings.append(f"Type inconnu dans une regle de pourcentage: {mapped}.")
        normalized.add(mapped)
    return normalized, warnings


def max_work_days_for_educator(
    educator: dict[str, Any],
    weekly_base: float,
    max_daily_hours: float,
) -> int:
    explicit = educator.get("max_work_days")
    if explicit is not None and str(explicit).strip() != "":
        return max(0, min(len(DAYS), int(explicit)))

    target_hours = float(educator.get("percentage", 0.0)) / 100.0 * weekly_base
    if target_hours <= 1e-9:
        return 0
    if max_daily_hours <= 0:
        return len(DAYS)
    return max(1, min(len(DAYS), int(math.ceil(target_hours / max_daily_hours - 1e-9))))


def normalize_colloque_list(row: Any) -> dict[str, Any]:
    if isinstance(row, dict):
        return {
            "group": row.get("group", ""),
            "day": row.get("day", ""),
            "start": row.get("start", ""),
            "end": row.get("end", ""),
        }
    values = list(row) if isinstance(row, (list, tuple)) else []
    while len(values) < 4:
        values.append("")
    return {"group": values[0], "day": values[1], "start": values[2], "end": values[3]}


def parse_colloques(
    data: dict[str, Any],
    horizon: Horizon,
    groups: list[dict[str, Any]],
    warnings: list[str] | None = None,
) -> list[dict[str, Any]]:
    group_by_name = {group["name"]: i for i, group in enumerate(groups)}
    day_by_name = {key: i for i, (key, _) in enumerate(DAYS)}
    colloques: list[dict[str, Any]] = []
    for raw_rule in data.get("rules_colloques", []):
        rule = normalize_colloque_list(raw_rule)
        group_name = str(rule.get("group", ""))
        day_key = normalize_day(str(rule.get("day", "")))
        if group_name not in group_by_name:
            if warnings is not None:
                warnings.append(f"Colloque avec groupe inconnu: {group_name}.")
            continue
        if day_key not in day_by_name:
            if warnings is not None:
                warnings.append(f"Colloque avec jour inconnu: {rule.get('day', '')}.")
            continue
        try:
            slots, clipped = slot_range_clipped(horizon, str(rule.get("start", "")), str(rule.get("end", "")))
        except Exception as exc:
            if warnings is not None:
                warnings.append(f"Colloque ignore ({group_name} {day_key}): {exc}")
            continue
        slot_list = list(slots)
        if not slot_list:
            continue
        if clipped and warnings is not None:
            warnings.append(f"Colloque rogne sur l'horizon: {raw_rule}.")
        group_i = group_by_name[group_name]
        colloques.append(
            {
                "id": len(colloques),
                "group": group_name,
                "group_i": group_i,
                "site": groups[group_i]["site"],
                "day": day_key,
                "day_i": day_by_name[day_key],
                "start_slot": slot_list[0],
                "end_slot": slot_list[-1] + 1,
                "slots": set(slot_list),
            }
        )
    return colloques


def make_horizon(data: dict[str, Any]) -> Horizon:
    starts: list[int] = []
    ends: list[int] = []
    for site in data.get("sites", []):
        starts.append(parse_time(site.get("open", "06:45")))
        ends.append(parse_time(site.get("close", "18:45")))
    for rule in data.get("rules_site_schedule", []):
        for interval in rule.get("time_intervals", []):
            starts.append(parse_time(interval["start"]))
            ends.append(parse_time(interval["end"]))
    for raw_rule in data.get("rules_colloques", []):
        rule = normalize_colloque_list(raw_rule)
        if rule.get("start") and rule.get("end"):
            starts.append(parse_time(str(rule["start"])))
            ends.append(parse_time(str(rule["end"])))
    if not starts or not ends:
        return Horizon(parse_time("06:45"), parse_time("18:45"))
    start = min(starts)
    end = max(ends)
    if (end - start) % 15:
        raise ValueError("Les horaires doivent tomber sur une granularite de 15 minutes.")
    return Horizon(start, end)


def slot_range(horizon: Horizon, start: str, end: str) -> range:
    start_min = parse_time(start)
    end_min = parse_time(end)
    if start_min < horizon.start or end_min > horizon.end:
        raise ValueError(f"Creneau hors horizon: {start}-{end}.")
    if (start_min - horizon.start) % horizon.step or (end_min - horizon.start) % horizon.step:
        raise ValueError(f"Creneau non aligne sur 15 minutes: {start}-{end}.")
    return range((start_min - horizon.start) // horizon.step, (end_min - horizon.start) // horizon.step)


def slot_range_clipped(horizon: Horizon, start: str, end: str) -> tuple[range, bool]:
    start_min = parse_time(start)
    end_min = parse_time(end)
    clipped = start_min < horizon.start or end_min > horizon.end
    start_min = max(start_min, horizon.start)
    end_min = min(end_min, horizon.end)
    if end_min <= start_min:
        return range(0), True
    if (start_min - horizon.start) % horizon.step or (end_min - horizon.start) % horizon.step:
        raise ValueError(f"Creneau non aligne sur 15 minutes: {start}-{end}.")
    return (
        range((start_min - horizon.start) // horizon.step, (end_min - horizon.start) // horizon.step),
        clipped,
    )


def add_row(
    rows: list[int],
    cols: list[int],
    vals: list[float],
    lower: list[float],
    upper: list[float],
    terms: list[tuple[int, float]],
    lb: float,
    ub: float,
) -> None:
    row_id = len(lower)
    for col, val in terms:
        if val:
            rows.append(row_id)
            cols.append(col)
            vals.append(float(val))
    lower.append(float(lb))
    upper.append(float(ub))


def build_demands(
    data: dict[str, Any],
    groups: list[dict[str, Any]],
    horizon: Horizon,
) -> tuple[dict[tuple[int, int], int], dict[tuple[str, int], int]]:
    group_demand_by_day, site_demand_by_day = build_demands_by_day(data, groups, horizon)
    group_demand: dict[tuple[int, int], int] = {
        (g_i, t_i): 0
        for g_i in range(len(groups))
        for t_i in range(horizon.slots)
    }
    site_demand: dict[tuple[str, int], int] = {}
    for (_d_i, g_i, t_i), staff in group_demand_by_day.items():
        key = (g_i, t_i)
        group_demand[key] = max(group_demand[key], staff)
    for (_d_i, site, t_i), staff in site_demand_by_day.items():
        key = (site, t_i)
        site_demand[key] = max(site_demand.get(key, 0), staff)
    return group_demand, site_demand


def build_demands_by_day(
    data: dict[str, Any],
    groups: list[dict[str, Any]],
    horizon: Horizon,
) -> tuple[dict[tuple[int, int, int], int], dict[tuple[int, str, int], int]]:
    group_demand: dict[tuple[int, int, int], int] = {
        (d_i, g_i, t_i): 0
        for d_i in range(len(DAYS))
        for g_i in range(len(groups))
        for t_i in range(horizon.slots)
    }
    site_demand: dict[tuple[int, str, int], int] = {}
    group_by_name = {group["name"]: i for i, group in enumerate(groups)}
    for rule in data.get("rules_site_schedule", []):
        site = rule["site"]
        for interval in rule.get("time_intervals", []):
            staff = int(interval.get("min_staff", 0))
            target_group = interval.get("group", "tous")
            day_indices = normalize_day_list(interval.get("days", rule.get("days")))
            for d_i in day_indices:
                for t_i in slot_range(horizon, interval["start"], interval["end"]):
                    if target_group == "tous":
                        key = (d_i, site, t_i)
                        site_demand[key] = max(site_demand.get(key, 0), staff)
                    else:
                        if target_group not in group_by_name:
                            raise ValueError(f"Groupe inconnu dans rules_site_schedule: {target_group}.")
                        key = (d_i, group_by_name[target_group], t_i)
                        group_demand[key] = max(group_demand[key], staff)
    return group_demand, site_demand


def split_slot_for_horizon(horizon: Horizon, split_time: str) -> int:
    split_min = parse_time(split_time)
    if split_min <= horizon.start or split_min >= horizon.end:
        return horizon.slots // 2
    return int(round((split_min - horizon.start) / horizon.step))
