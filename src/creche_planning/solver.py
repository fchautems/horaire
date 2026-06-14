from __future__ import annotations

import argparse
import itertools
import math
import os
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Callable

import numpy as np
from scipy.optimize import Bounds, LinearConstraint, milp
from scipy.sparse import coo_matrix

from .domain import (
    DAYS,
    DEFAULT_TYPE_ALIASES,
    Horizon,
    Pattern,
    PatternSolveBundle,
    SolveBundle,
    SolverIndexes,
    absolute_weekly_max_slots,
    add_row,
    build_demands_by_day,
    format_time,
    load_json,
    make_horizon,
    max_work_days_for_educator,
    normalize_day,
    normalize_flag,
    parse_colloques,
    parse_time,
    save_json,
    slot_range,
    slot_range_clipped,
    split_slot_for_horizon,
    split_types,
    the_target_slots,
    weekly_tolerance_slots,
)
from .quality import (
    attach_quality_profile,
    build_quality_summary,
    effective_max_split_gap_minutes,
    select_quality_profile,
)
from .pattern_search import (
    attempt_budget,
    build_candidate_attempts,
    choose_valid_payload,
    ensure_verified_status,
    payload_is_hard_valid,
    payload_is_retryable,
    release_over_limit_primary_groups,
)
from .reports import build_rule_summary, print_report, write_csv, write_html
from .runtime import (
    config_aliases,
    emit_progress,
    emit_stage,
    load_run_config,
    parse_aliases,
    pick,
    resolve_config_path,
    timestamped_path,
)


def educator_attends_colloque(educator: dict[str, Any]) -> bool:
    value = educator.get("attends_colloque", True)
    if isinstance(value, bool):
        return value
    if value is None:
        return True
    text = str(value).strip().lower()
    if text in {"non", "no", "n", "false", "faux", "0"}:
        return False
    if text in {"oui", "yes", "y", "true", "vrai", "1"}:
        return True
    return True


def hard_primary_group_rule_errors(
    data: dict[str, Any],
    primary_groups_by_educator: dict[str, str],
) -> list[str]:
    errors: list[str] = []
    for raw_rule in data.get("rules_group", []):
        if len(raw_rule) < 4:
            continue
        pref_type, strength, educator_name, group_name = raw_rule[:4]
        if normalize_flag(strength) != "hard":
            continue
        primary_group_name = primary_groups_by_educator.get(educator_name)
        if not primary_group_name:
            if primary_groups_by_educator:
                errors.append(
                    f"Regle groupe hard non verifiable: aucun groupe principal pour {educator_name}."
                )
            continue
        is_negative = normalize_flag(pref_type) in {"negatif", "negative", "neg"}
        if is_negative and primary_group_name == group_name:
            errors.append(
                f"Regle groupe hard violee: {educator_name} a {group_name} comme groupe principal interdit."
            )
        if not is_negative and primary_group_name != group_name:
            errors.append(
                f"Regle groupe hard violee: {educator_name} a {primary_group_name} comme groupe principal, "
                f"mais la regle impose {group_name}."
            )
    return errors


def mark_work_day_diagnostic(payload: dict[str, Any]) -> dict[str, Any]:
    relaxation_warning = (
        "Aucune solution stricte avec le maximum de jours travailles. "
        "Le planning affiche est uniquement un diagnostic et ne doit pas etre utilise tel quel."
    )
    warnings = list(payload.get("warnings", []))
    warnings.append(relaxation_warning)
    checks = payload.setdefault("checks", {})
    alert_list = list(checks.get("alerts", []))
    soft_warning_list = list(checks.get("soft_warnings", []))
    hard_error_list = list(checks.get("errors", []))
    hard_error_list.append(
        "Aucune solution ne respecte simultanement toutes les contraintes et le maximum de jours travailles."
    )
    alert_list.append(relaxation_warning)
    soft_warning_list.append(relaxation_warning)
    for warning in checks.get("work_day_warnings", []):
        warnings.append(warning)
        alert_list.append(warning)
        soft_warning_list.append(warning)
        hard_error_list.append(f"Limite de jours depassee: {warning}")
    checks["alerts"] = sorted(set(alert_list))
    checks["soft_warnings"] = sorted(set(soft_warning_list))
    checks["errors"] = sorted(set(hard_error_list))
    checks["hard_errors"] = checks["errors"]
    payload["warnings"] = sorted(set(warnings))
    payload["status"] = "invalid"
    payload["diagnostic_only"] = True
    payload["solver_message"] = (
        "Planning diagnostic calcule apres echec du modele strict. "
        + str(payload.get("solver_message", ""))
    )
    return payload


def build_indexes(
    educators: list[dict[str, Any]],
    groups: list[dict[str, Any]],
    sites: list[str],
    days: int,
    slots: int,
) -> SolverIndexes:
    x: dict[tuple[int, int, int, int], int] = {}
    work_start: dict[tuple[int, int, int], int] = {}
    group_start: dict[tuple[int, int, int, int], int] = {}
    site_day: dict[tuple[int, int, int], int] = {}
    group_day: dict[tuple[int, int, int], int] = {}
    half_group: dict[tuple[int, int, int, int], int] = {}
    mixed_group_day: dict[tuple[int, int], int] = {}
    primary_group: dict[tuple[int, int], int] = {}
    outside_group_slot: dict[tuple[int, int, int, int], int] = {}
    outside_group_day: dict[tuple[int, int], int] = {}
    primary_site: dict[tuple[int, int], int] = {}
    outside_site_day: dict[tuple[int, int], int] = {}
    idx = 0

    for e_i in range(len(educators)):
        for d_i in range(days):
            for g_i in range(len(groups)):
                for t_i in range(slots):
                    x[(e_i, d_i, g_i, t_i)] = idx
                    idx += 1

    for e_i in range(len(educators)):
        for d_i in range(days):
            for t_i in range(slots):
                work_start[(e_i, d_i, t_i)] = idx
                idx += 1

    for e_i in range(len(educators)):
        for d_i in range(days):
            for g_i in range(len(groups)):
                for t_i in range(slots):
                    group_start[(e_i, d_i, g_i, t_i)] = idx
                    idx += 1

    for e_i in range(len(educators)):
        for d_i in range(days):
            for s_i in range(len(sites)):
                site_day[(e_i, d_i, s_i)] = idx
                idx += 1

    for e_i in range(len(educators)):
        for d_i in range(days):
            for g_i in range(len(groups)):
                group_day[(e_i, d_i, g_i)] = idx
                idx += 1
                for half_i in range(2):
                    half_group[(e_i, d_i, half_i, g_i)] = idx
                    idx += 1

    for e_i in range(len(educators)):
        for d_i in range(days):
            mixed_group_day[(e_i, d_i)] = idx
            idx += 1

    for e_i in range(len(educators)):
        for g_i in range(len(groups)):
            primary_group[(e_i, g_i)] = idx
            idx += 1

    for e_i in range(len(educators)):
        for d_i in range(days):
            outside_group_day[(e_i, d_i)] = idx
            idx += 1

    for e_i in range(len(educators)):
        for s_i in range(len(sites)):
            primary_site[(e_i, s_i)] = idx
            idx += 1

    for e_i in range(len(educators)):
        for d_i in range(days):
            outside_site_day[(e_i, d_i)] = idx
            idx += 1

    return SolverIndexes(
        x,
        work_start,
        group_start,
        site_day,
        group_day,
        half_group,
        mixed_group_day,
        primary_group,
        outside_group_slot,
        outside_group_day,
        primary_site,
        outside_site_day,
        idx,
    )


def solve_schedule(
    data: dict[str, Any],
    *,
    time_limit: float = 120.0,
    mip_gap: float = 0.01,
    type_aliases: dict[str, str] | None = None,
    weekly_mode: str = "exact",
    readable_objective: bool = True,
    one_group_per_day: bool = False,
    one_site_per_day: bool = False,
    max_blocks_per_day: int | None = None,
    min_daily_hours: float = 0.0,
    weekly_hours_tolerance_percent: float = 1.0,
    weekly_hours_tolerance_minutes: int | None = None,
    half_day_split_time: str = "12:30",
    max_weekly_group_exception_days: int | None = 1,
    weekly_stability: bool = False,
    main_group_day_weight: float = 80.0,
    main_group_slot_weight: float = 3.0,
    main_site_day_weight: float = 100.0,
    preferred_groups: dict[int, int] | None = None,
    preferred_sites: dict[int, int] | None = None,
) -> SolveBundle:
    aliases = dict(DEFAULT_TYPE_ALIASES)
    if type_aliases:
        aliases.update(type_aliases)

    horizon = make_horizon(data)
    groups = list(data.get("groups", []))
    educators = list(data.get("educators", []))
    sites = [site["name"] for site in data.get("sites", [])]
    site_index = {site: i for i, site in enumerate(sites)}
    group_site = {i: group["site"] for i, group in enumerate(groups)}
    known_types = {item["name"] for item in data.get("educator_types", [])}
    warnings: list[str] = []

    if not groups:
        raise ValueError("Aucun groupe dans le JSON.")
    if not educators:
        raise ValueError("Aucun educateur dans le JSON.")
    if not sites:
        raise ValueError("Aucun site dans le JSON.")

    idxs = build_indexes(educators, groups, sites, len(DAYS), horizon.slots)
    c = np.zeros(idxs.var_count)
    integrality = np.ones(idxs.var_count, dtype=np.int8)
    lb = np.zeros(idxs.var_count)
    ub = np.ones(idxs.var_count)

    # Start variables may stay continuous because the objective pushes them down.
    for var_id in idxs.work_start.values():
        integrality[var_id] = 0
    for var_id in idxs.group_start.values():
        integrality[var_id] = 0
        if not readable_objective:
            ub[var_id] = 0
    for var_id in idxs.group_day.values():
        integrality[var_id] = 0
    for var_id in idxs.half_group.values():
        integrality[var_id] = 0
    for var_id in idxs.mixed_group_day.values():
        integrality[var_id] = 0
    for var_id in idxs.outside_group_slot.values():
        integrality[var_id] = 0
    for var_id in idxs.outside_group_day.values():
        integrality[var_id] = 0
    for var_id in idxs.outside_site_day.values():
        integrality[var_id] = 0
    if not weekly_stability:
        for var_id in idxs.primary_group.values():
            integrality[var_id] = 0
            ub[var_id] = 0
        for var_id in idxs.primary_site.values():
            integrality[var_id] = 0
            ub[var_id] = 0

    rows: list[int] = []
    cols: list[int] = []
    vals: list[float] = []
    lower: list[float] = []
    upper: list[float] = []

    group_demand, site_demand = build_demands_by_day(data, groups, horizon)
    group_by_name = {group["name"]: i for i, group in enumerate(groups)}

    max_staff_default = 3

    # Coverage per group and slot, for every day.
    for d_i in range(len(DAYS)):
        for g_i in range(len(groups)):
            for t_i in range(horizon.slots):
                demand = group_demand[(d_i, g_i, t_i)]
                max_staff = max(max_staff_default, demand)
                terms = [(idxs.x[(e_i, d_i, g_i, t_i)], 1.0) for e_i in range(len(educators))]
                add_row(rows, cols, vals, lower, upper, terms, demand, max_staff)

    # Site-wide "tous" coverage.
    for (d_i, site, t_i), demand in site_demand.items():
        terms = []
        for e_i in range(len(educators)):
            for g_i in range(len(groups)):
                if group_site[g_i] == site:
                    terms.append((idxs.x[(e_i, d_i, g_i, t_i)], 1.0))
        add_row(rows, cols, vals, lower, upper, terms, demand, math.inf)

    # One group at most per educator and slot.
    for e_i in range(len(educators)):
        for d_i in range(len(DAYS)):
            for t_i in range(horizon.slots):
                terms = [(idxs.x[(e_i, d_i, g_i, t_i)], 1.0) for g_i in range(len(groups))]
                add_row(rows, cols, vals, lower, upper, terms, 0.0, 1.0)

    max_daily_hours = float(data.get("rules_global", {}).get("max_daily_hours", 8.5))
    max_daily_slots = int(round(max_daily_hours / 0.25))
    min_daily_slots = int(round(min_daily_hours / 0.25))
    weekly_base = float(data.get("rules_global", {}).get("max_weekly_hours", 40.0))
    split_slot = split_slot_for_horizon(horizon, half_day_split_time)
    preferred_groups = preferred_groups or {}
    preferred_sites = preferred_sites or {}
    group_slot_weight = main_group_slot_weight + main_group_day_weight / max(1, max_daily_slots)
    site_slot_weight = main_site_day_weight / max(1, max_daily_slots)
    name_to_educator = {educator["name"]: i for i, educator in enumerate(educators)}
    rule_primary_groups: dict[int, int] = dict(preferred_groups)
    for raw_rule in data.get("rules_group", []):
        if len(raw_rule) < 4:
            continue
        pref_type, _strength, educator_name, group_name = raw_rule[:4]
        if normalize_flag(pref_type) in {"negatif", "negative", "neg"}:
            continue
        if educator_name in name_to_educator and group_name in group_by_name:
            rule_primary_groups[name_to_educator[educator_name]] = group_by_name[group_name]

    if preferred_groups or preferred_sites:
        for e_i in range(len(educators)):
            preferred_group = preferred_groups.get(e_i)
            preferred_site = preferred_sites.get(e_i)
            for d_i in range(len(DAYS)):
                for g_i in range(len(groups)):
                    is_other_group = preferred_group is not None and g_i != preferred_group
                    is_other_site = preferred_site is not None and site_index[group_site[g_i]] != preferred_site
                    if not is_other_group and not is_other_site:
                        continue
                    penalty = 0.0
                    if is_other_group:
                        penalty += group_slot_weight
                    if is_other_site:
                        penalty += site_slot_weight
                    for t_i in range(horizon.slots):
                        c[idxs.x[(e_i, d_i, g_i, t_i)]] += penalty

    # Daily and weekly educator hour limits.
    for e_i, educator in enumerate(educators):
        target_slots = int(round((float(educator["percentage"]) / 100.0) * weekly_base / 0.25))
        if weekly_hours_tolerance_minutes is None:
            tolerance_slots = int(math.ceil(target_slots * max(0.0, float(weekly_hours_tolerance_percent)) / 100.0))
        else:
            tolerance_slots = int(round(float(weekly_hours_tolerance_minutes) / horizon.step))
        for d_i in range(len(DAYS)):
            terms = [
                (idxs.x[(e_i, d_i, g_i, t_i)], 1.0)
                for g_i in range(len(groups))
                for t_i in range(horizon.slots)
            ]
            add_row(rows, cols, vals, lower, upper, terms, 0.0, max_daily_slots)
            if min_daily_slots > 0:
                link_terms = terms + [
                    (idxs.site_day[(e_i, d_i, s_i)], -float(min_daily_slots))
                    for s_i in range(len(sites))
                ]
                add_row(rows, cols, vals, lower, upper, link_terms, 0.0, math.inf)
        terms = [
            (idxs.x[(e_i, d_i, g_i, t_i)], 1.0)
            for d_i in range(len(DAYS))
            for g_i in range(len(groups))
            for t_i in range(horizon.slots)
        ]
        if weekly_mode == "exact":
            add_row(
                rows,
                cols,
                vals,
                lower,
                upper,
                terms,
                max(0, target_slots - tolerance_slots),
                target_slots + tolerance_slots,
            )
        else:
            add_row(rows, cols, vals, lower, upper, terms, 0.0, target_slots)

    # Site use per educator and day. Multi-site days are allowed but penalized.
    for e_i in range(len(educators)):
        for d_i in range(len(DAYS)):
            site_terms = [(idxs.site_day[(e_i, d_i, s_i)], 1.0) for s_i in range(len(sites))]
            if one_site_per_day:
                add_row(rows, cols, vals, lower, upper, site_terms, 0.0, 1.0)
            else:
                add_row(rows, cols, vals, lower, upper, site_terms, 0.0, float(len(sites)))
                for site_var, _ in site_terms:
                    c[site_var] += 0.05
            for g_i in range(len(groups)):
                s_i = site_index[group_site[g_i]]
                for t_i in range(horizon.slots):
                    terms = [
                        (idxs.x[(e_i, d_i, g_i, t_i)], 1.0),
                        (idxs.site_day[(e_i, d_i, s_i)], -1.0),
                    ]
                    add_row(rows, cols, vals, lower, upper, terms, -math.inf, 0.0)
    if weekly_stability:
        for e_i in range(len(educators)):
            primary_group_terms = [
                (idxs.primary_group[(e_i, g_i)], 1.0)
                for g_i in range(len(groups))
            ]
            add_row(rows, cols, vals, lower, upper, primary_group_terms, 1.0, 1.0)
            if e_i in rule_primary_groups:
                add_row(
                    rows,
                    cols,
                    vals,
                    lower,
                    upper,
                    [(idxs.primary_group[(e_i, rule_primary_groups[e_i])], 1.0)],
                    1.0,
                    1.0,
                )

            primary_site_terms = [
                (idxs.primary_site[(e_i, s_i)], 1.0)
                for s_i in range(len(sites))
            ]
            add_row(rows, cols, vals, lower, upper, primary_site_terms, 1.0, 1.0)

            for d_i in range(len(DAYS)):
                outside_group_day = idxs.outside_group_day[(e_i, d_i)]
                c[outside_group_day] = main_group_day_weight

                outside_site_day = idxs.outside_site_day[(e_i, d_i)]
                c[outside_site_day] = main_site_day_weight
                for s_i in range(len(sites)):
                    add_row(
                        rows,
                        cols,
                        vals,
                        lower,
                        upper,
                        [
                            (idxs.site_day[(e_i, d_i, s_i)], 1.0),
                            (idxs.primary_site[(e_i, s_i)], -1.0),
                            (outside_site_day, -1.0),
                        ],
                        -math.inf,
                        0.0,
                    )

                for g_i in range(len(groups)):
                    primary_group = idxs.primary_group[(e_i, g_i)]
                    for t_i in range(horizon.slots):
                        x_var = idxs.x[(e_i, d_i, g_i, t_i)]
                        add_row(
                            rows,
                            cols,
                            vals,
                            lower,
                            upper,
                            [
                                (x_var, 1.0),
                                (primary_group, -1.0),
                                (outside_group_day, -1.0),
                            ],
                        -math.inf,
                        0.0,
                    )
            if max_weekly_group_exception_days is not None:
                outside_terms = [
                    (idxs.outside_group_day[(e_i, d_i)], 1.0)
                    for d_i in range(len(DAYS))
                ]
                add_row(
                    rows,
                    cols,
                    vals,
                    lower,
                    upper,
                    outside_terms,
                    0.0,
                    float(max_weekly_group_exception_days),
                )

    if one_group_per_day:
        for e_i in range(len(educators)):
            for d_i in range(len(DAYS)):
                group_terms = [(idxs.group_day[(e_i, d_i, g_i)], 1.0) for g_i in range(len(groups))]
                add_row(rows, cols, vals, lower, upper, group_terms, 0.0, 1.0)
                for g_i in range(len(groups)):
                    for t_i in range(horizon.slots):
                        terms = [
                            (idxs.x[(e_i, d_i, g_i, t_i)], 1.0),
                            (idxs.group_day[(e_i, d_i, g_i)], -1.0),
                        ]
                        add_row(rows, cols, vals, lower, upper, terms, -math.inf, 0.0)

    if max_weekly_group_exception_days is not None:
        for e_i in range(len(educators)):
            weekly_mixed_terms = []
            for d_i in range(len(DAYS)):
                group_terms = [(idxs.group_day[(e_i, d_i, g_i)], 1.0) for g_i in range(len(groups))]
                mixed_var = idxs.mixed_group_day[(e_i, d_i)]
                c[mixed_var] += 25.0
                weekly_mixed_terms.append((mixed_var, 1.0))

                # At most one active group per half-day.
                for half_i in range(2):
                    half_terms = [(idxs.half_group[(e_i, d_i, half_i, g_i)], 1.0) for g_i in range(len(groups))]
                    add_row(rows, cols, vals, lower, upper, half_terms, 0.0, 1.0)

                for g_i in range(len(groups)):
                    day_x_terms: list[tuple[int, float]] = []
                    half_x_terms: dict[int, list[tuple[int, float]]] = {0: [], 1: []}
                    for t_i in range(horizon.slots):
                        x_var = idxs.x[(e_i, d_i, g_i, t_i)]
                        day_x_terms.append((x_var, 1.0))
                        half_i = 0 if t_i < split_slot else 1
                        half_x_terms[half_i].append((x_var, 1.0))
                        add_row(
                            rows,
                            cols,
                            vals,
                            lower,
                            upper,
                            [(x_var, 1.0), (idxs.group_day[(e_i, d_i, g_i)], -1.0)],
                            -math.inf,
                            0.0,
                        )
                        add_row(
                            rows,
                            cols,
                            vals,
                            lower,
                            upper,
                            [(x_var, 1.0), (idxs.half_group[(e_i, d_i, half_i, g_i)], -1.0)],
                            -math.inf,
                            0.0,
                        )
                    add_row(
                        rows,
                        cols,
                        vals,
                        lower,
                        upper,
                        [(idxs.group_day[(e_i, d_i, g_i)], 1.0)]
                        + [(var, -coef) for var, coef in day_x_terms],
                        -math.inf,
                        0.0,
                    )
                    for half_i in range(2):
                        add_row(
                            rows,
                            cols,
                            vals,
                            lower,
                            upper,
                            [(idxs.half_group[(e_i, d_i, half_i, g_i)], 1.0)]
                            + [(var, -coef) for var, coef in half_x_terms[half_i]],
                            -math.inf,
                            0.0,
                        )

                # mixed_group_day must be 1 when the day uses two groups.
                add_row(
                    rows,
                    cols,
                    vals,
                    lower,
                    upper,
                    group_terms + [(mixed_var, -1.0)],
                    -math.inf,
                    1.0,
                )
                add_row(
                    rows,
                    cols,
                    vals,
                    lower,
                    upper,
                    [(mixed_var, 1.0)] + [(var, -coef) for var, coef in group_terms],
                    -math.inf,
                    0.0,
                )
            add_row(
                rows,
                cols,
                vals,
                lower,
                upper,
                weekly_mixed_terms,
                0.0,
                float(max_weekly_group_exception_days),
            )

    # Work and group starts for a readable objective or hard block limits.
    if readable_objective or max_blocks_per_day is not None:
        for e_i in range(len(educators)):
            for d_i in range(len(DAYS)):
                for t_i in range(horizon.slots):
                    current = [(idxs.x[(e_i, d_i, g_i, t_i)], -1.0) for g_i in range(len(groups))]
                    previous = []
                    if t_i > 0:
                        previous = [(idxs.x[(e_i, d_i, g_i, t_i - 1)], 1.0) for g_i in range(len(groups))]
                    terms = [(idxs.work_start[(e_i, d_i, t_i)], 1.0)] + current + previous
                    add_row(rows, cols, vals, lower, upper, terms, 0.0, math.inf)
                    if readable_objective:
                        c[idxs.work_start[(e_i, d_i, t_i)]] = 8.0

                if max_blocks_per_day is not None:
                    start_terms = [
                        (idxs.work_start[(e_i, d_i, t_i)], 1.0)
                        for t_i in range(horizon.slots)
                    ]
                    add_row(rows, cols, vals, lower, upper, start_terms, 0.0, max_blocks_per_day)

    if readable_objective:
        for e_i in range(len(educators)):
            for d_i in range(len(DAYS)):
                for t_i in range(horizon.slots):
                    for g_i in range(len(groups)):
                        terms = [
                            (idxs.group_start[(e_i, d_i, g_i, t_i)], 1.0),
                            (idxs.x[(e_i, d_i, g_i, t_i)], -1.0),
                        ]
                        if t_i > 0:
                            terms.append((idxs.x[(e_i, d_i, g_i, t_i - 1)], 1.0))
                        add_row(rows, cols, vals, lower, upper, terms, 0.0, math.inf)
                        c[idxs.group_start[(e_i, d_i, g_i, t_i)]] = 1.5

                for s_i in range(len(sites)):
                    c[idxs.site_day[(e_i, d_i, s_i)]] = 0.05

    day_to_index = {key: i for i, (key, _) in enumerate(DAYS)}

    # Time rules.
    for raw_rule in data.get("rules_time", []):
        if len(raw_rule) < 6:
            warnings.append(f"Regle horaire ignoree: {raw_rule}.")
            continue
        pref_type, strength, educator_name, day_name, start, end = raw_rule[:6]
        if educator_name not in name_to_educator:
            warnings.append(f"Regle horaire avec educateur inconnu: {educator_name}.")
            continue
        day_key = normalize_day(day_name)
        if day_key not in day_to_index:
            warnings.append(f"Regle horaire avec jour ignore: {day_name}.")
            continue
        e_i = name_to_educator[educator_name]
        d_i = day_to_index[day_key]
        clipped_slots, clipped = slot_range_clipped(horizon, start, end)
        if clipped:
            warnings.append(f"Regle horaire rognee sur l'horizon: {raw_rule}.")
        slots = list(clipped_slots)
        if not slots:
            continue
        is_negative = normalize_flag(pref_type) in {"negatif", "negative", "neg"}
        is_hard = normalize_flag(strength) == "hard"

        if is_hard:
            if is_negative:
                for t_i in slots:
                    terms = [(idxs.x[(e_i, d_i, g_i, t_i)], 1.0) for g_i in range(len(groups))]
                    add_row(rows, cols, vals, lower, upper, terms, 0.0, 0.0)
            else:
                terms = [
                    (idxs.x[(e_i, d_i, g_i, t_i)], 1.0)
                    for g_i in range(len(groups))
                    for t_i in slots
                ]
                add_row(rows, cols, vals, lower, upper, terms, 1.0, math.inf)
        else:
            for t_i in slots:
                for g_i in range(len(groups)):
                    var_id = idxs.x[(e_i, d_i, g_i, t_i)]
                    if is_negative:
                        c[var_id] += 0.45
                    else:
                        c[var_id] -= 0.35

    # Group rules.
    for raw_rule in data.get("rules_group", []):
        if len(raw_rule) < 4:
            warnings.append(f"Regle groupe ignoree: {raw_rule}.")
            continue
        pref_type, strength, educator_name, group_name = raw_rule[:4]
        if educator_name not in name_to_educator:
            warnings.append(f"Regle groupe avec educateur inconnu: {educator_name}.")
            continue
        if group_name not in group_by_name:
            warnings.append(f"Regle groupe avec groupe inconnu: {group_name}.")
            continue
        e_i = name_to_educator[educator_name]
        preferred_g = group_by_name[group_name]
        is_negative = normalize_flag(pref_type) in {"negatif", "negative", "neg"}
        is_hard = normalize_flag(strength) == "hard"
        for d_i in range(len(DAYS)):
            for g_i in range(len(groups)):
                for t_i in range(horizon.slots):
                    var_id = idxs.x[(e_i, d_i, g_i, t_i)]
                    affected = g_i == preferred_g if is_negative else g_i != preferred_g
                    if not affected:
                        continue
                    if is_hard:
                        add_row(rows, cols, vals, lower, upper, [(var_id, 1.0)], 0.0, 0.0)
                    else:
                        c[var_id] += 0.18

    # Percentage rules per site.
    educator_types = [educator.get("type", "") for educator in educators]
    for raw_rule in data.get("rules_percentage", []):
        if len(raw_rule) < 4:
            warnings.append(f"Regle pourcentage ignoree: {raw_rule}.")
            continue
        raw_types, minmax, value, site = raw_rule[:4]
        wanted_types, type_warnings = split_types(list(raw_types), aliases, known_types)
        warnings.extend(type_warnings)
        if site not in site_index:
            warnings.append(f"Regle pourcentage avec site inconnu: {site}.")
            continue
        terms_by_var: dict[int, float] = {}
        pct = float(value)
        for e_i, educator_type in enumerate(educator_types):
            for d_i in range(len(DAYS)):
                for g_i in range(len(groups)):
                    if group_site[g_i] != site:
                        continue
                    for t_i in range(horizon.slots):
                        var_id = idxs.x[(e_i, d_i, g_i, t_i)]
                        coeff = -pct
                        if educator_type in wanted_types:
                            coeff += 100.0
                        terms_by_var[var_id] = terms_by_var.get(var_id, 0.0) + coeff
        terms = list(terms_by_var.items())
        if normalize_flag(minmax) == "min":
            add_row(rows, cols, vals, lower, upper, terms, 0.0, math.inf)
        else:
            add_row(rows, cols, vals, lower, upper, terms, -math.inf, 0.0)

    matrix = coo_matrix((vals, (rows, cols)), shape=(len(lower), idxs.var_count)).tocsr()
    constraints = LinearConstraint(matrix, np.array(lower), np.array(upper))
    result = milp(
        c=c,
        integrality=integrality,
        bounds=Bounds(lb, ub),
        constraints=constraints,
        options={"time_limit": time_limit, "mip_rel_gap": mip_gap},
    )

    return SolveBundle(
        result=result,
        data=data,
        horizon=horizon,
        indexes=idxs,
        groups=groups,
        educators=educators,
        sites=sites,
        warnings=sorted(set(warnings)),
    )


def generate_patterns(
    groups: list[dict[str, Any]],
    horizon: Horizon,
    *,
    min_hours: float,
    max_hours: float,
) -> list[Pattern]:
    min_slots = max(1, int(round(min_hours / 0.25)))
    max_slots = max(min_slots, int(round(max_hours / 0.25)))
    patterns: list[Pattern] = []
    for g_i, group in enumerate(groups):
        for start_slot in range(horizon.slots):
            latest_duration = min(max_slots, horizon.slots - start_slot)
            for duration in range(min_slots, latest_duration + 1):
                patterns.append(
                    Pattern(
                        site=group["site"],
                        group_index=g_i,
                        start_slot=start_slot,
                        end_slot=start_slot + duration,
                    )
                )
    return patterns


def pattern_rule_cost_and_allowed(
    *,
    data: dict[str, Any],
    pattern: Pattern,
    educator: dict[str, Any],
    day_key: str,
    horizon: Horizon,
    group_name: str,
    warnings: list[str],
) -> tuple[bool, float]:
    educator_name = educator["name"]
    cost = 0.75

    for raw_rule in data.get("rules_time", []):
        if len(raw_rule) < 6:
            continue
        pref_type, strength, rule_educator, rule_day, start, end = raw_rule[:6]
        if rule_educator != educator_name or normalize_day(rule_day) != day_key:
            continue
        clipped_slots, clipped = slot_range_clipped(horizon, start, end)
        if clipped:
            warnings.append(f"Regle horaire rognee sur l'horizon: {raw_rule}.")
        rule_slots = set(clipped_slots)
        if not rule_slots:
            continue
        pattern_slots = set(range(pattern.start_slot, pattern.end_slot))
        overlap = len(pattern_slots & rule_slots)
        is_negative = normalize_flag(pref_type) in {"negatif", "negative", "neg"}
        is_hard = normalize_flag(strength) == "hard"
        if is_hard:
            if is_negative and overlap:
                return False, cost
            if not is_negative and overlap == 0:
                return False, cost
        else:
            if is_negative:
                cost += overlap * 0.45
            else:
                cost -= overlap * 0.35

    for raw_rule in data.get("rules_group", []):
        if len(raw_rule) < 4:
            continue
        pref_type, strength, rule_educator, rule_group = raw_rule[:4]
        if rule_educator != educator_name:
            continue
        is_negative = normalize_flag(pref_type) in {"negatif", "negative", "neg"}
        is_hard = normalize_flag(strength) == "hard"
        affected = group_name == rule_group if is_negative else group_name != rule_group
        if not affected:
            continue
        if is_hard:
            return False, cost
        cost += pattern.duration_slots * 0.18

    return True, cost


