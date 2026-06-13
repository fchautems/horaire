from __future__ import annotations

import math
import time
from array import array
from itertools import chain
from typing import Any, Callable, Iterable

import numpy as np
from scipy.optimize import Bounds, LinearConstraint, milp
from scipy.sparse import csr_matrix

from .domain import (
    DAYS,
    DEFAULT_TYPE_ALIASES,
    absolute_weekly_max_slots,
    build_demands_by_day,
    format_time,
    make_horizon,
    max_work_days_for_educator,
    normalize_day,
    normalize_flag,
    parse_colloques,
    parse_time,
    slot_range_clipped,
    split_slot_for_horizon,
    split_types,
    the_target_slots,
    weekly_tolerance_slots,
)


class PatternTimeLimitError(RuntimeError):
    def __init__(self, payload: dict[str, Any], bundle: Any) -> None:
        super().__init__(str(payload.get("solver_message", "Temps limite atteint.")))
        self.payload = payload
        self.bundle = bundle


def weekly_pattern_bounds(
    *,
    target_slots: int,
    tolerance_slots: int,
    the_slots: int,
    max_work_days: int,
    max_daily_slots: int,
    absolute_max_slots: int | None,
) -> tuple[int, int, int, int]:
    upper_visible = target_slots + tolerance_slots
    if absolute_max_slots is not None:
        upper_visible = min(upper_visible, absolute_max_slots)
    lower_child = max(0, target_slots - tolerance_slots - the_slots)
    upper_child = max(0, upper_visible - the_slots)
    min_child_on_worked_day = max(
        0,
        lower_child - max(0, max_work_days - 1) * max_daily_slots,
    )
    return lower_child, upper_child, upper_visible, min_child_on_worked_day


def pattern_hours_can_reach_week(
    *,
    child_slots: int,
    visible_slots: int,
    lower_child_slots: int,
    upper_child_slots: int,
    upper_visible_slots: int,
    max_work_days: int,
    max_daily_slots: int,
) -> bool:
    if child_slots > upper_child_slots or visible_slots > upper_visible_slots:
        return False
    worked_days = 1 if visible_slots > 0 else 0
    if worked_days > max_work_days:
        return False
    remaining_days = max(0, max_work_days - worked_days)
    return child_slots + remaining_days * max_daily_slots >= lower_child_slots


def highs_solve_budget(remaining_seconds: float, pattern_count: int) -> float:
    native_setup_reserve = max(5.0, min(180.0, pattern_count / 10_000.0))
    return max(0.0, remaining_seconds - native_setup_reserve)