def solve_schedule_patterns(
    data: dict[str, Any],
    *,
    time_limit: float = 120.0,
    mip_gap: float = 0.01,
    type_aliases: dict[str, str] | None = None,
    min_shift_hours: float = 2.0,
    weekly_mode: str = "exact",
) -> PatternSolveBundle:
    aliases = dict(DEFAULT_TYPE_ALIASES)
    if type_aliases:
        aliases.update(type_aliases)

    horizon = make_horizon(data)
    groups = list(data.get("groups", []))
    educators = list(data.get("educators", []))
    sites = [site["name"] for site in data.get("sites", [])]
    if not groups:
        raise ValueError("Aucun groupe dans le JSON.")
    if not educators:
        raise ValueError("Aucun educateur dans le JSON.")
    if not sites:
        raise ValueError("Aucun site dans le JSON.")

    warnings: list[str] = []
    site_index = {site: i for i, site in enumerate(sites)}
    known_types = {item["name"] for item in data.get("educator_types", [])}
    max_daily_hours = float(data.get("rules_global", {}).get("max_daily_hours", 8.5))
    weekly_base = float(data.get("rules_global", {}).get("max_weekly_hours", 40.0))

    patterns = generate_patterns(groups, horizon, min_hours=min_shift_hours, max_hours=max_daily_hours)
    group_demand, site_demand = build_demands_by_day(data, groups, horizon)
    group_site = {i: group["site"] for i, group in enumerate(groups)}

    variables: list[tuple[int, int, int]] = []
    costs: list[float] = []
    group_names = [group["name"] for group in groups]

    for e_i, educator in enumerate(educators):
        for d_i, (day_key, _) in enumerate(DAYS):
            for p_i, pattern in enumerate(patterns):
                allowed, cost = pattern_rule_cost_and_allowed(
                    data=data,
                    pattern=pattern,
                    educator=educator,
                    day_key=day_key,
                    horizon=horizon,
                    group_name=group_names[pattern.group_index],
                    warnings=warnings,
                )
                if allowed:
                    variables.append((e_i, d_i, p_i))
                    costs.append(cost)

    var_count = len(variables)
    rows: list[int] = []
    cols: list[int] = []
    vals: list[float] = []
    lower: list[float] = []
    upper: list[float] = []

    for e_i in range(len(educators)):
        for d_i in range(len(DAYS)):
            terms = [
                (var_id, 1.0)
                for var_id, (var_e, var_d, _) in enumerate(variables)
                if var_e == e_i and var_d == d_i
            ]
            add_row(rows, cols, vals, lower, upper, terms, 0.0, 1.0)

    for e_i, educator in enumerate(educators):
        target_slots = int(round((float(educator["percentage"]) / 100.0) * weekly_base / 0.25))
        terms = [
            (var_id, patterns[p_i].duration_slots)
            for var_id, (var_e, _, p_i) in enumerate(variables)
            if var_e == e_i
        ]
        if weekly_mode == "exact":
            add_row(rows, cols, vals, lower, upper, terms, target_slots, target_slots)
        else:
            add_row(rows, cols, vals, lower, upper, terms, 0.0, target_slots)

    max_staff_default = 3
    for d_i in range(len(DAYS)):
        for g_i in range(len(groups)):
            for t_i in range(horizon.slots):
                demand = group_demand[(d_i, g_i, t_i)]
                terms = []
                for var_id, (_, var_d, p_i) in enumerate(variables):
                    pattern = patterns[p_i]
                    if var_d == d_i and pattern.group_index == g_i and pattern.start_slot <= t_i < pattern.end_slot:
                        terms.append((var_id, 1.0))
                add_row(rows, cols, vals, lower, upper, terms, demand, max(max_staff_default, demand))

    for (d_i, site, t_i), demand in site_demand.items():
        terms = []
        for var_id, (_, var_d, p_i) in enumerate(variables):
            pattern = patterns[p_i]
            if var_d == d_i and pattern.site == site and pattern.start_slot <= t_i < pattern.end_slot:
                terms.append((var_id, 1.0))
        add_row(rows, cols, vals, lower, upper, terms, demand, math.inf)

    educator_types = [educator.get("type", "") for educator in educators]
    for raw_rule in data.get("rules_percentage", []):
        if len(raw_rule) < 4:
            warnings.append(f"Regle pourcentage ignoree: {raw_rule}.")
            continue
        raw_types, minmax, value, site = raw_rule[:4]
        wanted_types, type_warnings = split_types(list(raw_types), aliases, known_types)
        warnings.extend(type_warnings)
        if site not in site_index:
            warnings.append(f"Regle pourcentage avec site inconnu: {site}.")
            continue
        terms = []
        pct = float(value)
        for var_id, (e_i, _, p_i) in enumerate(variables):
            pattern = patterns[p_i]
            if pattern.site != site:
                continue
            coeff = -pct * pattern.duration_slots
            if educator_types[e_i] in wanted_types:
                coeff += 100.0 * pattern.duration_slots
            terms.append((var_id, coeff))
        if normalize_flag(minmax) == "min":
            add_row(rows, cols, vals, lower, upper, terms, 0.0, math.inf)
        else:
            add_row(rows, cols, vals, lower, upper, terms, -math.inf, 0.0)

    matrix = coo_matrix((vals, (rows, cols)), shape=(len(lower), var_count)).tocsr()
    constraints = LinearConstraint(matrix, np.array(lower), np.array(upper))
    result = milp(
        c=np.array(costs),
        integrality=np.ones(var_count, dtype=np.int8),
        bounds=Bounds(np.zeros(var_count), np.ones(var_count)),
        constraints=constraints,
        options={"time_limit": time_limit, "mip_rel_gap": mip_gap},
    )
    return PatternSolveBundle(
        result=result,
        data=data,
        horizon=horizon,
        patterns=patterns,
        variables=variables,
        groups=groups,
        educators=educators,
        sites=sites,
        warnings=sorted(set(warnings)),
    )


def value_at(bundle: SolveBundle, var_id: int) -> int:
    if bundle.result.x is None:
        return 0
    return 1 if bundle.result.x[var_id] >= 0.5 else 0


def build_schedule(bundle: SolveBundle) -> dict[str, dict[str, list[dict[str, Any]]]]:
    schedule: dict[str, dict[str, list[dict[str, Any]]]] = {}
    idxs = bundle.indexes
    for e_i, educator in enumerate(bundle.educators):
        educator_name = educator["name"]
        schedule[educator_name] = {}
        for d_i, (day_key, day_label) in enumerate(DAYS):
            blocks: list[dict[str, Any]] = []
            current_group: int | None = None
            start_slot: int | None = None
            for t_i in range(bundle.horizon.slots + 1):
                active_group: int | None = None
                if t_i < bundle.horizon.slots:
                    for g_i in range(len(bundle.groups)):
                        if value_at(bundle, idxs.x[(e_i, d_i, g_i, t_i)]):
                            active_group = g_i
                            break
                if active_group != current_group:
                    if current_group is not None and start_slot is not None:
                        start_min = bundle.horizon.start + start_slot * bundle.horizon.step
                        end_min = bundle.horizon.start + t_i * bundle.horizon.step
                        group = bundle.groups[current_group]
                        blocks.append(
                            {
                                "site": group["site"],
                                "group": group["name"],
                                "start": format_time(start_min),
                                "end": format_time(end_min),
                                "hours": round((end_min - start_min) / 60.0, 2),
                            }
                        )
                    current_group = active_group
                    start_slot = t_i if active_group is not None else None
            schedule[educator_name][day_key] = blocks
    return schedule


def infer_main_groups(bundle: SolveBundle) -> dict[int, int]:
    group_by_name = {group["name"]: i for i, group in enumerate(bundle.groups)}
    educator_by_name = {educator["name"]: i for i, educator in enumerate(bundle.educators)}
    main_groups: dict[int, int] = {}
    soft_groups: dict[int, int] = {}

    for raw_rule in bundle.data.get("rules_group", []):
        if len(raw_rule) < 4:
            continue
        pref_type, strength, educator_name, group_name = raw_rule[:4]
        if normalize_flag(pref_type) in {"negatif", "negative", "neg"}:
            continue
        if educator_name not in educator_by_name or group_name not in group_by_name:
            continue
        e_i = educator_by_name[educator_name]
        g_i = group_by_name[group_name]
        if normalize_flag(strength) == "hard":
            main_groups.setdefault(e_i, g_i)
        else:
            soft_groups.setdefault(e_i, g_i)

    for e_i, g_i in soft_groups.items():
        main_groups.setdefault(e_i, g_i)

    if not bundle.result.success or bundle.result.x is None:
        return main_groups

    counts: dict[int, dict[int, int]] = {e_i: {} for e_i in range(len(bundle.educators))}
    for e_i in range(len(bundle.educators)):
        for d_i in range(len(DAYS)):
            for g_i in range(len(bundle.groups)):
                slots = 0
                for t_i in range(bundle.horizon.slots):
                    if value_at(bundle, bundle.indexes.x[(e_i, d_i, g_i, t_i)]):
                        slots += 1
                if slots:
                    counts[e_i][g_i] = counts[e_i].get(g_i, 0) + slots

    for e_i, by_group in counts.items():
        if e_i in main_groups or not by_group:
            continue
        ranked = sorted(by_group.items(), key=lambda item: item[1], reverse=True)
        if len(ranked) == 1 or ranked[0][1] > ranked[1][1]:
            main_groups[e_i] = ranked[0][0]

    return main_groups


def infer_main_sites(bundle: SolveBundle) -> dict[int, int]:
    site_by_name = {site: i for i, site in enumerate(bundle.sites)}
    counts: dict[int, dict[int, int]] = {e_i: {} for e_i in range(len(bundle.educators))}

    if not bundle.result.success or bundle.result.x is None:
        return {}

    for e_i in range(len(bundle.educators)):
        for d_i in range(len(DAYS)):
            for g_i, group in enumerate(bundle.groups):
                s_i = site_by_name[group["site"]]
                slots = 0
                for t_i in range(bundle.horizon.slots):
                    if value_at(bundle, bundle.indexes.x[(e_i, d_i, g_i, t_i)]):
                        slots += 1
                if slots:
                    counts[e_i][s_i] = counts[e_i].get(s_i, 0) + slots

    main_sites: dict[int, int] = {}
    for e_i, by_site in counts.items():
        if not by_site:
            continue
        ranked = sorted(by_site.items(), key=lambda item: item[1], reverse=True)
        if len(ranked) == 1 or ranked[0][1] > ranked[1][1]:
            main_sites[e_i] = ranked[0][0]
    return main_sites


def smooth_schedule_slot_mip(
    bundle: SolveBundle,
    *,
    time_limit_per_site: float = 8.0,
    split_shift_weight: float = 120.0,
    split_gap_weight: float = 4.0,
    max_split_gap_minutes: int | None = 90,
    group_switch_day_weight: float = 8.0,
    same_group_week_weight: float = 0.4,
) -> dict[str, dict[str, list[dict[str, Any]]]]:
    original = build_schedule(bundle)
    if not bundle.result.success or bundle.result.x is None:
        return original

    idxs = bundle.indexes
    use_gap_penalty = split_gap_weight > 0
    group_demand, site_demand = build_demands_by_day(bundle.data, bundle.groups, bundle.horizon)
    group_by_site = {
        site: [g_i for g_i, group in enumerate(bundle.groups) if group["site"] == site]
        for site in bundle.sites
    }
    main_groups = infer_main_groups(bundle)
    macro: dict[tuple[int, int], tuple[str | None, int]] = {}
    for e_i in range(len(bundle.educators)):
        for d_i in range(len(DAYS)):
            slots = 0
            used_sites: set[str] = set()
            for g_i, group in enumerate(bundle.groups):
                for t_i in range(bundle.horizon.slots):
                    if value_at(bundle, idxs.x[(e_i, d_i, g_i, t_i)]):
                        slots += 1
                        used_sites.add(group["site"])
            macro[(e_i, d_i)] = (next(iter(used_sites)) if used_sites else None, slots)

    schedule = original
    for d_i, (day_key, _) in enumerate(DAYS):
        for site in bundle.sites:
            local_educators = [
                (e_i, slots)
                for e_i in range(len(bundle.educators))
                for used_site, slots in [macro[(e_i, d_i)]]
                if used_site == site and slots > 0
            ]
            local_groups = group_by_site[site]
            if not local_educators or not local_groups:
                continue

            x: dict[tuple[int, int, int], int] = {}
            work_start: dict[tuple[int, int], int] = {}
            work_before: dict[tuple[int, int], int] = {}
            work_after: dict[tuple[int, int], int] = {}
            work_gap: dict[tuple[int, int], int] = {}
            group_start: dict[tuple[int, int, int], int] = {}
            var_id = 0
            for le_i in range(len(local_educators)):
                for lg_i in range(len(local_groups)):
                    for t_i in range(bundle.horizon.slots):
                        x[(le_i, lg_i, t_i)] = var_id
                        var_id += 1
            for le_i in range(len(local_educators)):
                for t_i in range(bundle.horizon.slots):
                    work_start[(le_i, t_i)] = var_id
                    var_id += 1
                    if use_gap_penalty:
                        work_before[(le_i, t_i)] = var_id
                        var_id += 1
                        work_after[(le_i, t_i)] = var_id
                        var_id += 1
                        work_gap[(le_i, t_i)] = var_id
                        var_id += 1
            for le_i in range(len(local_educators)):
                for lg_i in range(len(local_groups)):
                    for t_i in range(bundle.horizon.slots):
                        group_start[(le_i, lg_i, t_i)] = var_id
                        var_id += 1

            c = np.zeros(var_id)
            integrality = np.ones(var_id, dtype=np.int8)
            lb = np.zeros(var_id)
            ub = np.ones(var_id)
            for item in work_start.values():
                integrality[item] = 0
                c[item] = split_shift_weight
            for item in work_gap.values():
                integrality[item] = 0
                c[item] = split_gap_weight
            for item in work_before.values():
                integrality[item] = 0
            for item in work_after.values():
                integrality[item] = 0
            for item in group_start.values():
                integrality[item] = 0
                c[item] = group_switch_day_weight

            rows: list[int] = []
            cols: list[int] = []
            vals: list[float] = []
            lower: list[float] = []
            upper: list[float] = []

            # Coverage for the groups on this site.
            for lg_i, g_i in enumerate(local_groups):
                for t_i in range(bundle.horizon.slots):
                    demand = group_demand[(d_i, g_i, t_i)]
                    terms = [(x[(le_i, lg_i, t_i)], 1.0) for le_i in range(len(local_educators))]
                    add_row(rows, cols, vals, lower, upper, terms, demand, max(3, demand))

            for (demand_d_i, site_name, t_i), demand in site_demand.items():
                if demand_d_i != d_i or site_name != site:
                    continue
                terms = [
                    (x[(le_i, lg_i, t_i)], 1.0)
                    for le_i in range(len(local_educators))
                    for lg_i in range(len(local_groups))
                ]
                add_row(rows, cols, vals, lower, upper, terms, demand, math.inf)

            # One group per educator and slot.
            for le_i in range(len(local_educators)):
                for t_i in range(bundle.horizon.slots):
                    terms = [(x[(le_i, lg_i, t_i)], 1.0) for lg_i in range(len(local_groups))]
                    add_row(rows, cols, vals, lower, upper, terms, 0.0, 1.0)

            # Preserve daily hours from the global feasible solution.
            for le_i, (_, slots) in enumerate(local_educators):
                terms = [
                    (x[(le_i, lg_i, t_i)], 1.0)
                    for lg_i in range(len(local_groups))
                    for t_i in range(bundle.horizon.slots)
                ]
                add_row(rows, cols, vals, lower, upper, terms, slots, slots)

            if use_gap_penalty:
                # Mark empty slots located between two worked slots. Penalizing
                # these gaps makes split shifts shorter when a split is needed.
                for le_i in range(len(local_educators)):
                    for t_i in range(bundle.horizon.slots):
                        work_terms = [(x[(le_i, lg_i, t_i)], 1.0) for lg_i in range(len(local_groups))]
                        before = work_before[(le_i, t_i)]
                        after = work_after[(le_i, t_i)]

                        if t_i == 0:
                            add_row(
                                rows,
                                cols,
                                vals,
                                lower,
                                upper,
                                [(before, 1.0)] + [(var, -coef) for var, coef in work_terms],
                                0.0,
                                0.0,
                            )
                        else:
                            previous_before = work_before[(le_i, t_i - 1)]
                            add_row(rows, cols, vals, lower, upper, [(before, 1.0), (previous_before, -1.0)], 0.0, math.inf)
                            add_row(
                                rows,
                                cols,
                                vals,
                                lower,
                                upper,
                                [(before, 1.0), (previous_before, -1.0)] + [(var, -coef) for var, coef in work_terms],
                                -math.inf,
                                0.0,
                            )
                            add_row(
                                rows,
                                cols,
                                vals,
                                lower,
                                upper,
                                [(before, 1.0)] + [(var, -coef) for var, coef in work_terms],
                                0.0,
                                math.inf,
                            )

                        if t_i == bundle.horizon.slots - 1:
                            add_row(
                                rows,
                                cols,
                                vals,
                                lower,
                                upper,
                                [(after, 1.0)] + [(var, -coef) for var, coef in work_terms],
                                0.0,
                                0.0,
                            )
                        else:
                            next_after = work_after[(le_i, t_i + 1)]
                            add_row(rows, cols, vals, lower, upper, [(after, 1.0), (next_after, -1.0)], 0.0, math.inf)
                            add_row(
                                rows,
                                cols,
                                vals,
                                lower,
                                upper,
                                [(after, 1.0), (next_after, -1.0)] + [(var, -coef) for var, coef in work_terms],
                                -math.inf,
                                0.0,
                            )
                            add_row(
                                rows,
                                cols,
                                vals,
                                lower,
                                upper,
                                [(after, 1.0)] + [(var, -coef) for var, coef in work_terms],
                                0.0,
                                math.inf,
                            )

                        add_row(
                            rows,
                            cols,
                            vals,
                            lower,
                            upper,
                            [(work_gap[(le_i, t_i)], 1.0), (before, -1.0), (after, -1.0)] + work_terms,
                            -1.0,
                            math.inf,
                        )

            for le_i, (e_i, _) in enumerate(local_educators):
                educator_name = bundle.educators[e_i]["name"]
                for t_i in range(bundle.horizon.slots):
                    current = [(x[(le_i, lg_i, t_i)], -1.0) for lg_i in range(len(local_groups))]
                    previous = []
                    if t_i > 0:
                        previous = [(x[(le_i, lg_i, t_i - 1)], 1.0) for lg_i in range(len(local_groups))]
                    add_row(
                        rows,
                        cols,
                        vals,
                        lower,
                        upper,
                        [(work_start[(le_i, t_i)], 1.0)] + current + previous,
                        0.0,
                        math.inf,
                    )

                    for lg_i, g_i in enumerate(local_groups):
                        terms = [
                            (group_start[(le_i, lg_i, t_i)], 1.0),
                            (x[(le_i, lg_i, t_i)], -1.0),
                        ]
                        if t_i > 0:
                            terms.append((x[(le_i, lg_i, t_i - 1)], 1.0))
                        add_row(rows, cols, vals, lower, upper, terms, 0.0, math.inf)

                        # Light preference costs and hard bans on actual assignment variables.
                        var = x[(le_i, lg_i, t_i)]
                        group_name = bundle.groups[g_i]["name"]
                        main_group = main_groups.get(e_i)
                        if main_group is not None and main_group != g_i:
                            c[var] += same_group_week_weight
                        for raw_rule in bundle.data.get("rules_group", []):
                            if len(raw_rule) < 4 or raw_rule[2] != educator_name:
                                continue
                            pref_type, strength, _, rule_group = raw_rule[:4]
                            is_negative = normalize_flag(pref_type) in {"negatif", "negative", "neg"}
                            affected = group_name == rule_group if is_negative else group_name != rule_group
                            if affected and normalize_flag(strength) == "hard":
                                add_row(rows, cols, vals, lower, upper, [(var, 1.0)], 0.0, 0.0)
                            elif affected:
                                c[var] += 0.18

                        minute = bundle.horizon.start + t_i * bundle.horizon.step
                        for raw_rule in bundle.data.get("rules_time", []):
                            if len(raw_rule) < 6 or raw_rule[2] != educator_name or normalize_day(raw_rule[3]) != day_key:
                                continue
                            pref_type, strength, _, _, start, end = raw_rule[:6]
                            start_min = parse_time(start)
                            end_min = parse_time(end)
                            if not (start_min <= minute < end_min):
                                continue
                            is_negative = normalize_flag(pref_type) in {"negatif", "negative", "neg"}
                            if normalize_flag(strength) == "hard":
                                if is_negative:
                                    add_row(rows, cols, vals, lower, upper, [(var, 1.0)], 0.0, 0.0)
                            elif is_negative:
                                c[var] += 0.45
                            else:
                                c[var] -= 0.35

                for raw_rule in bundle.data.get("rules_time", []):
                    if len(raw_rule) < 6 or raw_rule[2] != educator_name or normalize_day(raw_rule[3]) != day_key:
                        continue
                    pref_type, strength, _, _, start, end = raw_rule[:6]
                    is_negative = normalize_flag(pref_type) in {"negatif", "negative", "neg"}
                    if is_negative or normalize_flag(strength) != "hard":
                        continue
                    slots = list(slot_range_clipped(bundle.horizon, start, end)[0])
                    if not slots:
                        continue
                    terms = [
                        (x[(le_i, lg_i, t_i)], 1.0)
                        for lg_i in range(len(local_groups))
                        for t_i in slots
                    ]
                    add_row(rows, cols, vals, lower, upper, terms, 1.0, math.inf)

            matrix = coo_matrix((vals, (rows, cols)), shape=(len(lower), var_id)).tocsr()
            result = milp(
                c=c,
                integrality=integrality,
                bounds=Bounds(lb, ub),
                constraints=LinearConstraint(matrix, np.array(lower), np.array(upper)),
                options={"time_limit": time_limit_per_site, "mip_rel_gap": 0.03},
            )
            if not result.success or result.x is None:
                continue

            for e_i, _ in local_educators:
                schedule[bundle.educators[e_i]["name"]][day_key] = []

            for le_i, (e_i, _) in enumerate(local_educators):
                educator_name = bundle.educators[e_i]["name"]
                current_group: int | None = None
                start_slot: int | None = None
                for t_i in range(bundle.horizon.slots + 1):
                    active_group: int | None = None
                    if t_i < bundle.horizon.slots:
                        for lg_i, g_i in enumerate(local_groups):
                            if result.x[x[(le_i, lg_i, t_i)]] >= 0.5:
                                active_group = g_i
                                break
                    if active_group != current_group:
                        if current_group is not None and start_slot is not None:
                            start_min = bundle.horizon.start + start_slot * bundle.horizon.step
                            end_min = bundle.horizon.start + t_i * bundle.horizon.step
                            group = bundle.groups[current_group]
                            schedule[educator_name][day_key].append(
                                {
                                    "site": group["site"],
                                    "group": group["name"],
                                    "start": format_time(start_min),
                                    "end": format_time(end_min),
                                    "hours": round((end_min - start_min) / 60.0, 2),
                                }
                            )
                        current_group = active_group
                        start_slot = t_i if active_group is not None else None
                schedule[educator_name][day_key].sort(key=lambda item: item["start"])

    return schedule