def solve_pattern_mip(
    data: dict[str, Any],
    *,
    time_limit: float = 300.0,
    type_aliases: dict[str, str] | None = None,
    min_daily_hours: float = 2.0,
    enforce_min_daily_hours: bool = False,
    short_day_penalty_weight: float = 30.0,
    max_split_gap_minutes: int | None = 90,
    generation_max_split_gap_minutes: int | None = None,
    generation_time_step_minutes: int | None = None,
    fine_generation_time_step_minutes: int | None = None,
    fine_time_step_educators: set[str] | None = None,
    fixed_daily_schedules: dict[str, dict[str, list[dict[str, Any]]]] | None = None,
    reference_daily_schedules: dict[str, dict[str, list[dict[str, Any]]]] | None = None,
    continuous_only_educators: set[str] | None = None,
    weekly_hours_tolerance_minutes: int | None = None,
    weekly_hours_tolerance_percent: float = 3.0,
    weekly_hours_tolerance_step_minutes: int | None = 15,
    enforce_absolute_max_weekly_hours: bool = True,
    absolute_max_weekly_hours: float | None = 40.0,
    the_enabled: bool = True,
    the_percent: float = 10.0,
    the_colloques_count: bool = True,
    half_day_split_time: str = "12:30",
    max_weekly_group_exception_days: int | None = 1,
    split_shift_weight: float = 120.0,
    split_gap_weight: float = 4.0,
    group_switch_day_weight: float = 8.0,
    same_group_week_weight: float = 0.4,
    soft_time_rule_weight: float = 1.0,
    soft_group_rule_weight: float = 1.0,
    compact_work_days: bool = True,
    compact_work_day_weight: float = 45.0,
    compact_part_time_priority: bool = True,
    hard_max_work_days: bool = True,
    feasible_only: bool = False,
    restricted_patterns: bool = False,
    restricted_pattern_mode: str = "primary_only",
    fixed_primary_groups: dict[int, int] | None = None,
    quality_profile: str = "equilibre",
    quality_profile_label: str = "Equilibre",
    primary_group_report_enabled: bool = True,
    primary_group_warning_outside_hours: float = 4.0,
    primary_group_warning_outside_days: int = 1,
    progress_callback: Callable[[int, str], None] | None = None,
) -> tuple[dict[str, Any], Any]:
    # Imported lazily to keep solver.py's public API and avoid a module cycle.
    from .solver import (
        diagnose_basic_conflicts,
        diagnose_the_capacity,
        educator_attends_colloque,
        verify_solution,
    )

    started_at = time.monotonic()

    def elapsed_seconds() -> float:
        return time.monotonic() - started_at

    def remaining_seconds() -> float:
        return max(0.0, float(time_limit) - elapsed_seconds())

    def time_limit_payload(stage: str) -> dict[str, Any]:
        return {
            "status": "infeasible_or_not_solved",
            "solver_message": (
                f"Temps limite atteint pendant {stage} "
                f"({elapsed_seconds():.1f}s / {float(time_limit):.1f}s)."
            ),
            "warnings": sorted(set(warnings)),
            "diagnostics": [],
        }

    aliases = dict(DEFAULT_TYPE_ALIASES)
    if type_aliases:
        aliases.update(type_aliases)

    horizon = make_horizon(data)
    groups = list(data.get("groups", []))
    educators = list(data.get("educators", []))
    attends_colloque_by_educator = [educator_attends_colloque(educator) for educator in educators]
    sites = [site["name"] for site in data.get("sites", [])]
    warnings: list[str] = []
    bundle = type(
        "PatternMipBundle",
        (),
        {"data": data, "horizon": horizon, "groups": groups, "educators": educators, "sites": sites},
    )()
    restricted_mode = normalize_flag(restricted_pattern_mode)
    restricted_primary_only = restricted_patterns and restricted_mode in {
        "primary_only",
        "principal",
        "groupe_principal",
        "main_group",
        "strict",
    }
    restricted_one_group_per_day = restricted_patterns and restricted_mode in {
        "primary_only",
        "principal",
        "groupe_principal",
        "main_group",
        "strict",
        "continuous_any_group",
        "any_group",
        "single_group",
        "one_group",
    }
    if not groups or not educators or not sites:
        return (
            {
                "status": "infeasible_or_not_solved",
                "solver_message": "Donnees incompletes: sites, groupes ou educateurs manquants.",
                "warnings": warnings,
                "diagnostics": [],
            },
            bundle,
        )

    capacity_diagnostics = diagnose_the_capacity(
        data,
        horizon,
        weekly_hours_tolerance_percent=weekly_hours_tolerance_percent,
        weekly_hours_tolerance_minutes=weekly_hours_tolerance_minutes,
        weekly_hours_tolerance_step_minutes=weekly_hours_tolerance_step_minutes,
        enforce_absolute_max_weekly_hours=enforce_absolute_max_weekly_hours,
        absolute_max_weekly_hours=absolute_max_weekly_hours,
        the_enabled=the_enabled,
        the_percent=the_percent,
    )
    if any(item.startswith("Capacite enfants insuffisante") for item in capacity_diagnostics):
        return (
            {
                "status": "infeasible_or_not_solved",
                "solver_message": "Capacite enfants insuffisante avec le THE.",
                "warnings": warnings,
                "diagnostics": diagnose_basic_conflicts(data, horizon) + capacity_diagnostics,
            },
            bundle,
        )

    if progress_callback:
        if restricted_patterns and not restricted_one_group_per_day:
            message = "Generation des patrons simples demi-journees"
        elif restricted_patterns and not restricted_primary_only:
            message = "Generation des patrons simples elargis"
        elif restricted_patterns:
            message = "Generation des patrons simples"
        else:
            message = "Generation des patrons de journee"
        progress_callback(
            12,
            message,
        )

    group_demand, site_demand = build_demands_by_day(data, groups, horizon)
    group_by_site = {
        site: [g_i for g_i, group in enumerate(groups) if group["site"] == site]
        for site in sites
    }
    group_by_name = {group["name"]: i for i, group in enumerate(groups)}
    educator_by_name = {educator["name"]: i for i, educator in enumerate(educators)}
    known_types = {item["name"] for item in data.get("educator_types", [])}
    educator_types = [educator.get("type", "") for educator in educators]
    weekly_base = float(data.get("rules_global", {}).get("max_weekly_hours", 40.0))
    max_daily_hours = float(data.get("rules_global", {}).get("max_daily_hours", 8.5))
    max_daily_slots = int(round(max_daily_hours / (horizon.step / 60.0)))
    min_daily_slots = int(round(float(min_daily_hours) / (horizon.step / 60.0)))
    generated_min_daily_slots = min_daily_slots if enforce_min_daily_hours else 1
    absolute_max_slots = absolute_weekly_max_slots(
        horizon,
        absolute_max_weekly_hours if enforce_absolute_max_weekly_hours else None,
    )
    max_work_days_by_educator = {
        e_i: max_work_days_for_educator(educator, weekly_base, max_daily_hours)
        for e_i, educator in enumerate(educators)
    }
    split_slot = split_slot_for_horizon(horizon, half_day_split_time)
    generated_gap_minutes = (
        generation_max_split_gap_minutes
        if generation_max_split_gap_minutes is not None
        else max_split_gap_minutes
    )
    max_gap_slots = (
        None
        if generated_gap_minutes is None
        else int(round(generated_gap_minutes / horizon.step))
    )
    generation_max_gap_slots = max_gap_slots if max_gap_slots is not None else horizon.slots
    min_segment_slots = 4
    scale = 100.0
    colloques = parse_colloques(data, horizon, groups, warnings)
    colloques_by_day: dict[int, list[dict[str, Any]]] = {}
    colloque_by_group: dict[int, dict[str, Any]] = {}
    for colloque in colloques:
        colloques_by_day.setdefault(int(colloque["day_i"]), []).append(colloque)
        group_i = int(colloque["group_i"])
        colloque["_slot_mask"] = sum(1 << int(slot) for slot in colloque["slots"])
        if group_i in colloque_by_group:
            warnings.append(f"Plusieurs colloques definis pour le groupe {groups[group_i]['name']}.")
        else:
            colloque_by_group[group_i] = colloque

    weekly_pattern_limits: dict[int, tuple[int, int, int, int]] = {}
    for e_i, educator in enumerate(educators):
        target_hours = float(educator["percentage"]) / 100.0 * weekly_base
        target_slots = int(round(target_hours / (horizon.step / 60.0)))
        tolerance_slots = weekly_tolerance_slots(
            target_hours,
            horizon,
            percent=weekly_hours_tolerance_percent,
            minutes=weekly_hours_tolerance_minutes,
            step_minutes=weekly_hours_tolerance_step_minutes,
        )
        weekly_pattern_limits[e_i] = weekly_pattern_bounds(
            target_slots=target_slots,
            tolerance_slots=tolerance_slots,
            the_slots=the_target_slots(target_slots, the_percent, enabled=the_enabled),
            max_work_days=max_work_days_by_educator[e_i],
            max_daily_slots=max_daily_slots,
            absolute_max_slots=absolute_max_slots,
        )

    day_index = {day_key: d_i for d_i, (day_key, _label) in enumerate(DAYS)}
    forbidden_masks: dict[tuple[int, int], int] = {}
    required_masks: dict[tuple[int, int], list[int]] = {}
    soft_slot_costs: dict[tuple[int, int], list[float]] = {}
    for raw_rule in data.get("rules_time", []):
        if len(raw_rule) < 6:
            continue
        pref_type, strength, educator_name, day_name, start, end = raw_rule[:6]
        e_i = educator_by_name.get(educator_name)
        d_i = day_index.get(normalize_day(day_name))
        if e_i is None or d_i is None:
            continue
        slots = tuple(slot_range_clipped(horizon, str(start), str(end))[0])
        slot_mask = sum(1 << int(slot) for slot in slots)
        key = (e_i, d_i)
        is_negative = normalize_flag(pref_type) in {"negatif", "negative", "neg"}
        if normalize_flag(strength) == "hard":
            if is_negative:
                forbidden_masks[key] = forbidden_masks.get(key, 0) | slot_mask
            else:
                required_masks.setdefault(key, []).append(slot_mask)
            continue
        costs_for_day = soft_slot_costs.setdefault(key, [0.0] * horizon.slots)
        slot_cost = 45.0 * soft_time_rule_weight if is_negative else -35.0 * soft_time_rule_weight
        for slot in slots:
            costs_for_day[int(slot)] += slot_cost
    soft_cost_prefixes: dict[tuple[int, int], list[float]] = {}
    for key, slot_costs in soft_slot_costs.items():
        prefix = [0.0]
        for slot_cost in slot_costs:
            prefix.append(prefix[-1] + slot_cost)
        soft_cost_prefixes[key] = prefix

    hard_primary_groups: dict[int, int] = {}
    primary_group_costs: dict[tuple[int, int], float] = {
        (e_i, g_i): 0.0
        for e_i in range(len(educators))
        for g_i in range(len(groups))
    }
    allowed_primary_groups: dict[int, set[int]] = {
        e_i: set(range(len(groups)))
        for e_i in range(len(educators))
    }
    for raw_rule in data.get("rules_group", []):
        if len(raw_rule) < 4:
            continue
        pref_type, strength, educator_name, group_name = raw_rule[:4]
        if educator_name not in educator_by_name or group_name not in group_by_name:
            continue
        e_i = educator_by_name[educator_name]
        g_i = group_by_name[group_name]
        is_negative = normalize_flag(pref_type) in {"negatif", "negative", "neg"}
        is_hard = normalize_flag(strength) == "hard"
        if is_hard and is_negative:
            allowed_primary_groups[e_i].discard(g_i)
        elif is_hard:
            previous = hard_primary_groups.get(e_i)
            if previous is not None and previous != g_i:
                return (
                    {
                        "status": "infeasible_or_not_solved",
                        "solver_message": "Regles groupe hard incompatibles.",
                        "warnings": sorted(set(warnings)),
                        "diagnostics": [
                            f"{educator_name} a plusieurs groupes principaux hard: "
                            f"{groups[previous]['name']} et {group_name}."
                        ],
                    },
                    bundle,
                )
            hard_primary_groups[e_i] = g_i
        else:
            primary_group_costs[(e_i, g_i)] += 6_000.0 if is_negative else -6_000.0
    for e_i, g_i in hard_primary_groups.items():
        allowed_primary_groups[e_i] = {g_i} if g_i in allowed_primary_groups[e_i] else set()
    for e_i, educator in enumerate(educators):
        if not attends_colloque_by_educator[e_i]:
            continue
        educator_name = educator["name"]
        for g_i, colloque in colloque_by_group.items():
            if g_i not in allowed_primary_groups[e_i]:
                continue
            blocked = False
            for raw_rule in data.get("rules_time", []):
                if len(raw_rule) < 6:
                    continue
                pref_type, strength, rule_educator, rule_day, start, end = raw_rule[:6]
                if rule_educator != educator_name or normalize_day(rule_day) != str(colloque["day"]):
                    continue
                if normalize_flag(strength) != "hard":
                    continue
                if normalize_flag(pref_type) not in {"negatif", "negative", "neg"}:
                    continue
                rule_slots = set(slot_range_clipped(horizon, str(start), str(end))[0])
                if rule_slots & set(colloque["slots"]):
                    blocked = True
                    break
            if blocked:
                allowed_primary_groups[e_i].discard(g_i)
    if fixed_primary_groups:
        for e_i, g_i in fixed_primary_groups.items():
            if 0 <= e_i < len(educators) and g_i in allowed_primary_groups[e_i]:
                allowed_primary_groups[e_i] = {g_i}
            elif 0 <= e_i < len(educators):
                warnings.append(
                    f"Groupe principal suggere ignore pour {educators[e_i]['name']}: "
                    f"{groups[g_i]['name'] if 0 <= g_i < len(groups) else g_i}."
                )

    for e_i, allowed in list(allowed_primary_groups.items()):
        if attends_colloque_by_educator[e_i] or not allowed:
            continue
        forced = hard_primary_groups.get(e_i)
        selected = forced if forced in allowed else min(
            allowed,
            key=lambda g_i: (primary_group_costs.get((e_i, g_i), 0.0), g_i),
        )
        allowed_primary_groups[e_i] = {selected}

    for e_i, allowed in allowed_primary_groups.items():
        if not allowed:
            return (
                {
                    "status": "infeasible_or_not_solved",
                    "solver_message": "Aucun groupe principal possible.",
                    "warnings": sorted(set(warnings)),
                    "diagnostics": [f"Aucun groupe principal possible pour {educators[e_i]['name']}."],
                },
                bundle,
            )

    primary_class_representative: dict[tuple[int, int, int], int] = {}
    for e_i, allowed in allowed_primary_groups.items():
        for d_i in range(len(DAYS)):
            target_groups = {
                int(colloque["group_i"])
                for colloque in colloques_by_day.get(d_i, [])
                if int(colloque["group_i"]) in allowed
            }
            shared_groups = sorted(allowed - target_groups)
            shared_representative = shared_groups[0] if shared_groups else None
            for g_i in allowed:
                if feasible_only and not restricted_primary_only and g_i not in target_groups:
                    primary_class_representative[(e_i, d_i, g_i)] = int(shared_representative)
                else:
                    primary_class_representative[(e_i, d_i, g_i)] = g_i

    base_generation_step_slots = max(
        1,
        int(round(float(generation_time_step_minutes or horizon.step) / horizon.step)),
    )
    fine_generation_step_slots = max(
        1,
        int(round(float(fine_generation_time_step_minutes or horizon.step) / horizon.step)),
    )
    fine_time_step_educators = set(fine_time_step_educators or set())
    fixed_daily_schedules = dict(fixed_daily_schedules or {})
    reference_daily_schedules = dict(reference_daily_schedules or {})
    continuous_only_educators = set(continuous_only_educators or set())
    mandatory_start_candidates: set[int] = set()
    mandatory_end_candidates: set[int] = set()
    for rule in data.get("rules_site_schedule", []):
        for interval in rule.get("time_intervals", []):
            for value in (interval.get("start"), interval.get("end")):
                if value:
                    minute = parse_time(str(value))
                    if horizon.start <= minute <= horizon.end:
                        slot = (minute - horizon.start) // horizon.step
                        mandatory_start_candidates.add(slot)
                        mandatory_end_candidates.add(slot)
    for raw_rule in data.get("rules_time", []):
        if len(raw_rule) < 6:
            continue
        for value in (raw_rule[4], raw_rule[5]):
            minute = max(horizon.start, min(horizon.end, parse_time(str(value))))
            slot = (minute - horizon.start) // horizon.step
            mandatory_start_candidates.add(slot)
            mandatory_end_candidates.add(slot)
    mandatory_start_candidates = {
        slot for slot in mandatory_start_candidates if 0 <= slot < horizon.slots
    }
    mandatory_end_candidates = {
        slot for slot in mandatory_end_candidates if 0 < slot <= horizon.slots
    }

    costs = array("d")
    pattern_owner_educator = array("H")
    pattern_owner_day = array("B")
    pattern_first_start = array("h")
    pattern_first_end = array("h")
    pattern_second_start = array("h")
    pattern_second_end = array("h")
    pattern_morning_group = array("h")
    pattern_afternoon_group = array("h")
    pattern_slot_coverage_overrides: list[dict[int, int] | None] = []
    pattern_slot_display_overrides: list[dict[int, int] | None] = []
    pattern_slot_activities: list[dict[int, str] | None] = []
    pattern_duration = array("h")
    pattern_child_duration = array("h")
    pattern_mixed = array("b")
    by_educator_day: dict[tuple[int, int], array] = {}
    by_educator_day_primary: dict[tuple[int, int, int], array] = {}
    by_educator: dict[int, array] = {}
    coverage_terms: dict[tuple[int, int, int], array] = {}
    site_terms: dict[tuple[int, str, int], array] = {}
    percentage_terms: dict[str, tuple[array, array, array]] = {
        site: (array("i"), array("H"), array("h"))
        for site in sites
    }
    replacement_terms: dict[tuple[int, int], array] = {}
    pattern_breakdown: dict[str, dict[str, dict[str, int]]] = {}
    pattern_stats = {
        "off": 0,
        "continuous": 0,
        "split": 0,
        "mixed_group": 0,
        "cross_site_split": 0,
        "replacement": 0,
        "colloque": 0,
        "deduplicated": 0,
        "weekly_pruned": 0,
    }

    def current_pattern_statistics() -> dict[str, Any]:
        return {
            "total": len(costs),
            **pattern_stats,
            "by_educator_day": pattern_breakdown,
        }

    def generation_time_limit_result() -> tuple[dict[str, Any], Any]:
        payload = time_limit_payload("la generation des patrons")
        payload["pattern_statistics"] = current_pattern_statistics()
        return payload, bundle

    def raise_time_limit(stage: str) -> None:
        payload = time_limit_payload(stage)
        payload["pattern_statistics"] = current_pattern_statistics()
        raise PatternTimeLimitError(payload, bundle)

    def append_pattern_index(mapping: dict[Any, array], key: Any, pattern_id: int) -> None:
        mapping.setdefault(key, array("i")).append(pattern_id)

    def segments_mask(segments: tuple[tuple[int, int], ...]) -> int:
        mask = 0
        for start, end in segments:
            if end > start:
                mask |= ((1 << (end - start)) - 1) << start
        return mask

    work_cost_cache: dict[tuple[int, int, tuple[tuple[int, int], ...]], float | None] = {}

    def work_cost_or_none(e_i: int, day_key: str, segments: tuple[tuple[int, int], ...]) -> float | None:
        d_i = day_index[day_key]
        cache_key = (e_i, d_i, segments)
        if cache_key in work_cost_cache:
            return work_cost_cache[cache_key]
        worked_mask = segments_mask(segments)
        rule_key = (e_i, d_i)
        if worked_mask & forbidden_masks.get(rule_key, 0):
            work_cost_cache[cache_key] = None
            return None
        if any(not (worked_mask & required) for required in required_masks.get(rule_key, ())):
            work_cost_cache[cache_key] = None
            return None
        cost = 0.0
        prefix = soft_cost_prefixes.get(rule_key)
        if prefix is not None:
            for start, end in segments:
                cost += prefix[end] - prefix[start]
        if len(segments) > 1:
            gap = segments[1][0] - segments[0][1]
            if max_gap_slots is not None and gap > max_gap_slots:
                work_cost_cache[cache_key] = None
                return None
            cost += split_shift_weight * scale + gap * split_gap_weight * scale
        work_cost_cache[cache_key] = cost
        return cost

    group_cost_cache: dict[tuple[int, int, int, int], float | None] = {}

    def group_cost_or_none(e_i: int, primary_g: int, g_i: int, slots: int) -> float | None:
        cache_key = (e_i, primary_g, g_i, slots)
        if cache_key in group_cost_cache:
            return group_cost_cache[cache_key]
        educator_name = educators[e_i]["name"]
        group_name = groups[g_i]["name"]
        cost = 0.0
        if attends_colloque_by_educator[e_i] and primary_g != g_i:
            cost += slots * same_group_week_weight * scale
        for raw_rule in data.get("rules_group", []):
            if len(raw_rule) < 4 or raw_rule[2] != educator_name:
                continue
            pref_type, strength, _, rule_group = raw_rule[:4]
            is_negative = normalize_flag(pref_type) in {"negatif", "negative", "neg"}
            affected = group_name == rule_group if is_negative else group_name != rule_group
            if not affected:
                continue
            if normalize_flag(strength) == "hard":
                # Hard group rules select the primary group. Daily assignments
                # may still cover another group when the other hard rules allow it.
                continue
            cost += slots * 18.0 * soft_group_rule_weight
        group_cost_cache[cache_key] = cost
        return cost

    def pattern_hours_possible(e_i: int, child_slots: int, visible_slots: int) -> bool:
        lower_child, upper_child, upper_visible, _minimum_worked = weekly_pattern_limits[e_i]
        return pattern_hours_can_reach_week(
            child_slots=child_slots,
            visible_slots=visible_slots,
            lower_child_slots=lower_child,
            upper_child_slots=upper_child,
            upper_visible_slots=upper_visible,
            max_work_days=max_work_days_by_educator[e_i],
            max_daily_slots=max_daily_slots,
        )

    current_signature_domain: tuple[int, int, int] | None = None
    current_pattern_signatures: dict[tuple[Any, ...], int] = {}
    generation_operations = 0

    def begin_pattern_domain(e_i: int, d_i: int, primary_g: int) -> None:
        nonlocal current_signature_domain, current_pattern_signatures
        current_signature_domain = (e_i, d_i, primary_g)
        current_pattern_signatures = {}

    def pattern_signature(
        segments: tuple[tuple[int, int], ...],
        half_groups: dict[int, int],
        coverage_overrides: dict[int, int],
        display_overrides: dict[int, int],
        activities: dict[int, str],
    ) -> tuple[Any, ...]:
        return (
            segments,
            half_groups.get(0, -1),
            half_groups.get(1, -1),
            tuple(sorted(coverage_overrides.items())),
            tuple(sorted(display_overrides.items())),
            tuple(sorted(activities.items())),
        )

    def add_pattern(
        e_i: int,
        d_i: int,
        primary_g: int,
        site: str | None,
        segments: tuple[tuple[int, int], ...],
        half_groups: dict[int, int],
        duration: int,
        cost: float,
        replacement: tuple[int, int] | None = None,
        expand_replacements: bool = True,
    ) -> None:
        nonlocal generation_operations
        generation_operations += 1
        if generation_operations % 2048 == 0 and remaining_seconds() <= 1.0:
            raise_time_limit("la generation des patrons")
        if expand_replacements and duration > 0:
            for option in replacement_options(d_i, segments, half_groups):
                add_pattern(
                    e_i,
                    d_i,
                    primary_g,
                    site,
                    segments,
                    half_groups,
                    duration,
                    cost,
                    replacement=option,
                    expand_replacements=False,
                )
            return
        worked = {slot for start, end in segments for slot in range(start, end)}
        coverage_overrides: dict[int, int] = {}
        display_overrides: dict[int, int] = {}
        activities: dict[int, str] = {}
        invalid_pattern = False
        attends_colloque = attends_colloque_by_educator[e_i]
        for colloque in colloques_by_day.get(d_i, []):
            target_g = int(colloque["group_i"])
            overlap = worked & colloque["slots"]
            if attends_colloque and primary_g == target_g and overlap and not colloque["slots"].issubset(worked):
                invalid_pattern = True
                break
            for slot in overlap:
                base_g = half_groups[0 if slot < split_slot else 1]
                if attends_colloque and primary_g == target_g and base_g == target_g:
                    coverage_overrides[slot] = -1
                    display_overrides[slot] = target_g
                    activities[slot] = "colloque"
                elif base_g == target_g and not (primary_g == target_g and not attends_colloque):
                    invalid_pattern = True
                    break
            if invalid_pattern:
                break
            if replacement and replacement[0] == int(colloque["id"]):
                for slot in colloque["slots"]:
                    if slot in worked:
                        coverage_overrides[slot] = target_g
                        display_overrides[slot] = target_g
                        activities[slot] = "remplacement_colloque"
        if invalid_pattern:
            return
        used_groups = {
            half_groups[0 if slot < split_slot else 1]
            for start, end in segments
            for slot in range(start, end)
        }
        mixed = 1 if len({item for item in used_groups if item >= 0}) > 1 else 0
        used_sites = {
            str(groups[group_i]["site"])
            for group_i in used_groups
            if group_i >= 0
        }
        cross_site_split = len(segments) > 1 and len(used_sites) > 1
        if 0 < duration < min_daily_slots:
            missing_slots = min_daily_slots - duration
            cost += missing_slots * short_day_penalty_weight * scale
        if compact_work_days and duration > 0:
            compact_multiplier = 1.0
            if compact_part_time_priority:
                percentage = max(1.0, float(educators[e_i].get("percentage", 100.0)))
                compact_multiplier = max(1.0, 100.0 / percentage)
            cost += compact_work_day_weight * scale * compact_multiplier
        final_cost = cost + (group_switch_day_weight * scale if mixed else 0.0)
        child_duration = 0
        colloque_the_duration = 0
        for start, end in segments:
            for slot in range(start, end):
                half_i = 0 if slot < split_slot else 1
                g_i = coverage_overrides.get(slot, half_groups[half_i])
                if activities.get(slot) == "colloque" and the_colloques_count:
                    colloque_the_duration += 1
                if g_i >= 0:
                    child_duration += 1
        if not pattern_hours_possible(e_i, child_duration, duration):
            pattern_stats["weekly_pruned"] += 1
            return
        signature = pattern_signature(
            segments,
            half_groups,
            coverage_overrides,
            display_overrides,
            activities,
        )
        if current_signature_domain == (e_i, d_i, primary_g):
            duplicate_id = current_pattern_signatures.get(signature)
            if duplicate_id is not None:
                if final_cost < costs[duplicate_id]:
                    costs[duplicate_id] = final_cost
                pattern_stats["deduplicated"] += 1
                return
        pattern_id = len(costs)
        if current_signature_domain == (e_i, d_i, primary_g):
            current_pattern_signatures[signature] = pattern_id
        costs.append(final_cost)
        pattern_owner_educator.append(e_i)
        pattern_owner_day.append(d_i)
        first_start, first_end = segments[0] if segments else (-1, -1)
        second_start, second_end = segments[1] if len(segments) > 1 else (-1, -1)
        pattern_first_start.append(first_start)
        pattern_first_end.append(first_end)
        pattern_second_start.append(second_start)
        pattern_second_end.append(second_end)
        pattern_morning_group.append(half_groups.get(0, -1))
        pattern_afternoon_group.append(half_groups.get(1, -1))
        pattern_slot_coverage_overrides.append(coverage_overrides or None)
        pattern_slot_display_overrides.append(display_overrides or None)
        pattern_slot_activities.append(activities or None)
        pattern_duration.append(duration)
        pattern_child_duration.append(child_duration)
        pattern_mixed.append(mixed)
        if duration == 0:
            pattern_stats["off"] += 1
        elif len(segments) > 1:
            pattern_stats["split"] += 1
        else:
            pattern_stats["continuous"] += 1
        if mixed:
            pattern_stats["mixed_group"] += 1
        if cross_site_split:
            pattern_stats["cross_site_split"] += 1
        if replacement:
            pattern_stats["replacement"] += 1
        if colloque_the_duration:
            pattern_stats["colloque"] += 1
        day_stats = pattern_breakdown.setdefault(educators[e_i]["name"], {}).setdefault(
            DAYS[d_i][0],
            {
                "total": 0,
                "off": 0,
                "continuous": 0,
                "split": 0,
                "mixed_group": 0,
                "cross_site_split": 0,
                "replacement": 0,
                "colloque": 0,
            },
        )
        day_stats["total"] += 1
        if duration == 0:
            day_stats["off"] += 1
        elif len(segments) > 1:
            day_stats["split"] += 1
        else:
            day_stats["continuous"] += 1
        if mixed:
            day_stats["mixed_group"] += 1
        if cross_site_split:
            day_stats["cross_site_split"] += 1
        if replacement:
            day_stats["replacement"] += 1
        if colloque_the_duration:
            day_stats["colloque"] += 1
        append_pattern_index(by_educator_day, (e_i, d_i), pattern_id)
        append_pattern_index(by_educator_day_primary, (e_i, d_i, primary_g), pattern_id)
        append_pattern_index(by_educator, e_i, pattern_id)
        if replacement:
            append_pattern_index(replacement_terms, replacement, pattern_id)
        site_durations: dict[str, int] = {}
        for start, end in segments:
            for slot in range(start, end):
                half_i = 0 if slot < split_slot else 1
                g_i = coverage_overrides.get(slot, half_groups[half_i])
                if g_i < 0:
                    continue
                append_pattern_index(coverage_terms, (d_i, g_i, slot), pattern_id)
                slot_site = groups[g_i]["site"]
                if (d_i, slot_site, slot) in site_demand:
                    append_pattern_index(site_terms, (d_i, slot_site, slot), pattern_id)
                site_durations[slot_site] = site_durations.get(slot_site, 0) + 1
        for slot_site, site_duration in site_durations.items():
            pattern_ids, educator_ids, durations = percentage_terms[slot_site]
            pattern_ids.append(pattern_id)
            educator_ids.append(e_i)
            durations.append(site_duration)

    def replacement_options(
        d_i: int,
        segments: tuple[tuple[int, int], ...],
        half_groups: dict[int, int],
    ) -> list[tuple[int, int] | None]:
        worked_mask = segments_mask(segments)
        options: list[tuple[int, int] | None] = [None]
        for colloque in colloques_by_day.get(d_i, []):
            colloque_mask = int(colloque["_slot_mask"])
            if worked_mask & colloque_mask != colloque_mask:
                continue
            base_groups = {half_groups[0 if slot < split_slot else 1] for slot in colloque["slots"]}
            if len(base_groups) != 1:
                continue
            source_g = next(iter(base_groups))
            if source_g >= 0 and source_g != int(colloque["group_i"]):
                options.append((int(colloque["id"]), source_g))
        return options

    def add_fixed_day_pattern(
        e_i: int,
        d_i: int,
        primary_g: int,
        blocks: list[dict[str, Any]],
    ) -> bool:
        if not blocks:
            add_pattern(
                e_i,
                d_i,
                primary_g,
                None,
                (),
                {0: -1, 1: -1},
                0,
                0.0,
                expand_replacements=False,
            )
            return True

        worked: set[int] = set()
        ordinary_groups_by_half: dict[int, set[int]] = {0: set(), 1: set()}
        replacement: tuple[int, int] | None = None
        replacement_target: int | None = None
        for block in blocks:
            group_name = str(block.get("group", ""))
            if group_name not in group_by_name:
                return False
            block_slots = set(
                slot_range_clipped(
                    horizon,
                    str(block.get("start", "")),
                    str(block.get("end", "")),
                )[0]
            )
            worked.update(block_slots)
            activity = str(block.get("activity", ""))
            if activity == "remplacement_colloque":
                replacement_target = group_by_name[group_name]
                continue
            if activity == "colloque":
                continue
            group_i = group_by_name[group_name]
            for slot in block_slots:
                ordinary_groups_by_half[0 if slot < split_slot else 1].add(group_i)

        half_groups: dict[int, int] = {}
        for half_i in (0, 1):
            half_groups_found = ordinary_groups_by_half[half_i]
            if len(half_groups_found) > 1:
                return False
            half_groups[half_i] = (
                next(iter(half_groups_found))
                if half_groups_found
                else primary_g
            )

        if replacement_target is not None:
            colloque = colloque_by_group.get(replacement_target)
            if colloque is None or int(colloque["day_i"]) != d_i:
                return False
            source_half = 0 if int(colloque["start_slot"]) < split_slot else 1
            replacement = (int(colloque["id"]), half_groups[source_half])

        segments: list[tuple[int, int]] = []
        for slot in sorted(worked):
            if not segments or slot > segments[-1][1]:
                segments.append((slot, slot + 1))
            else:
                segments[-1] = (segments[-1][0], slot + 1)
        if len(segments) > 2:
            return False
        add_pattern(
            e_i,
            d_i,
            primary_g,
            None,
            tuple(segments),
            half_groups,
            len(worked),
            0.0,
            replacement=replacement,
            expand_replacements=False,
        )
        return True

    for colloque in colloques:
        mandatory_start_candidates.add(int(colloque["start_slot"]))
        mandatory_end_candidates.add(int(colloque["end_slot"]))

    for e_i in range(len(educators)):
        educator_name = educators[e_i]["name"]
        fixed_days = fixed_daily_schedules.get(educator_name)
        if fixed_days is not None:
            if len(allowed_primary_groups[e_i]) != 1:
                return (
                    {
                        "status": "infeasible_or_not_solved",
                        "solver_message": (
                            f"Groupe principal non fixe pour le planning conserve de {educator_name}."
                        ),
                        "warnings": warnings,
                        "diagnostics": [],
                    },
                    bundle,
                )
            primary_g = next(iter(allowed_primary_groups[e_i]))
            for d_i, (day_key, _) in enumerate(DAYS):
                blocks = fixed_days.get(day_key, [])
                if not add_fixed_day_pattern(e_i, d_i, primary_g, list(blocks)):
                    return (
                        {
                            "status": "infeasible_or_not_solved",
                            "solver_message": (
                                f"Planning conserve impossible a convertir pour "
                                f"{educator_name} {day_key}."
                            ),
                            "warnings": warnings,
                            "diagnostics": [],
                        },
                        bundle,
                    )
            continue
        reference_days = reference_daily_schedules.get(educator_name)
        if reference_days is not None:
            if len(allowed_primary_groups[e_i]) != 1:
                return (
                    {
                        "status": "infeasible_or_not_solved",
                        "solver_message": (
                            f"Groupe principal non fixe pour le planning de reference "
                            f"de {educator_name}."
                        ),
                        "warnings": warnings,
                        "diagnostics": [],
                    },
                    bundle,
                )
            reference_primary_g = next(iter(allowed_primary_groups[e_i]))
            for reference_d_i, (reference_day_key, _) in enumerate(DAYS):
                add_fixed_day_pattern(
                    e_i,
                    reference_d_i,
                    reference_primary_g,
                    list(reference_days.get(reference_day_key, [])),
                )
        generation_step_slots = (
            fine_generation_step_slots
            if educators[e_i]["name"] in fine_time_step_educators
            else base_generation_step_slots
        )
        start_candidates = mandatory_start_candidates | set(
            range(0, horizon.slots, generation_step_slots)
        )
        end_candidates = mandatory_end_candidates | set(
            range(generation_step_slots, horizon.slots + 1, generation_step_slots)
        )
        sorted_start_candidates = tuple(sorted(start_candidates))
        attends_colloque = attends_colloque_by_educator[e_i]
        sorted_primary_groups = sorted(allowed_primary_groups[e_i])
        for primary_g in sorted_primary_groups:
            primary_group = groups[primary_g]
            primary_site = primary_group["site"]
            primary_colloque = colloque_by_group.get(primary_g)
            for d_i, (day_key, _) in enumerate(DAYS):
                if primary_class_representative[(e_i, d_i, primary_g)] != primary_g:
                    continue
                begin_pattern_domain(e_i, d_i, primary_g)
                requires_colloque = (
                    attends_colloque
                    and primary_colloque is not None
                    and int(primary_colloque["day_i"]) == d_i
                )
                off_cost = work_cost_or_none(e_i, day_key, ())
                if off_cost is not None and not requires_colloque:
                    add_pattern(e_i, d_i, primary_g, None, (), {0: -1, 1: -1}, 0, off_cost)

                if requires_colloque:
                    colloque_start = int(primary_colloque["start_slot"])
                    colloque_end = int(primary_colloque["end_slot"])
                    colloque_slots = set(primary_colloque["slots"])
                    colloque_duration = colloque_end - colloque_start
                    segments = ((colloque_start, colloque_end),)
                    base_cost = work_cost_or_none(e_i, day_key, segments)
                    if base_cost is not None:
                        add_pattern(
                            e_i,
                            d_i,
                            primary_g,
                            primary_site,
                            segments,
                            {0: primary_g, 1: primary_g},
                            colloque_duration,
                            base_cost + 900.0 * scale,
                        )

                    for duration in range(
                        max(generated_min_daily_slots, colloque_duration),
                        max_daily_slots + 1,
                    ):
                        if remaining_seconds() <= 1.0:
                            return generation_time_limit_result()
                        if not pattern_hours_possible(
                            e_i,
                            duration - colloque_duration,
                            duration,
                        ):
                            pattern_stats["weekly_pruned"] += 1
                            continue
                        for start in sorted_start_candidates:
                            end = start + duration
                            if end > horizon.slots or end not in end_candidates:
                                continue
                            worked = set(range(start, end))
                            if not colloque_slots.issubset(worked):
                                continue
                            segments = ((start, end),)
                            base_cost = work_cost_or_none(e_i, day_key, segments)
                            if base_cost is None:
                                continue
                            child_slots = duration - colloque_duration
                            group_cost = group_cost_or_none(e_i, primary_g, primary_g, child_slots)
                            if group_cost is None:
                                continue
                            add_pattern(
                                e_i,
                                d_i,
                                primary_g,
                                primary_site,
                                segments,
                                {0: primary_g, 1: primary_g},
                                duration,
                                base_cost + group_cost,
                            )

                        if (
                            restricted_patterns
                            or educator_name in continuous_only_educators
                            or duration < 2 * min_segment_slots + colloque_duration
                        ):
                            continue
                        for first_len in range(min_segment_slots, duration - min_segment_slots + 1):
                            second_len = duration - first_len
                            for gap in range(1, generation_max_gap_slots + 1):
                                first_end = split_slot
                                first_start = first_end - first_len
                                second_start = first_end + gap
                                second_end = second_start + second_len
                                if first_start < 0 or second_end > horizon.slots:
                                    continue
                                if (
                                    generation_step_slots > 1
                                    and (
                                        first_start not in start_candidates
                                        or second_end not in end_candidates
                                    )
                                ):
                                    continue
                                segments = ((first_start, first_end), (second_start, second_end))
                                worked = {
                                    slot
                                    for seg_start, seg_end in segments
                                    for slot in range(seg_start, seg_end)
                                }
                                if not colloque_slots.issubset(worked):
                                    continue
                                base_cost = work_cost_or_none(e_i, day_key, segments)
                                if base_cost is None:
                                    continue
                                child_slots = duration - colloque_duration
                                group_cost = group_cost_or_none(e_i, primary_g, primary_g, child_slots)
                                if group_cost is None:
                                    continue
                                add_pattern(
                                    e_i,
                                    d_i,
                                    primary_g,
                                    primary_site,
                                    segments,
                                    {0: primary_g, 1: primary_g},
                                    duration,
                                    base_cost + group_cost,
                                )
                    continue

                for site in sites:
                    if restricted_primary_only and site != primary_site:
                        continue
                    local_groups = group_by_site[site]
                    for duration in range(max(1, generated_min_daily_slots), max_daily_slots + 1):
                        if remaining_seconds() <= 1.0:
                            return generation_time_limit_result()
                        if not pattern_hours_possible(e_i, duration, duration):
                            pattern_stats["weekly_pruned"] += 1
                            continue
                        for start in sorted_start_candidates:
                            end = start + duration
                            if end > horizon.slots or end not in end_candidates:
                                continue
                            segments = ((start, end),)
                            base_cost = work_cost_or_none(e_i, day_key, segments)
                            if base_cost is None:
                                continue
                            if start < split_slot < end:
                                worked_halves = {0, 1}
                            else:
                                worked_halves = {0 if start < split_slot else 1}
                            if restricted_one_group_per_day:
                                candidate_groups = [primary_g] if restricted_primary_only else local_groups
                                for g_i in candidate_groups:
                                    group_cost = group_cost_or_none(e_i, primary_g, g_i, duration)
                                    if group_cost is None:
                                        continue
                                    add_pattern(
                                        e_i,
                                        d_i,
                                        primary_g,
                                        site,
                                        segments,
                                        {0: g_i, 1: g_i},
                                        duration,
                                        base_cost + group_cost,
                                    )
                                continue
                            if worked_halves == {0, 1}:
                                morning_slots = split_slot - start
                                afternoon_slots = duration - morning_slots
                                for g_morning in local_groups:
                                    morning_cost = group_cost_or_none(e_i, primary_g, g_morning, morning_slots)
                                    if morning_cost is None:
                                        continue
                                    for g_afternoon in local_groups:
                                        afternoon_cost = group_cost_or_none(
                                            e_i,
                                            primary_g,
                                            g_afternoon,
                                            afternoon_slots,
                                        )
                                        if afternoon_cost is None:
                                            continue
                                        add_pattern(
                                            e_i,
                                            d_i,
                                            primary_g,
                                            site,
                                            segments,
                                            {0: g_morning, 1: g_afternoon},
                                            duration,
                                            base_cost + morning_cost + afternoon_cost,
                                        )
                            else:
                                half_i = next(iter(worked_halves))
                                for g_i in local_groups:
                                    group_cost = group_cost_or_none(e_i, primary_g, g_i, duration)
                                    if group_cost is None:
                                        continue
                                    add_pattern(
                                        e_i,
                                        d_i,
                                        primary_g,
                                        site,
                                        segments,
                                        {half_i: g_i, 1 - half_i: g_i},
                                        duration,
                                        base_cost + group_cost,
                                    )

                        if (
                            restricted_patterns
                            or educator_name in continuous_only_educators
                            or duration < 2 * min_segment_slots
                            or site != primary_site
                        ):
                            continue
                        for first_len in range(min_segment_slots, duration - min_segment_slots + 1):
                            second_len = duration - first_len
                            for gap in range(1, generation_max_gap_slots + 1):
                                first_end = split_slot
                                first_start = first_end - first_len
                                second_start = first_end + gap
                                second_end = second_start + second_len
                                if first_start < 0 or second_end > horizon.slots:
                                    continue
                                if (
                                    generation_step_slots > 1
                                    and (
                                        first_start not in start_candidates
                                        or second_end not in end_candidates
                                    )
                                ):
                                    continue
                                segments = ((first_start, first_end), (second_start, second_end))
                                base_cost = work_cost_or_none(e_i, day_key, segments)
                                if base_cost is None:
                                    continue
                                for g_morning in range(len(groups)):
                                    morning_cost = group_cost_or_none(e_i, primary_g, g_morning, first_len)
                                    if morning_cost is None:
                                        continue
                                    for g_afternoon in range(len(groups)):
                                        afternoon_cost = group_cost_or_none(
                                            e_i,
                                            primary_g,
                                            g_afternoon,
                                            second_len,
                                        )
                                        if afternoon_cost is None:
                                            continue
                                        add_pattern(
                                            e_i,
                                            d_i,
                                            primary_g,
                                            None,
                                            segments,
                                            {0: g_morning, 1: g_afternoon},
                                            duration,
                                            base_cost + morning_cost + afternoon_cost,
                                        )

    bundle.pattern_stats = dict(pattern_stats)
    bundle.pattern_count = len(costs)
    pattern_statistics = current_pattern_statistics()
    if progress_callback:
        progress_callback(
            25,
            (
                f"Patrons generes: {len(costs)} "
                f"(continus {pattern_stats['continuous']}, "
                f"coupes {pattern_stats['split']}, "
                f"mixtes {pattern_stats['mixed_group']}, "
                f"coupes intersites {pattern_stats['cross_site_split']}, "
                f"remplacements {pattern_stats['replacement']}, "
                f"doublons retires {pattern_stats['deduplicated']}, "
                f"durees impossibles {pattern_stats['weekly_pruned']})"
            ),
        )
    if remaining_seconds() <= 1.0:
        payload = time_limit_payload("la generation des patrons")
        payload["pattern_statistics"] = pattern_statistics
        return payload, bundle

    # The pattern model contains tens of millions of non-zero coefficients.
    # Building it with Python lists of row/column integers can consume several
    # gigabytes before SciPy even starts. Rows are appended in order, so build
    # the CSR arrays directly with compact typed buffers.
    cols = array("i")
    vals = array("d")
    indptr = array("q", [0])
    lower = array("d")
    upper = array("d")
    model_operations = 0

    def add_model_row(
        terms: Iterable[tuple[int, float]],
        lb: float,
        ub: float,
    ) -> None:
        nonlocal model_operations
        if remaining_seconds() <= 1.0:
            raise_time_limit("la construction du modele")
        for col, val in terms:
            if val:
                cols.append(int(col))
                vals.append(float(val))
            model_operations += 1
            if model_operations % 65536 == 0 and remaining_seconds() <= 1.0:
                raise_time_limit("la construction du modele")
        lower.append(float(lb))
        upper.append(float(ub))
        indptr.append(len(cols))

    primary_vars: dict[tuple[int, int], int] = {}
    for e_i in range(len(educators)):
        terms: list[tuple[int, float]] = []
        for g_i in sorted(allowed_primary_groups[e_i]):
            var_id = len(costs)
            primary_vars[(e_i, g_i)] = var_id
            costs.append(primary_group_costs.get((e_i, g_i), 0.0))
            terms.append((var_id, 1.0))
        add_model_row(terms, 1.0, 1.0)

    for e_i in range(len(educators)):
        for d_i in range(len(DAYS)):
            if not by_educator_day.get((e_i, d_i)):
                return (
                    {
                        "status": "infeasible_or_not_solved",
                        "solver_message": f"Aucun patron possible pour {educators[e_i]['name']} {DAYS[d_i][0]}.",
                        "warnings": warnings,
                        "diagnostics": [],
                    },
                    bundle,
                )
            primary_classes: dict[int, list[int]] = {}
            for g_i in sorted(allowed_primary_groups[e_i]):
                representative = primary_class_representative[(e_i, d_i, g_i)]
                primary_classes.setdefault(representative, []).append(g_i)
            for representative, compatible_groups in primary_classes.items():
                terms = chain(
                    (
                        (p_i, 1.0)
                        for p_i in by_educator_day_primary.get(
                            (e_i, d_i, representative),
                            (),
                        )
                    ),
                    (
                        (primary_vars[(e_i, g_i)], -1.0)
                        for g_i in compatible_groups
                    ),
                )
                add_model_row(terms, 0.0, 0.0)

    for e_i, educator in enumerate(educators):
        target_hours = float(educator["percentage"]) / 100.0 * weekly_base
        target = int(round(target_hours / (horizon.step / 60.0)))
        the_slots = the_target_slots(target, the_percent, enabled=the_enabled)
        tolerance_slots = weekly_tolerance_slots(
            target_hours,
            horizon,
            percent=weekly_hours_tolerance_percent,
            minutes=weekly_hours_tolerance_minutes,
            step_minutes=weekly_hours_tolerance_step_minutes,
        )
        upper_target = target + tolerance_slots
        if absolute_max_slots is not None:
            upper_target = min(upper_target, absolute_max_slots)
        child_terms = (
            (p_i, float(pattern_child_duration[p_i]))
            for p_i in by_educator.get(e_i, ())
        )
        visible_terms = (
            (p_i, float(pattern_duration[p_i]))
            for p_i in by_educator.get(e_i, ())
        )
        add_model_row(
            child_terms,
            max(0, target - tolerance_slots - the_slots),
            max(0, upper_target - the_slots),
        )
        add_model_row(visible_terms, 0.0, upper_target)
        if hard_max_work_days:
            day_terms = (
                (p_i, 1.0)
                for p_i in by_educator.get(e_i, ())
                if pattern_duration[p_i] > 0
            )
            add_model_row(
                day_terms,
                0.0,
                float(max_work_days_by_educator[e_i]),
            )

    for d_i in range(len(DAYS)):
        for g_i in range(len(groups)):
            for slot in range(horizon.slots):
                terms = (
                    (p_i, 1.0)
                    for p_i in coverage_terms.get((d_i, g_i, slot), ())
                )
                demand = group_demand[(d_i, g_i, slot)]
                add_model_row(terms, demand, max(3, demand))
        for (demand_d_i, site, slot), demand in site_demand.items():
            if demand_d_i != d_i:
                continue
            terms = (
                (p_i, 1.0)
                for p_i in site_terms.get((d_i, site, slot), ())
            )
            add_model_row(terms, demand, math.inf)

    for colloque in colloques:
        target_g = int(colloque["group_i"])
        for source_g in range(len(groups)):
            if source_g == target_g:
                continue
            terms = (
                (p_i, 1.0)
                for p_i in replacement_terms.get((int(colloque["id"]), source_g), ())
            )
            add_model_row(terms, 1.0, 1.0)

    if max_weekly_group_exception_days is not None:
        for e_i in range(len(educators)):
            if not attends_colloque_by_educator[e_i]:
                continue
            terms = (
                (p_i, float(pattern_mixed[p_i]))
                for p_i in by_educator.get(e_i, ())
                if pattern_mixed[p_i]
            )
            if any(pattern_mixed[p_i] for p_i in by_educator.get(e_i, ())):
                add_model_row(terms, 0.0, float(max_weekly_group_exception_days))

    for raw_rule in data.get("rules_percentage", []):
        if len(raw_rule) < 4:
            warnings.append(f"Regle pourcentage ignoree: {raw_rule}.")
            continue
        raw_types, minmax, value, site = raw_rule[:4]
        if site not in percentage_terms:
            warnings.append(f"Regle pourcentage avec site inconnu: {site}.")
            continue
        wanted_types, type_warnings = split_types(list(raw_types), aliases, known_types)
        warnings.extend(type_warnings)
        pct = float(value)
        pattern_ids, educator_ids, durations = percentage_terms[site]
        def percentage_coefficients() -> Iterable[tuple[int, float]]:
            for p_i, e_i, duration in zip(pattern_ids, educator_ids, durations):
                coeff = -pct * duration
                if educator_types[e_i] in wanted_types:
                    coeff += 100.0 * duration
                if coeff:
                    yield p_i, coeff
        terms = percentage_coefficients()
        if normalize_flag(minmax) == "min":
            add_model_row(terms, 0.0, math.inf)
        else:
            add_model_row(terms, -math.inf, 0.0)

    matrix = csr_matrix(
        (
            np.frombuffer(vals, dtype=np.float64),
            np.frombuffer(cols, dtype=np.int32),
            np.frombuffer(indptr, dtype=np.int64),
        ),
        shape=(len(lower), len(costs)),
    )
    if remaining_seconds() <= 1.0:
        payload = time_limit_payload("la construction du modele")
        payload["pattern_statistics"] = pattern_statistics
        return payload, bundle
    solver_budget = highs_solve_budget(remaining_seconds(), len(costs))
    if solver_budget < 1.0:
        payload = time_limit_payload("la preparation du solveur natif")
        payload["pattern_statistics"] = pattern_statistics
        return payload, bundle
    if progress_callback:
        progress_callback(45, "Resolution rapide des patrons" if feasible_only else "Resolution des patrons")
    # A zero objective leaves every feasible combination equivalent and gives
    # HiGHS little guidance for finding its first incumbent. The existing soft
    # costs do not relax any hard row; they only steer the feasibility search
    # toward compact, stable schedules.
    objective_costs = np.frombuffer(costs, dtype=np.float64)
    result = milp(
        c=objective_costs,
        integrality=np.ones(len(costs), dtype=np.int8),
        bounds=Bounds(np.zeros(len(costs)), np.ones(len(costs))),
        constraints=LinearConstraint(
            matrix,
            np.frombuffer(lower, dtype=np.float64),
            np.frombuffer(upper, dtype=np.float64),
        ),
        options={"time_limit": solver_budget, "mip_rel_gap": 0.03},
    )
    if progress_callback:
        progress_callback(82, "Preparation du resultat")
    if result.x is None:
        diagnostics = diagnose_basic_conflicts(data, horizon) + diagnose_the_capacity(
            data,
            horizon,
            weekly_hours_tolerance_percent=weekly_hours_tolerance_percent,
            weekly_hours_tolerance_minutes=weekly_hours_tolerance_minutes,
            weekly_hours_tolerance_step_minutes=weekly_hours_tolerance_step_minutes,
            enforce_absolute_max_weekly_hours=enforce_absolute_max_weekly_hours,
            absolute_max_weekly_hours=absolute_max_weekly_hours,
            the_enabled=the_enabled,
            the_percent=the_percent,
        )
        return (
            {
                "status": "infeasible_or_not_solved",
                "solver_message": result.message,
                "warnings": sorted(set(warnings)),
                "diagnostics": diagnostics,
                "solve_status": str(result.message),
                "pattern_statistics": pattern_statistics,
            },
            bundle,
        )

    primary_groups_by_educator = {
        educators[e_i]["name"]: groups[g_i]["name"]
        for (e_i, g_i), var_id in primary_vars.items()
        if result.x[var_id] >= 0.5
    }

    schedule = {educator["name"]: {day_key: [] for day_key, _ in DAYS} for educator in educators}
    for pattern_id, value in enumerate(result.x[: len(pattern_duration)]):
        if value < 0.5 or pattern_duration[pattern_id] <= 0:
            continue
        e_i = pattern_owner_educator[pattern_id]
        d_i = pattern_owner_day[pattern_id]
        day_key = DAYS[d_i][0]
        educator_name = educators[e_i]["name"]
        worked = set(range(pattern_first_start[pattern_id], pattern_first_end[pattern_id]))
        if pattern_second_start[pattern_id] >= 0:
            worked.update(
                range(pattern_second_start[pattern_id], pattern_second_end[pattern_id])
            )
        current_state: tuple[int, str] | None = None
        start_slot: int | None = None
        for slot in range(horizon.slots + 1):
            active_state: tuple[int, str] | None = None
            if slot in worked:
                half_i = 0 if slot < split_slot else 1
                display_overrides = pattern_slot_display_overrides[pattern_id] or {}
                coverage_overrides = pattern_slot_coverage_overrides[pattern_id] or {}
                activities = pattern_slot_activities[pattern_id] or {}
                display_group = display_overrides.get(
                    slot,
                    coverage_overrides.get(
                        slot,
                        (
                            pattern_morning_group[pattern_id]
                            if half_i == 0
                            else pattern_afternoon_group[pattern_id]
                        ),
                    ),
                )
                activity = activities.get(slot, "")
                if display_group >= 0:
                    active_state = (display_group, activity)
            if active_state != current_state:
                if current_state is not None and start_slot is not None:
                    start_min = horizon.start + start_slot * horizon.step
                    end_min = horizon.start + slot * horizon.step
                    group_i, activity = current_state
                    group = groups[group_i]
                    block = {
                        "site": group["site"],
                        "group": group["name"],
                        "start": format_time(start_min),
                        "end": format_time(end_min),
                        "hours": round((end_min - start_min) / 60.0, 2),
                    }
                    if activity:
                        block["activity"] = activity
                    schedule[educator_name][day_key].append(block)
                current_state = active_state
                start_slot = slot if active_state is not None else None

    checks = verify_solution(
        bundle,
        schedule,
        half_day_split_time=half_day_split_time,
        max_weekly_group_exception_days=max_weekly_group_exception_days,
        max_split_gap_minutes=max_split_gap_minutes,
        hard_max_work_days=hard_max_work_days,
        weekly_hours_tolerance_percent=weekly_hours_tolerance_percent,
        weekly_hours_tolerance_minutes=weekly_hours_tolerance_minutes,
        weekly_hours_tolerance_step_minutes=weekly_hours_tolerance_step_minutes,
        enforce_absolute_max_weekly_hours=enforce_absolute_max_weekly_hours,
        absolute_max_weekly_hours=absolute_max_weekly_hours,
        the_enabled=the_enabled,
        the_percent=the_percent,
        the_colloques_count=the_colloques_count,
        primary_groups_by_educator=primary_groups_by_educator,
        quality_profile=quality_profile,
        quality_profile_label=quality_profile_label,
        primary_group_report_enabled=primary_group_report_enabled,
        primary_group_warning_outside_hours=primary_group_warning_outside_hours,
        primary_group_warning_outside_days=primary_group_warning_outside_days,
    )
    weekly_errors = []
    for name, actual in checks["hours_by_educator"].items():
        target = checks["weekly_targets"][name]
        allowed_hours = checks.get("weekly_tolerances", {}).get(name, 0.0)
        if abs(actual - target) > allowed_hours + 1e-6:
            weekly_errors.append(
                f"{name}: {actual:.2f}h hors tolerance autour de {target:.2f}h "
                f"(+/- {allowed_hours:.2f}h)"
            )
    checks["errors"] = [
        error for error in checks["errors"] if "hors tolerance autour" not in error and "!=" not in error
    ] + weekly_errors
    checks["hard_errors"] = checks["errors"]
    status_text = "ok" if not checks["errors"] else "invalid"
    if feasible_only and status_text == "ok":
        warnings.append("Solution valide rapide: toutes les regles hard sont respectees, qualite non optimisee.")
    if restricted_patterns and status_text == "ok":
        if restricted_patterns and not restricted_one_group_per_day:
            warnings.append(
                "Patrons simples demi-journees utilises: journees continues avec groupe matin/apres-midi possible."
            )
        elif restricted_primary_only:
            warnings.append(
                "Patrons simples utilises: journees continues et groupe principal uniquement, hors remplacements colloque."
            )
        else:
            warnings.append(
                "Patrons simples elargis utilises: journees continues avec un seul groupe par jour, hors remplacements colloque."
            )
    return (
        {
            "status": status_text,
            "objective": round(float(result.fun) if result.fun is not None else 0.0, 4),
            "solver_message": result.message,
            "warnings": sorted(set(warnings)),
            "solve_mode": (
                "solution_valide_rapide_patrons_simples"
                if feasible_only and restricted_patterns and restricted_primary_only
                else "solution_valide_rapide_patrons_demi_journees"
                if feasible_only and restricted_patterns and not restricted_one_group_per_day
                else "solution_valide_rapide_patrons_simples_elargis"
                if feasible_only and restricted_patterns
                else "solution_valide_rapide"
                if feasible_only
                else "qualite"
            ),
            "schedule": schedule,
            "checks": checks,
            "pattern_statistics": pattern_statistics,
        },
        bundle,
    )