def smooth_schedule(
    bundle: SolveBundle,
    *,
    time_limit_per_site: float = 8.0,
    split_shift_weight: float = 120.0,
    split_gap_weight: float = 4.0,
    max_split_gap_minutes: int | None = 90,
    group_switch_day_weight: float = 8.0,
    same_group_week_weight: float = 0.4,
    half_day_split_time: str = "12:30",
    max_weekly_group_exception_days: int | None = 1,
    progress_callback: Callable[[int, int, str], None] | None = None,
) -> dict[str, dict[str, list[dict[str, Any]]]]:
    original = build_schedule(bundle)
    if not bundle.result.success or bundle.result.x is None:
        return original

    idxs = bundle.indexes
    group_demand, site_demand = build_demands_by_day(bundle.data, bundle.groups, bundle.horizon)
    group_by_site = {
        site: [g_i for g_i, group in enumerate(bundle.groups) if group["site"] == site]
        for site in bundle.sites
    }
    main_groups = infer_main_groups(bundle)
    horizon_slots = bundle.horizon.slots
    split_slot = split_slot_for_horizon(bundle.horizon, half_day_split_time)
    max_split_gap_slots = (
        None
        if max_split_gap_minutes is None
        else max(1, int(round(max_split_gap_minutes / bundle.horizon.step)))
    )
    min_segment_slots = 4

    macro: dict[tuple[int, int], tuple[str | None, int]] = {}
    for e_i in range(len(bundle.educators)):
        for d_i in range(len(DAYS)):
            slots = 0
            used_sites: set[str] = set()
            for g_i, group in enumerate(bundle.groups):
                for t_i in range(horizon_slots):
                    if value_at(bundle, idxs.x[(e_i, d_i, g_i, t_i)]):
                        slots += 1
                        used_sites.add(group["site"])
            macro[(e_i, d_i)] = (next(iter(used_sites)) if used_sites else None, slots)

    def work_pattern_cost(e_i: int, day_key: str, segments: tuple[tuple[int, int], ...]) -> float | None:
        educator_name = bundle.educators[e_i]["name"]
        worked_slots: set[int] = set()
        for start, end in segments:
            worked_slots.update(range(start, end))

        cost = 0.0
        for raw_rule in bundle.data.get("rules_time", []):
            if len(raw_rule) < 6 or raw_rule[2] != educator_name or normalize_day(raw_rule[3]) != day_key:
                continue
            pref_type, strength, _, _, start, end = raw_rule[:6]
            rule_slots = set(slot_range_clipped(bundle.horizon, start, end)[0])
            overlap = len(worked_slots & rule_slots)
            is_negative = normalize_flag(pref_type) in {"negatif", "negative", "neg"}
            is_hard = normalize_flag(strength) == "hard"
            if is_hard:
                if is_negative and overlap:
                    return None
                if not is_negative and overlap == 0:
                    return None
            elif is_negative:
                cost += overlap * 0.45
            else:
                cost -= overlap * 0.35

        if len(segments) > 1:
            gap_slots = segments[1][0] - segments[0][1]
            if max_split_gap_slots is not None and gap_slots > max_split_gap_slots:
                return None
            cost += split_shift_weight + gap_slots * split_gap_weight
        return cost

    def group_slot_cost(e_i: int, g_i: int) -> float | None:
        educator_name = bundle.educators[e_i]["name"]
        group_name = bundle.groups[g_i]["name"]
        cost = 0.0
        main_group = main_groups.get(e_i)
        if main_group is not None and main_group != g_i:
            cost += same_group_week_weight

        for raw_rule in bundle.data.get("rules_group", []):
            if len(raw_rule) < 4 or raw_rule[2] != educator_name:
                continue
            pref_type, strength, _, rule_group = raw_rule[:4]
            is_negative = normalize_flag(pref_type) in {"negatif", "negative", "neg"}
            affected = group_name == rule_group if is_negative else group_name != rule_group
            if not affected:
                continue
            if normalize_flag(strength) == "hard":
                return None
            cost += 0.18
        return cost

    def solve_work_patterns(
        local_educators: list[tuple[int, int]],
        site: str,
        d_i: int,
        day_key: str,
    ) -> tuple[dict[int, tuple[tuple[int, int], ...]] | None, bool]:
        patterns: list[tuple[int, tuple[tuple[int, int], ...]]] = []
        costs: list[float] = []

        for le_i, (e_i, daily_slots) in enumerate(local_educators):
            for start in range(horizon_slots - daily_slots + 1):
                segments = ((start, start + daily_slots),)
                cost = work_pattern_cost(e_i, day_key, segments)
                if cost is not None:
                    patterns.append((le_i, segments))
                    costs.append(cost)

            segment_min = min(min_segment_slots, max(1, daily_slots // 2))
            if daily_slots >= 2 * segment_min:
                for first_len in range(segment_min, daily_slots - segment_min + 1):
                    second_len = daily_slots - first_len
                    max_gap = horizon_slots - daily_slots
                    if max_split_gap_slots is not None:
                        max_gap = min(max_gap, max_split_gap_slots)
                    for gap in range(1, max_gap + 1):
                        latest_start = horizon_slots - daily_slots - gap
                        for first_start in range(latest_start + 1):
                            first_end = first_start + first_len
                            second_start = first_end + gap
                            segments = (
                                (first_start, first_end),
                                (second_start, second_start + second_len),
                            )
                            cost = work_pattern_cost(e_i, day_key, segments)
                            if cost is not None:
                                patterns.append((le_i, segments))
                                costs.append(cost)

        if not patterns:
            return None, False

        rows: list[int] = []
        cols: list[int] = []
        vals: list[float] = []
        lower: list[float] = []
        upper: list[float] = []

        for le_i in range(len(local_educators)):
            terms = [
                (pattern_id, 1.0)
                for pattern_id, (pattern_le, _) in enumerate(patterns)
                if pattern_le == le_i
            ]
            add_row(rows, cols, vals, lower, upper, terms, 1.0, 1.0)

        local_groups = group_by_site[site]
        for t_i in range(horizon_slots):
            minimum = max(
                site_demand.get((d_i, site, t_i), 0),
                sum(group_demand[(d_i, g_i, t_i)] for g_i in local_groups),
            )
            maximum = sum(max(3, group_demand[(d_i, g_i, t_i)]) for g_i in local_groups)
            terms = [
                (pattern_id, 1.0)
                for pattern_id, (_, segments) in enumerate(patterns)
                if any(start <= t_i < end for start, end in segments)
            ]
            add_row(rows, cols, vals, lower, upper, terms, minimum, maximum)

        matrix = coo_matrix((vals, (rows, cols)), shape=(len(lower), len(patterns))).tocsr()
        result = milp(
            c=np.array(costs),
            integrality=np.ones(len(patterns), dtype=np.int8),
            bounds=Bounds(np.zeros(len(patterns)), np.ones(len(patterns))),
            constraints=LinearConstraint(matrix, np.array(lower), np.array(upper)),
            options={"time_limit": time_limit_per_site, "mip_rel_gap": 0.03},
        )
        if result.x is None:
            return None, False

        chosen: dict[int, tuple[tuple[int, int], ...]] = {}
        for pattern_id, value in enumerate(result.x):
            if value >= 0.5:
                le_i, segments = patterns[pattern_id]
                chosen[le_i] = segments
        if len(chosen) != len(local_educators):
            return None, False
        return chosen, bool(result.success)

    def solve_group_assignment(
        local_educators: list[tuple[int, int]],
        site: str,
        d_i: int,
        chosen_work: dict[int, tuple[tuple[int, int], ...]],
    ) -> tuple[Any, dict[tuple[int, int, int], int]] | None:
        local_groups = group_by_site[site]
        works = {
            (le_i, t_i): any(start <= t_i < end for start, end in segments)
            for le_i, segments in chosen_work.items()
            for t_i in range(horizon_slots)
        }

        y: dict[tuple[int, int, int], int] = {}
        group_start: dict[tuple[int, int, int], int] = {}
        costs: list[float] = []
        start_vars: set[int] = set()
        var_id = 0

        for le_i, (e_i, _) in enumerate(local_educators):
            for t_i in range(horizon_slots):
                if not works.get((le_i, t_i), False):
                    continue
                for lg_i, g_i in enumerate(local_groups):
                    cost = group_slot_cost(e_i, g_i)
                    if cost is None:
                        continue
                    y[(le_i, lg_i, t_i)] = var_id
                    costs.append(cost)
                    var_id += 1

        for le_i in range(len(local_educators)):
            worked = [t_i for t_i in range(horizon_slots) if works.get((le_i, t_i), False)]
            for t_i in worked[1:]:
                for lg_i in range(len(local_groups)):
                    group_start[(le_i, lg_i, t_i)] = var_id
                    start_vars.add(var_id)
                    costs.append(group_switch_day_weight)
                    var_id += 1

        if var_id == 0:
            return None

        rows: list[int] = []
        cols: list[int] = []
        vals: list[float] = []
        lower: list[float] = []
        upper: list[float] = []

        for le_i in range(len(local_educators)):
            for t_i in range(horizon_slots):
                if not works.get((le_i, t_i), False):
                    continue
                terms = [
                    (y[(le_i, lg_i, t_i)], 1.0)
                    for lg_i in range(len(local_groups))
                    if (le_i, lg_i, t_i) in y
                ]
                add_row(rows, cols, vals, lower, upper, terms, 1.0, 1.0)

        for lg_i, g_i in enumerate(local_groups):
            for t_i in range(horizon_slots):
                demand = group_demand[(d_i, g_i, t_i)]
                terms = [
                    (y[(le_i, lg_i, t_i)], 1.0)
                    for le_i in range(len(local_educators))
                    if (le_i, lg_i, t_i) in y
                ]
                add_row(rows, cols, vals, lower, upper, terms, demand, max(3, demand))

        for (demand_d_i, site_name, t_i), demand in site_demand.items():
            if demand_d_i != d_i or site_name != site:
                continue
            terms = [
                (var, 1.0)
                for (le_i, lg_i, var_t), var in y.items()
                if var_t == t_i
            ]
            add_row(rows, cols, vals, lower, upper, terms, demand, math.inf)

        for le_i in range(len(local_educators)):
            worked = [t_i for t_i in range(horizon_slots) if works.get((le_i, t_i), False)]
            for pos in range(1, len(worked)):
                previous_t = worked[pos - 1]
                t_i = worked[pos]
                for lg_i in range(len(local_groups)):
                    current = y.get((le_i, lg_i, t_i))
                    start_var = group_start.get((le_i, lg_i, t_i))
                    if current is None or start_var is None:
                        continue
                    terms = [(start_var, 1.0), (current, -1.0)]
                    previous = y.get((le_i, lg_i, previous_t))
                    if previous is not None:
                        terms.append((previous, 1.0))
                    add_row(rows, cols, vals, lower, upper, terms, 0.0, math.inf)

        integrality = np.ones(var_id, dtype=np.int8)
        for start_var in start_vars:
            integrality[start_var] = 0
        matrix = coo_matrix((vals, (rows, cols)), shape=(len(lower), var_id)).tocsr()
        result = milp(
            c=np.array(costs),
            integrality=integrality,
            bounds=Bounds(np.zeros(var_id), np.ones(var_id)),
            constraints=LinearConstraint(matrix, np.array(lower), np.array(upper)),
            options={"time_limit": max(1.0, min(10.0, time_limit_per_site)), "mip_rel_gap": 0.03},
        )
        if result.x is None:
            return None
        return result, y

    def solve_group_assignment_global(
        task_records: list[tuple[int, int, str, str, list[tuple[int, int]], dict[int, tuple[tuple[int, int], ...]]]]
    ) -> tuple[Any, dict[tuple[int, int, int, int], int]] | None:
        y: dict[tuple[int, int, int, int], int] = {}
        group_start: dict[tuple[int, int, int, int], int] = {}
        half_group: dict[tuple[int, int, int, int], int] = {}
        day_group: dict[tuple[int, int, int], int] = {}
        mixed_group_day: dict[tuple[int, int], int] = {}
        costs: list[float] = []
        start_vars: set[int] = set()
        var_id = 0

        for task_i, (_, _, site, _, local_educators, chosen_work) in enumerate(task_records):
            local_groups = group_by_site[site]
            for le_i, (e_i, _) in enumerate(local_educators):
                segments = chosen_work[le_i]
                worked = [t_i for t_i in range(horizon_slots) if any(start <= t_i < end for start, end in segments)]
                for t_i in worked:
                    for lg_i, g_i in enumerate(local_groups):
                        cost = group_slot_cost(e_i, g_i)
                        if cost is None:
                            continue
                        y[(task_i, le_i, lg_i, t_i)] = var_id
                        costs.append(cost)
                        var_id += 1
                for t_i in worked[1:]:
                    for lg_i in range(len(local_groups)):
                        group_start[(task_i, le_i, lg_i, t_i)] = var_id
                        start_vars.add(var_id)
                        costs.append(group_switch_day_weight)
                        var_id += 1

        for e_i in range(len(bundle.educators)):
            for d_i in range(len(DAYS)):
                if max_weekly_group_exception_days is not None:
                    mixed_group_day[(e_i, d_i)] = var_id
                    costs.append(50.0)
                    var_id += 1
                for half_i in (0, 1):
                    for g_i in range(len(bundle.groups)):
                        half_group[(e_i, d_i, half_i, g_i)] = var_id
                        costs.append(0.0)
                        var_id += 1
                for g_i in range(len(bundle.groups)):
                    day_group[(e_i, d_i, g_i)] = var_id
                    costs.append(0.0)
                    var_id += 1

        if var_id == 0:
            return None

        rows: list[int] = []
        cols: list[int] = []
        vals: list[float] = []
        lower: list[float] = []
        upper: list[float] = []

        for task_i, (d_i, _, site, _, local_educators, chosen_work) in enumerate(task_records):
            local_groups = group_by_site[site]
            for le_i, (e_i, _) in enumerate(local_educators):
                segments = chosen_work[le_i]
                worked = [t_i for t_i in range(horizon_slots) if any(start <= t_i < end for start, end in segments)]
                for t_i in worked:
                    terms = [
                        (y[(task_i, le_i, lg_i, t_i)], 1.0)
                        for lg_i in range(len(local_groups))
                        if (task_i, le_i, lg_i, t_i) in y
                    ]
                    add_row(rows, cols, vals, lower, upper, terms, 1.0, 1.0)

                    half_i = 0 if t_i < split_slot else 1
                    for lg_i, g_i in enumerate(local_groups):
                        var = y.get((task_i, le_i, lg_i, t_i))
                        if var is None:
                            continue
                        add_row(
                            rows,
                            cols,
                            vals,
                            lower,
                            upper,
                            [(var, 1.0), (half_group[(e_i, d_i, half_i, g_i)], -1.0)],
                            -math.inf,
                            0.0,
                        )
                        add_row(
                            rows,
                            cols,
                            vals,
                            lower,
                            upper,
                            [(var, 1.0), (day_group[(e_i, d_i, g_i)], -1.0)],
                            -math.inf,
                            0.0,
                        )

                for half_i in (0, 1):
                    terms = [
                        (half_group[(e_i, d_i, half_i, g_i)], 1.0)
                        for g_i in range(len(bundle.groups))
                    ]
                    add_row(rows, cols, vals, lower, upper, terms, 0.0, 1.0)

                mixed_day = mixed_group_day.get((e_i, d_i))
                if mixed_day is not None:
                    terms = [
                        (day_group[(e_i, d_i, g_i)], 1.0)
                        for g_i in range(len(bundle.groups))
                    ]
                    terms.append((mixed_day, -1.0))
                    add_row(rows, cols, vals, lower, upper, terms, -math.inf, 1.0)

                worked_set = set(worked)
                for pos in range(1, len(worked)):
                    previous_t = worked[pos - 1]
                    t_i = worked[pos]
                    if previous_t not in worked_set:
                        continue
                    for lg_i in range(len(local_groups)):
                        current = y.get((task_i, le_i, lg_i, t_i))
                        start_var = group_start.get((task_i, le_i, lg_i, t_i))
                        if current is None or start_var is None:
                            continue
                        terms = [(start_var, 1.0), (current, -1.0)]
                        previous = y.get((task_i, le_i, lg_i, previous_t))
                        if previous is not None:
                            terms.append((previous, 1.0))
                        add_row(rows, cols, vals, lower, upper, terms, 0.0, math.inf)

            for lg_i, g_i in enumerate(local_groups):
                for t_i in range(horizon_slots):
                    demand = group_demand[(d_i, g_i, t_i)]
                    terms = [
                        (y[(task_i, le_i, lg_i, t_i)], 1.0)
                        for le_i in range(len(local_educators))
                        if (task_i, le_i, lg_i, t_i) in y
                    ]
                    add_row(rows, cols, vals, lower, upper, terms, demand, max(3, demand))

            for (demand_d_i, site_name, t_i), demand in site_demand.items():
                if demand_d_i != d_i or site_name != site:
                    continue
                terms = [
                    (var, 1.0)
                    for (var_task, _, _, var_t), var in y.items()
                    if var_task == task_i and var_t == t_i
                ]
                add_row(rows, cols, vals, lower, upper, terms, demand, math.inf)

        if max_weekly_group_exception_days is not None:
            for e_i in range(len(bundle.educators)):
                terms = [
                    (mixed_group_day[(e_i, d_i)], 1.0)
                    for d_i in range(len(DAYS))
                    if (e_i, d_i) in mixed_group_day
                ]
                if terms:
                    add_row(rows, cols, vals, lower, upper, terms, 0.0, float(max_weekly_group_exception_days))

        integrality = np.ones(var_id, dtype=np.int8)
        for start_var in start_vars:
            integrality[start_var] = 0

        matrix = coo_matrix((vals, (rows, cols)), shape=(len(lower), var_id)).tocsr()
        result = milp(
            c=np.array(costs),
            integrality=integrality,
            bounds=Bounds(np.zeros(var_id), np.ones(var_id)),
            constraints=LinearConstraint(matrix, np.array(lower), np.array(upper)),
            options={"time_limit": max(1.0, time_limit_per_site), "mip_rel_gap": 0.03},
        )
        if result.x is None:
            return None
        return result, y

    def solve_structured_patterns_global(
        tasks_to_solve: list[tuple[int, str, str, list[tuple[int, int]]]]
    ) -> dict[str, dict[str, list[dict[str, Any]]]] | None:
        pattern_owner: list[tuple[int, int, int]] = []
        pattern_segments: list[tuple[tuple[int, int], ...]] = []
        pattern_half_groups: list[dict[int, int]] = []
        pattern_mixed: list[int] = []
        pattern_costs: list[float] = []
        by_worker_day: dict[tuple[int, int], list[int]] = {}
        by_educator: dict[int, list[int]] = {}

        def add_pattern(
            *,
            task_i: int,
            le_i: int,
            e_i: int,
            d_i: int,
            day_key: str,
            segments: tuple[tuple[int, int], ...],
            half_groups: dict[int, int],
            base_cost: float,
        ) -> None:
            worked_slots = [
                t_i
                for start, end in segments
                for t_i in range(start, end)
            ]
            if not worked_slots:
                return
            group_cost = 0.0
            for t_i in worked_slots:
                half_i = 0 if t_i < split_slot else 1
                g_i = half_groups[half_i]
                slot_cost = group_slot_cost(e_i, g_i)
                if slot_cost is None:
                    return
                group_cost += slot_cost
            used_groups = {
                half_groups[0 if t_i < split_slot else 1]
                for t_i in worked_slots
            }
            mixed = 1 if len(used_groups) > 1 else 0
            switch_cost = group_switch_day_weight if mixed else 0.0
            pattern_id = len(pattern_owner)
            pattern_owner.append((task_i, le_i, e_i))
            pattern_segments.append(segments)
            pattern_half_groups.append(dict(half_groups))
            pattern_mixed.append(mixed)
            pattern_costs.append(base_cost + group_cost + switch_cost)
            by_worker_day.setdefault((task_i, le_i), []).append(pattern_id)
            by_educator.setdefault(e_i, []).append(pattern_id)

        for task_i, (d_i, day_key, site, local_educators) in enumerate(tasks_to_solve):
            local_groups = group_by_site[site]
            if not local_groups:
                return None
            for le_i, (e_i, daily_slots) in enumerate(local_educators):
                segment_options: list[tuple[tuple[tuple[int, int], ...], float]] = []
                for start in range(horizon_slots - daily_slots + 1):
                    segments = ((start, start + daily_slots),)
                    cost = work_pattern_cost(e_i, day_key, segments)
                    if cost is not None:
                        segment_options.append((segments, cost))

                segment_min = min(min_segment_slots, max(1, daily_slots // 2))
                if daily_slots >= 2 * segment_min:
                    for first_len in range(segment_min, daily_slots - segment_min + 1):
                        second_len = daily_slots - first_len
                        max_gap = horizon_slots - daily_slots
                        if max_split_gap_slots is not None:
                            max_gap = min(max_gap, max_split_gap_slots)
                        for gap in range(1, max_gap + 1):
                            latest_start = horizon_slots - daily_slots - gap
                            for first_start in range(latest_start + 1):
                                first_end = first_start + first_len
                                second_start = first_end + gap
                                segments = (
                                    (first_start, first_end),
                                    (second_start, second_start + second_len),
                                )
                                cost = work_pattern_cost(e_i, day_key, segments)
                                if cost is not None:
                                    segment_options.append((segments, cost))

                for segments, base_cost in segment_options:
                    worked_halves = {
                        0 if t_i < split_slot else 1
                        for start, end in segments
                        for t_i in range(start, end)
                    }
                    half_choices: dict[int, list[int]] = {}
                    for half_i in worked_halves:
                        allowed = [
                            g_i
                            for g_i in local_groups
                            if group_slot_cost(e_i, g_i) is not None
                        ]
                        if not allowed:
                            half_choices = {}
                            break
                        half_choices[half_i] = allowed
                    if not half_choices:
                        continue
                    if worked_halves == {0, 1}:
                        for morning_group in half_choices[0]:
                            for afternoon_group in half_choices[1]:
                                add_pattern(
                                    task_i=task_i,
                                    le_i=le_i,
                                    e_i=e_i,
                                    d_i=d_i,
                                    day_key=day_key,
                                    segments=segments,
                                    half_groups={0: morning_group, 1: afternoon_group},
                                    base_cost=base_cost,
                                )
                    else:
                        half_i = next(iter(worked_halves))
                        other_half = 1 - half_i
                        for group_i in half_choices[half_i]:
                            add_pattern(
                                task_i=task_i,
                                le_i=le_i,
                                e_i=e_i,
                                d_i=d_i,
                                day_key=day_key,
                                segments=segments,
                                half_groups={half_i: group_i, other_half: group_i},
                                base_cost=base_cost,
                            )

        if not pattern_owner:
            return None

        rows: list[int] = []
        cols: list[int] = []
        vals: list[float] = []
        lower: list[float] = []
        upper: list[float] = []

        for task_i, (_, _, _, local_educators) in enumerate(tasks_to_solve):
            for le_i in range(len(local_educators)):
                terms = [(pattern_id, 1.0) for pattern_id in by_worker_day.get((task_i, le_i), [])]
                if not terms:
                    return None
                add_row(rows, cols, vals, lower, upper, terms, 1.0, 1.0)

        for task_i, (d_i, _, site, local_educators) in enumerate(tasks_to_solve):
            local_groups = group_by_site[site]
            for g_i in local_groups:
                for t_i in range(horizon_slots):
                    demand = group_demand[(d_i, g_i, t_i)]
                    terms = []
                    for pattern_id, (owner_task, _, _) in enumerate(pattern_owner):
                        if owner_task != task_i:
                            continue
                        segments = pattern_segments[pattern_id]
                        if not any(start <= t_i < end for start, end in segments):
                            continue
                        half_i = 0 if t_i < split_slot else 1
                        if pattern_half_groups[pattern_id][half_i] == g_i:
                            terms.append((pattern_id, 1.0))
                    add_row(rows, cols, vals, lower, upper, terms, demand, max(3, demand))

            for (demand_d_i, site_name, t_i), demand in site_demand.items():
                if demand_d_i != d_i or site_name != site:
                    continue
                terms = []
                for pattern_id, (owner_task, _, _) in enumerate(pattern_owner):
                    if owner_task != task_i:
                        continue
                    if any(start <= t_i < end for start, end in pattern_segments[pattern_id]):
                        terms.append((pattern_id, 1.0))
                add_row(rows, cols, vals, lower, upper, terms, demand, math.inf)

        if max_weekly_group_exception_days is not None:
            for e_i in range(len(bundle.educators)):
                terms = [
                    (pattern_id, float(pattern_mixed[pattern_id]))
                    for pattern_id in by_educator.get(e_i, [])
                    if pattern_mixed[pattern_id]
                ]
                if terms:
                    add_row(rows, cols, vals, lower, upper, terms, 0.0, float(max_weekly_group_exception_days))

        matrix = coo_matrix((vals, (rows, cols)), shape=(len(lower), len(pattern_owner))).tocsr()
        result = milp(
            c=np.array(pattern_costs),
            integrality=np.ones(len(pattern_owner), dtype=np.int8),
            bounds=Bounds(np.zeros(len(pattern_owner)), np.ones(len(pattern_owner))),
            constraints=LinearConstraint(matrix, np.array(lower), np.array(upper)),
            options={"time_limit": max(30.0, time_limit_per_site * 4.0), "mip_rel_gap": 0.03},
        )
        if result.x is None:
            return None

        new_schedule = {
            educator: {day_key: list(blocks) for day_key, blocks in by_day.items()}
            for educator, by_day in original.items()
        }
        for _, day_key, _, local_educators in tasks_to_solve:
            for e_i, _ in local_educators:
                new_schedule[bundle.educators[e_i]["name"]][day_key] = []

        for pattern_id, value in enumerate(result.x):
            if value < 0.5:
                continue
            task_i, le_i, e_i = pattern_owner[pattern_id]
            d_i, day_key, _, _ = tasks_to_solve[task_i]
            educator_name = bundle.educators[e_i]["name"]
            current_group: int | None = None
            start_slot: int | None = None
            worked = {
                t_i
                for start, end in pattern_segments[pattern_id]
                for t_i in range(start, end)
            }
            for t_i in range(horizon_slots + 1):
                active_group: int | None = None
                if t_i in worked:
                    half_i = 0 if t_i < split_slot else 1
                    active_group = pattern_half_groups[pattern_id][half_i]
                if active_group != current_group:
                    if current_group is not None and start_slot is not None:
                        start_min = bundle.horizon.start + start_slot * bundle.horizon.step
                        end_min = bundle.horizon.start + t_i * bundle.horizon.step
                        group = bundle.groups[current_group]
                        new_schedule[educator_name][day_key].append(
                            {
                                "site": group["site"],
                                "group": group["name"],
                                "start": format_time(start_min),
                                "end": format_time(end_min),
                                "hours": round((end_min - start_min) / 60.0, 2),
                            }
                        )
                    current_group = active_group
                    start_slot = t_i if active_group is not None else None

        for by_day in new_schedule.values():
            for blocks in by_day.values():
                blocks.sort(key=lambda item: item["start"])
        return new_schedule

    def solve_free_day_patterns() -> dict[str, dict[str, list[dict[str, Any]]]] | None:
        max_daily_hours = float(bundle.data.get("rules_global", {}).get("max_daily_hours", 8.5))
        max_daily_slots = int(round(max_daily_hours / (bundle.horizon.step / 60.0)))
        min_daily_slots = 8
        weekly_base = float(bundle.data.get("rules_global", {}).get("max_weekly_hours", 40.0))
        group_demand_local, site_demand_local = build_demands_by_day(bundle.data, bundle.groups, bundle.horizon)
        known_types = {item["name"] for item in bundle.data.get("educator_types", [])}
        educator_types = [educator.get("type", "") for educator in bundle.educators]

        owner: list[tuple[int, int]] = []
        segments_by_pattern: list[tuple[tuple[int, int], ...]] = []
        half_groups_by_pattern: list[dict[int, int]] = []
        site_by_pattern: list[str | None] = []
        duration_by_pattern: list[int] = []
        mixed_by_pattern: list[int] = []
        costs: list[float] = []
        by_educator_day: dict[tuple[int, int], list[int]] = {}
        by_educator_patterns: dict[int, list[int]] = {}
        start_candidates: set[int] = {0}
        for rule in bundle.data.get("rules_site_schedule", []):
            for interval in rule.get("time_intervals", []):
                for value in (interval.get("start"), interval.get("end")):
                    if value:
                        try:
                            minute = parse_time(str(value))
                        except Exception:
                            continue
                        if bundle.horizon.start <= minute < bundle.horizon.end:
                            start_candidates.add((minute - bundle.horizon.start) // bundle.horizon.step)
        for raw_rule in bundle.data.get("rules_time", []):
            if len(raw_rule) < 6:
                continue
            for value in (raw_rule[4], raw_rule[5]):
                try:
                    minute = parse_time(str(value))
                except Exception:
                    continue
                if bundle.horizon.start <= minute < bundle.horizon.end:
                    start_candidates.add((minute - bundle.horizon.start) // bundle.horizon.step)
        for minute in range(bundle.horizon.start, bundle.horizon.end, 60):
            start_candidates.add((minute - bundle.horizon.start) // bundle.horizon.step)
        ordered_starts = sorted(slot for slot in start_candidates if 0 <= slot < horizon_slots)

        group_slot_cost_cache: dict[tuple[int, int], float | None] = {}

        def cached_group_cost(e_i: int, g_i: int) -> float | None:
            key = (e_i, g_i)
            if key not in group_slot_cost_cache:
                group_slot_cost_cache[key] = group_slot_cost(e_i, g_i)
            return group_slot_cost_cache[key]

        def add_day_pattern(
            *,
            e_i: int,
            d_i: int,
            site: str | None,
            segments: tuple[tuple[int, int], ...],
            half_groups: dict[int, int],
            duration_slots: int,
            cost: float,
        ) -> None:
            pattern_id = len(owner)
            owner.append((e_i, d_i))
            segments_by_pattern.append(segments)
            half_groups_by_pattern.append(dict(half_groups))
            site_by_pattern.append(site)
            duration_by_pattern.append(duration_slots)
            worked_slots = [
                t_i
                for start, end in segments
                for t_i in range(start, end)
            ]
            used_groups = {
                half_groups[0 if t_i < split_slot else 1]
                for t_i in worked_slots
            }
            mixed_by_pattern.append(1 if len(used_groups) > 1 else 0)
            costs.append(cost)
            by_educator_day.setdefault((e_i, d_i), []).append(pattern_id)
            by_educator_patterns.setdefault(e_i, []).append(pattern_id)

        for e_i, educator in enumerate(bundle.educators):
            educator_name = educator["name"]
            for d_i, (day_key, _) in enumerate(DAYS):
                off_cost = work_pattern_cost(e_i, day_key, ())
                if off_cost is not None:
                    add_day_pattern(
                        e_i=e_i,
                        d_i=d_i,
                        site=None,
                        segments=(),
                        half_groups={0: -1, 1: -1},
                        duration_slots=0,
                        cost=off_cost,
                    )

                for site in bundle.sites:
                    local_groups = group_by_site[site]
                    allowed_groups = [
                        g_i
                        for g_i in local_groups
                        if cached_group_cost(e_i, g_i) is not None
                    ]
                    if not allowed_groups:
                        continue
                    for daily_slots in range(min_daily_slots, max_daily_slots + 1, 2):
                        segment_options: list[tuple[tuple[tuple[int, int], ...], float]] = []
                        for start in ordered_starts:
                            if start + daily_slots > horizon_slots:
                                continue
                            segments = ((start, start + daily_slots),)
                            cost = work_pattern_cost(e_i, day_key, segments)
                            if cost is not None:
                                segment_options.append((segments, cost))

                        segment_min = min(min_segment_slots, max(1, daily_slots // 2))
                        if daily_slots >= 2 * segment_min:
                            split_gap_choices = [gap for gap in (2, 4, 6) if max_split_gap_slots is None or gap <= max_split_gap_slots]
                            for first_len in range(segment_min, daily_slots - segment_min + 1, 2):
                                second_len = daily_slots - first_len
                                first_end = split_slot
                                first_start = first_end - first_len
                                if first_start < 0:
                                    continue
                                for gap in split_gap_choices:
                                    second_start = first_end + gap
                                    second_end = second_start + second_len
                                    if second_end > horizon_slots:
                                        continue
                                    segments = (
                                        (first_start, first_end),
                                        (second_start, second_end),
                                    )
                                    cost = work_pattern_cost(e_i, day_key, segments)
                                    if cost is not None:
                                        segment_options.append((segments, cost))

                        for segments, base_cost in segment_options:
                            worked_slots = [
                                t_i
                                for start, end in segments
                                for t_i in range(start, end)
                            ]
                            worked_halves = {0 if t_i < split_slot else 1 for t_i in worked_slots}
                            if worked_halves == {0, 1}:
                                for morning_group in allowed_groups:
                                    for afternoon_group in allowed_groups:
                                        group_cost = 0.0
                                        for t_i in worked_slots:
                                            g_i = morning_group if t_i < split_slot else afternoon_group
                                            slot_cost = cached_group_cost(e_i, g_i)
                                            if slot_cost is None:
                                                group_cost = math.inf
                                                break
                                            group_cost += slot_cost
                                        if math.isinf(group_cost):
                                            continue
                                        switch_cost = group_switch_day_weight if morning_group != afternoon_group else 0.0
                                        add_day_pattern(
                                            e_i=e_i,
                                            d_i=d_i,
                                            site=site,
                                            segments=segments,
                                            half_groups={0: morning_group, 1: afternoon_group},
                                            duration_slots=daily_slots,
                                            cost=base_cost + group_cost + switch_cost,
                                        )
                            else:
                                half_i = next(iter(worked_halves))
                                other_half = 1 - half_i
                                for group_i in allowed_groups:
                                    group_cost = 0.0
                                    for t_i in worked_slots:
                                        slot_cost = cached_group_cost(e_i, group_i)
                                        if slot_cost is None:
                                            group_cost = math.inf
                                            break
                                        group_cost += slot_cost
                                    if math.isinf(group_cost):
                                        continue
                                    add_day_pattern(
                                        e_i=e_i,
                                        d_i=d_i,
                                        site=site,
                                        segments=segments,
                                        half_groups={half_i: group_i, other_half: group_i},
                                        duration_slots=daily_slots,
                                        cost=base_cost + group_cost,
                                    )

        if not owner:
            return None

        rows: list[int] = []
        cols: list[int] = []
        vals: list[float] = []
        lower: list[float] = []
        upper: list[float] = []

        for e_i in range(len(bundle.educators)):
            for d_i in range(len(DAYS)):
                terms = [(pattern_id, 1.0) for pattern_id in by_educator_day.get((e_i, d_i), [])]
                if not terms:
                    return None
                add_row(rows, cols, vals, lower, upper, terms, 1.0, 1.0)

        for e_i, educator in enumerate(bundle.educators):
            target_slots = int(round((float(educator["percentage"]) / 100.0) * weekly_base / (bundle.horizon.step / 60.0)))
            terms = [
                (pattern_id, float(duration_by_pattern[pattern_id]))
                for pattern_id in by_educator_patterns.get(e_i, [])
            ]
            add_row(rows, cols, vals, lower, upper, terms, float(target_slots), float(target_slots))

        for d_i, (day_key, _) in enumerate(DAYS):
            for g_i in range(len(bundle.groups)):
                for t_i in range(horizon_slots):
                    demand = group_demand_local[(d_i, g_i, t_i)]
                    terms = []
                    for pattern_id, (_, pattern_day) in enumerate(owner):
                        if pattern_day != d_i:
                            continue
                        if not any(start <= t_i < end for start, end in segments_by_pattern[pattern_id]):
                            continue
                        half_i = 0 if t_i < split_slot else 1
                        if half_groups_by_pattern[pattern_id][half_i] == g_i:
                            terms.append((pattern_id, 1.0))
                    add_row(rows, cols, vals, lower, upper, terms, demand, max(3, demand))

            for (demand_d_i, site, t_i), demand in site_demand_local.items():
                if demand_d_i != d_i:
                    continue
                terms = []
                for pattern_id, (_, pattern_day) in enumerate(owner):
                    if pattern_day != d_i or site_by_pattern[pattern_id] != site:
                        continue
                    if any(start <= t_i < end for start, end in segments_by_pattern[pattern_id]):
                        terms.append((pattern_id, 1.0))
                add_row(rows, cols, vals, lower, upper, terms, demand, math.inf)

        if max_weekly_group_exception_days is not None:
            for e_i in range(len(bundle.educators)):
                terms = [
                    (pattern_id, float(mixed_by_pattern[pattern_id]))
                    for pattern_id in by_educator_patterns.get(e_i, [])
                    if mixed_by_pattern[pattern_id]
                ]
                if terms:
                    add_row(rows, cols, vals, lower, upper, terms, 0.0, float(max_weekly_group_exception_days))

        for raw_rule in bundle.data.get("rules_percentage", []):
            if len(raw_rule) < 4:
                continue
            raw_types, minmax, value, site = raw_rule[:4]
            wanted_types, _ = split_types(list(raw_types), DEFAULT_TYPE_ALIASES, known_types)
            pct = float(value)
            terms_by_var: dict[int, float] = {}
            for pattern_id, (e_i, _) in enumerate(owner):
                if site_by_pattern[pattern_id] != site:
                    continue
                coeff = -pct * duration_by_pattern[pattern_id]
                if educator_types[e_i] in wanted_types:
                    coeff += 100.0 * duration_by_pattern[pattern_id]
                terms_by_var[pattern_id] = terms_by_var.get(pattern_id, 0.0) + coeff
            terms = list(terms_by_var.items())
            if normalize_flag(minmax) == "min":
                add_row(rows, cols, vals, lower, upper, terms, 0.0, math.inf)
            else:
                add_row(rows, cols, vals, lower, upper, terms, -math.inf, 0.0)

        matrix = coo_matrix((vals, (rows, cols)), shape=(len(lower), len(owner))).tocsr()
        result = milp(
            c=np.zeros(len(owner)),
            integrality=np.ones(len(owner), dtype=np.int8),
            bounds=Bounds(np.zeros(len(owner)), np.ones(len(owner))),
            constraints=LinearConstraint(matrix, np.array(lower), np.array(upper)),
            options={"time_limit": max(60.0, time_limit_per_site * 8.0), "mip_rel_gap": 0.03},
        )
        if result.x is None:
            return None

        new_schedule = {
            educator["name"]: {day_key: [] for day_key, _ in DAYS}
            for educator in bundle.educators
        }
        for pattern_id, value in enumerate(result.x):
            if value < 0.5 or duration_by_pattern[pattern_id] == 0:
                continue
            e_i, d_i = owner[pattern_id]
            day_key = DAYS[d_i][0]
            educator_name = bundle.educators[e_i]["name"]
            worked = {
                t_i
                for start, end in segments_by_pattern[pattern_id]
                for t_i in range(start, end)
            }
            current_group: int | None = None
            start_slot: int | None = None
            for t_i in range(horizon_slots + 1):
                active_group: int | None = None
                if t_i in worked:
                    half_i = 0 if t_i < split_slot else 1
                    active_group = half_groups_by_pattern[pattern_id][half_i]
                if active_group != current_group:
                    if current_group is not None and start_slot is not None:
                        start_min = bundle.horizon.start + start_slot * bundle.horizon.step
                        end_min = bundle.horizon.start + t_i * bundle.horizon.step
                        group = bundle.groups[current_group]
                        new_schedule[educator_name][day_key].append(
                            {
                                "site": group["site"],
                                "group": group["name"],
                                "start": format_time(start_min),
                                "end": format_time(end_min),
                                "hours": round((end_min - start_min) / 60.0, 2),
                            }
                        )
                    current_group = active_group
                    start_slot = t_i if active_group is not None else None

        for by_day in new_schedule.values():
            for blocks in by_day.values():
                blocks.sort(key=lambda item: item["start"])
        return new_schedule

    tasks: list[tuple[int, str, str, list[tuple[int, int]]]] = []
    for d_i, (day_key, _) in enumerate(DAYS):
        for site in bundle.sites:
            local_educators = [
                (e_i, slots)
                for e_i in range(len(bundle.educators))
                for used_site, slots in [macro[(e_i, d_i)]]
                if used_site == site and slots > 0
            ]
            if local_educators:
                tasks.append((d_i, day_key, site, local_educators))

    schedule = original
    total_tasks = len(tasks)
    if tasks:
        if progress_callback:
            progress_callback(0, total_tasks, "Structuration globale blocs/groupes")
        structured_schedule = solve_structured_patterns_global(tasks)
        if structured_schedule is not None:
            if progress_callback:
                progress_callback(total_tasks, total_tasks, "Structuration globale terminee")
            return structured_schedule
        bundle.warnings.append("Structuration globale blocs/groupes introuvable: ancien lissage utilise.")
        enable_expensive_free_search = False
        if enable_expensive_free_search and progress_callback:
            progress_callback(0, total_tasks, "Recherche globale par modeles de journee")
        if enable_expensive_free_search:
            free_schedule = solve_free_day_patterns()
            if free_schedule is not None:
                if progress_callback:
                    progress_callback(total_tasks, total_tasks, "Recherche globale terminee")
                bundle.warnings.append("Planning reconstruit par modeles de journee.")
                return free_schedule
            bundle.warnings.append("Recherche globale par modeles de journee introuvable.")

    task_records: list[tuple[int, str, str, str, list[tuple[int, int]], dict[int, tuple[tuple[int, int], ...]]]] = []
    for task_i, (d_i, day_key, site, local_educators) in enumerate(tasks):
        if progress_callback:
            progress_callback(task_i, total_tasks, f"Blocs {day_key} / {site}")
        chosen_work, _ = solve_work_patterns(local_educators, site, d_i, day_key)
        if chosen_work is None:
            bundle.warnings.append(f"Lissage ignore {day_key} / {site}: blocs de presence introuvables.")
            if progress_callback:
                progress_callback(task_i + 1, total_tasks, f"Lissage ignore {day_key} / {site}")
            continue
        task_records.append((d_i, day_key, site, site, local_educators, chosen_work))
        if progress_callback:
            progress_callback(task_i + 1, total_tasks, f"Blocs termines {day_key} / {site}")

    if not task_records:
        return schedule

    if progress_callback:
        progress_callback(total_tasks, total_tasks, "Affectation globale des groupes")
    group_solution = solve_group_assignment_global(task_records)
    if group_solution is None:
        bundle.warnings.append("Affectation globale des groupes introuvable: lissage par jour conserve.")
        for task_i, (_, day_key, site, local_educators, chosen_work) in enumerate(
            (record[0], record[1], record[2], record[4], record[5]) for record in task_records
        ):
            group_solution_local = solve_group_assignment(local_educators, site, d_i, chosen_work)
            if group_solution_local is None:
                continue
            result, local_y = group_solution_local
            local_groups = group_by_site[site]
            for e_i, _ in local_educators:
                schedule[bundle.educators[e_i]["name"]][day_key] = []
            for le_i, (e_i, _) in enumerate(local_educators):
                educator_name = bundle.educators[e_i]["name"]
                current_group: int | None = None
                start_slot: int | None = None
                for t_i in range(horizon_slots + 1):
                    active_group: int | None = None
                    if t_i < horizon_slots:
                        for lg_i, g_i in enumerate(local_groups):
                            var = local_y.get((le_i, lg_i, t_i))
                            if var is not None and result.x[var] >= 0.5:
                                active_group = g_i
                                break
                    if active_group != current_group:
                        if current_group is not None and start_slot is not None:
                            start_min = bundle.horizon.start + start_slot * bundle.horizon.step
                            end_min = bundle.horizon.start + t_i * bundle.horizon.step
                            group = bundle.groups[current_group]
                            schedule[educator_name][day_key].append(
                                {
                                    "site": group["site"],
                                    "group": group["name"],
                                    "start": format_time(start_min),
                                    "end": format_time(end_min),
                                    "hours": round((end_min - start_min) / 60.0, 2),
                                }
                            )
                        current_group = active_group
                        start_slot = t_i if active_group is not None else None
                schedule[educator_name][day_key].sort(key=lambda item: item["start"])
        return schedule

    result, y = group_solution
    for task_i, (_, day_key, site, _, local_educators, _) in enumerate(task_records):
        local_groups = group_by_site[site]
        for e_i, _ in local_educators:
            schedule[bundle.educators[e_i]["name"]][day_key] = []
        for le_i, (e_i, _) in enumerate(local_educators):
            educator_name = bundle.educators[e_i]["name"]
            current_group: int | None = None
            start_slot: int | None = None
            for t_i in range(horizon_slots + 1):
                active_group: int | None = None
                if t_i < horizon_slots:
                    for lg_i, g_i in enumerate(local_groups):
                        var = y.get((task_i, le_i, lg_i, t_i))
                        if var is not None and result.x[var] >= 0.5:
                            active_group = g_i
                            break
                if active_group != current_group:
                    if current_group is not None and start_slot is not None:
                        start_min = bundle.horizon.start + start_slot * bundle.horizon.step
                        end_min = bundle.horizon.start + t_i * bundle.horizon.step
                        group = bundle.groups[current_group]
                        schedule[educator_name][day_key].append(
                            {
                                "site": group["site"],
                                "group": group["name"],
                                "start": format_time(start_min),
                                "end": format_time(end_min),
                                "hours": round((end_min - start_min) / 60.0, 2),
                            }
                        )
                    current_group = active_group
                    start_slot = t_i if active_group is not None else None
            schedule[educator_name][day_key].sort(key=lambda item: item["start"])
    if progress_callback:
        progress_callback(total_tasks, total_tasks, "Affectation globale terminee")

    return schedule


def hard_half_day_group_errors(
    schedule: dict[str, dict[str, list[dict[str, Any]]]],
    horizon: Horizon,
    *,
    half_day_split_time: str = "12:30",
    max_weekly_group_exception_days: int | None = 1,
    attends_colloque_by_name: dict[str, bool] | None = None,
) -> list[str]:
    errors: list[str] = []
    split_slot = split_slot_for_horizon(horizon, half_day_split_time)
    split_min = horizon.start + split_slot * horizon.step
    attends_colloque_by_name = attends_colloque_by_name or {}

    for educator_name, by_day in schedule.items():
        for day_key, blocks in by_day.items():
            morning_groups: set[str] = set()
            afternoon_groups: set[str] = set()
            for block in blocks:
                if block.get("activity") in {"colloque", "remplacement_colloque"}:
                    continue
                start_min = parse_time(block["start"])
                end_min = parse_time(block["end"])
                if start_min < split_min and end_min > horizon.start:
                    morning_groups.add(block["group"])
                if start_min < horizon.end and end_min > split_min:
                    afternoon_groups.add(block["group"])
            if len(morning_groups) > 1:
                errors.append(
                    f"Changement de groupe interdit le matin: "
                    f"{educator_name} {day_key} {sorted(morning_groups)}."
                )
            if len(afternoon_groups) > 1:
                errors.append(
                    f"Changement de groupe interdit l'apres-midi: "
                    f"{educator_name} {day_key} {sorted(afternoon_groups)}."
                )

        if (
            max_weekly_group_exception_days is not None
            and attends_colloque_by_name.get(educator_name, True)
        ):
            exception_days = [
                day_key
                for day_key, blocks in by_day.items()
                if len(
                    {
                        block["group"]
                        for block in blocks
                        if block.get("activity") not in {"colloque", "remplacement_colloque"}
                    }
                )
                > 1
            ]
            if len(exception_days) > max_weekly_group_exception_days:
                errors.append(
                    f"Trop de jours avec changement de groupe pour {educator_name}: "
                    f"{len(exception_days)} > {max_weekly_group_exception_days} "
                    f"(jours: {', '.join(exception_days)})."
                )
    return errors


def verify_solution(
    bundle: SolveBundle,
    schedule: dict[str, dict[str, list[dict[str, Any]]]],
    *,
    half_day_split_time: str = "12:30",
    max_weekly_group_exception_days: int | None = 1,
    max_split_gap_minutes: int | None = 90,
    hard_max_work_days: bool = True,
    weekly_hours_tolerance_percent: float = 3.0,
    weekly_hours_tolerance_minutes: int | None = None,
    weekly_hours_tolerance_step_minutes: int | None = 15,
    enforce_absolute_max_weekly_hours: bool = True,
    absolute_max_weekly_hours: float | None = 40.0,
    the_enabled: bool = True,
    the_percent: float = 10.0,
    the_colloques_count: bool = True,
    primary_groups_by_educator: dict[str, str] | None = None,
    quality_profile: str = "equilibre",
    quality_profile_label: str = "Equilibre",
    primary_group_report_enabled: bool = True,
    primary_group_warning_outside_hours: float = 4.0,
    primary_group_warning_outside_days: int = 1,
) -> dict[str, Any]:
    data = bundle.data
    primary_groups_by_educator = dict(primary_groups_by_educator or {})
    by_educator: dict[str, float] = {}
    child_hours_by_educator: dict[str, float] = {}
    colloque_the_hours_by_educator: dict[str, float] = {}
    invisible_the_hours_by_educator: dict[str, float] = {}
    total_the_hours_by_educator: dict[str, float] = {}
    worked_days_by_educator: dict[str, int] = {}
    by_site: dict[str, float] = {site: 0.0 for site in bundle.sites}
    by_site_type: dict[str, dict[str, float]] = {site: {} for site in bundle.sites}
    hard_errors: list[str] = []
    soft_warnings: list[str] = []

    type_by_name = {educator["name"]: educator.get("type", "") for educator in bundle.educators}
    weekly_base = float(data.get("rules_global", {}).get("max_weekly_hours", 40.0))
    max_daily_hours = float(data.get("rules_global", {}).get("max_daily_hours", 8.5))

    for educator in bundle.educators:
        name = educator["name"]
        total = 0.0
        child_total = 0.0
        colloque_the_total = 0.0
        worked_days = 0
        for day_key, blocks in schedule[name].items():
            visible_daily = sum(float(block["hours"]) for block in blocks)
            child_daily = sum(
                float(block["hours"])
                for block in blocks
                if block.get("activity") != "colloque"
            )
            colloque_daily = sum(
                float(block["hours"])
                for block in blocks
                if block.get("activity") == "colloque"
            )
            child_total += child_daily
            colloque_the_total += colloque_daily if the_colloques_count else 0.0
            if visible_daily > 1e-6:
                worked_days += 1
            if visible_daily > max_daily_hours + 1e-6:
                hard_errors.append(f"{name} {day_key}: {visible_daily:.2f}h > {max_daily_hours:.2f}h")
            for block in blocks:
                if block.get("activity") == "colloque":
                    continue
                site = block["site"]
                hours = float(block["hours"])
                by_site[site] = by_site.get(site, 0.0) + hours
                educator_type = type_by_name[name]
                by_site_type[site][educator_type] = by_site_type[site].get(educator_type, 0.0) + hours
            if max_split_gap_minutes is not None and len(blocks) > 1:
                sorted_blocks = sorted(blocks, key=lambda item: parse_time(item["start"]))
                for previous, current in zip(sorted_blocks, sorted_blocks[1:]):
                    gap = parse_time(current["start"]) - parse_time(previous["end"])
                    if gap > max_split_gap_minutes:
                        hard_errors.append(
                            f"{name} {day_key}: coupure de {gap} minutes > {max_split_gap_minutes} minutes "
                            f"({previous['end']}-{current['start']})"
                        )
        child_hours_by_educator[name] = round(child_total, 2)
        colloque_the_hours_by_educator[name] = round(colloque_the_total, 2)
        worked_days_by_educator[name] = worked_days

    step_hours = bundle.horizon.step / 60.0
    weekly_target_slots = {
        educator["name"]: int(round((float(educator["percentage"]) / 100.0 * weekly_base) / step_hours))
        for educator in bundle.educators
    }
    weekly_targets = {
        name: round(target_slots * step_hours, 2)
        for name, target_slots in weekly_target_slots.items()
    }
    weekly_the_targets: dict[str, float] = {}
    for educator in bundle.educators:
        name = educator["name"]
        target_slots = weekly_target_slots[name]
        the_slots = the_target_slots(target_slots, the_percent, enabled=the_enabled)
        the_target = the_slots * bundle.horizon.step / 60.0
        visible_the = colloque_the_hours_by_educator.get(name, 0.0)
        invisible_the = max(0.0, the_target - visible_the)
        total_the = visible_the + invisible_the
        total = child_hours_by_educator.get(name, 0.0) + total_the
        weekly_the_targets[name] = round(the_target, 2)
        invisible_the_hours_by_educator[name] = round(invisible_the, 2)
        total_the_hours_by_educator[name] = round(total_the, 2)
        by_educator[name] = round(total, 2)
    target_work_days = {
        name: int(math.ceil(target / max_daily_hours - 1e-9)) if target > 0 else 0
        for name, target in weekly_targets.items()
    }
    max_work_days = {
        educator["name"]: max_work_days_for_educator(educator, weekly_base, max_daily_hours)
        for educator in bundle.educators
    }
    work_day_errors = [
        f"{name}: {worked_days_by_educator[name]} jours travailles > maximum {max_work_days[name]}"
        for name in worked_days_by_educator
        if hard_max_work_days and worked_days_by_educator[name] > max_work_days[name]
    ]
    work_day_warnings = [
        f"{name}: {worked_days_by_educator[name]} jours travailles > maximum souhaite {max_work_days[name]}"
        for name in worked_days_by_educator
        if not hard_max_work_days and worked_days_by_educator[name] > max_work_days[name]
    ]
    weekly_tolerance_slots_by_name: dict[str, int] = {}
    weekly_tolerances: dict[str, float] = {}
    for educator in bundle.educators:
        name = educator["name"]
        tolerance_slots = weekly_tolerance_slots(
            weekly_targets[name],
            bundle.horizon,
            percent=weekly_hours_tolerance_percent,
            minutes=weekly_hours_tolerance_minutes,
            step_minutes=weekly_hours_tolerance_step_minutes,
        )
        weekly_tolerance_slots_by_name[name] = tolerance_slots
        weekly_tolerances[name] = round(tolerance_slots * bundle.horizon.step / 60.0, 2)
    weekly_errors = [
        f"{name}: {actual:.2f}h hors tolerance autour de {weekly_targets[name]:.2f}h "
        f"(+/- {weekly_tolerances[name]:.2f}h)"
        for name, actual in by_educator.items()
        if abs(actual - weekly_targets[name]) > weekly_tolerances[name] + 1e-6
    ]
    weekly_max_errors: list[str] = []
    if enforce_absolute_max_weekly_hours and absolute_max_weekly_hours is not None:
        weekly_max_errors = [
            f"{name}: {actual:.2f}h > maximum absolu {float(absolute_max_weekly_hours):.2f}h"
            for name, actual in by_educator.items()
            if actual > float(absolute_max_weekly_hours) + 1e-6
        ]

    percentage_report: list[dict[str, Any]] = []
    aliases = DEFAULT_TYPE_ALIASES
    known_types = {item["name"] for item in data.get("educator_types", [])}
    for raw_rule in data.get("rules_percentage", []):
        raw_types, minmax, value, site = raw_rule[:4]
        wanted_types, _ = split_types(list(raw_types), aliases, known_types)
        total = by_site.get(site, 0.0)
        matching = sum(by_site_type.get(site, {}).get(item, 0.0) for item in wanted_types)
        actual_pct = 0.0 if total == 0 else matching / total * 100.0
        ok = actual_pct + 1e-6 >= value if normalize_flag(minmax) == "min" else actual_pct <= value + 1e-6
        percentage_report.append(
            {
                "site": site,
                "types": sorted(wanted_types),
                "rule": minmax,
                "target_percent": value,
                "actual_percent": round(actual_pct, 2),
                "ok": ok,
            }
        )

    group_demand, site_demand = build_demands_by_day(data, bundle.groups, bundle.horizon)
    group_by_name = {group["name"]: i for i, group in enumerate(bundle.groups)}
    coverage_errors: list[str] = []
    for d_i, (day_key, day_label) in enumerate(DAYS):
        counts = {
            (g_i, t_i): 0
            for g_i in range(len(bundle.groups))
            for t_i in range(bundle.horizon.slots)
        }
        for educator_blocks in schedule.values():
            for block in educator_blocks[day_key]:
                if block.get("activity") == "colloque":
                    continue
                g_i = group_by_name[block["group"]]
                start_slot = (parse_time(block["start"]) - bundle.horizon.start) // bundle.horizon.step
                end_slot = (parse_time(block["end"]) - bundle.horizon.start) // bundle.horizon.step
                for t_i in range(start_slot, end_slot):
                    counts[(g_i, t_i)] += 1
        for g_i, group in enumerate(bundle.groups):
            for t_i in range(bundle.horizon.slots):
                actual = counts[(g_i, t_i)]
                demand = group_demand[(d_i, g_i, t_i)]
                maximum = max(3, demand)
                if actual < demand:
                    when = format_time(bundle.horizon.start + t_i * bundle.horizon.step)
                    coverage_errors.append(f"{day_label} {group['name']} {when}: {actual} < {demand}")
                if actual > maximum:
                    when = format_time(bundle.horizon.start + t_i * bundle.horizon.step)
                    coverage_errors.append(f"{day_label} {group['name']} {when}: {actual} > {maximum}")
        for (demand_d_i, site, t_i), demand in site_demand.items():
            if demand_d_i != d_i:
                continue
            actual = sum(
                counts[(g_i, t_i)]
                for g_i, group in enumerate(bundle.groups)
                if group["site"] == site
            )
            if actual < demand:
                when = format_time(bundle.horizon.start + t_i * bundle.horizon.step)
                coverage_errors.append(f"{day_label} {site} {when}: {actual} < {demand}")

    hard_rule_errors: list[str] = []
    group_structure_errors: list[str] = []
    primary_group_errors: list[str] = []
    attends_colloque_by_name = {
        educator["name"]: educator_attends_colloque(educator)
        for educator in bundle.educators
    }

    for raw_rule in data.get("rules_time", []):
        if len(raw_rule) < 6:
            continue
        pref_type, strength, educator_name, day_name, start, end = raw_rule[:6]
        if normalize_flag(strength) != "hard" or educator_name not in schedule:
            continue
        day_key = normalize_day(day_name)
        if day_key not in schedule[educator_name]:
            continue
        start_min = max(parse_time(str(start)), bundle.horizon.start)
        end_min = min(parse_time(str(end)), bundle.horizon.end)
        if end_min <= start_min:
            continue
        overlaps = []
        for block in schedule[educator_name][day_key]:
            block_start = parse_time(block["start"])
            block_end = parse_time(block["end"])
            if block_start < end_min and block_end > start_min:
                overlaps.append(block)
        is_negative = normalize_flag(pref_type) in {"negatif", "negative", "neg"}
        if is_negative and overlaps:
            hard_rule_errors.append(
                f"Regle hard violee: {educator_name} travaille {day_key} "
                f"{format_time(start_min)}-{format_time(end_min)} malgre une interdiction."
            )
        if not is_negative and not overlaps:
            hard_rule_errors.append(
                f"Regle hard violee: {educator_name} ne travaille pas {day_key} "
                f"{format_time(start_min)}-{format_time(end_min)} malgre une obligation de presence."
            )

    hard_rule_errors.extend(
        hard_primary_group_rule_errors(data, primary_groups_by_educator)
    )

    explicit_main_group: dict[str, str] = {}
    soft_main_group: dict[str, str] = {}
    for raw_rule in data.get("rules_group", []):
        if len(raw_rule) < 4:
            continue
        pref_type, strength, educator_name, group_name = raw_rule[:4]
        if normalize_flag(pref_type) in {"negatif", "negative", "neg"}:
            continue
        if normalize_flag(strength) == "hard":
            explicit_main_group.setdefault(educator_name, group_name)
        else:
            soft_main_group.setdefault(educator_name, group_name)

    group_structure_errors.extend(
        hard_half_day_group_errors(
            schedule,
            bundle.horizon,
            half_day_split_time=half_day_split_time,
            max_weekly_group_exception_days=max_weekly_group_exception_days,
            attends_colloque_by_name=attends_colloque_by_name,
        )
    )

    if primary_groups_by_educator:
        colloque_warnings: list[str] = []
        colloque_by_group_name = {
            str(colloque["group"]): colloque
            for colloque in parse_colloques(data, bundle.horizon, bundle.groups, colloque_warnings)
        }
        soft_warnings.extend(colloque_warnings)
        for educator in bundle.educators:
            educator_name = educator["name"]
            if not educator_attends_colloque(educator):
                continue
            primary_group_name = primary_groups_by_educator.get(educator_name)
            if not primary_group_name:
                primary_group_errors.append(f"{educator_name}: aucun groupe principal choisi.")
                continue
            colloque = colloque_by_group_name.get(primary_group_name)
            if not colloque:
                soft_warnings.append(
                    f"{educator_name}: groupe principal {primary_group_name} sans colloque defini."
                )
                continue
            day_key = str(colloque["day"])
            required_slots = set(colloque["slots"])
            present_slots: set[int] = set()
            for block in schedule.get(educator_name, {}).get(day_key, []):
                if block.get("activity") not in {"colloque", "remplacement_colloque"}:
                    if block.get("group") != primary_group_name:
                        primary_group_errors.append(
                            f"{educator_name}: le jour du colloque {day_key}, travaille en "
                            f"{block.get('group')} au lieu de {primary_group_name}."
                        )
                    continue
                if block.get("activity") != "colloque" or block.get("group") != primary_group_name:
                    continue
                start_slot = (parse_time(block["start"]) - bundle.horizon.start) // bundle.horizon.step
                end_slot = (parse_time(block["end"]) - bundle.horizon.start) // bundle.horizon.step
                present_slots.update(range(start_slot, end_slot))
            if not required_slots.issubset(present_slots):
                primary_group_errors.append(
                    f"{educator_name}: colloque incomplet pour {primary_group_name} "
                    f"({colloque['day']} {format_time(bundle.horizon.start + int(colloque['start_slot']) * bundle.horizon.step)}-"
                    f"{format_time(bundle.horizon.start + int(colloque['end_slot']) * bundle.horizon.step)})."
                )

    percentage_errors = [
        f"Pourcentage invalide: {item}"
        for item in percentage_report
        if not item["ok"]
    ]
    all_hard_errors = (
        hard_errors
        + weekly_errors
        + weekly_max_errors
        + work_day_errors
        + coverage_errors
        + hard_rule_errors
        + group_structure_errors
        + primary_group_errors
        + percentage_errors
    )
    report_primary_groups_by_educator = {
        educator_name: group_name
        for educator_name, group_name in primary_groups_by_educator.items()
        if attends_colloque_by_name.get(educator_name, True)
    }
    quality_summary = build_quality_summary(
        bundle,
        schedule,
        profile_name=quality_profile,
        profile_label=quality_profile_label,
        hard_error_count=len(all_hard_errors),
        soft_warning_count=len(soft_warnings),
        max_split_gap_minutes=max_split_gap_minutes,
        max_weekly_group_exception_days=max_weekly_group_exception_days,
        primary_groups_by_educator=report_primary_groups_by_educator,
        primary_group_report_enabled=primary_group_report_enabled,
        primary_group_warning_outside_hours=primary_group_warning_outside_hours,
        primary_group_warning_outside_days=primary_group_warning_outside_days,
    )

    return {
        "hours_by_educator": by_educator,
        "weekly_targets": weekly_targets,
        "child_hours_by_educator": child_hours_by_educator,
        "weekly_the_targets": weekly_the_targets,
        "colloque_the_hours_by_educator": colloque_the_hours_by_educator,
        "invisible_the_hours_by_educator": invisible_the_hours_by_educator,
        "total_the_hours_by_educator": total_the_hours_by_educator,
        "worked_days_by_educator": worked_days_by_educator,
        "primary_groups_by_educator": primary_groups_by_educator,
        "primary_group_errors": primary_group_errors,
        "target_work_days": target_work_days,
        "max_work_days": max_work_days,
        "work_day_errors": work_day_errors,
        "work_day_warnings": work_day_warnings,
        "weekly_tolerances": weekly_tolerances,
        "weekly_max_errors": weekly_max_errors,
        "hours_by_site": {site: round(hours, 2) for site, hours in by_site.items()},
        "hours_by_site_type": {
            site: {kind: round(hours, 2) for kind, hours in values.items()}
            for site, values in by_site_type.items()
        },
        "percentage_rules": percentage_report,
        "coverage_errors": coverage_errors,
        "hard_rule_errors": hard_rule_errors,
        "group_structure_errors": group_structure_errors,
        "quality_rule_errors": group_structure_errors,
        "quality_profile": quality_summary["profile"],
        "quality_summary": quality_summary,
        "soft_warnings": soft_warnings,
        "alerts": soft_warnings,
        "hard_errors": all_hard_errors,
        "errors": all_hard_errors,
    }


def make_payload(
    bundle: SolveBundle,
    *,
    smooth: bool = False,
    smooth_time_limit: float = 8.0,
    split_shift_weight: float = 120.0,
    split_gap_weight: float = 4.0,
    max_split_gap_minutes: int | None = 90,
    group_switch_day_weight: float = 8.0,
    same_group_week_weight: float = 0.4,
    half_day_split_time: str = "12:30",
    max_weekly_group_exception_days: int | None = 1,
    progress_callback: Callable[[int, str], None] | None = None,
    progress_start: int = 60,
    progress_end: int = 95,
    weekly_hours_tolerance_percent: float = 1.0,
) -> dict[str, Any]:
    if not bundle.result.success or bundle.result.x is None:
        return {
            "status": "infeasible_or_not_solved",
            "solver_message": bundle.result.message,
            "warnings": bundle.warnings,
            "diagnostics": diagnose_basic_conflicts(bundle.data, bundle.horizon),
        }
    raw_schedule = build_schedule(bundle)
    if smooth:
        def smooth_progress(done: int, total: int, message: str) -> None:
            if progress_callback:
                span = max(0, progress_end - progress_start)
                percent = progress_start + int(span * done / max(1, total))
                progress_callback(percent, message)

        schedule = smooth_schedule(
            bundle,
            time_limit_per_site=smooth_time_limit,
            split_shift_weight=split_shift_weight,
            split_gap_weight=split_gap_weight,
            max_split_gap_minutes=max_split_gap_minutes,
            group_switch_day_weight=group_switch_day_weight,
            same_group_week_weight=same_group_week_weight,
            half_day_split_time=half_day_split_time,
            max_weekly_group_exception_days=max_weekly_group_exception_days,
            progress_callback=smooth_progress,
        )
    else:
        schedule = raw_schedule
    checks = verify_solution(
        bundle,
        schedule,
        half_day_split_time=half_day_split_time,
        max_weekly_group_exception_days=max_weekly_group_exception_days,
        max_split_gap_minutes=max_split_gap_minutes,
        weekly_hours_tolerance_percent=weekly_hours_tolerance_percent,
    )
    if smooth and checks["hard_errors"]:
        raw_checks = verify_solution(
            bundle,
            raw_schedule,
            half_day_split_time=half_day_split_time,
            max_weekly_group_exception_days=max_weekly_group_exception_days,
            max_split_gap_minutes=max_split_gap_minutes,
            weekly_hours_tolerance_percent=weekly_hours_tolerance_percent,
        )
        if len(raw_checks["hard_errors"]) <= len(checks["hard_errors"]):
            bundle.warnings.append("Lissage rejete: il violait des regles hard. Planning brut conserve.")
            schedule = raw_schedule
            checks = raw_checks
    status = "ok" if not checks["hard_errors"] else "invalid"
    return {
        "status": status,
        "objective": round(float(bundle.result.fun), 4),
        "solver_message": bundle.result.message,
        "warnings": bundle.warnings,
        "schedule": schedule,
        "checks": checks,
    }


def make_ortools_payload(
    data: dict[str, Any],
    *,
    time_limit: float = 300.0,
    type_aliases: dict[str, str] | None = None,
    min_daily_hours: float = 2.0,
    max_split_gap_minutes: int | None = 90,
    weekly_hours_tolerance_minutes: int = 30,
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
    hard_max_work_days: bool = True,
    progress_callback: Callable[[int, str], None] | None = None,
) -> tuple[dict[str, Any], Any]:
    try:
        from ortools.sat.python import cp_model
    except Exception as exc:
        horizon = make_horizon(data)
        bundle = type(
            "OrtoolsBundle",
            (),
            {
                "data": data,
                "horizon": horizon,
                "groups": list(data.get("groups", [])),
                "educators": list(data.get("educators", [])),
                "sites": [site["name"] for site in data.get("sites", [])],
            },
        )()
        return (
            {
                "status": "infeasible_or_not_solved",
                "solver_message": f"OR-Tools indisponible: {exc}",
                "warnings": [],
                "diagnostics": [],
            },
            bundle,
        )

    aliases = dict(DEFAULT_TYPE_ALIASES)
    if type_aliases:
        aliases.update(type_aliases)

    horizon = make_horizon(data)
    groups = list(data.get("groups", []))
    educators = list(data.get("educators", []))
    sites = [site["name"] for site in data.get("sites", [])]
    warnings: list[str] = []

    bundle = type(
        "OrtoolsBundle",
        (),
        {
            "data": data,
            "horizon": horizon,
            "groups": groups,
            "educators": educators,
            "sites": sites,
        },
    )()

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

    if progress_callback:
        progress_callback(12, "Preparation CP-SAT")

    model = cp_model.CpModel()
    group_demand, site_demand = build_demands_by_day(data, groups, horizon)
    group_by_site = {
        site: [g_i for g_i, group in enumerate(groups) if group["site"] == site]
        for site in sites
    }
    known_types = {item["name"] for item in data.get("educator_types", [])}
    educator_types = [educator.get("type", "") for educator in educators]
    max_daily_hours = float(data.get("rules_global", {}).get("max_daily_hours", 8.5))
    weekly_base = float(data.get("rules_global", {}).get("max_weekly_hours", 40.0))
    max_daily_slots = int(round(max_daily_hours / (horizon.step / 60.0)))
    min_daily_slots = int(round(float(min_daily_hours) / (horizon.step / 60.0)))
    absolute_max_slots = absolute_weekly_max_slots(
        horizon,
        absolute_max_weekly_hours if enforce_absolute_max_weekly_hours else None,
    )
    split_slot = split_slot_for_horizon(horizon, half_day_split_time)
    max_gap_slots = None if max_split_gap_minutes is None else int(round(max_split_gap_minutes / horizon.step))
    generation_max_gap_slots = max_gap_slots if max_gap_slots is not None else horizon.slots
    min_segment_slots = 4

    group_by_name = {group["name"]: i for i, group in enumerate(groups)}
    educator_by_name = {educator["name"]: i for i, educator in enumerate(educators)}
    day_by_name = {key: i for i, (key, _) in enumerate(DAYS)}
    main_groups: dict[int, int] = {}
    soft_groups: dict[int, int] = {}
    for raw_rule in data.get("rules_group", []):
        if len(raw_rule) < 4:
            continue
        pref_type, strength, educator_name, group_name = raw_rule[:4]
        if normalize_flag(pref_type) in {"negatif", "negative", "neg"}:
            continue
        if educator_name not in educator_by_name or group_name not in group_by_name:
            continue
        target = group_by_name[group_name]
        if normalize_flag(strength) == "hard":
            main_groups.setdefault(educator_by_name[educator_name], target)
        else:
            soft_groups.setdefault(educator_by_name[educator_name], target)
    for e_i, g_i in soft_groups.items():
        main_groups.setdefault(e_i, g_i)

    start_candidates: set[int] = {slot for slot in range(0, horizon.slots, 2)}
    end_candidates: set[int] = {slot for slot in range(2, horizon.slots + 1, 2)}
    end_candidates.add(horizon.slots)
    for rule in data.get("rules_site_schedule", []):
        for interval in rule.get("time_intervals", []):
            for value in (interval.get("start"), interval.get("end")):
                if not value:
                    continue
                minute = parse_time(str(value))
                if horizon.start <= minute <= horizon.end:
                    slot = (minute - horizon.start) // horizon.step
                    start_candidates.add(slot)
                    end_candidates.add(slot)
    for raw_rule in data.get("rules_time", []):
        if len(raw_rule) < 6:
            continue
        for value in (raw_rule[4], raw_rule[5]):
            minute = max(horizon.start, min(horizon.end, parse_time(str(value))))
            slot = (minute - horizon.start) // horizon.step
            start_candidates.add(slot)
            end_candidates.add(slot)
    start_candidates = {slot for slot in start_candidates if 0 <= slot < horizon.slots}
    end_candidates = {slot for slot in end_candidates if 0 < slot <= horizon.slots}

    variables: list[Any] = []
    pattern_owner: list[tuple[int, int]] = []
    pattern_segments: list[tuple[tuple[int, int], ...]] = []
    pattern_half_groups: list[dict[int, int]] = []
    pattern_site: list[str | None] = []
    pattern_duration: list[int] = []
    pattern_child_duration: list[int] = []
    pattern_colloque_the_duration: list[int] = []
    pattern_mixed: list[int] = []
    pattern_cost: list[int] = []
    by_educator_day: dict[tuple[int, int], list[int]] = {}
    by_educator: dict[int, list[int]] = {}
    coverage_terms: dict[tuple[int, int, int], list[Any]] = {}
    site_terms: dict[tuple[int, str, int], list[Any]] = {}
    percentage_terms: dict[str, list[tuple[Any, int, int]]] = {site: [] for site in sites}
    scale = 100

    def work_cost_or_none(e_i: int, day_key: str, segments: tuple[tuple[int, int], ...]) -> int | None:
        educator_name = educators[e_i]["name"]
        worked_slots = {slot for start, end in segments for slot in range(start, end)}
        cost = 0
        for raw_rule in data.get("rules_time", []):
            if len(raw_rule) < 6:
                continue
            pref_type, strength, rule_educator, rule_day, start, end = raw_rule[:6]
            if rule_educator != educator_name or normalize_day(rule_day) != day_key:
                continue
            rule_slots = set(slot_range_clipped(horizon, start, end)[0])
            overlap = len(worked_slots & rule_slots)
            is_negative = normalize_flag(pref_type) in {"negatif", "negative", "neg"}
            is_hard = normalize_flag(strength) == "hard"
            if is_hard:
                if is_negative and overlap:
                    return None
                if not is_negative and overlap == 0:
                    return None
            elif is_negative:
                cost += overlap * 45
            else:
                cost -= overlap * 35
        if len(segments) > 1:
            gap = segments[1][0] - segments[0][1]
            if max_gap_slots is not None and gap > max_gap_slots:
                return None
            cost += int(round(split_shift_weight * scale)) + int(round(gap * split_gap_weight * scale))
        return cost

    def group_cost_or_none(e_i: int, g_i: int, slots: int) -> int | None:
        educator_name = educators[e_i]["name"]
        group_name = groups[g_i]["name"]
        cost = 0
        main_group = main_groups.get(e_i)
        if main_group is not None and main_group != g_i:
            cost += int(round(slots * same_group_week_weight * scale))
        for raw_rule in data.get("rules_group", []):
            if len(raw_rule) < 4 or raw_rule[2] != educator_name:
                continue
            pref_type, strength, _, rule_group = raw_rule[:4]
            is_negative = normalize_flag(pref_type) in {"negatif", "negative", "neg"}
            affected = group_name == rule_group if is_negative else group_name != rule_group
            if not affected:
                continue
            if normalize_flag(strength) == "hard":
                return None
            cost += int(round(slots * 0.18 * scale))
        return cost

    def add_pattern(
        e_i: int,
        d_i: int,
        site: str | None,
        segments: tuple[tuple[int, int], ...],
        half_groups: dict[int, int],
        duration: int,
        cost: int,
    ) -> None:
        var = model.NewBoolVar(f"p_{len(variables)}")
        pattern_id = len(variables)
        variables.append(var)
        pattern_owner.append((e_i, d_i))
        pattern_segments.append(segments)
        pattern_half_groups.append(dict(half_groups))
        pattern_site.append(site)
        pattern_duration.append(duration)
        used_groups = {
            half_groups[0 if slot < split_slot else 1]
            for start, end in segments
            for slot in range(start, end)
        }
        mixed = 1 if len({item for item in used_groups if item >= 0}) > 1 else 0
        pattern_mixed.append(mixed)
        pattern_cost.append(cost + (int(round(group_switch_day_weight * scale)) if mixed else 0))
        by_educator_day.setdefault((e_i, d_i), []).append(pattern_id)
        by_educator.setdefault(e_i, []).append(pattern_id)
        if site is not None:
            percentage_terms[site].append((var, e_i, duration))
        for start, end in segments:
            for slot in range(start, end):
                half_i = 0 if slot < split_slot else 1
                g_i = half_groups[half_i]
                coverage_terms.setdefault((d_i, g_i, slot), []).append(var)
                if site is not None:
                    site_terms.setdefault((d_i, site, slot), []).append(var)

    pattern_count = 0
    for e_i, educator in enumerate(educators):
        for d_i, (day_key, _) in enumerate(DAYS):
            off_cost = work_cost_or_none(e_i, day_key, ())
            if off_cost is not None:
                add_pattern(e_i, d_i, None, (), {0: -1, 1: -1}, 0, off_cost)
                pattern_count += 1
            for site in sites:
                local_groups = group_by_site[site]
                for duration in range(max(1, min_daily_slots), max_daily_slots + 1, 2):
                    for start in sorted(start_candidates):
                        end = start + duration
                        if end > horizon.slots or end not in end_candidates:
                            continue
                        segments = ((start, end),)
                        base_cost = work_cost_or_none(e_i, day_key, segments)
                        if base_cost is None:
                            continue
                        worked_slots = list(range(start, end))
                        worked_halves = {0 if slot < split_slot else 1 for slot in worked_slots}
                        if worked_halves == {0, 1}:
                            for g_i in local_groups:
                                group_cost = group_cost_or_none(e_i, g_i, duration)
                                if group_cost is None:
                                    continue
                                add_pattern(
                                    e_i,
                                    d_i,
                                    site,
                                    segments,
                                    {0: g_i, 1: g_i},
                                    duration,
                                    base_cost + group_cost,
                                )
                                pattern_count += 1
                        else:
                            half_i = next(iter(worked_halves))
                            for g_i in local_groups:
                                group_cost = group_cost_or_none(e_i, g_i, duration)
                                if group_cost is None:
                                    continue
                                add_pattern(
                                    e_i,
                                    d_i,
                                    site,
                                    segments,
                                    {half_i: g_i, 1 - half_i: g_i},
                                    duration,
                                    base_cost + group_cost,
                                )
                                pattern_count += 1

                    if duration < 2 * min_segment_slots:
                        continue
                    for first_len in range(min_segment_slots, duration - min_segment_slots + 1, 2):
                        second_len = duration - first_len
                        for gap in range(2, (max_gap_slots or 6) + 1, 2):
                            first_end = split_slot
                            first_start = first_end - first_len
                            second_start = first_end + gap
                            second_end = second_start + second_len
                            if first_start < 0 or second_end > horizon.slots:
                                continue
                            segments = ((first_start, first_end), (second_start, second_end))
                            base_cost = work_cost_or_none(e_i, day_key, segments)
                            if base_cost is None:
                                continue
                            for g_i in local_groups:
                                group_cost = group_cost_or_none(e_i, g_i, duration)
                                if group_cost is None:
                                    continue
                                add_pattern(
                                    e_i,
                                    d_i,
                                    site,
                                    segments,
                                    {0: g_i, 1: g_i},
                                    duration,
                                    base_cost + group_cost,
                                )
                                pattern_count += 1

    if progress_callback:
        progress_callback(20, f"Modeles de journee generes: {pattern_count}")

    for e_i in range(len(educators)):
        for d_i in range(len(DAYS)):
            terms = [variables[p_i] for p_i in by_educator_day.get((e_i, d_i), [])]
            if not terms:
                return (
                    {
                        "status": "infeasible_or_not_solved",
                        "solver_message": f"Aucun modele de journee possible pour {educators[e_i]['name']} {DAYS[d_i][0]}.",
                        "warnings": warnings,
                        "diagnostics": [],
                    },
                    bundle,
                )
            model.Add(sum(terms) == 1)

    objective_terms: list[Any] = []
    for pattern_id, var in enumerate(variables):
        if pattern_cost[pattern_id]:
            objective_terms.append(var * int(pattern_cost[pattern_id]))

    for e_i, educator in enumerate(educators):
        target_hours = float(educator["percentage"]) / 100.0 * weekly_base
        target = int(round(target_hours / (horizon.step / 60.0)))
        the_slots = the_target_slots(target, the_percent, enabled=the_enabled)
        child_target = max(0, target - the_slots)
        tolerance_slots = weekly_tolerance_slots(
            target_hours,
            horizon,
            percent=weekly_hours_tolerance_percent,
            minutes=weekly_hours_tolerance_minutes,
            step_minutes=weekly_hours_tolerance_step_minutes,
        )
        total = sum(variables[p_i] * int(pattern_duration[p_i]) for p_i in by_educator.get(e_i, []))
        model.Add(total >= max(0, child_target - tolerance_slots))
        model.Add(total <= child_target + tolerance_slots)
        over = model.NewIntVar(0, tolerance_slots, f"over_{e_i}")
        under = model.NewIntVar(0, tolerance_slots, f"under_{e_i}")
        model.Add(total - child_target == over - under)
        objective_terms.append((over + under) * 2500)
        if hard_max_work_days:
            worked_day_terms = [
                variables[p_i]
                for p_i in by_educator.get(e_i, [])
                if pattern_duration[p_i] > 0
            ]
            model.Add(
                sum(worked_day_terms)
                <= max_work_days_for_educator(
                    educator,
                    weekly_base,
                    float(data.get("rules_global", {}).get("max_daily_hours", 8.5)),
                )
            )

    for d_i in range(len(DAYS)):
        for g_i in range(len(groups)):
            for slot in range(horizon.slots):
                terms = coverage_terms.get((d_i, g_i, slot), [])
                demand = group_demand[(d_i, g_i, slot)]
                model.Add(sum(terms) >= demand)
                model.Add(sum(terms) <= max(3, demand))
        for (demand_d_i, site, slot), demand in site_demand.items():
            if demand_d_i == d_i:
                model.Add(sum(site_terms.get((d_i, site, slot), [])) >= demand)

    if max_weekly_group_exception_days is not None:
        for e_i in range(len(educators)):
            terms = [
                variables[p_i] * int(pattern_mixed[p_i])
                for p_i in by_educator.get(e_i, [])
                if pattern_mixed[p_i]
            ]
            if terms:
                model.Add(sum(terms) <= int(max_weekly_group_exception_days))

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
        pct = int(round(float(value)))
        terms = []
        for var, e_i, duration in percentage_terms[site]:
            coeff = -pct * int(duration)
            if educator_types[e_i] in wanted_types:
                coeff += 100 * int(duration)
            if coeff:
                terms.append(var * coeff)
        if normalize_flag(minmax) == "min":
            model.Add(sum(terms) >= 0)
        else:
            model.Add(sum(terms) <= 0)

    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = max(5.0, min(90.0, float(time_limit) * 0.35))
    solver.parameters.num_search_workers = max(1, min(8, os.cpu_count() or 1))
    solver.parameters.stop_after_first_solution = True
    if progress_callback:
        progress_callback(35, "Recherche d'une solution valide")
    status = solver.Solve(model)
    if status not in {cp_model.OPTIMAL, cp_model.FEASIBLE}:
        return (
            {
                "status": "infeasible_or_not_solved",
                "solver_message": solver.StatusName(status),
                "warnings": warnings,
                "diagnostics": diagnose_basic_conflicts(data, horizon),
            },
            bundle,
        )

    for var in variables:
        model.AddHint(var, int(solver.Value(var)))
    model.Minimize(sum(objective_terms) if objective_terms else 0)
    optimizer = cp_model.CpSolver()
    optimizer.parameters.max_time_in_seconds = max(5.0, float(time_limit) - solver.WallTime())
    optimizer.parameters.num_search_workers = max(1, min(8, os.cpu_count() or 1))
    optimizer.parameters.relative_gap_limit = 0.05
    if progress_callback:
        progress_callback(55, "Optimisation de la qualite")
    opt_status = optimizer.Solve(model)
    best_solver = optimizer if opt_status in {cp_model.OPTIMAL, cp_model.FEASIBLE} else solver
    best_status = opt_status if opt_status in {cp_model.OPTIMAL, cp_model.FEASIBLE} else status

    schedule = {
        educator["name"]: {day_key: [] for day_key, _ in DAYS}
        for educator in educators
    }
    for pattern_id, var in enumerate(variables):
        if best_solver.Value(var) < 1:
            continue
        duration = pattern_duration[pattern_id]
        if duration <= 0:
            continue
        e_i, d_i = pattern_owner[pattern_id]
        day_key = DAYS[d_i][0]
        educator_name = educators[e_i]["name"]
        worked = {slot for start, end in pattern_segments[pattern_id] for slot in range(start, end)}
        current_state: tuple[int, str] | None = None
        start_slot: int | None = None
        for slot in range(horizon.slots + 1):
            active_state: tuple[int, str] | None = None
            if slot in worked:
                half_i = 0 if slot < split_slot else 1
                display_group = pattern_half_groups[pattern_id][half_i]
                activity = ""
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
        weekly_hours_tolerance_percent=0.0,
    )
    # Replace percent tolerance with the actual minute tolerance for hours.
    weekly_errors = []
    for name, actual in checks["hours_by_educator"].items():
        target = checks["weekly_targets"][name]
        if abs(actual - target) > weekly_hours_tolerance_minutes / 60.0 + 1e-6:
            weekly_errors.append(
                f"{name}: {actual:.2f}h hors tolerance autour de {target:.2f}h "
                f"(+/- {weekly_hours_tolerance_minutes} min)"
            )
    if weekly_errors:
        other_errors = [
            error
            for error in checks["errors"]
            if "hors tolerance autour" not in error and "!=" not in error
        ]
        checks["errors"] = other_errors + weekly_errors
        checks["hard_errors"] = checks["errors"]
    else:
        checks["errors"] = [
            error
            for error in checks["errors"]
            if "hors tolerance autour" not in error and "!=" not in error
        ]
        checks["hard_errors"] = checks["errors"]
    status_text = "ok" if not checks["errors"] else "invalid"
    objective = 0.0
    try:
        objective = float(best_solver.ObjectiveValue())
    except Exception:
        objective = 0.0
    return (
        {
            "status": status_text,
            "objective": round(objective, 4),
            "solver_message": f"OR-Tools CP-SAT {best_solver.StatusName(best_status)}",
            "warnings": sorted(set(warnings)),
            "schedule": schedule,
            "checks": checks,
        },
        bundle,
    )


def make_ortools_slot_payload(
    data: dict[str, Any],
    *,
    time_limit: float = 300.0,
    type_aliases: dict[str, str] | None = None,
    min_daily_hours: float = 2.0,
    enforce_min_daily_hours: bool = False,
    max_split_gap_minutes: int | None = 90,
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
    work_day_weight: float = 0.0,
    hard_max_work_days: bool = True,
    enforce_daily_block_structure: bool = True,
    enforce_half_day_group_structure: bool = True,
    enforce_percentage_rules: bool = True,
    enforce_daily_hours: bool = True,
    enforce_weekly_hours: bool = True,
    progress_callback: Callable[[int, str], None] | None = None,
    hint_payload: dict[str, Any] | None = None,
    fixed_schedule: dict[str, dict[str, list[dict[str, Any]]]] | None = None,
    debug_log_path: Path | None = None,
    candidate_callback: Callable[[dict[str, Any], Any], None] | None = None,
    accept_invalid_for_hint: bool = False,
) -> tuple[dict[str, Any], Any]:
    try:
        from ortools.sat.python import cp_model
    except Exception as exc:
        horizon = make_horizon(data)
        bundle = type(
            "OrtoolsBundle",
            (),
            {
                "data": data,
                "horizon": horizon,
                "groups": list(data.get("groups", [])),
                "educators": list(data.get("educators", [])),
                "sites": [site["name"] for site in data.get("sites", [])],
            },
        )()
        return (
            {
                "status": "infeasible_or_not_solved",
                "solver_message": f"OR-Tools indisponible: {exc}",
                "warnings": [],
                "diagnostics": [],
            },
            bundle,
        )

    aliases = dict(DEFAULT_TYPE_ALIASES)
    if type_aliases:
        aliases.update(type_aliases)

    horizon = make_horizon(data)
    groups = list(data.get("groups", []))
    educators = list(data.get("educators", []))
    sites = [site["name"] for site in data.get("sites", [])]
    warnings: list[str] = []
    debug_lines: list[str] = []

    def debug(message: str) -> None:
        line = f"{time.monotonic():.3f}|{message}"
        debug_lines.append(line)
        if debug_log_path is not None:
            debug_log_path.parent.mkdir(parents=True, exist_ok=True)
            with debug_log_path.open("a", encoding="utf-8") as stream:
                stream.write(line + "\n")

    if debug_log_path is not None:
        debug_log_path.parent.mkdir(parents=True, exist_ok=True)
        debug_log_path.write_text("", encoding="utf-8")
    debug(
        f"start educators={len(educators)} groups={len(groups)} "
        f"slots={horizon.slots} time_limit={float(time_limit):.1f}"
    )
    bundle = type(
        "OrtoolsBundle",
        (),
        {
            "data": data,
            "horizon": horizon,
            "groups": groups,
            "educators": educators,
            "sites": sites,
        },
    )()
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

    if progress_callback:
        progress_callback(12, "Construction du modele CP-SAT")

    model = cp_model.CpModel()
    group_demand, site_demand = build_demands_by_day(data, groups, horizon)
    site_index = {site: i for i, site in enumerate(sites)}
    group_site = {g_i: group["site"] for g_i, group in enumerate(groups)}
    group_by_name = {group["name"]: i for i, group in enumerate(groups)}
    educator_by_name = {educator["name"]: i for i, educator in enumerate(educators)}
    day_by_name = {key: i for i, (key, _) in enumerate(DAYS)}
    known_types = {item["name"] for item in data.get("educator_types", [])}
    educator_types = [educator.get("type", "") for educator in educators]
    weekly_base = float(data.get("rules_global", {}).get("max_weekly_hours", 40.0))
    max_daily_hours = float(data.get("rules_global", {}).get("max_daily_hours", 8.5))
    max_daily_slots = int(round(max_daily_hours / (horizon.step / 60.0)))
    min_daily_slots = int(round(float(min_daily_hours) / (horizon.step / 60.0)))
    absolute_max_slots = absolute_weekly_max_slots(
        horizon,
        absolute_max_weekly_hours if enforce_absolute_max_weekly_hours else None,
    )
    split_slot = split_slot_for_horizon(horizon, half_day_split_time)
    max_gap_slots = None if max_split_gap_minutes is None else int(round(max_split_gap_minutes / horizon.step))
    colloques = parse_colloques(data, horizon, groups, warnings)
    colloque_by_group = {int(colloque["group_i"]): colloque for colloque in colloques}

    hard_main_groups: dict[int, int] = {}
    soft_groups: dict[int, int] = {}
    forbidden_main_groups: dict[int, set[int]] = {}
    for raw_rule in data.get("rules_group", []):
        if len(raw_rule) < 4:
            continue
        pref_type, strength, educator_name, group_name = raw_rule[:4]
        if educator_name not in educator_by_name or group_name not in group_by_name:
            continue
        is_negative = normalize_flag(pref_type) in {"negatif", "negative", "neg"}
        target = group_by_name[group_name]
        if normalize_flag(strength) == "hard" and is_negative:
            forbidden_main_groups.setdefault(educator_by_name[educator_name], set()).add(target)
            continue
        if is_negative:
            continue
        if normalize_flag(strength) == "hard":
            hard_main_groups.setdefault(educator_by_name[educator_name], target)
        else:
            soft_groups.setdefault(educator_by_name[educator_name], target)
    hinted_main_groups: dict[int, int] = {}
    if hint_payload and isinstance(hint_payload.get("schedule"), dict):
        explicit_hint_groups = hint_payload.get("checks", {}).get(
            "primary_groups_by_educator",
            {},
        )
        if isinstance(explicit_hint_groups, dict):
            for educator_name, group_name in explicit_hint_groups.items():
                if educator_name in educator_by_name and group_name in group_by_name:
                    hinted_main_groups[educator_by_name[educator_name]] = group_by_name[
                        group_name
                    ]
        hinted_totals: dict[int, dict[int, int]] = {}
        for educator_name, by_day in hint_payload.get("schedule", {}).items():
            if educator_name not in educator_by_name or not isinstance(by_day, dict):
                continue
            e_i = educator_by_name[educator_name]
            for blocks in by_day.values():
                if not isinstance(blocks, list):
                    continue
                for block in blocks:
                    if block.get("activity") in {"colloque", "remplacement_colloque"}:
                        continue
                    group_name = block.get("group")
                    if group_name not in group_by_name:
                        continue
                    minutes = int(round(float(block.get("hours", 0.0)) * 60))
                    hinted_totals.setdefault(e_i, {})
                    hinted_totals[e_i][group_by_name[group_name]] = hinted_totals[e_i].get(group_by_name[group_name], 0) + minutes
        for e_i, totals in hinted_totals.items():
            if totals:
                allowed = [
                    (minutes, g_i)
                    for g_i, minutes in totals.items()
                    if g_i not in forbidden_main_groups.get(e_i, set())
                ]
                if allowed:
                    hinted_main_groups.setdefault(e_i, max(allowed)[1])

    primary_hint_groups: dict[int, int] = dict(hard_main_groups)
    for source in (soft_groups, hinted_main_groups):
        for e_i, g_i in source.items():
            if g_i not in forbidden_main_groups.get(e_i, set()):
                primary_hint_groups.setdefault(e_i, g_i)
    demand_by_group = {
        g_i: sum(
            demand
            for (_d_i, demand_g_i, _t_i), demand in group_demand.items()
            if demand_g_i == g_i
        )
        for g_i in range(len(groups))
    }
    hinted_capacity_by_group = {g_i: 0 for g_i in range(len(groups))}

    def educator_child_capacity(e_i: int) -> int:
        target_slots = int(
            round(
                float(educators[e_i].get("percentage", 0.0))
                / 100.0
                * weekly_base
                / (horizon.step / 60.0)
            )
        )
        return max(
            0,
            target_slots - the_target_slots(target_slots, the_percent, enabled=the_enabled),
        )

    for e_i, g_i in primary_hint_groups.items():
        hinted_capacity_by_group[g_i] += educator_child_capacity(e_i)
    for e_i in sorted(
        range(len(educators)),
        key=educator_child_capacity,
        reverse=True,
    ):
        if e_i in primary_hint_groups:
            continue
        allowed_groups = [
            g_i
            for g_i in range(len(groups))
            if g_i not in forbidden_main_groups.get(e_i, set())
        ]
        if not allowed_groups:
            continue
        selected_group = max(
            allowed_groups,
            key=lambda g_i: (
                demand_by_group[g_i] - hinted_capacity_by_group[g_i],
                demand_by_group[g_i],
                -g_i,
            ),
        )
        primary_hint_groups[e_i] = selected_group
        hinted_capacity_by_group[selected_group] += educator_child_capacity(e_i)

    def ranked_primary_group_candidates(limit: int = 8) -> list[dict[int, int]]:
        provisional_fixed = dict(hard_main_groups)
        for e_i, g_i in soft_groups.items():
            if g_i not in forbidden_main_groups.get(e_i, set()):
                provisional_fixed.setdefault(e_i, g_i)
        free_educators = [
            e_i for e_i in range(len(educators)) if e_i not in provisional_fixed
        ]
        allowed_by_educator = [
            [
                g_i
                for g_i in range(len(groups))
                if g_i not in forbidden_main_groups.get(e_i, set())
            ]
            for e_i in free_educators
        ]
        if any(not allowed for allowed in allowed_by_educator):
            return []

        percentage_rules: list[tuple[set[str], str, float, str]] = []
        for raw_rule in data.get("rules_percentage", []):
            if len(raw_rule) < 4:
                continue
            raw_types, minmax, value, site = raw_rule[:4]
            wanted_types, _type_warnings = split_types(
                list(raw_types),
                aliases,
                known_types,
            )
            percentage_rules.append(
                (wanted_types, normalize_flag(minmax), float(value), str(site))
            )

        scored: list[tuple[float, tuple[int, ...]]] = []
        for choices in itertools.product(*allowed_by_educator):
            assignment = dict(provisional_fixed)
            assignment.update(zip(free_educators, choices))
            group_capacity = {g_i: 0 for g_i in range(len(groups))}
            site_capacity: dict[str, int] = {site: 0 for site in sites}
            site_type_capacity: dict[tuple[str, str], int] = {}
            for e_i, g_i in assignment.items():
                capacity = educator_child_capacity(e_i)
                site = str(groups[g_i]["site"])
                educator_type = str(educators[e_i].get("type", ""))
                group_capacity[g_i] += capacity
                site_capacity[site] = site_capacity.get(site, 0) + capacity
                site_type_capacity[(site, educator_type)] = (
                    site_type_capacity.get((site, educator_type), 0) + capacity
                )
            capacity_score = sum(
                abs(group_capacity[g_i] - demand_by_group[g_i])
                for g_i in range(len(groups))
            )
            percentage_score = 0.0
            for wanted_types, minmax, value, site in percentage_rules:
                total = site_capacity.get(site, 0)
                selected = sum(
                    site_type_capacity.get((site, educator_type), 0)
                    for educator_type in wanted_types
                )
                actual = 100.0 * selected / max(1, total)
                violation = (
                    max(0.0, value - actual)
                    if minmax == "min"
                    else max(0.0, actual - value)
                )
                percentage_score += violation * 5.0
            ordered_assignment = tuple(
                assignment[e_i] for e_i in range(len(educators))
            )
            scored.append((capacity_score + percentage_score, ordered_assignment))
        scored.sort(key=lambda item: item[0])
        if not scored:
            return []
        positions = [0, 1, 3, 7, 15, 31, 63, 127]
        selected: list[dict[int, int]] = []
        seen: set[tuple[int, ...]] = set()
        for position in positions:
            if len(selected) >= limit or position >= len(scored):
                break
            assignment_tuple = scored[position][1]
            if assignment_tuple in seen:
                continue
            seen.add(assignment_tuple)
            selected.append(
                {e_i: g_i for e_i, g_i in enumerate(assignment_tuple)}
            )
        heuristic_tuple = tuple(
            primary_hint_groups[e_i] for e_i in range(len(educators))
        )
        if heuristic_tuple not in seen and len(selected) < limit:
            selected.append(
                {e_i: g_i for e_i, g_i in enumerate(heuristic_tuple)}
            )
        return selected

    primary_group_candidates = ranked_primary_group_candidates()
    if len(hinted_main_groups) == len(educators):
        hinted_candidate = {
            e_i: hinted_main_groups[e_i] for e_i in range(len(educators))
        }
        primary_group_candidates = [
            hinted_candidate,
            *[
                candidate
                for candidate in primary_group_candidates
                if candidate != hinted_candidate
            ],
        ]

    x: dict[tuple[int, int, int, int], Any] = {}
    work: dict[tuple[int, int, int], Any] = {}
    work_day: dict[tuple[int, int], Any] = {}
    site_day: dict[tuple[int, int, int], Any] = {}
    half_group: dict[tuple[int, int, int, int], Any] = {}
    group_day: dict[tuple[int, int, int], Any] = {}
    mixed_day: dict[tuple[int, int], Any] = {}
    outside_primary_day: dict[tuple[int, int], Any] = {}
    outside_primary_group_day: dict[tuple[int, int, int], Any] = {}
    start_var: dict[tuple[int, int, int], Any] = {}
    primary_group: dict[tuple[int, int], Any] = {}
    replacement_assignment: dict[tuple[int, int, int, int], Any] = {}
    objective_terms: list[Any] = []
    scale = 100

    for e_i in range(len(educators)):
        primary_terms = []
        for g_i in range(len(groups)):
            var = model.NewBoolVar(f"primary_{e_i}_{g_i}")
            primary_group[(e_i, g_i)] = var
            primary_terms.append(var)
        model.Add(sum(primary_terms) == 1)
        required_group = hard_main_groups.get(e_i)
        if required_group is not None:
            model.Add(primary_group[(e_i, required_group)] == 1)
        for forbidden_group in forbidden_main_groups.get(e_i, set()):
            model.Add(primary_group[(e_i, forbidden_group)] == 0)
        preferred_group = soft_groups.get(e_i)
        if preferred_group is not None:
            objective_terms.append(primary_group[(e_i, preferred_group)] * -500)

    for e_i in range(len(educators)):
        for d_i in range(len(DAYS)):
            work_day[(e_i, d_i)] = model.NewBoolVar(f"wd_{e_i}_{d_i}")
            if work_day_weight:
                objective_terms.append(
                    work_day[(e_i, d_i)]
                    * int(round(work_day_weight * scale))
                )
            mixed_day[(e_i, d_i)] = model.NewBoolVar(f"mix_{e_i}_{d_i}")
            outside_primary_day[(e_i, d_i)] = model.NewBoolVar(f"outside_{e_i}_{d_i}")
            for s_i in range(len(sites)):
                site_day[(e_i, d_i, s_i)] = model.NewBoolVar(f"site_{e_i}_{d_i}_{s_i}")
            for g_i in range(len(groups)):
                group_day[(e_i, d_i, g_i)] = model.NewBoolVar(f"gd_{e_i}_{d_i}_{g_i}")
                outside_primary_group_day[(e_i, d_i, g_i)] = model.NewBoolVar(
                    f"outside_group_{e_i}_{d_i}_{g_i}"
                )
                for half_i in range(2):
                    half_group[(e_i, d_i, half_i, g_i)] = model.NewBoolVar(f"hg_{e_i}_{d_i}_{half_i}_{g_i}")
            for t_i in range(horizon.slots):
                work[(e_i, d_i, t_i)] = model.NewBoolVar(f"w_{e_i}_{d_i}_{t_i}")
                start_var[(e_i, d_i, t_i)] = model.NewBoolVar(f"st_{e_i}_{d_i}_{t_i}")
                for g_i in range(len(groups)):
                    assignment = model.NewBoolVar(f"x_{e_i}_{d_i}_{g_i}_{t_i}")
                    x[(e_i, d_i, g_i, t_i)] = assignment
                    objective_terms.append(assignment)

    replacement_windows: set[tuple[int, int, int, int]] = set()
    colloque_group_by_slot: dict[tuple[int, int], int] = {}
    for target_g, target_colloque in colloque_by_group.items():
        d_i = int(target_colloque["day_i"])
        for t_i in target_colloque["slots"]:
            colloque_group_by_slot[(d_i, int(t_i))] = target_g
        start = max(0, int(target_colloque["start_slot"]) - 1)
        end = min(horizon.slots, int(target_colloque["end_slot"]) + 2)
        for e_i in range(len(educators)):
            for t_i in range(start, end):
                key = (e_i, d_i, target_g, t_i)
                replacement_windows.add(key)
                replacement = model.NewBoolVar(
                    f"replacement_{e_i}_{d_i}_{target_g}_{t_i}"
                )
                replacement_assignment[key] = replacement
                model.Add(replacement <= x[key])
                model.Add(replacement + primary_group[(e_i, target_g)] <= 1)
                model.Add(replacement >= x[key] - primary_group[(e_i, target_g)])
    debug(
        f"primary_group_variables={len(primary_group)} "
        f"hard_primary_groups={len(hard_main_groups)} "
        f"soft_primary_groups={len(soft_groups)} "
        f"replacement_variables={len(replacement_assignment)}"
    )
    debug(
        "primary_group_hints="
        + ",".join(
            f"{educators[e_i]['name']}:{groups[g_i]['name']}"
            for e_i, g_i in sorted(primary_hint_groups.items())
        )
    )
    debug(f"primary_group_candidates={len(primary_group_candidates)}")

    if progress_callback:
        progress_callback(20, "Contraintes de couverture")

    for d_i in range(len(DAYS)):
        for g_i in range(len(groups)):
            for t_i in range(horizon.slots):
                terms = [x[(e_i, d_i, g_i, t_i)] for e_i in range(len(educators))]
                demand = group_demand[(d_i, g_i, t_i)]
                model.Add(sum(terms) >= demand)
                model.Add(sum(terms) <= max(3, demand))
        for (demand_d_i, site, t_i), demand in site_demand.items():
            if demand_d_i != d_i:
                continue
            terms = [
                x[(e_i, d_i, g_i, t_i)]
                for e_i in range(len(educators))
                for g_i, group in enumerate(groups)
                if group["site"] == site
            ]
            model.Add(sum(terms) >= demand)

    if progress_callback:
        progress_callback(28, "Contraintes educateurs")

    max_gap = max_gap_slots if max_gap_slots is not None else horizon.slots
    overflow_state = 10_000
    second_state = 20_000
    final_done_state = 30_000
    transitions: list[tuple[int, int, int]] = [(0, 0, 0), (0, 1, 1), (1, 1, 1), (1, 0, 2)]
    for gap in range(1, max_gap + 1):
        state = 1 + gap
        transitions.append((state, 1, second_state))
        transitions.append((state, 0, state + 1 if gap < max_gap else overflow_state))
    transitions.extend(
        [
            (overflow_state, 0, overflow_state),
            (second_state, 1, second_state),
            (second_state, 0, final_done_state),
            (final_done_state, 0, final_done_state),
        ]
    )
    final_states = [0, 1, overflow_state, second_state, final_done_state] + [1 + gap for gap in range(1, max_gap + 1)]

    def regular_assignment(e_i: int, d_i: int, g_i: int, t_i: int) -> Any:
        key = (e_i, d_i, g_i, t_i)
        replacement = replacement_assignment.get(key)
        return x[key] if replacement is None else x[key] - replacement

    for e_i, educator in enumerate(educators):
        if not educator_attends_colloque(educator):
            continue
        for primary_g, colloque in colloque_by_group.items():
            colloque_day = int(colloque["day_i"])
            for assigned_g in range(len(groups)):
                if assigned_g == primary_g:
                    continue
                for t_i in range(horizon.slots):
                    model.Add(
                        regular_assignment(
                            e_i,
                            colloque_day,
                            assigned_g,
                            t_i,
                        )
                        + primary_group[(e_i, primary_g)]
                        <= 1
                    )

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
        weekly_child_terms = []
        weekly_visible_terms = []
        for d_i in range(len(DAYS)):
            day_work_terms = []
            for t_i in range(horizon.slots):
                group_terms = [x[(e_i, d_i, g_i, t_i)] for g_i in range(len(groups))]
                colloque_group = colloque_group_by_slot.get((d_i, t_i))
                if colloque_group is not None and educator_attends_colloque(educator):
                    model.Add(
                        sum(group_terms) + primary_group[(e_i, colloque_group)]
                        == work[(e_i, d_i, t_i)]
                    )
                else:
                    model.Add(sum(group_terms) == work[(e_i, d_i, t_i)])
                model.Add(work[(e_i, d_i, t_i)] <= work_day[(e_i, d_i)])
                day_work_terms.append(work[(e_i, d_i, t_i)])
                weekly_child_terms.extend(group_terms)
                weekly_visible_terms.append(work[(e_i, d_i, t_i)])
                if t_i == 0:
                    model.Add(start_var[(e_i, d_i, t_i)] == work[(e_i, d_i, t_i)])
                else:
                    model.Add(start_var[(e_i, d_i, t_i)] >= work[(e_i, d_i, t_i)] - work[(e_i, d_i, t_i - 1)])
                    model.Add(start_var[(e_i, d_i, t_i)] <= work[(e_i, d_i, t_i)])
                    model.Add(start_var[(e_i, d_i, t_i)] <= 1 - work[(e_i, d_i, t_i - 1)])
                objective_terms.append(start_var[(e_i, d_i, t_i)] * int(round(split_shift_weight * scale)))
            if enforce_daily_hours:
                model.Add(sum(day_work_terms) <= max_daily_slots)
            minimum_worked_slots = min_daily_slots if enforce_min_daily_hours else 1
            model.Add(
                sum(day_work_terms)
                >= (
                    minimum_worked_slots if enforce_daily_hours else 1
                )
                * work_day[(e_i, d_i)]
            )
            if enforce_daily_block_structure:
                model.Add(
                    sum(
                        start_var[(e_i, d_i, t_i)]
                        for t_i in range(horizon.slots)
                    )
                    <= 2
                )
                model.AddAutomaton(
                    [work[(e_i, d_i, t_i)] for t_i in range(horizon.slots)],
                    0,
                    final_states,
                    transitions,
                )

            for g_i, group in enumerate(groups):
                s_i = site_index[group["site"]]
                regular_group_terms_for_day = []
                for t_i in range(horizon.slots):
                    model.Add(x[(e_i, d_i, g_i, t_i)] <= site_day[(e_i, d_i, s_i)])
                    regular_term = regular_assignment(e_i, d_i, g_i, t_i)
                    regular_group_terms_for_day.append(regular_term)
                    half_i = 0 if t_i < split_slot else 1
                    if enforce_half_day_group_structure:
                        model.Add(
                            regular_term
                            <= half_group[(e_i, d_i, half_i, g_i)]
                        )
                    model.Add(regular_term <= group_day[(e_i, d_i, g_i)])
                if regular_group_terms_for_day:
                    model.Add(group_day[(e_i, d_i, g_i)] <= sum(regular_group_terms_for_day))
                else:
                    model.Add(group_day[(e_i, d_i, g_i)] == 0)
            for s_i, site_name in enumerate(sites):
                site_terms_for_day = [
                    x[(e_i, d_i, g_i, t_i)]
                    for g_i, group in enumerate(groups)
                    if group["site"] == site_name
                    for t_i in range(horizon.slots)
                ]
                if site_terms_for_day:
                    model.Add(site_day[(e_i, d_i, s_i)] <= sum(site_terms_for_day))
                else:
                    model.Add(site_day[(e_i, d_i, s_i)] == 0)
            for half_i in range(2):
                half_slots = (
                    range(0, split_slot)
                    if half_i == 0
                    else range(split_slot, horizon.slots)
                )
                for g_i in range(len(groups)):
                    half_terms = [
                        regular_assignment(e_i, d_i, g_i, t_i)
                        for t_i in half_slots
                    ]
                    if enforce_half_day_group_structure and half_terms:
                        model.Add(
                            half_group[(e_i, d_i, half_i, g_i)]
                            <= sum(half_terms)
                        )
                    else:
                        model.Add(half_group[(e_i, d_i, half_i, g_i)] == 0)
                if enforce_half_day_group_structure:
                    model.Add(
                        sum(
                            half_group[(e_i, d_i, half_i, g_i)]
                            for g_i in range(len(groups))
                        )
                        <= 1
                    )
            regular_group_count = sum(group_day[(e_i, d_i, g_i)] for g_i in range(len(groups)))
            model.Add(regular_group_count <= 1 + mixed_day[(e_i, d_i)])
            model.Add(regular_group_count >= 2 * mixed_day[(e_i, d_i)])
            objective_terms.append(mixed_day[(e_i, d_i)] * int(round(group_switch_day_weight * scale)))
            outside_var = outside_primary_day[(e_i, d_i)]
            non_primary_terms = []
            for g_i in range(len(groups)):
                outside_group = outside_primary_group_day[(e_i, d_i, g_i)]
                model.Add(outside_group <= group_day[(e_i, d_i, g_i)])
                model.Add(outside_group + primary_group[(e_i, g_i)] <= 1)
                model.Add(
                    outside_group
                    >= group_day[(e_i, d_i, g_i)] - primary_group[(e_i, g_i)]
                )
                model.Add(outside_group <= outside_var)
                non_primary_terms.append(outside_group)
                objective_terms.append(
                    outside_group * int(round(same_group_week_weight * scale))
                )
            model.Add(outside_var <= sum(non_primary_terms))
            objective_terms.append(
                outside_var * int(round(group_switch_day_weight * scale * 4))
            )
        if enforce_weekly_hours:
            upper_visible = target + tolerance_slots
            if absolute_max_slots is not None:
                upper_visible = min(upper_visible, absolute_max_slots)
            child_target = max(0, target - the_slots)
            model.Add(
                sum(weekly_child_terms)
                >= max(0, target - tolerance_slots - the_slots)
            )
            model.Add(
                sum(weekly_child_terms)
                <= max(0, upper_visible - the_slots)
            )
            model.Add(sum(weekly_visible_terms) <= upper_visible)
            over = model.NewIntVar(0, tolerance_slots, f"over_{e_i}")
            under = model.NewIntVar(0, tolerance_slots, f"under_{e_i}")
            model.Add(sum(weekly_child_terms) - child_target == over - under)
            objective_terms.append((over + under) * 2500)
        else:
            child_target = max(0, target - the_slots)
            max_deviation = len(DAYS) * horizon.slots
            over = model.NewIntVar(0, max_deviation, f"soft_over_{e_i}")
            under = model.NewIntVar(0, max_deviation, f"soft_under_{e_i}")
            model.Add(sum(weekly_child_terms) - child_target == over - under)
            objective_terms.append((over + under) * 2500)
        if hard_max_work_days:
            minimum_work_days = int(
                math.ceil(
                    max(0, target - tolerance_slots)
                    / max(1, max_daily_slots)
                    - 1e-9
                )
            )
            model.Add(
                sum(work_day[(e_i, d_i)] for d_i in range(len(DAYS)))
                <= max_work_days_for_educator(educator, weekly_base, max_daily_hours)
            )
            model.Add(
                sum(work_day[(e_i, d_i)] for d_i in range(len(DAYS)))
                >= minimum_work_days
            )

        if max_weekly_group_exception_days is not None and educator_attends_colloque(educator):
            model.Add(sum(mixed_day[(e_i, d_i)] for d_i in range(len(DAYS))) <= int(max_weekly_group_exception_days))
            outside_terms = [outside_primary_day[(e_i, d_i)] for d_i in range(len(DAYS))]
            if outside_terms:
                model.Add(sum(outside_terms) <= int(max_weekly_group_exception_days))

    if progress_callback:
        progress_callback(36, "Contraintes hard et preferences")

    for raw_rule in data.get("rules_time", []):
        if len(raw_rule) < 6:
            warnings.append(f"Regle horaire ignoree: {raw_rule}.")
            continue
        pref_type, strength, educator_name, day_name, start, end = raw_rule[:6]
        if educator_name not in educator_by_name:
            warnings.append(f"Regle horaire avec educateur inconnu: {educator_name}.")
            continue
        day_key = normalize_day(day_name)
        if day_key not in day_by_name:
            warnings.append(f"Regle horaire avec jour ignore: {day_name}.")
            continue
        e_i = educator_by_name[educator_name]
        d_i = day_by_name[day_key]
        slots, clipped = slot_range_clipped(horizon, start, end)
        if clipped:
            warnings.append(f"Regle horaire rognee sur l'horizon: {raw_rule}.")
        slot_list = list(slots)
        if not slot_list:
            continue
        is_negative = normalize_flag(pref_type) in {"negatif", "negative", "neg"}
        is_hard = normalize_flag(strength) == "hard"
        if is_hard:
            if is_negative:
                for t_i in slot_list:
                    model.Add(work[(e_i, d_i, t_i)] == 0)
            else:
                model.Add(sum(work[(e_i, d_i, t_i)] for t_i in slot_list) >= 1)
        else:
            for t_i in slot_list:
                objective_terms.append(work[(e_i, d_i, t_i)] * (45 if is_negative else -35))

    for raw_rule in data.get("rules_group", []):
        if len(raw_rule) < 4:
            warnings.append(f"Regle groupe ignoree: {raw_rule}.")
            continue
        pref_type, strength, educator_name, group_name = raw_rule[:4]
        if educator_name not in educator_by_name:
            warnings.append(f"Regle groupe avec educateur inconnu: {educator_name}.")
            continue
        if group_name not in group_by_name:
            warnings.append(f"Regle groupe avec groupe inconnu: {group_name}.")
            continue
        e_i = educator_by_name[educator_name]
        target_g = group_by_name[group_name]
        is_negative = normalize_flag(pref_type) in {"negatif", "negative", "neg"}
        is_hard = normalize_flag(strength) == "hard"
        if is_hard:
            # Hard group rules select the educator's primary group. Temporary
            # coverage and colloque replacements remain allowed.
            continue
        for d_i in range(len(DAYS)):
            for g_i in range(len(groups)):
                affected = g_i == target_g if is_negative else g_i != target_g
                if not affected:
                    continue
                for t_i in range(horizon.slots):
                    objective_terms.append(x[(e_i, d_i, g_i, t_i)] * 18)

    for raw_rule in data.get("rules_percentage", []) if enforce_percentage_rules else []:
        if len(raw_rule) < 4:
            warnings.append(f"Regle pourcentage ignoree: {raw_rule}.")
            continue
        raw_types, minmax, value, site = raw_rule[:4]
        if site not in site_index:
            warnings.append(f"Regle pourcentage avec site inconnu: {site}.")
            continue
        wanted_types, type_warnings = split_types(list(raw_types), aliases, known_types)
        warnings.extend(type_warnings)
        pct = int(round(float(value)))
        terms = []
        for e_i, educator_type in enumerate(educator_types):
            for d_i in range(len(DAYS)):
                for g_i, group in enumerate(groups):
                    if group["site"] != site:
                        continue
                    coeff = -pct
                    if educator_type in wanted_types:
                        coeff += 100
                    if coeff:
                        for t_i in range(horizon.slots):
                            terms.append(x[(e_i, d_i, g_i, t_i)] * coeff)
        if normalize_flag(minmax) == "min":
            model.Add(sum(terms) >= 0)
        else:
            model.Add(sum(terms) <= 0)

    if progress_callback:
        progress_callback(48, "Recherche d'une solution valide")

    def schedule_slot_sets(
        source: dict[str, dict[str, list[dict[str, Any]]]],
    ) -> tuple[
        set[tuple[int, int, int, int]],
        set[tuple[int, int, int]],
        set[tuple[int, int, int, int]],
    ]:
        assigned: set[tuple[int, int, int, int]] = set()
        visible: set[tuple[int, int, int]] = set()
        regular: set[tuple[int, int, int, int]] = set()
        for educator_name, by_day in source.items():
            if educator_name not in educator_by_name or not isinstance(by_day, dict):
                continue
            e_i = educator_by_name[educator_name]
            for day_key, blocks in by_day.items():
                if day_key not in day_by_name or not isinstance(blocks, list):
                    continue
                d_i = day_by_name[day_key]
                for block in blocks:
                    group_name = block.get("group")
                    if group_name not in group_by_name:
                        continue
                    g_i = group_by_name[group_name]
                    try:
                        start_slot = (parse_time(block["start"]) - horizon.start) // horizon.step
                        end_slot = (parse_time(block["end"]) - horizon.start) // horizon.step
                    except Exception:
                        continue
                    activity = str(block.get("activity", "children"))
                    for t_i in range(max(0, start_slot), min(horizon.slots, end_slot)):
                        visible.add((e_i, d_i, t_i))
                        if activity == "colloque":
                            continue
                        key = (e_i, d_i, g_i, t_i)
                        assigned.add(key)
                        if activity != "remplacement_colloque":
                            regular.add(key)
        return assigned, visible, regular

    has_hint = bool(primary_hint_groups)
    has_schedule_hint = False
    for key, var in primary_group.items():
        e_i, g_i = key
        model.AddHint(var, 1 if primary_hint_groups.get(e_i) == g_i else 0)
    if hint_payload and isinstance(hint_payload.get("schedule"), dict):
        hinted_x, hinted_work, hinted_regular_x = schedule_slot_sets(hint_payload["schedule"])
        has_schedule_hint = bool(hinted_work)
        has_hint = has_hint or bool(hinted_work)
        for key, var in x.items():
            model.AddHint(var, 1 if key in hinted_x else 0)
        for key, var in work.items():
            model.AddHint(var, 1 if key in hinted_work else 0)
        for key, var in work_day.items():
            e_i, d_i = key
            model.AddHint(var, 1 if any((e_i, d_i, t_i) in hinted_work for t_i in range(horizon.slots)) else 0)
        for key, var in group_day.items():
            e_i, d_i, g_i = key
            model.AddHint(
                var,
                1 if any((e_i, d_i, g_i, t_i) in hinted_regular_x for t_i in range(horizon.slots)) else 0,
            )
        for key, var in half_group.items():
            e_i, d_i, half_i, g_i = key
            half_slots = range(0, split_slot) if half_i == 0 else range(split_slot, horizon.slots)
            model.AddHint(
                var,
                1 if any((e_i, d_i, g_i, t_i) in hinted_regular_x for t_i in half_slots) else 0,
            )
        for key, var in site_day.items():
            e_i, d_i, s_i = key
            model.AddHint(
                var,
                1
                if any(
                    (e_i, d_i, g_i, t_i) in hinted_x
                    for g_i, group in enumerate(groups)
                    if site_index[group["site"]] == s_i
                    for t_i in range(horizon.slots)
                )
                else 0,
            )
        for key, var in mixed_day.items():
            e_i, d_i = key
            hinted_groups = {
                g_i
                for g_i in range(len(groups))
                if any((e_i, d_i, g_i, t_i) in hinted_regular_x for t_i in range(horizon.slots))
            }
            model.AddHint(var, 1 if len(hinted_groups) > 1 else 0)
        for key, var in outside_primary_day.items():
            e_i, d_i = key
            hinted_group = hinted_main_groups.get(e_i, soft_groups.get(e_i))
            model.AddHint(
                var,
                1
                if hinted_group is not None
                and any(
                    g_i != hinted_group and (e_i, d_i, g_i, t_i) in hinted_regular_x
                    for g_i in range(len(groups))
                    for t_i in range(horizon.slots)
                )
                else 0,
            )
        for key, var in start_var.items():
            e_i, d_i, t_i = key
            previous = (e_i, d_i, t_i - 1) in hinted_work if t_i else False
            model.AddHint(var, 1 if key in hinted_work and not previous else 0)

    if fixed_schedule is not None:
        fixed_x, fixed_work, _fixed_regular_x = schedule_slot_sets(fixed_schedule)
        for key, var in x.items():
            model.Add(var == int(key in fixed_x))
        for key, var in work.items():
            model.Add(var == int(key in fixed_work))
        debug(f"fixed_schedule assigned={len(fixed_x)} visible={len(fixed_work)}")

    model.Minimize(sum(objective_terms) if objective_terms else 0)
    model_variable_count = len(model.Proto().variables)
    model_constraint_count = len(model.Proto().constraints)
    debug(
        f"model variables={model_variable_count} constraints={model_constraint_count} "
        f"x={len(x)} hint={has_hint} fixed={fixed_schedule is not None}"
    )
    if progress_callback:
        progress_callback(
            48,
            f"CP-SAT: {model_variable_count} variables, {model_constraint_count} contraintes",
        )

    def build_candidate(
        solution_solver: Any,
        solution_status: Any,
        solver_message: str,
    ) -> dict[str, Any]:
        selected_main_groups = {
            e_i: next(
                g_i
                for g_i in range(len(groups))
                if solution_solver.Value(primary_group[(e_i, g_i)])
            )
            for e_i in range(len(educators))
        }
        schedule = {
            educator["name"]: {day_key: [] for day_key, _ in DAYS}
            for educator in educators
        }
        for e_i, educator in enumerate(educators):
            name = educator["name"]
            selected_main_group = selected_main_groups[e_i]
            for d_i, (day_key, _) in enumerate(DAYS):
                current_state: tuple[int, str] | None = None
                start_slot: int | None = None
                for t_i in range(horizon.slots + 1):
                    active_state: tuple[int, str] | None = None
                    if t_i < horizon.slots:
                        colloque_group = colloque_group_by_slot.get((d_i, t_i))
                        if (
                            colloque_group == selected_main_group
                            and educator_attends_colloque(educator)
                        ):
                            active_state = (selected_main_group, "colloque")
                        else:
                            for g_i in range(len(groups)):
                                if solution_solver.Value(x[(e_i, d_i, g_i, t_i)]):
                                    replacement = replacement_assignment.get(
                                        (e_i, d_i, g_i, t_i)
                                    )
                                    activity = (
                                        "remplacement_colloque"
                                        if replacement is not None
                                        and solution_solver.Value(replacement)
                                        else "children"
                                    )
                                    active_state = (g_i, activity)
                                    break
                    if active_state != current_state:
                        if current_state is not None and start_slot is not None:
                            start_min = horizon.start + start_slot * horizon.step
                            end_min = horizon.start + t_i * horizon.step
                            group_i, activity = current_state
                            group = groups[group_i]
                            schedule[name][day_key].append(
                                {
                                    "site": group["site"],
                                    "group": group["name"],
                                    "start": format_time(start_min),
                                    "end": format_time(end_min),
                                    "hours": round((end_min - start_min) / 60.0, 2),
                                    "activity": activity,
                                }
                            )
                        current_state = active_state
                        start_slot = t_i if active_state is not None else None

        primary_groups_by_educator = {
            educators[e_i]["name"]: groups[g_i]["name"]
            for e_i, g_i in selected_main_groups.items()
        }
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
        )
        objective = 0.0
        try:
            objective = float(solution_solver.ObjectiveValue())
        except Exception:
            objective = 0.0
        debug(
            "selected_primary_groups="
            + ",".join(
                f"{educators[e_i]['name']}:{groups[g_i]['name']}"
                for e_i, g_i in selected_main_groups.items()
            )
        )
        debug(f"validation hard_errors={len(checks['errors'])}")
        return {
            "status": "ok" if not checks["errors"] else "invalid",
            "objective": round(objective, 4),
            "solver_message": solver_message,
            "warnings": sorted(set(warnings)),
            "schedule": schedule,
            "checks": checks,
            "diagnostics": list(debug_lines),
        }

    class IncumbentProgressCallback(cp_model.CpSolverSolutionCallback):
        def __init__(self, phase: str, progress_percent: int) -> None:
            super().__init__()
            self.phase = phase
            self.progress_percent = progress_percent
            self.solution_count = 0
            self.best_objective: float | None = None

        def on_solution_callback(self) -> None:
            self.solution_count += 1
            if self.phase == "faisabilite":
                objective = float(self.ObjectiveValue())
                message = (
                    f"CP-SAT: candidat realisable {self.solution_count}, "
                    f"note interne {objective:.0f}, validation en cours"
                )
            else:
                objective = float(self.ObjectiveValue())
                if (
                    self.best_objective is not None
                    and objective >= self.best_objective - 1e-6
                ):
                    return
                self.best_objective = objective
                message = (
                    f"CP-SAT: solution {self.solution_count}, "
                    f"note interne {objective:.0f} (plus bas = mieux)"
                )
            debug(f"incumbent phase={self.phase} count={self.solution_count} message={message}")
            if progress_callback:
                progress_callback(self.progress_percent, message)

    total_limit = max(1.0, float(time_limit))
    solve_started_at = time.monotonic()
    feasibility_limit = total_limit
    if fixed_schedule is not None or has_schedule_hint or feasibility_limit < 90.0:
        attempt_specs = [("automatic", cp_model.AUTOMATIC_SEARCH, 1, 1.0)]
    else:
        attempt_specs = [
            ("automatic", cp_model.AUTOMATIC_SEARCH, 1, 0.60),
            ("portfolio", cp_model.PORTFOLIO_SEARCH, 17, 0.25),
            ("pseudo_cost", cp_model.PSEUDO_COST_SEARCH, 43, 0.15),
        ]

    feasibility_attempts: list[dict[str, Any]] = []
    solver: Any = None
    status: Any = None
    remaining_feasibility = feasibility_limit
    if (
        fixed_schedule is None
        and not has_schedule_hint
        and primary_group_candidates
        and feasibility_limit >= 60.0
    ):
        candidate_phase_limit = min(240.0, feasibility_limit * 0.30)
        candidate_count = min(
            len(primary_group_candidates),
            max(1, min(6, int(candidate_phase_limit // 20.0))),
        )
        candidate_limit = candidate_phase_limit / candidate_count
        for candidate_index, candidate_groups in enumerate(
            primary_group_candidates[:candidate_count]
        ):
            elapsed = time.monotonic() - solve_started_at
            remaining_total = max(0.0, total_limit - elapsed)
            if remaining_total < 1.0 or remaining_feasibility < 1.0:
                break
            assumptions = [
                primary_group[(e_i, g_i)]
                for e_i, g_i in candidate_groups.items()
            ]
            model.ClearAssumptions()
            model.AddAssumptions(assumptions)
            solver = cp_model.CpSolver()
            solver.parameters.max_time_in_seconds = min(
                candidate_limit,
                remaining_total,
                remaining_feasibility,
            )
            solver.parameters.num_search_workers = max(
                1,
                min(8, os.cpu_count() or 1),
            )
            solver.parameters.stop_after_first_solution = True
            solver.parameters.random_seed = 101 + candidate_index
            solver.parameters.use_optimization_hints = True
            if os.environ.get("CRECHE_CP_LOG"):
                solver.parameters.log_search_progress = True
            callback = IncumbentProgressCallback("faisabilite", 52)
            if progress_callback:
                progress_callback(
                    50 + min(5, candidate_index),
                    f"CP-SAT groupes candidats {candidate_index + 1}/{candidate_count} "
                    f"(budget {int(solver.parameters.max_time_in_seconds)} s)",
                )
            status = solver.Solve(model, callback)
            statistics = {
                "attempt": len(feasibility_attempts) + 1,
                "strategy": f"primary_candidate_{candidate_index + 1}",
                "status": solver.StatusName(status),
                "wall_time_seconds": round(float(solver.WallTime()), 3),
                "conflicts": int(solver.NumConflicts()),
                "branches": int(solver.NumBranches()),
                "solutions": callback.solution_count,
                "variables": model_variable_count,
                "constraints": model_constraint_count,
            }
            feasibility_attempts.append(statistics)
            remaining_feasibility = max(
                0.0,
                remaining_feasibility - float(solver.WallTime()),
            )
            debug(
                f"primary_candidate={candidate_index + 1} "
                f"status={statistics['status']} wall={statistics['wall_time_seconds']} "
                f"groups="
                + ",".join(
                    f"{educators[e_i]['name']}:{groups[g_i]['name']}"
                    for e_i, g_i in candidate_groups.items()
                )
            )
            if progress_callback:
                progress_callback(
                    52,
                    f"CP-SAT groupes {candidate_index + 1}/{candidate_count}: "
                    f"{statistics['status']} en {statistics['wall_time_seconds']:.1f}s",
                )
            if status in {cp_model.OPTIMAL, cp_model.FEASIBLE}:
                break
        model.ClearAssumptions()

    for attempt_index, (label, strategy, random_seed, share) in enumerate(attempt_specs):
        if status in {cp_model.OPTIMAL, cp_model.FEASIBLE}:
            break
        elapsed = time.monotonic() - solve_started_at
        remaining_total = max(0.0, total_limit - elapsed)
        if remaining_total < 1.0 or remaining_feasibility < 1.0:
            break
        if attempt_index == len(attempt_specs) - 1:
            attempt_limit = remaining_feasibility
        else:
            attempt_limit = max(1.0, feasibility_limit * share)
            attempt_limit = min(attempt_limit, remaining_feasibility)
        solver = cp_model.CpSolver()
        solver.parameters.max_time_in_seconds = min(attempt_limit, remaining_total)
        solver.parameters.num_search_workers = max(1, min(8, os.cpu_count() or 1))
        solver.parameters.stop_after_first_solution = True
        solver.parameters.search_branching = strategy
        solver.parameters.random_seed = random_seed
        if os.environ.get("CRECHE_CP_LOG"):
            solver.parameters.log_search_progress = True
        if has_hint:
            solver.parameters.use_optimization_hints = True
        callback = IncumbentProgressCallback("faisabilite", 55)
        if progress_callback:
            progress_callback(
                50 + min(9, attempt_index * 3),
                f"CP-SAT faisabilite {attempt_index + 1}/{len(attempt_specs)} "
                f"({label}, budget {int(solver.parameters.max_time_in_seconds)} s)",
            )
        status = solver.Solve(model, callback)
        statistics = {
            "attempt": attempt_index + 1,
            "strategy": label,
            "status": solver.StatusName(status),
            "wall_time_seconds": round(float(solver.WallTime()), 3),
            "conflicts": int(solver.NumConflicts()),
            "branches": int(solver.NumBranches()),
            "solutions": callback.solution_count,
            "variables": model_variable_count,
            "constraints": model_constraint_count,
        }
        feasibility_attempts.append(statistics)
        remaining_feasibility = max(
            0.0,
            remaining_feasibility - float(solver.WallTime()),
        )
        debug(
            f"feasibility_attempt={attempt_index + 1} strategy={label} "
            f"status={statistics['status']} wall={statistics['wall_time_seconds']} "
            f"conflicts={statistics['conflicts']} branches={statistics['branches']}"
        )
        if progress_callback:
            progress_callback(
                55,
                f"CP-SAT {statistics['status']}: "
                f"{statistics['wall_time_seconds']:.1f}s, "
                f"{statistics['conflicts']} conflits, "
                f"{statistics['branches']} branches",
            )
        if status in {cp_model.OPTIMAL, cp_model.FEASIBLE}:
            break
        if status == cp_model.INFEASIBLE:
            break

    if solver is None or status not in {cp_model.OPTIMAL, cp_model.FEASIBLE}:
        status_name = solver.StatusName(status) if solver is not None else "UNKNOWN"
        debug(f"feasibility_finished status={status_name} attempts={len(feasibility_attempts)}")
        return (
            {
                "status": "infeasible_or_not_solved",
                "solver_message": status_name,
                "warnings": sorted(set(warnings)),
                "diagnostics": diagnose_basic_conflicts(data, horizon) + debug_lines,
                "cp_sat_statistics": {
                    "feasibility": (
                        feasibility_attempts[-1] if feasibility_attempts else None
                    ),
                    "feasibility_attempts": feasibility_attempts,
                    "optimization": None,
                },
            },
            bundle,
        )

    first_statistics = feasibility_attempts[-1]
    first_payload = build_candidate(
        solver,
        status,
        f"OR-Tools CP-SAT {solver.StatusName(status)}",
    )
    first_score = planning_quality_score(first_payload)
    debug(f"first_candidate status={first_payload['status']} score={first_score:.0f}")
    if payload_is_hard_valid(first_payload):
        if progress_callback:
            progress_callback(
                60,
                f"Solution hard-valide trouvee - note {first_score:.0f} "
                "(plus bas = mieux)",
            )
        if candidate_callback is not None:
            candidate_callback(first_payload, bundle)
    elif not accept_invalid_for_hint:
        first_payload["cp_sat_statistics"] = {
            "feasibility": first_statistics,
            "feasibility_attempts": feasibility_attempts,
            "optimization": None,
        }
        first_payload["diagnostics"] = list(debug_lines)
        return first_payload, bundle

    best_payload = first_payload
    optimization_statistics: dict[str, Any] | None = None
    remaining_for_optimization = max(
        0.0,
        total_limit - (time.monotonic() - solve_started_at),
    )
    if fixed_schedule is None and remaining_for_optimization >= 1.0:
        model.ClearHints()
        hinted_variables = (
            list(primary_group.values())
            + list(x.values())
            + list(work.values())
            + list(work_day.values())
            + list(site_day.values())
            + list(half_group.values())
            + list(group_day.values())
            + list(mixed_day.values())
            + list(outside_primary_day.values())
            + list(outside_primary_group_day.values())
            + list(start_var.values())
            + list(replacement_assignment.values())
        )
        for var in hinted_variables:
            model.AddHint(var, int(solver.Value(var)))
        optimizer = cp_model.CpSolver()
        optimizer.parameters.max_time_in_seconds = remaining_for_optimization
        optimizer.parameters.num_search_workers = max(1, min(8, os.cpu_count() or 1))
        optimizer.parameters.relative_gap_limit = 0.05
        optimizer.parameters.use_optimization_hints = True
        if os.environ.get("CRECHE_CP_LOG"):
            optimizer.parameters.log_search_progress = True
        if progress_callback:
            progress_callback(
                64,
                f"Optimisation de la qualite (budget {int(remaining_for_optimization)} s)",
            )
        optimization_callback = IncumbentProgressCallback("optimisation", 70)
        opt_status = optimizer.Solve(model, optimization_callback)
        optimization_statistics = {
            "status": optimizer.StatusName(opt_status),
            "wall_time_seconds": round(float(optimizer.WallTime()), 3),
            "conflicts": int(optimizer.NumConflicts()),
            "branches": int(optimizer.NumBranches()),
            "solutions": optimization_callback.solution_count,
        }
        debug(
            f"optimization status={optimization_statistics['status']} "
            f"wall={optimization_statistics['wall_time_seconds']} "
            f"conflicts={optimization_statistics['conflicts']} "
            f"branches={optimization_statistics['branches']}"
        )
        if opt_status in {cp_model.OPTIMAL, cp_model.FEASIBLE}:
            optimized_payload = build_candidate(
                optimizer,
                opt_status,
                f"OR-Tools CP-SAT {optimizer.StatusName(opt_status)}",
            )
            optimized_score = planning_quality_score(optimized_payload)
            if accept_invalid_for_hint or (
                payload_is_hard_valid(optimized_payload)
                and optimized_score <= first_score
            ):
                best_payload = optimized_payload
                if progress_callback and payload_is_hard_valid(optimized_payload):
                    progress_callback(
                        90,
                        f"Meilleure solution hard-valide - note {optimized_score:.0f}",
                    )
                if (
                    candidate_callback is not None
                    and payload_is_hard_valid(best_payload)
                ):
                    candidate_callback(best_payload, bundle)
            elif not payload_is_hard_valid(optimized_payload):
                warnings.append(
                    "Amelioration CP-SAT invalide apres verification; "
                    "premiere solution hard-valide conservee."
                )

    best_payload["warnings"] = sorted(set(warnings + list(best_payload.get("warnings", []))))
    best_payload["diagnostics"] = list(debug_lines)
    best_payload["cp_sat_statistics"] = {
        "feasibility": first_statistics,
        "feasibility_attempts": feasibility_attempts,
        "optimization": optimization_statistics,
    }
    return best_payload, bundle


def make_pattern_mip_payload(
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
    from .pattern_mip import PatternTimeLimitError, solve_pattern_mip

    try:
        return solve_pattern_mip(
            data,
            time_limit=time_limit,
            type_aliases=type_aliases,
            min_daily_hours=min_daily_hours,
            enforce_min_daily_hours=enforce_min_daily_hours,
            short_day_penalty_weight=short_day_penalty_weight,
            max_split_gap_minutes=max_split_gap_minutes,
            generation_max_split_gap_minutes=generation_max_split_gap_minutes,
            generation_time_step_minutes=generation_time_step_minutes,
            fine_generation_time_step_minutes=fine_generation_time_step_minutes,
            fine_time_step_educators=fine_time_step_educators,
            fixed_daily_schedules=fixed_daily_schedules,
            reference_daily_schedules=reference_daily_schedules,
            continuous_only_educators=continuous_only_educators,
            weekly_hours_tolerance_minutes=weekly_hours_tolerance_minutes,
            weekly_hours_tolerance_percent=weekly_hours_tolerance_percent,
            weekly_hours_tolerance_step_minutes=weekly_hours_tolerance_step_minutes,
            enforce_absolute_max_weekly_hours=enforce_absolute_max_weekly_hours,
            absolute_max_weekly_hours=absolute_max_weekly_hours,
            the_enabled=the_enabled,
            the_percent=the_percent,
            the_colloques_count=the_colloques_count,
            half_day_split_time=half_day_split_time,
            max_weekly_group_exception_days=max_weekly_group_exception_days,
            split_shift_weight=split_shift_weight,
            split_gap_weight=split_gap_weight,
            group_switch_day_weight=group_switch_day_weight,
            same_group_week_weight=same_group_week_weight,
            soft_time_rule_weight=soft_time_rule_weight,
            soft_group_rule_weight=soft_group_rule_weight,
            compact_work_days=compact_work_days,
            compact_work_day_weight=compact_work_day_weight,
            compact_part_time_priority=compact_part_time_priority,
            hard_max_work_days=hard_max_work_days,
            feasible_only=feasible_only,
            restricted_patterns=restricted_patterns,
            restricted_pattern_mode=restricted_pattern_mode,
            fixed_primary_groups=fixed_primary_groups,
            quality_profile=quality_profile,
            quality_profile_label=quality_profile_label,
            primary_group_report_enabled=primary_group_report_enabled,
            primary_group_warning_outside_hours=primary_group_warning_outside_hours,
            primary_group_warning_outside_days=primary_group_warning_outside_days,
            progress_callback=progress_callback,
        )
    except PatternTimeLimitError as exc:
        return exc.payload, exc.bundle


def planning_quality_score(payload: dict[str, Any]) -> float:
    if payload.get("status") != "ok":
        return 1_000_000_000.0

    schedule = payload.get("schedule", {})
    errors = len(payload.get("checks", {}).get("errors", []))
    blocks = 0
    extra_blocks = 0
    bad_days = 0
    mixed_groups = 0
    mixed_sites = 0

    for by_day in schedule.values():
        educator_groups: set[str] = set()
        educator_sites: set[str] = set()
        for day_blocks in by_day.values():
            day_count = len(day_blocks)
            blocks += day_count
            extra_blocks += max(0, day_count - 1)
            if day_count > 3:
                bad_days += 1
            educator_groups.update(str(block.get("group", "")) for block in day_blocks)
            educator_sites.update(str(block.get("site", "")) for block in day_blocks)
        mixed_groups += max(0, len({item for item in educator_groups if item}) - 1)
        mixed_sites += max(0, len({item for item in educator_sites if item}) - 1)

    return (
        errors * 1_000_000
        + bad_days * 10_000
        + mixed_sites * 1_500
        + mixed_groups * 900
        + extra_blocks * 80
        + blocks * 10
    )


def infer_preferred_groups_from_payload(
    data: dict[str, Any],
    payload: dict[str, Any] | None,
) -> dict[int, int]:
    if not payload or not isinstance(payload.get("schedule"), dict):
        return {}
    educators = list(data.get("educators", []))
    groups = list(data.get("groups", []))
    educator_by_name = {educator["name"]: e_i for e_i, educator in enumerate(educators)}
    group_by_name = {group["name"]: g_i for g_i, group in enumerate(groups)}
    explicit = payload.get("checks", {}).get("primary_groups_by_educator", {})
    if isinstance(explicit, dict):
        mapped = {
            educator_by_name[educator_name]: group_by_name[group_name]
            for educator_name, group_name in explicit.items()
            if educator_name in educator_by_name and group_name in group_by_name
        }
        if mapped:
            return mapped
    totals: dict[int, dict[int, int]] = {}
    for educator_name, by_day in payload.get("schedule", {}).items():
        if educator_name not in educator_by_name or not isinstance(by_day, dict):
            continue
        e_i = educator_by_name[educator_name]
        for blocks in by_day.values():
            if not isinstance(blocks, list):
                continue
            for block in blocks:
                group_name = block.get("group")
                if group_name not in group_by_name:
                    continue
                minutes = int(round(float(block.get("hours", 0.0)) * 60))
                totals.setdefault(e_i, {})
                totals[e_i][group_by_name[group_name]] = totals[e_i].get(group_by_name[group_name], 0) + minutes
    return {
        e_i: max(group_totals.items(), key=lambda item: item[1])[0]
        for e_i, group_totals in totals.items()
        if group_totals
    }


def load_latest_valid_payload(*paths: Path | None) -> dict[str, Any] | None:
    explicit_candidates: list[Path] = []
    seen: set[Path] = set()
    for path in paths:
        if path is None:
            continue
        resolved = path.resolve()
        if resolved not in seen and resolved.exists():
            explicit_candidates.append(resolved)
            seen.add(resolved)

    for candidate in explicit_candidates:
        try:
            payload = load_json(candidate)
        except Exception:
            continue
        if payload.get("status") == "ok" and isinstance(payload.get("schedule"), dict):
            return payload

    fallback_candidates: list[Path] = []
    for path in paths:
        if path is None:
            continue
        resolved = path.resolve()
        directory = resolved.parent
        if directory.exists():
            for candidate in directory.glob("*.json"):
                candidate = candidate.resolve()
                if candidate not in seen:
                    fallback_candidates.append(candidate)
                    seen.add(candidate)

    fallback_candidates.sort(
        key=lambda item: item.stat().st_mtime if item.exists() else 0.0,
        reverse=True,
    )
    for candidate in fallback_candidates:
        try:
            payload = load_json(candidate)
        except Exception:
            continue
        if payload.get("status") == "ok" and isinstance(payload.get("schedule"), dict):
            return payload
    return None


def revalidate_cached_payload(
    data: dict[str, Any],
    payload: dict[str, Any] | None,
    **verification_options: Any,
) -> tuple[dict[str, Any], Any] | None:
    if not payload or not isinstance(payload.get("schedule"), dict):
        return None
    groups = list(data.get("groups", []))
    educators = list(data.get("educators", []))
    sites = [site["name"] for site in data.get("sites", [])]
    schedule = payload["schedule"]
    missing_entries = [
        f"{educator['name']}:{day_key}"
        for educator in educators
        for day_key, _label in DAYS
        if not isinstance(schedule.get(educator["name"]), dict)
        or not isinstance(schedule[educator["name"]].get(day_key), list)
    ]
    if missing_entries:
        candidate = dict(payload)
        errors = [
            "Planning en cache incomplet: "
            + ", ".join(missing_entries[:10])
            + ("..." if len(missing_entries) > 10 else "")
        ]
        candidate["checks"] = {"errors": errors, "hard_errors": errors}
        candidate["status"] = "invalid"
        candidate["solver_message"] = "Dernier planning refuse: structure incomplete."
        return candidate, None
    bundle = type(
        "CachedPlanningBundle",
        (),
        {
            "data": data,
            "horizon": make_horizon(data),
            "groups": groups,
            "educators": educators,
            "sites": sites,
        },
    )()
    primary_groups = payload.get("checks", {}).get("primary_groups_by_educator", {})
    if not isinstance(primary_groups, dict) or not primary_groups:
        preferred = infer_preferred_groups_from_payload(data, payload)
        primary_groups = {
            educators[e_i]["name"]: groups[g_i]["name"]
            for e_i, g_i in preferred.items()
            if 0 <= e_i < len(educators) and 0 <= g_i < len(groups)
        }
    checks = verify_solution(
        bundle,
        schedule,
        primary_groups_by_educator=primary_groups,
        **verification_options,
    )
    candidate = dict(payload)
    candidate["checks"] = checks
    candidate["status"] = "ok" if not checks["errors"] else "invalid"
    candidate["diagnostics"] = [
        "Planning en cache revalide avec les donnees et regles actuelles."
    ]
    candidate["solver_message"] = (
        "Dernier planning revalide avec les donnees et regles actuelles."
        if candidate["status"] == "ok"
        else "Dernier planning refuse apres revalidation avec les regles actuelles."
    )
    return candidate, bundle


def infer_majority_primary_groups_from_payload(
    data: dict[str, Any],
    payload: dict[str, Any] | None,
) -> dict[int, int]:
    if not payload or not isinstance(payload.get("schedule"), dict):
        return {}

    educators = list(data.get("educators", []))
    groups = list(data.get("groups", []))
    if not educators or not groups:
        return {}

    horizon = make_horizon(data)
    warnings: list[str] = []
    colloques = parse_colloques(data, horizon, groups, warnings)
    colloque_by_group = {int(colloque["group_i"]): colloque for colloque in colloques}
    educator_by_name = {educator["name"]: e_i for e_i, educator in enumerate(educators)}
    group_by_name = {group["name"]: g_i for g_i, group in enumerate(groups)}
    allowed_groups: dict[int, set[int]] = {
        e_i: set(range(len(groups)))
        for e_i in range(len(educators))
    }
    forced_groups: dict[int, int] = {}

    for raw_rule in data.get("rules_group", []):
        if len(raw_rule) < 4:
            continue
        pref_type, strength, educator_name, group_name = raw_rule[:4]
        if educator_name not in educator_by_name or group_name not in group_by_name:
            continue
        if normalize_flag(strength) != "hard":
            continue
        e_i = educator_by_name[educator_name]
        g_i = group_by_name[group_name]
        is_negative = normalize_flag(pref_type) in {"negatif", "negative", "neg"}
        if is_negative:
            allowed_groups[e_i].discard(g_i)
        else:
            forced_groups[e_i] = g_i

    for e_i, educator in enumerate(educators):
        if not educator_attends_colloque(educator):
            continue
        educator_name = educator["name"]
        for g_i, colloque in colloque_by_group.items():
            if g_i not in allowed_groups[e_i]:
                continue
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
                    allowed_groups[e_i].discard(g_i)
                    break

    explicit = payload.get("checks", {}).get("primary_groups_by_educator", {})
    previous_primary: dict[int, int] = {}
    if isinstance(explicit, dict):
        previous_primary = {
            educator_by_name[educator_name]: group_by_name[group_name]
            for educator_name, group_name in explicit.items()
            if educator_name in educator_by_name and group_name in group_by_name
        }

    totals: dict[int, dict[int, int]] = {}
    for educator_name, by_day in payload.get("schedule", {}).items():
        if educator_name not in educator_by_name or not isinstance(by_day, dict):
            continue
        e_i = educator_by_name[educator_name]
        for blocks in by_day.values():
            if not isinstance(blocks, list):
                continue
            for block in blocks:
                if block.get("activity") in {"colloque", "remplacement_colloque"}:
                    continue
                group_name = block.get("group")
                if group_name not in group_by_name:
                    continue
                minutes = int(round(float(block.get("hours", 0.0)) * 60))
                totals.setdefault(e_i, {})
                g_i = group_by_name[group_name]
                totals[e_i][g_i] = totals[e_i].get(g_i, 0) + minutes

    result: dict[int, int] = {}
    for e_i in range(len(educators)):
        allowed = allowed_groups.get(e_i, set())
        if e_i in forced_groups and forced_groups[e_i] in allowed:
            result[e_i] = forced_groups[e_i]
            continue
        ranked = sorted(
            (
                (minutes, g_i)
                for g_i, minutes in totals.get(e_i, {}).items()
                if g_i in allowed
            ),
            reverse=True,
        )
        if ranked:
            result[e_i] = ranked[0][1]
            continue
        previous = previous_primary.get(e_i)
        if previous in allowed:
            result[e_i] = previous
            continue
        if allowed:
            result[e_i] = sorted(allowed)[0]
    return result


def diagnose_basic_conflicts(data: dict[str, Any], horizon: Horizon) -> list[str]:
    diagnostics: list[str] = []
    targets = {
        educator["name"]: float(educator["percentage"])
        for educator in data.get("educators", [])
    }

    for rule in data.get("rules_time", []):
        if len(rule) < 6:
            continue
        pos_neg, hard_soft, educator, day, start, end = rule[:6]
        if normalize_flag(pos_neg) != "positif" or normalize_flag(hard_soft) != "hard":
            continue
        start_min = max(parse_time(str(start)), horizon.start)
        end_min = min(parse_time(str(end)), horizon.end)
        if end_min <= start_min:
            diagnostics.append(f"{educator} a une regle positif hard {day} sans plage utilisable.")
            continue
        if educator in targets and targets[educator] <= 0:
            diagnostics.append(f"{educator} a une regle positif hard, mais son pourcentage est 0%.")
    return diagnostics


def diagnose_the_capacity(
    data: dict[str, Any],
    horizon: Horizon,
    *,
    weekly_hours_tolerance_percent: float = 3.0,
    weekly_hours_tolerance_minutes: int | None = None,
    weekly_hours_tolerance_step_minutes: int | None = 15,
    enforce_absolute_max_weekly_hours: bool = True,
    absolute_max_weekly_hours: float | None = 40.0,
    the_enabled: bool = True,
    the_percent: float = 10.0,
) -> list[str]:
    if not the_enabled:
        return []

    groups = list(data.get("groups", []))
    educators = list(data.get("educators", []))
    if not groups or not educators:
        return []

    group_demand, site_demand = build_demands_by_day(data, groups, horizon)
    warnings: list[str] = []
    colloques = parse_colloques(data, horizon, groups, warnings)
    colloque_minimums: dict[tuple[int, int, int], int] = {}
    for colloque in colloques:
        minimum = max(0, len(groups) - 1)
        for slot in colloque["slots"]:
            key = (int(colloque["day_i"]), int(colloque["group_i"]), int(slot))
            colloque_minimums[key] = max(colloque_minimums.get(key, 0), minimum)

    demand_slots = 0
    for d_i in range(len(DAYS)):
        for t_i in range(horizon.slots):
            slot_demands: dict[int, int] = {}
            for g_i, group in enumerate(groups):
                demand = group_demand[(d_i, g_i, t_i)]
                demand = max(demand, colloque_minimums.get((d_i, g_i, t_i), 0))
                slot_demands[g_i] = demand
                demand_slots += demand
            for (demand_d_i, site, site_slot), site_minimum in site_demand.items():
                if demand_d_i != d_i or site_slot != t_i:
                    continue
                site_total = sum(
                    demand
                    for g_i, demand in slot_demands.items()
                    if groups[g_i].get("site") == site
                )
                demand_slots += max(0, int(site_minimum) - site_total)

    weekly_base = float(data.get("rules_global", {}).get("max_weekly_hours", 40.0))
    absolute_max_slots = absolute_weekly_max_slots(
        horizon,
        absolute_max_weekly_hours if enforce_absolute_max_weekly_hours else None,
    )
    capacity_slots = 0
    for educator in educators:
        target_hours = float(educator.get("percentage", 0.0)) / 100.0 * weekly_base
        target_slots = int(round(target_hours / (horizon.step / 60.0)))
        tolerance_slots = weekly_tolerance_slots(
            target_hours,
            horizon,
            percent=weekly_hours_tolerance_percent,
            minutes=weekly_hours_tolerance_minutes,
            step_minutes=weekly_hours_tolerance_step_minutes,
        )
        upper_target = target_slots + tolerance_slots
        if absolute_max_slots is not None:
            upper_target = min(upper_target, absolute_max_slots)
        capacity_slots += max(0, upper_target - the_target_slots(target_slots, the_percent, enabled=True))

    if capacity_slots + 1e-9 >= demand_slots:
        return warnings

    step_hours = horizon.step / 60.0
    missing = (demand_slots - capacity_slots) * step_hours
    diagnostics = list(warnings)
    diagnostics.append(
        "Capacite enfants insuffisante avec le THE: "
        f"besoin minimum {demand_slots * step_hours:.2f}h, "
        f"capacite maximale {capacity_slots * step_hours:.2f}h, "
        f"manque {missing:.2f}h. "
        "Il faut augmenter les heures disponibles, reduire certains besoins minimums, "
        "ou assouplir une contrainte contractuelle."
    )
    return diagnostics


def main() -> int:
    parser = argparse.ArgumentParser(description="Solveur de planning creche base sur scipy.milp.")
    parser.add_argument("json_path", nargs="?", type=Path, help="Fichier JSON de planning.")
    parser.add_argument("--config", type=Path, help="Fichier de configuration du solveur.")
    parser.add_argument("--output", type=Path, help="Fichier JSON de sortie.")
    parser.add_argument("--csv", type=Path, help="Fichier CSV de sortie.")
    parser.add_argument("--html", type=Path, help="Fichier HTML visuel de sortie.")
    parser.add_argument(
        "--timestamp-outputs",
        action="store_true",
        default=None,
        help="Ajoute la date et l'heure aux fichiers de sortie.",
    )
    parser.add_argument(
        "--no-timestamp-outputs",
        action="store_true",
        default=None,
        help="Desactive l'horodatage des fichiers de sortie.",
    )
    parser.add_argument("--time-limit", type=float, help="Limite en secondes.")
    parser.add_argument("--mip-gap", type=float, help="Gap MIP relatif.")
    parser.add_argument("--weekly-mode", choices=["exact", "maximum"])
    parser.add_argument(
        "--quality-profile",
        help="Profil de qualite a utiliser: equilibre, journees_continues, groupes_stables, preferences_horaires, preferences_groupes.",
    )
    parser.add_argument(
        "--fast-feasible",
        action="store_true",
        default=None,
        help="Cherche d'abord une solution valide sans objectif de lisibilite.",
    )
    parser.add_argument(
        "--structured",
        action="store_true",
        default=None,
        help="Force au plus un groupe par jour et deux blocs de travail par jour.",
    )
    parser.add_argument(
        "--smooth",
        action="store_true",
        default=None,
        help="Lisse chaque jour/site apres une solution globale rapide.",
    )
    parser.add_argument(
        "--smooth-time-limit",
        type=float,
        help="Temps maximum par sous-probleme de lissage.",
    )
    parser.add_argument(
        "--smooth-split-shift-weight",
        type=float,
        help="Poids pour eviter les horaires coupes.",
    )
    parser.add_argument(
        "--smooth-split-gap-weight",
        type=float,
        help="Poids pour raccourcir le trou entre deux blocs de travail.",
    )
    parser.add_argument(
        "--smooth-max-split-gap-minutes",
        type=int,
        help="Duree maximale d'une coupure en minutes.",
    )
    parser.add_argument(
        "--smooth-group-switch-day-weight",
        type=float,
        help="Poids pour eviter plusieurs groupes dans la meme journee.",
    )
    parser.add_argument(
        "--smooth-same-group-week-weight",
        type=float,
        help="Poids pour garder un educateur dans son groupe principal sur la semaine.",
    )
    parser.add_argument(
        "--weekly-hours-tolerance-percent",
        type=float,
        help="Tolerance sur les heures hebdomadaires contractuelles, en pourcentage.",
    )
    parser.add_argument(
        "--weekly-hours-tolerance-minutes",
        type=int,
        help="Tolerance sur les heures hebdomadaires contractuelles, en minutes.",
    )
    parser.add_argument(
        "--weekly-stability",
        action="store_true",
        default=None,
        help="Penalise fortement les changements de groupe/site sur la semaine.",
    )
    parser.add_argument(
        "--no-weekly-stability",
        action="store_true",
        default=None,
        help="Desactive les penalites de stabilite hebdomadaire.",
    )
    parser.add_argument(
        "--main-group-day-weight",
        type=float,
        help="Poids pour chaque jour passe hors du groupe principal.",
    )
    parser.add_argument(
        "--main-group-slot-weight",
        type=float,
        help="Poids par tranche de 15 minutes hors du groupe principal.",
    )
    parser.add_argument(
        "--main-site-day-weight",
        type=float,
        help="Poids pour chaque jour passe hors du site principal.",
    )
    parser.add_argument(
        "--half-day-split-time",
        help="Heure qui separe matin et apres-midi pour interdire les changements intra demi-journee.",
    )
    parser.add_argument(
        "--max-weekly-group-exception-days",
        type=int,
        help="Nombre maximal de jours hors groupe principal par educateur.",
    )
    parser.add_argument(
        "--max-blocks-per-day",
        type=int,
        help="Nombre maximal de blocs de travail par educateur et par jour.",
    )
    parser.add_argument(
        "--min-daily-hours",
        type=float,
        help="Si un educateur travaille une journee, impose ce minimum d'heures.",
    )
    parser.add_argument(
        "--type-alias",
        action="append",
        default=[],
        help="Alias de type, ex: ANCIEN=NOUVEAU. Peut etre repete.",
    )
    args = parser.parse_args()

    config, config_dir = load_run_config(args.config)
    quality_profile_name, quality_profile_label, profile_weights, profile_warnings = select_quality_profile(
        config,
        args.quality_profile,
    )
    json_path = args.json_path or resolve_config_path(config.get("input_json"), config_dir)
    if json_path is None:
        parser.error("Indiquez un fichier JSON ou un fichier --config avec input_json.")

    output_path = args.output or resolve_config_path(config.get("output_json"), config_dir)
    csv_path = args.csv or resolve_config_path(config.get("csv_output"), config_dir)
    html_path = args.html or resolve_config_path(config.get("html_output"), config_dir)
    write_latest_outputs = bool(config.get("write_latest_outputs", True))
    latest_output_path = (
        resolve_config_path(config.get("latest_output_json", "planning_gwendo_latest.json"), config_dir)
        if write_latest_outputs
        else None
    )
    latest_csv_path = (
        resolve_config_path(config.get("latest_csv_output", "planning_gwendo_latest.csv"), config_dir)
        if write_latest_outputs
        else None
    )
    latest_html_path = (
        resolve_config_path(config.get("latest_html_output", "planning_gwendo_latest.html"), config_dir)
        if write_latest_outputs
        else None
    )
    initial_solution_path = resolve_config_path(
        config.get("initial_solution_json"),
        config_dir,
    )
    timestamp_outputs = bool(config.get("timestamp_outputs", False))
    if args.timestamp_outputs:
        timestamp_outputs = True
    if args.no_timestamp_outputs:
        timestamp_outputs = False
    timestamp = None
    if timestamp_outputs:
        timestamp = datetime.now().strftime(str(config.get("timestamp_format", "%Y-%m-%d_%H-%M-%S")))
        output_path = timestamped_path(output_path, timestamp)
        csv_path = timestamped_path(csv_path, timestamp)
        html_path = timestamped_path(html_path, timestamp)
    time_limit = float(pick(args.time_limit, config, "time_limit_seconds", 300.0))
    raw_compact_candidate_time = config.get("compact_candidate_time_seconds")
    compact_candidate_time = (
        None
        if raw_compact_candidate_time is None
        else max(1.0, float(raw_compact_candidate_time))
    )
    pattern_fallback_time = max(
        0.0,
        float(config.get("pattern_fallback_time_seconds", 60.0)),
    )
    run_started_at = time.monotonic()

    def remaining_time_limit() -> float:
        return max(0.0, time_limit - (time.monotonic() - run_started_at))

    mip_gap = float(pick(args.mip_gap, config, "quality_gap", 0.01))
    weekly_mode = pick(args.weekly_mode, config, "weekly_mode", "exact")
    fast_feasible = bool(pick(args.fast_feasible, config, "fast_feasible", False))
    structured = bool(pick(args.structured, config, "structured", False))
    smooth = bool(pick(args.smooth, config, "smooth", False))
    smooth_time_limit = float(pick(args.smooth_time_limit, config, "smooth_time_limit_seconds", 30.0))
    split_shift_weight = float(pick(args.smooth_split_shift_weight, config, "smooth_split_shift_weight", 120.0))
    split_gap_weight = float(pick(args.smooth_split_gap_weight, config, "smooth_split_gap_weight", 4.0))
    if args.smooth_split_shift_weight is None:
        split_shift_weight = float(profile_weights.get("smooth_split_shift_weight", split_shift_weight))
    if args.smooth_split_gap_weight is None:
        split_gap_weight = float(profile_weights.get("smooth_split_gap_weight", split_gap_weight))
    max_split_gap_minutes = effective_max_split_gap_minutes(config, args.smooth_max_split_gap_minutes)
    enforce_max_split_gap = bool(config.get("enforce_max_pause_between_blocks", False))
    hard_max_split_gap_minutes = max_split_gap_minutes if enforce_max_split_gap else None
    group_switch_day_weight = float(
        pick(args.smooth_group_switch_day_weight, config, "smooth_group_switch_day_weight", 8.0)
    )
    same_group_week_weight = float(
        pick(args.smooth_same_group_week_weight, config, "smooth_same_group_week_weight", 0.4)
    )
    if args.smooth_group_switch_day_weight is None:
        group_switch_day_weight = float(profile_weights.get("smooth_group_switch_day_weight", group_switch_day_weight))
    if args.smooth_same_group_week_weight is None:
        same_group_week_weight = float(profile_weights.get("smooth_same_group_week_weight", same_group_week_weight))
    soft_time_rule_weight = float(config.get("soft_time_rule_weight", 1.0))
    soft_group_rule_weight = float(config.get("soft_group_rule_weight", 1.0))
    soft_time_rule_weight = float(profile_weights.get("soft_time_rule_weight", soft_time_rule_weight))
    soft_group_rule_weight = float(profile_weights.get("soft_group_rule_weight", soft_group_rule_weight))
    compact_work_days = bool(config.get("compact_work_days", True))
    compact_work_day_weight = float(config.get("compact_work_day_weight", 45.0))
    compact_work_day_weight = float(profile_weights.get("compact_work_day_weight", compact_work_day_weight))
    compact_part_time_priority = bool(config.get("compact_part_time_priority", True))
    relax_work_days_if_infeasible = bool(config.get("relax_work_days_if_infeasible", False))
    relaxed_work_day_weight = float(
        config.get("relaxed_work_day_weight", max(500.0, compact_work_day_weight))
    )
    fix_primary_groups_from_latest = bool(config.get("fix_primary_groups_from_latest", False))
    restricted_patterns = bool(config.get("restricted_patterns", False))
    restricted_pattern_mode = str(config.get("restricted_pattern_mode", "primary_only"))
    hard_max_work_days = bool(config.get("hard_max_work_days", True))
    enforce_absolute_max_weekly_hours = bool(config.get("enforce_absolute_max_weekly_hours", True))
    absolute_max_weekly_hours = config.get("absolute_max_weekly_hours", 40.0)
    if absolute_max_weekly_hours is not None:
        absolute_max_weekly_hours = float(absolute_max_weekly_hours)
    weekly_hours_tolerance_percent = float(
        pick(args.weekly_hours_tolerance_percent, config, "weekly_hours_tolerance_percent", 3.0)
    )
    raw_weekly_minutes = pick(args.weekly_hours_tolerance_minutes, config, "weekly_hours_tolerance_minutes", None)
    weekly_hours_tolerance_minutes = None if raw_weekly_minutes is None else int(raw_weekly_minutes)
    raw_tolerance_step = config.get("weekly_hours_tolerance_step_minutes", 15)
    weekly_hours_tolerance_step_minutes = None if raw_tolerance_step is None else int(raw_tolerance_step)
    the_enabled = bool(config.get("the_enabled", True))
    the_percent = float(config.get("the_percent", 10.0))
    the_colloques_count = bool(config.get("the_colloques_count", True))
    weekly_stability = bool(config.get("weekly_stability", True))
    if args.weekly_stability:
        weekly_stability = True
    if args.no_weekly_stability:
        weekly_stability = False
    primary_group_config = config.get("primary_group", {})
    if not isinstance(primary_group_config, dict):
        primary_group_config = {}
    primary_group_report_enabled = bool(primary_group_config.get("report_enabled", True))
    primary_group_warning_outside_hours = float(primary_group_config.get("warning_outside_hours", 4.0))
    primary_group_warning_outside_days = int(primary_group_config.get("warning_outside_days", 1))
    main_group_day_weight = float(
        args.main_group_day_weight
        if args.main_group_day_weight is not None
        else primary_group_config.get("day_weight", config.get("main_group_day_weight", 80.0))
    )
    main_group_slot_weight = float(
        args.main_group_slot_weight
        if args.main_group_slot_weight is not None
        else primary_group_config.get("slot_weight", config.get("main_group_slot_weight", 3.0))
    )
    main_site_day_weight = float(
        args.main_site_day_weight
        if args.main_site_day_weight is not None
        else primary_group_config.get("site_day_weight", config.get("main_site_day_weight", 100.0))
    )
    if args.main_group_day_weight is None:
        main_group_day_weight = float(profile_weights.get("main_group_day_weight", main_group_day_weight))
    if args.main_group_slot_weight is None:
        main_group_slot_weight = float(profile_weights.get("main_group_slot_weight", main_group_slot_weight))
    if args.main_site_day_weight is None:
        main_site_day_weight = float(profile_weights.get("main_site_day_weight", main_site_day_weight))
    half_day_split_time = str(pick(args.half_day_split_time, config, "half_day_split_time", "12:30"))
    max_weekly_group_exception_days = pick(
        args.max_weekly_group_exception_days,
        config,
        "max_weekly_group_exception_days",
        1,
    )
    if max_weekly_group_exception_days is not None:
        max_weekly_group_exception_days = int(max_weekly_group_exception_days)
    min_daily_hours = float(pick(args.min_daily_hours, config, "min_daily_hours", 0.0))
    enforce_min_daily_hours = bool(config.get("enforce_min_daily_hours", False))
    short_day_penalty_weight = float(config.get("short_day_penalty_weight", 30.0))
    max_blocks_per_day = pick(args.max_blocks_per_day, config, "max_blocks_per_day", None)
    if max_blocks_per_day is not None:
        max_blocks_per_day = int(max_blocks_per_day)

    emit_progress(3, "Lecture des donnees")
    data = load_json(json_path)
    aliases = config_aliases(config.get("type_aliases"))
    aliases.update(parse_aliases(args.type_alias))
    latest_payload = load_latest_valid_payload(latest_output_path, output_path)
    revalidated_latest = revalidate_cached_payload(
        data,
        latest_payload,
        half_day_split_time=half_day_split_time,
        max_weekly_group_exception_days=max_weekly_group_exception_days,
        max_split_gap_minutes=hard_max_split_gap_minutes,
        hard_max_work_days=hard_max_work_days,
        weekly_hours_tolerance_percent=weekly_hours_tolerance_percent,
        weekly_hours_tolerance_minutes=weekly_hours_tolerance_minutes,
        weekly_hours_tolerance_step_minutes=weekly_hours_tolerance_step_minutes,
        enforce_absolute_max_weekly_hours=enforce_absolute_max_weekly_hours,
        absolute_max_weekly_hours=absolute_max_weekly_hours,
        the_enabled=the_enabled,
        the_percent=the_percent,
        the_colloques_count=the_colloques_count,
        quality_profile=quality_profile_name,
        quality_profile_label=quality_profile_label,
        primary_group_report_enabled=primary_group_report_enabled,
        primary_group_warning_outside_hours=primary_group_warning_outside_hours,
        primary_group_warning_outside_days=primary_group_warning_outside_days,
    )
    initial_solution_used = False
    if (
        initial_solution_path is not None
        and initial_solution_path.exists()
        and (
            revalidated_latest is None
            or not payload_is_hard_valid(revalidated_latest[0])
        )
    ):
        try:
            initial_payload = load_json(initial_solution_path)
        except Exception as exc:
            profile_warnings.append(
                f"Solution initiale illisible ({initial_solution_path.name}): {exc}"
            )
        else:
            revalidated_initial = revalidate_cached_payload(
                data,
                initial_payload,
                half_day_split_time=half_day_split_time,
                max_weekly_group_exception_days=max_weekly_group_exception_days,
                max_split_gap_minutes=hard_max_split_gap_minutes,
                hard_max_work_days=hard_max_work_days,
                weekly_hours_tolerance_percent=weekly_hours_tolerance_percent,
                weekly_hours_tolerance_minutes=weekly_hours_tolerance_minutes,
                weekly_hours_tolerance_step_minutes=weekly_hours_tolerance_step_minutes,
                enforce_absolute_max_weekly_hours=enforce_absolute_max_weekly_hours,
                absolute_max_weekly_hours=absolute_max_weekly_hours,
                the_enabled=the_enabled,
                the_percent=the_percent,
                the_colloques_count=the_colloques_count,
                quality_profile=quality_profile_name,
                quality_profile_label=quality_profile_label,
                primary_group_report_enabled=primary_group_report_enabled,
                primary_group_warning_outside_hours=primary_group_warning_outside_hours,
                primary_group_warning_outside_days=primary_group_warning_outside_days,
            )
            if (
                revalidated_initial is not None
                and payload_is_hard_valid(revalidated_initial[0])
            ):
                latest_payload = revalidated_initial[0]
                revalidated_latest = revalidated_initial
                initial_solution_used = True
            else:
                profile_warnings.append(
                    "Solution initiale refusee: elle ne passe plus la validation hard."
                )
    fixed_primary_groups = (
        infer_majority_primary_groups_from_payload(data, latest_payload)
        if fix_primary_groups_from_latest
        else None
    )
    protected_valid = (
        revalidated_latest
        if (
            revalidated_latest is not None
            and payload_is_hard_valid(revalidated_latest[0])
        )
        else None
    )
    protected_score = (
        planning_quality_score(protected_valid[0])
        if protected_valid is not None
        else float("inf")
    )
    checkpoint_score = protected_score

    def finish_payload(payload: dict[str, Any], output_bundle: Any) -> int:
        ensure_verified_status(payload)
        if profile_warnings:
            warnings = list(payload.get("warnings", []))
            warnings.extend(profile_warnings)
            payload["warnings"] = sorted(set(warnings))
        attach_quality_profile(payload, quality_profile_name, quality_profile_label)
        payload["rule_summary"] = build_rule_summary(data, config)
        print_report(payload)
        if output_path:
            save_json(output_path, payload)
        if csv_path:
            write_csv(csv_path, payload)
        if html_path:
            write_html(html_path, payload, output_bundle)
        write_latest_valid = payload_is_hard_valid(payload)
        if latest_output_path and write_latest_valid:
            save_json(latest_output_path, payload)
        if latest_csv_path and write_latest_valid:
            write_csv(latest_csv_path, payload)
        if latest_html_path and write_latest_valid:
            write_html(latest_html_path, payload, output_bundle)
        emit_progress(100, "Termine")
        return 0 if payload["status"] == "ok" else 2

    def save_valid_checkpoint(payload: dict[str, Any], output_bundle: Any) -> None:
        nonlocal checkpoint_score
        ensure_verified_status(payload)
        if not payload_is_hard_valid(payload):
            return
        candidate_score = planning_quality_score(payload)
        if candidate_score > checkpoint_score:
            return
        checkpoint_score = candidate_score
        attach_quality_profile(payload, quality_profile_name, quality_profile_label)
        payload["rule_summary"] = build_rule_summary(data, config)
        if latest_output_path:
            save_json(latest_output_path, payload)
        if latest_csv_path:
            write_csv(latest_csv_path, payload)
        if latest_html_path:
            write_html(latest_html_path, payload, output_bundle)

    debug_output = latest_output_path or output_path
    cp_sat_debug_log_path = (
        debug_output.with_name("cp_sat_debug.log")
        if debug_output is not None
        else Path.cwd() / "cp_sat_debug.log"
    )
    if protected_valid is not None:
        save_valid_checkpoint(protected_valid[0], protected_valid[1])

    def run_compact_candidate(budget_seconds: float) -> tuple[dict[str, Any], Any]:
        return make_ortools_slot_payload(
            data,
            time_limit=max(1.0, budget_seconds),
            type_aliases=aliases,
            min_daily_hours=min_daily_hours,
            enforce_min_daily_hours=enforce_min_daily_hours,
            max_split_gap_minutes=hard_max_split_gap_minutes,
            weekly_hours_tolerance_minutes=weekly_hours_tolerance_minutes,
            weekly_hours_tolerance_percent=weekly_hours_tolerance_percent,
            weekly_hours_tolerance_step_minutes=weekly_hours_tolerance_step_minutes,
            enforce_absolute_max_weekly_hours=enforce_absolute_max_weekly_hours,
            absolute_max_weekly_hours=absolute_max_weekly_hours,
            the_enabled=the_enabled,
            the_percent=the_percent,
            the_colloques_count=the_colloques_count,
            half_day_split_time=half_day_split_time,
            max_weekly_group_exception_days=max_weekly_group_exception_days,
            split_shift_weight=split_shift_weight,
            split_gap_weight=split_gap_weight,
            group_switch_day_weight=group_switch_day_weight,
            same_group_week_weight=same_group_week_weight,
            work_day_weight=compact_work_day_weight,
            hard_max_work_days=hard_max_work_days,
            progress_callback=emit_progress,
            hint_payload=latest_payload,
            debug_log_path=cp_sat_debug_log_path,
            candidate_callback=save_valid_checkpoint,
        )

    solver_engine = str(config.get("solver_engine", "scipy")).strip().lower()
    if solver_engine in {"pattern_mip", "pattern-mip", "patterns", "patrons"}:
        emit_progress(5, "Preparation de la recherche par patrons")
        if protected_valid is not None:
            emit_progress(
                5,
                (
                    "Solution initiale valide conservee comme secours et indice"
                    if initial_solution_used
                    else "Dernier planning valide conserve comme secours et indice"
                ),
            )
        compact_failure: str | None = None
        if bool(config.get("compact_candidate_first", True)) and remaining_time_limit() >= 30.0:
            fallback_reserve = min(
                pattern_fallback_time,
                max(0.0, time_limit * 0.10),
                remaining_time_limit(),
            )
            if compact_candidate_time is None:
                compact_budget = max(
                    1.0,
                    remaining_time_limit() - fallback_reserve,
                )
            else:
                compact_budget = min(
                    compact_candidate_time,
                    remaining_time_limit(),
                )
            emit_stage(1, 6, compact_budget, "Recherche compacte CP-SAT")
            emit_progress(6, f"Recherche compacte CP-SAT (budget {int(compact_budget)} s)")
            compact_payload, compact_bundle = run_compact_candidate(compact_budget)
            ensure_verified_status(compact_payload)
            if payload_is_hard_valid(compact_payload):
                compact_score = planning_quality_score(compact_payload)
                if (
                    protected_valid is not None
                    and compact_score > protected_score
                ):
                    compact_payload, compact_bundle = protected_valid
                    warnings = list(compact_payload.get("warnings", []))
                    warnings.append(
                        "La recherche CP-SAT a trouve un planning valide mais moins bon; "
                        "la solution de secours a ete conservee."
                    )
                else:
                    warnings = list(compact_payload.get("warnings", []))
                    warnings.append(
                        "Planning hard-valide trouve par la recherche compacte CP-SAT; "
                        "le modele exhaustif par patrons n'a pas ete lance."
                    )
                compact_payload["warnings"] = sorted(set(warnings))
                emit_progress(96, "Verification et ecriture des fichiers")
                return finish_payload(compact_payload, compact_bundle)
            compact_failure = str(
                compact_payload.get("solver_message", "aucun candidat hard-valide")
            )

        pattern_budget = min(
            pattern_fallback_time,
            max(0.0, time_limit * 0.10),
            remaining_time_limit(),
        )
        pattern_started_at = time.monotonic()

        def remaining_pattern_time() -> float:
            return max(
                0.0,
                min(
                    remaining_time_limit(),
                    pattern_budget - (time.monotonic() - pattern_started_at),
                ),
            )

        def empty_pattern_bundle() -> Any:
            horizon = make_horizon(data)
            return type(
                "PatternMipBundle",
                (),
                {
                    "data": data,
                    "horizon": horizon,
                    "groups": list(data.get("groups", [])),
                    "educators": list(data.get("educators", [])),
                    "sites": [site["name"] for site in data.get("sites", [])],
                },
            )()

        def memory_payload(stage: str) -> dict[str, Any]:
            return {
                "status": "infeasible_or_not_solved",
                "solver_message": f"Memoire insuffisante pendant {stage}.",
                "warnings": [],
                "diagnostics": [
                    "Le calcul a ete arrete proprement avant saturation de l'application.",
                    "Activez la reutilisation des groupes principaux du dernier planning ou reduisez les patrons.",
                ],
            }

        def run_pattern_attempt(
            *,
            budget_seconds: float,
            feasible: bool,
            fixed_groups: dict[int, int] | None,
            attempt_restricted_patterns: bool,
            attempt_restricted_mode: str,
            generation_gap_minutes: int | None,
            generation_step_minutes: int | None,
            fine_generation_step_minutes: int | None,
            fine_step_educators: set[str],
            progress_start: int,
            progress_end: int,
            label: str,
            enforce_work_days: bool = True,
            work_day_weight: float | None = None,
        ) -> tuple[dict[str, Any], Any]:
            def attempt_progress(percent: int, message: str) -> None:
                span = max(1, progress_end - progress_start)
                mapped = progress_start + int(span * max(0, min(100, percent)) / 100)
                emit_progress(mapped, f"{label}: {message}")

            try:
                return make_pattern_mip_payload(
                    data,
                    time_limit=max(1.0, budget_seconds),
                    type_aliases=aliases,
                    min_daily_hours=min_daily_hours,
                    enforce_min_daily_hours=enforce_min_daily_hours,
                    short_day_penalty_weight=short_day_penalty_weight,
                    max_split_gap_minutes=hard_max_split_gap_minutes,
                    generation_max_split_gap_minutes=generation_gap_minutes,
                    generation_time_step_minutes=generation_step_minutes,
                    fine_generation_time_step_minutes=fine_generation_step_minutes,
                    fine_time_step_educators=fine_step_educators,
                    weekly_hours_tolerance_minutes=weekly_hours_tolerance_minutes,
                    weekly_hours_tolerance_percent=weekly_hours_tolerance_percent,
                    weekly_hours_tolerance_step_minutes=weekly_hours_tolerance_step_minutes,
                    enforce_absolute_max_weekly_hours=enforce_absolute_max_weekly_hours,
                    absolute_max_weekly_hours=absolute_max_weekly_hours,
                    the_enabled=the_enabled,
                    the_percent=the_percent,
                    the_colloques_count=the_colloques_count,
                    half_day_split_time=half_day_split_time,
                    max_weekly_group_exception_days=max_weekly_group_exception_days,
                    split_shift_weight=split_shift_weight,
                    split_gap_weight=split_gap_weight,
                    group_switch_day_weight=group_switch_day_weight,
                    same_group_week_weight=same_group_week_weight,
                    soft_time_rule_weight=soft_time_rule_weight,
                    soft_group_rule_weight=soft_group_rule_weight,
                    compact_work_days=compact_work_days,
                    compact_work_day_weight=(
                        compact_work_day_weight if work_day_weight is None else work_day_weight
                    ),
                    compact_part_time_priority=compact_part_time_priority,
                    hard_max_work_days=enforce_work_days,
                    feasible_only=feasible,
                    restricted_patterns=attempt_restricted_patterns,
                    restricted_pattern_mode=attempt_restricted_mode,
                    fixed_primary_groups=fixed_groups,
                    quality_profile=quality_profile_name,
                    quality_profile_label=quality_profile_label,
                    primary_group_report_enabled=primary_group_report_enabled,
                    primary_group_warning_outside_hours=primary_group_warning_outside_hours,
                    primary_group_warning_outside_days=primary_group_warning_outside_days,
                    progress_callback=attempt_progress,
                )
            except MemoryError:
                return memory_payload(label), empty_pattern_bundle()

        targeted_groups, released_names = release_over_limit_primary_groups(
            data,
            latest_payload,
            fixed_primary_groups,
        )
        attempts = build_candidate_attempts(
            fixed_primary_groups=fixed_primary_groups,
            targeted_primary_groups=targeted_groups,
            max_split_gap_minutes=max_split_gap_minutes,
        )
        payload: dict[str, Any] = {
            "status": "infeasible_or_not_solved",
            "solver_message": "Aucun essai de recherche execute.",
            "warnings": [],
            "diagnostics": [],
        }
        output_bundle = empty_pattern_bundle()
        best_payload: dict[str, Any] | None = None
        best_bundle: Any = None
        search_history: list[str] = []
        if compact_failure:
            search_history.append(f"Recherche compacte CP-SAT: {compact_failure}.")

        for attempt_index, attempt in enumerate(attempts):
            remaining = remaining_pattern_time()
            budget = attempt_budget(
                remaining,
                attempts,
                attempt_index,
                reserve_fraction=0.10,
            )
            if budget < 30.0:
                search_history.append("Temps global insuffisant pour lancer les essais restants.")
                break
            stage_start = 5 + int(65 * attempt_index / max(1, len(attempts)))
            stage_end = 5 + int(65 * (attempt_index + 1) / max(1, len(attempts)))
            label = f"Essai {attempt_index + 1}/{len(attempts)} - {attempt.label}"
            emit_stage(
                attempt_index + 1,
                len(attempts) + 1,
                budget,
                attempt.label,
            )
            emit_progress(stage_start, f"{label} (budget {int(budget)} s)")
            attempt_payload, attempt_bundle = run_pattern_attempt(
                budget_seconds=budget,
                feasible=True,
                fixed_groups=attempt.fixed_primary_groups,
                attempt_restricted_patterns=attempt.restricted_patterns or restricted_patterns,
                attempt_restricted_mode=(
                    attempt.restricted_pattern_mode
                    if attempt.restricted_patterns
                    else restricted_pattern_mode
                ),
                generation_gap_minutes=attempt.generation_max_split_gap_minutes,
                generation_step_minutes=attempt.generation_time_step_minutes,
                fine_generation_step_minutes=attempt.fine_generation_time_step_minutes,
                fine_step_educators=set(released_names),
                progress_start=stage_start,
                progress_end=stage_end,
                label=label,
                enforce_work_days=hard_max_work_days,
            )
            ensure_verified_status(attempt_payload)
            payload, output_bundle = attempt_payload, attempt_bundle
            if payload_is_hard_valid(attempt_payload):
                best_payload, best_bundle = attempt_payload, attempt_bundle
                search_history.append(f"{attempt.label}: solution hard-valide trouvee.")
                break
            search_history.append(
                f"{attempt.label}: {attempt_payload.get('solver_message', 'sans solution')}."
            )
            if any(
                str(item).startswith("Capacite enfants insuffisante")
                for item in attempt_payload.get("diagnostics", [])
            ):
                break
            if not payload_is_retryable(attempt_payload) and attempt_payload.get("status") != "invalid":
                break

        if best_payload is not None:
            remaining = remaining_pattern_time()
            if remaining >= 60.0 and not fast_feasible:
                fixed_from_candidate = infer_majority_primary_groups_from_payload(data, best_payload)
                emit_stage(
                    len(attempts) + 1,
                    len(attempts) + 1,
                    remaining,
                    "Amelioration du candidat hard-valide",
                )
                emit_progress(72, f"Amelioration du candidat valide (budget {int(remaining)} s)")
                quality_payload, quality_bundle = run_pattern_attempt(
                    budget_seconds=remaining,
                    feasible=False,
                    fixed_groups=fixed_from_candidate or None,
                    attempt_restricted_patterns=restricted_patterns,
                    attempt_restricted_mode=restricted_pattern_mode,
                    generation_gap_minutes=max_split_gap_minutes,
                    generation_step_minutes=15,
                    fine_generation_step_minutes=None,
                    fine_step_educators=set(),
                    progress_start=72,
                    progress_end=95,
                    label="Amelioration",
                    enforce_work_days=hard_max_work_days,
                )
                ensure_verified_status(quality_payload)
                if payload_is_hard_valid(quality_payload):
                    if planning_quality_score(quality_payload) <= planning_quality_score(best_payload):
                        best_payload, best_bundle = quality_payload, quality_bundle
                        search_history.append("Amelioration: meilleure solution hard-valide retenue.")
                else:
                    search_history.append(
                        "Amelioration interrompue ou invalide: candidat hard-valide conserve."
                    )
            payload, output_bundle = best_payload, best_bundle
        elif (
            hard_max_work_days
            and relax_work_days_if_infeasible
            and remaining_pattern_time() >= 30.0
        ):
            diagnostic_budget = remaining_pattern_time()
            emit_stage(
                len(attempts) + 1,
                len(attempts) + 1,
                diagnostic_budget,
                "Diagnostic avec limite de jours assouplie",
            )
            emit_progress(72, f"Diagnostic avec limite de jours assouplie (budget {int(diagnostic_budget)} s)")
            relaxed_payload, relaxed_bundle = run_pattern_attempt(
                budget_seconds=diagnostic_budget,
                feasible=True,
                fixed_groups=None,
                attempt_restricted_patterns=restricted_patterns,
                attempt_restricted_mode=restricted_pattern_mode,
                generation_gap_minutes=max_split_gap_minutes,
                generation_step_minutes=15,
                fine_generation_step_minutes=None,
                fine_step_educators=set(),
                progress_start=72,
                progress_end=95,
                label="Diagnostic jours assouplis",
                enforce_work_days=False,
                work_day_weight=max(compact_work_day_weight, relaxed_work_day_weight),
            )
            if payload_is_hard_valid(relaxed_payload):
                payload = mark_work_day_diagnostic(relaxed_payload)
                output_bundle = relaxed_bundle

        if protected_valid is not None:
            candidate_is_valid = payload_is_hard_valid(payload)
            candidate_score = (
                planning_quality_score(payload)
                if candidate_is_valid
                else float("inf")
            )
            if candidate_score > protected_score:
                payload, output_bundle = protected_valid
                search_history.append(
                    "Aucune meilleure solution hard-valide trouvee; "
                    "la solution de secours revalidee a ete conservee."
                )

        warnings = list(payload.get("warnings", []))
        warnings.extend(search_history)
        if released_names:
            warnings.append(
                "Groupes principaux liberes en priorite pour: " + ", ".join(released_names) + "."
            )
        payload["warnings"] = sorted(set(warnings))
        emit_progress(96, "Verification et ecriture des fichiers")
        return finish_payload(payload, output_bundle)

    if solver_engine in {"ortools", "cp-sat", "cpsat"}:
        emit_progress(10, "Calcul OR-Tools CP-SAT")
        payload, output_bundle = run_compact_candidate(time_limit)
        emit_progress(96, "Verification et ecriture des fichiers")
        return finish_payload(payload, output_bundle)

    emit_progress(10, "Calcul principal")
    inferred_preferred_groups = infer_preferred_groups_from_payload(data, latest_payload)
    bundle = solve_schedule(
        data,
        time_limit=time_limit,
        mip_gap=mip_gap,
        type_aliases=aliases,
        weekly_mode=weekly_mode,
        readable_objective=not fast_feasible and not smooth,
        one_group_per_day=structured,
        one_site_per_day=True,
        max_blocks_per_day=max_blocks_per_day if max_blocks_per_day is not None else 2,
        min_daily_hours=min_daily_hours,
        weekly_hours_tolerance_percent=weekly_hours_tolerance_percent,
        weekly_hours_tolerance_minutes=weekly_hours_tolerance_minutes,
        half_day_split_time=half_day_split_time,
        max_weekly_group_exception_days=max_weekly_group_exception_days,
        weekly_stability=weekly_stability,
        main_group_day_weight=main_group_day_weight,
        main_group_slot_weight=main_group_slot_weight,
        main_site_day_weight=main_site_day_weight,
        preferred_groups=inferred_preferred_groups,
    )
    stable_bundle: SolveBundle | None = None
    run_secondary_stabilization = False
    if run_secondary_stabilization and weekly_stability and bundle.result.success and bundle.result.x is not None:
        emit_progress(36, "Stabilisation groupe/site")
        preferred_groups = infer_main_groups(bundle)
        preferred_sites: dict[int, int] = {}
        stable_bundle = solve_schedule(
            data,
            time_limit=time_limit,
            mip_gap=mip_gap,
            type_aliases=aliases,
            weekly_mode=weekly_mode,
            readable_objective=False,
            one_group_per_day=structured,
            one_site_per_day=True,
            max_blocks_per_day=max_blocks_per_day if max_blocks_per_day is not None else 2,
            min_daily_hours=min_daily_hours,
            weekly_hours_tolerance_percent=weekly_hours_tolerance_percent,
            weekly_hours_tolerance_minutes=weekly_hours_tolerance_minutes,
            half_day_split_time=half_day_split_time,
            max_weekly_group_exception_days=max_weekly_group_exception_days,
            weekly_stability=False,
            main_group_day_weight=main_group_day_weight,
            main_group_slot_weight=main_group_slot_weight,
            main_site_day_weight=main_site_day_weight,
            preferred_groups=preferred_groups,
            preferred_sites=preferred_sites,
        )
        if not (stable_bundle.result.success and stable_bundle.result.x is not None):
            bundle.warnings.append("Stabilisation groupe/site non terminee: planning de base conserve.")
            stable_bundle = None
    emit_progress(58, "Preparation du planning")
    payload = make_payload(
        bundle,
        smooth=smooth,
        smooth_time_limit=smooth_time_limit,
        split_shift_weight=split_shift_weight,
        split_gap_weight=split_gap_weight,
        max_split_gap_minutes=hard_max_split_gap_minutes,
        group_switch_day_weight=group_switch_day_weight,
        same_group_week_weight=same_group_week_weight,
        half_day_split_time=half_day_split_time,
        max_weekly_group_exception_days=max_weekly_group_exception_days,
        weekly_hours_tolerance_percent=weekly_hours_tolerance_percent,
        progress_callback=emit_progress,
        progress_start=58,
        progress_end=74 if stable_bundle is not None else 95,
    )
    if stable_bundle is not None:
        emit_progress(74, "Controle de la variante stabilisee")
        stable_payload = make_payload(
            stable_bundle,
            smooth=smooth,
            smooth_time_limit=smooth_time_limit,
            split_shift_weight=split_shift_weight,
            split_gap_weight=split_gap_weight,
            max_split_gap_minutes=hard_max_split_gap_minutes,
            group_switch_day_weight=group_switch_day_weight,
            same_group_week_weight=same_group_week_weight,
            half_day_split_time=half_day_split_time,
            max_weekly_group_exception_days=max_weekly_group_exception_days,
            weekly_hours_tolerance_percent=weekly_hours_tolerance_percent,
            progress_callback=emit_progress,
            progress_start=74,
            progress_end=95,
        )
        if planning_quality_score(stable_payload) < planning_quality_score(payload):
            payload = stable_payload
            payload["warnings"].append("Variante stabilisee retenue.")
        else:
            payload["warnings"].append("Variante stabilisee non retenue: elle degrade trop la lisibilite.")
    emit_progress(96, "Verification et ecriture des fichiers")
    return finish_payload(payload, bundle)


if __name__ == "__main__":
    raise SystemExit(main())



