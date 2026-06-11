from __future__ import annotations

import argparse
import math
import os
import time
from array import array
from datetime import datetime
from pathlib import Path
from typing import Any, Callable

import numpy as np
from scipy.optimize import Bounds, LinearConstraint, milp
from scipy.sparse import coo_matrix, csr_matrix

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
from .reports import build_rule_summary, print_report, write_csv, write_html
from .runtime import (
    config_aliases,
    emit_progress,
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
            used_sites = {
                block["site"]
                for block in blocks
                if block.get("activity") not in {"colloque", "remplacement_colloque"}
            }
            if len(used_sites) > 1:
                soft_warnings.append(f"{name} {day_key}: plusieurs sites {sorted(used_sites)}")
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
    split_slot = split_slot_for_horizon(bundle.horizon, half_day_split_time)
    split_min = bundle.horizon.start + split_slot * bundle.horizon.step
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

    for raw_rule in data.get("rules_group", []):
        if len(raw_rule) < 4:
            continue
        pref_type, strength, educator_name, group_name = raw_rule[:4]
        if normalize_flag(strength) != "hard" or educator_name not in schedule:
            continue
        is_negative = normalize_flag(pref_type) in {"negatif", "negative", "neg"}
        for day_key, blocks in schedule[educator_name].items():
            for block in blocks:
                if block.get("activity") in {"colloque", "remplacement_colloque"}:
                    continue
                if is_negative and block["group"] == group_name:
                    hard_rule_errors.append(
                        f"Regle groupe hard violee: {educator_name} est en {group_name} {day_key}."
                    )
                if not is_negative and block["group"] != group_name:
                    hard_rule_errors.append(
                        f"Regle groupe hard violee: {educator_name} est en {block['group']} "
                        f"{day_key}, mais la regle impose {group_name}."
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

    for educator_name, by_day in schedule.items():
        totals: dict[str, int] = {}
        for day_key, blocks in by_day.items():
            morning_groups: set[str] = set()
            afternoon_groups: set[str] = set()
            for block in blocks:
                if block.get("activity") in {"colloque", "remplacement_colloque"}:
                    continue
                start_min = parse_time(block["start"])
                end_min = parse_time(block["end"])
                minutes = max(0, end_min - start_min)
                totals[block["group"]] = totals.get(block["group"], 0) + minutes
                if start_min < split_min and end_min > bundle.horizon.start:
                    morning_groups.add(block["group"])
                if start_min < bundle.horizon.end and end_min > split_min:
                    afternoon_groups.add(block["group"])
            if len(morning_groups) > 1:
                group_structure_errors.append(
                    f"Changement de groupe interdit le matin: {educator_name} {day_key} {sorted(morning_groups)}."
                )
            if len(afternoon_groups) > 1:
                group_structure_errors.append(
                    f"Changement de groupe interdit l'apres-midi: {educator_name} {day_key} {sorted(afternoon_groups)}."
                )

        if max_weekly_group_exception_days is not None and attends_colloque_by_name.get(educator_name, True):
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
                group_structure_errors.append(
                    f"Trop de jours avec changement de groupe pour {educator_name}: "
                    f"{len(exception_days)} > {max_weekly_group_exception_days} "
                    f"(jours: {', '.join(exception_days)})."
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
        primary_g: int,
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
        target = int(round((float(educator["percentage"]) / 100.0) * weekly_base / (horizon.step / 60.0)))
        total = sum(variables[p_i] * int(pattern_duration[p_i]) for p_i in by_educator.get(e_i, []))
        model.Add(total >= max(0, target - tolerance_slots))
        model.Add(total <= target + tolerance_slots)
        over = model.NewIntVar(0, tolerance_slots, f"over_{e_i}")
        under = model.NewIntVar(0, tolerance_slots, f"under_{e_i}")
        model.Add(total - target == over - under)
        objective_terms.append((over + under) * 2500)

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
                display_group = pattern_slot_display_overrides[pattern_id].get(
                    slot,
                    pattern_slot_coverage_overrides[pattern_id].get(slot, pattern_half_groups[pattern_id][half_i]),
                )
                activity = pattern_slot_activities[pattern_id].get(slot, "")
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
    max_split_gap_minutes: int | None = 90,
    weekly_hours_tolerance_minutes: int | None = None,
    weekly_hours_tolerance_percent: float = 3.0,
    weekly_hours_tolerance_step_minutes: int | None = 15,
    enforce_absolute_max_weekly_hours: bool = True,
    absolute_max_weekly_hours: float | None = 40.0,
    half_day_split_time: str = "12:30",
    max_weekly_group_exception_days: int | None = 1,
    split_shift_weight: float = 120.0,
    split_gap_weight: float = 4.0,
    group_switch_day_weight: float = 8.0,
    same_group_week_weight: float = 0.4,
    hard_max_work_days: bool = True,
    progress_callback: Callable[[int, str], None] | None = None,
    hint_payload: dict[str, Any] | None = None,
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
    if hint_payload and isinstance(hint_payload.get("schedule"), dict):
        hinted_totals: dict[int, dict[int, int]] = {}
        for educator_name, by_day in hint_payload.get("schedule", {}).items():
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
                    hinted_totals.setdefault(e_i, {})
                    hinted_totals[e_i][group_by_name[group_name]] = hinted_totals[e_i].get(group_by_name[group_name], 0) + minutes
        for e_i, totals in hinted_totals.items():
            if totals:
                main_groups.setdefault(e_i, max(totals.items(), key=lambda item: item[1])[0])

    x: dict[tuple[int, int, int, int], Any] = {}
    work: dict[tuple[int, int, int], Any] = {}
    work_day: dict[tuple[int, int], Any] = {}
    site_day: dict[tuple[int, int, int], Any] = {}
    half_group: dict[tuple[int, int, int, int], Any] = {}
    group_day: dict[tuple[int, int, int], Any] = {}
    mixed_day: dict[tuple[int, int], Any] = {}
    outside_primary_day: dict[tuple[int, int], Any] = {}
    start_var: dict[tuple[int, int, int], Any] = {}
    objective_terms: list[Any] = []
    scale = 100

    for e_i in range(len(educators)):
        for d_i in range(len(DAYS)):
            work_day[(e_i, d_i)] = model.NewBoolVar(f"wd_{e_i}_{d_i}")
            mixed_day[(e_i, d_i)] = model.NewBoolVar(f"mix_{e_i}_{d_i}")
            if e_i in main_groups:
                outside_primary_day[(e_i, d_i)] = model.NewBoolVar(f"outside_{e_i}_{d_i}")
            for s_i in range(len(sites)):
                site_day[(e_i, d_i, s_i)] = model.NewBoolVar(f"site_{e_i}_{d_i}_{s_i}")
            for g_i in range(len(groups)):
                group_day[(e_i, d_i, g_i)] = model.NewBoolVar(f"gd_{e_i}_{d_i}_{g_i}")
                for half_i in range(2):
                    half_group[(e_i, d_i, half_i, g_i)] = model.NewBoolVar(f"hg_{e_i}_{d_i}_{half_i}_{g_i}")
            for t_i in range(horizon.slots):
                work[(e_i, d_i, t_i)] = model.NewBoolVar(f"w_{e_i}_{d_i}_{t_i}")
                start_var[(e_i, d_i, t_i)] = model.NewBoolVar(f"st_{e_i}_{d_i}_{t_i}")
                for g_i in range(len(groups)):
                    x[(e_i, d_i, g_i, t_i)] = model.NewBoolVar(f"x_{e_i}_{d_i}_{g_i}_{t_i}")

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

    for e_i, educator in enumerate(educators):
        target_hours = float(educator["percentage"]) / 100.0 * weekly_base
        target = int(round(target_hours / (horizon.step / 60.0)))
        tolerance_slots = weekly_tolerance_slots(
            target_hours,
            horizon,
            percent=weekly_hours_tolerance_percent,
            minutes=weekly_hours_tolerance_minutes,
            step_minutes=weekly_hours_tolerance_step_minutes,
        )
        weekly_terms = []
        for d_i in range(len(DAYS)):
            day_work_terms = []
            for t_i in range(horizon.slots):
                group_terms = [x[(e_i, d_i, g_i, t_i)] for g_i in range(len(groups))]
                model.Add(sum(group_terms) == work[(e_i, d_i, t_i)])
                model.Add(work[(e_i, d_i, t_i)] <= work_day[(e_i, d_i)])
                day_work_terms.append(work[(e_i, d_i, t_i)])
                weekly_terms.append(work[(e_i, d_i, t_i)])
                if t_i == 0:
                    model.Add(start_var[(e_i, d_i, t_i)] == work[(e_i, d_i, t_i)])
                else:
                    model.Add(start_var[(e_i, d_i, t_i)] >= work[(e_i, d_i, t_i)] - work[(e_i, d_i, t_i - 1)])
                    model.Add(start_var[(e_i, d_i, t_i)] <= work[(e_i, d_i, t_i)])
                    model.Add(start_var[(e_i, d_i, t_i)] <= 1 - work[(e_i, d_i, t_i - 1)])
                objective_terms.append(start_var[(e_i, d_i, t_i)] * int(round(split_shift_weight * scale)))
            model.Add(sum(day_work_terms) <= max_daily_slots)
            model.Add(sum(day_work_terms) >= min_daily_slots * work_day[(e_i, d_i)])
            model.Add(sum(start_var[(e_i, d_i, t_i)] for t_i in range(horizon.slots)) <= 2)

            site_terms = [site_day[(e_i, d_i, s_i)] for s_i in range(len(sites))]
            model.Add(sum(site_terms) <= 1)
            for g_i, group in enumerate(groups):
                s_i = site_index[group["site"]]
                group_terms_for_day = []
                for t_i in range(horizon.slots):
                    group_terms_for_day.append(x[(e_i, d_i, g_i, t_i)])
                    model.Add(x[(e_i, d_i, g_i, t_i)] <= site_day[(e_i, d_i, s_i)])
                    half_i = 0 if t_i < split_slot else 1
                    model.Add(x[(e_i, d_i, g_i, t_i)] <= half_group[(e_i, d_i, half_i, g_i)])
                    model.Add(x[(e_i, d_i, g_i, t_i)] <= group_day[(e_i, d_i, g_i)])
                model.Add(group_day[(e_i, d_i, g_i)] <= sum(group_terms_for_day))
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
                half_slots = range(0, split_slot) if half_i == 0 else range(split_slot, horizon.slots)
                for g_i in range(len(groups)):
                    half_terms = [x[(e_i, d_i, g_i, t_i)] for t_i in half_slots]
                    if half_terms:
                        model.Add(half_group[(e_i, d_i, half_i, g_i)] <= sum(half_terms))
                    else:
                        model.Add(half_group[(e_i, d_i, half_i, g_i)] == 0)
                model.Add(sum(half_group[(e_i, d_i, half_i, g_i)] for g_i in range(len(groups))) <= 1)
            model.Add(sum(group_day[(e_i, d_i, g_i)] for g_i in range(len(groups))) <= 1 + mixed_day[(e_i, d_i)])
            objective_terms.append(mixed_day[(e_i, d_i)] * int(round(group_switch_day_weight * scale)))
            if e_i in main_groups:
                outside_var = outside_primary_day[(e_i, d_i)]
                primary_group = main_groups[e_i]
                for g_i in range(len(groups)):
                    if g_i != primary_group:
                        model.Add(group_day[(e_i, d_i, g_i)] <= outside_var)
                objective_terms.append(outside_var * int(round(group_switch_day_weight * scale * 4)))
        model.Add(sum(weekly_terms) >= max(0, target - tolerance_slots))
        model.Add(sum(weekly_terms) <= target + tolerance_slots)
        over = model.NewIntVar(0, tolerance_slots, f"over_{e_i}")
        under = model.NewIntVar(0, tolerance_slots, f"under_{e_i}")
        model.Add(sum(weekly_terms) - target == over - under)
        objective_terms.append((over + under) * 2500)

        if max_weekly_group_exception_days is not None:
            model.Add(sum(mixed_day[(e_i, d_i)] for d_i in range(len(DAYS))) <= int(max_weekly_group_exception_days))
            outside_terms = [outside_primary_day[(e_i, d_i)] for d_i in range(len(DAYS)) if (e_i, d_i) in outside_primary_day]
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
        for d_i in range(len(DAYS)):
            for g_i in range(len(groups)):
                affected = g_i == target_g if is_negative else g_i != target_g
                if not affected:
                    continue
                for t_i in range(horizon.slots):
                    if is_hard:
                        model.Add(x[(e_i, d_i, g_i, t_i)] == 0)
                    else:
                        objective_terms.append(x[(e_i, d_i, g_i, t_i)] * 18)

    for e_i, main_g in main_groups.items():
        for d_i in range(len(DAYS)):
            for g_i in range(len(groups)):
                if g_i == main_g:
                    continue
                for t_i in range(horizon.slots):
                    objective_terms.append(x[(e_i, d_i, g_i, t_i)] * int(round(same_group_week_weight * scale)))

    for raw_rule in data.get("rules_percentage", []):
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
    has_hint = False
    if hint_payload and isinstance(hint_payload.get("schedule"), dict):
        hinted_x: set[tuple[int, int, int, int]] = set()
        hinted_work: set[tuple[int, int, int]] = set()
        schedule_hint = hint_payload.get("schedule", {})
        for e_i, educator in enumerate(educators):
            educator_name = educator["name"]
            if educator_name not in schedule_hint:
                continue
            for d_i, (day_key, _) in enumerate(DAYS):
                for block in schedule_hint.get(educator_name, {}).get(day_key, []):
                    group_name = block.get("group")
                    if group_name not in group_by_name:
                        continue
                    g_i = group_by_name[group_name]
                    try:
                        start_slot = (parse_time(block["start"]) - horizon.start) // horizon.step
                        end_slot = (parse_time(block["end"]) - horizon.start) // horizon.step
                    except Exception:
                        continue
                    for t_i in range(max(0, start_slot), min(horizon.slots, end_slot)):
                        hinted_x.add((e_i, d_i, g_i, t_i))
                        hinted_work.add((e_i, d_i, t_i))
        has_hint = bool(hinted_x)
        for key, var in x.items():
            model.AddHint(var, 1 if key in hinted_x else 0)
        for key, var in work.items():
            model.AddHint(var, 1 if key in hinted_work else 0)
        for key, var in work_day.items():
            e_i, d_i = key
            model.AddHint(var, 1 if any((e_i, d_i, t_i) in hinted_work for t_i in range(horizon.slots)) else 0)
        for key, var in group_day.items():
            e_i, d_i, g_i = key
            model.AddHint(var, 1 if any((e_i, d_i, g_i, t_i) in hinted_x for t_i in range(horizon.slots)) else 0)
        for key, var in half_group.items():
            e_i, d_i, half_i, g_i = key
            half_slots = range(0, split_slot) if half_i == 0 else range(split_slot, horizon.slots)
            model.AddHint(var, 1 if any((e_i, d_i, g_i, t_i) in hinted_x for t_i in half_slots) else 0)
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
                if any((e_i, d_i, g_i, t_i) in hinted_x for t_i in range(horizon.slots))
            }
            model.AddHint(var, 1 if len(hinted_groups) > 1 else 0)
        for key, var in outside_primary_day.items():
            e_i, d_i = key
            primary_group = main_groups.get(e_i)
            model.AddHint(
                var,
                1
                if primary_group is not None
                and any(
                    g_i != primary_group and (e_i, d_i, g_i, t_i) in hinted_x
                    for g_i in range(len(groups))
                    for t_i in range(horizon.slots)
                )
                else 0,
            )
        for key, var in start_var.items():
            e_i, d_i, t_i = key
            previous = (e_i, d_i, t_i - 1) in hinted_work if t_i else False
            model.AddHint(var, 1 if key in hinted_work and not previous else 0)
    solver = cp_model.CpSolver()
    first_phase_limit = max(30.0, min(float(time_limit) * 0.7, max(30.0, float(time_limit) - 30.0)))
    solver.parameters.max_time_in_seconds = first_phase_limit
    solver.parameters.num_search_workers = max(1, min(8, os.cpu_count() or 1))
    solver.parameters.stop_after_first_solution = True
    if os.environ.get("CRECHE_CP_LOG"):
        solver.parameters.log_search_progress = True
    if has_hint:
        solver.parameters.use_optimization_hints = True
    status = solver.Solve(model)
    if status not in {cp_model.OPTIMAL, cp_model.FEASIBLE}:
        return (
            {
                "status": "infeasible_or_not_solved",
                "solver_message": solver.StatusName(status),
                "warnings": sorted(set(warnings)),
                "diagnostics": diagnose_basic_conflicts(data, horizon),
            },
            bundle,
        )

    for var in list(x.values()) + list(work.values()) + list(work_day.values()) + list(mixed_day.values()):
        model.AddHint(var, int(solver.Value(var)))
    model.Minimize(sum(objective_terms) if objective_terms else 0)
    optimizer = cp_model.CpSolver()
    optimizer.parameters.max_time_in_seconds = max(10.0, float(time_limit) - solver.WallTime())
    optimizer.parameters.num_search_workers = max(1, min(8, os.cpu_count() or 1))
    optimizer.parameters.relative_gap_limit = 0.05
    optimizer.parameters.use_optimization_hints = True
    if progress_callback:
        progress_callback(64, "Optimisation de la qualite")
    opt_status = optimizer.Solve(model)
    best_solver = optimizer if opt_status in {cp_model.OPTIMAL, cp_model.FEASIBLE} else solver
    best_status = opt_status if opt_status in {cp_model.OPTIMAL, cp_model.FEASIBLE} else status

    schedule = {educator["name"]: {day_key: [] for day_key, _ in DAYS} for educator in educators}
    for e_i, educator in enumerate(educators):
        name = educator["name"]
        for d_i, (day_key, _) in enumerate(DAYS):
            current_group: int | None = None
            start_slot: int | None = None
            for t_i in range(horizon.slots + 1):
                active_group: int | None = None
                if t_i < horizon.slots:
                    for g_i in range(len(groups)):
                        if best_solver.Value(x[(e_i, d_i, g_i, t_i)]):
                            active_group = g_i
                            break
                if active_group != current_group:
                    if current_group is not None and start_slot is not None:
                        start_min = horizon.start + start_slot * horizon.step
                        end_min = horizon.start + t_i * horizon.step
                        group = groups[current_group]
                        schedule[name][day_key].append(
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

    checks = verify_solution(
        bundle,
        schedule,
        half_day_split_time=half_day_split_time,
        max_weekly_group_exception_days=max_weekly_group_exception_days,
        max_split_gap_minutes=max_split_gap_minutes,
        weekly_hours_tolerance_percent=0.0,
    )
    weekly_errors = []
    allowed_hours = float(weekly_hours_tolerance_minutes) / 60.0
    for name, actual in checks["hours_by_educator"].items():
        target = checks["weekly_targets"][name]
        if abs(actual - target) > allowed_hours + 1e-6:
            weekly_errors.append(
                f"{name}: {actual:.2f}h hors tolerance autour de {target:.2f}h "
                f"(+/- {weekly_hours_tolerance_minutes} min)"
            )
    filtered = [
        error
        for error in checks["errors"]
        if "hors tolerance autour" not in error and "!=" not in error
    ]
    checks["errors"] = filtered + weekly_errors
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
        if group_i in colloque_by_group:
            warnings.append(f"Plusieurs colloques definis pour le groupe {groups[group_i]['name']}.")
        else:
            colloque_by_group[group_i] = colloque

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

    start_candidates: set[int] = set(range(0, horizon.slots))
    end_candidates: set[int] = set(range(1, horizon.slots + 1))
    for rule in data.get("rules_site_schedule", []):
        for interval in rule.get("time_intervals", []):
            for value in (interval.get("start"), interval.get("end")):
                if value:
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

    costs: list[float] = []
    pattern_owner: list[tuple[int, int]] = []
    pattern_segments: list[tuple[tuple[int, int], ...]] = []
    pattern_half_groups: list[dict[int, int]] = []
    pattern_slot_coverage_overrides: list[dict[int, int]] = []
    pattern_slot_display_overrides: list[dict[int, int]] = []
    pattern_slot_activities: list[dict[int, str]] = []
    pattern_site: list[str | None] = []
    pattern_duration: list[int] = []
    pattern_child_duration: list[int] = []
    pattern_colloque_the_duration: list[int] = []
    pattern_mixed: list[int] = []
    pattern_primary_group: list[int] = []
    by_educator_day: dict[tuple[int, int], list[int]] = {}
    by_educator_day_primary: dict[tuple[int, int, int], list[int]] = {}
    by_educator: dict[int, list[int]] = {}
    coverage_terms: dict[tuple[int, int, int], list[int]] = {}
    site_terms: dict[tuple[int, str, int], list[int]] = {}
    percentage_terms: dict[str, list[tuple[int, int, int]]] = {site: [] for site in sites}
    replacement_terms: dict[tuple[int, int], list[int]] = {}
    pattern_stats = {
        "off": 0,
        "continuous": 0,
        "split": 0,
        "mixed_group": 0,
        "replacement": 0,
        "colloque": 0,
    }

    def work_cost_or_none(e_i: int, day_key: str, segments: tuple[tuple[int, int], ...]) -> float | None:
        educator_name = educators[e_i]["name"]
        worked_slots = {slot for start, end in segments for slot in range(start, end)}
        cost = 0.0
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
                cost += overlap * 45.0 * soft_time_rule_weight
            else:
                cost -= overlap * 35.0 * soft_time_rule_weight
        if len(segments) > 1:
            gap = segments[1][0] - segments[0][1]
            if max_gap_slots is not None and gap > max_gap_slots:
                return None
            cost += split_shift_weight * scale + gap * split_gap_weight * scale
        return cost

    def group_cost_or_none(e_i: int, primary_g: int, g_i: int, slots: int) -> float | None:
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
                return None
            cost += slots * 18.0 * soft_group_rule_weight
        return cost

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
        pattern_id = len(costs)
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
        if 0 < duration < min_daily_slots:
            missing_slots = min_daily_slots - duration
            cost += missing_slots * short_day_penalty_weight * scale
        if compact_work_days and duration > 0:
            compact_multiplier = 1.0
            if compact_part_time_priority:
                percentage = max(1.0, float(educators[e_i].get("percentage", 100.0)))
                compact_multiplier = max(1.0, 100.0 / percentage)
            cost += compact_work_day_weight * scale * compact_multiplier
        costs.append(cost + (group_switch_day_weight * scale if mixed else 0.0))
        pattern_owner.append((e_i, d_i))
        pattern_segments.append(segments)
        pattern_half_groups.append(dict(half_groups))
        pattern_slot_coverage_overrides.append(coverage_overrides)
        pattern_slot_display_overrides.append(display_overrides)
        pattern_slot_activities.append(activities)
        pattern_site.append(site)
        pattern_duration.append(duration)
        pattern_primary_group.append(primary_g)
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
        pattern_child_duration.append(child_duration)
        pattern_colloque_the_duration.append(colloque_the_duration)
        pattern_mixed.append(mixed)
        if duration == 0:
            pattern_stats["off"] += 1
        elif len(segments) > 1:
            pattern_stats["split"] += 1
        else:
            pattern_stats["continuous"] += 1
        if mixed:
            pattern_stats["mixed_group"] += 1
        if replacement:
            pattern_stats["replacement"] += 1
        if colloque_the_duration:
            pattern_stats["colloque"] += 1
        by_educator_day.setdefault((e_i, d_i), []).append(pattern_id)
        by_educator_day_primary.setdefault((e_i, d_i, primary_g), []).append(pattern_id)
        by_educator.setdefault(e_i, []).append(pattern_id)
        if replacement:
            replacement_terms.setdefault(replacement, []).append(pattern_id)
        site_durations: dict[str, int] = {}
        for start, end in segments:
            for slot in range(start, end):
                half_i = 0 if slot < split_slot else 1
                g_i = coverage_overrides.get(slot, half_groups[half_i])
                if g_i < 0:
                    continue
                coverage_terms.setdefault((d_i, g_i, slot), []).append(pattern_id)
                slot_site = groups[g_i]["site"]
                if (d_i, slot_site, slot) in site_demand:
                    site_terms.setdefault((d_i, slot_site, slot), []).append(pattern_id)
                site_durations[slot_site] = site_durations.get(slot_site, 0) + 1
        for slot_site, site_duration in site_durations.items():
            percentage_terms[slot_site].append((pattern_id, e_i, site_duration))

    def replacement_options(
        d_i: int,
        segments: tuple[tuple[int, int], ...],
        half_groups: dict[int, int],
    ) -> list[tuple[int, int] | None]:
        worked = {slot for start, end in segments for slot in range(start, end)}
        options: list[tuple[int, int] | None] = [None]
        for colloque in colloques_by_day.get(d_i, []):
            if not colloque["slots"].issubset(worked):
                continue
            base_groups = {half_groups[0 if slot < split_slot else 1] for slot in colloque["slots"]}
            if len(base_groups) != 1:
                continue
            source_g = next(iter(base_groups))
            if source_g >= 0 and source_g != int(colloque["group_i"]):
                options.append((int(colloque["id"]), source_g))
        return options

    for colloque in colloques:
        start_candidates.add(int(colloque["start_slot"]))
        end_candidates.add(int(colloque["end_slot"]))
    start_candidates = {slot for slot in start_candidates if 0 <= slot < horizon.slots}
    end_candidates = {slot for slot in end_candidates if 0 < slot <= horizon.slots}

    for e_i in range(len(educators)):
        attends_colloque = attends_colloque_by_educator[e_i]
        for primary_g in sorted(allowed_primary_groups[e_i]):
            primary_group = groups[primary_g]
            primary_site = primary_group["site"]
            primary_colloque = colloque_by_group.get(primary_g)
            for d_i, (day_key, _) in enumerate(DAYS):
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
                        for start in sorted(start_candidates):
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

                        if restricted_patterns or duration < 2 * min_segment_slots + colloque_duration:
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
                                morning_slots = sum(1 for slot in worked_slots if slot < split_slot)
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

                        if restricted_patterns or duration < 2 * min_segment_slots:
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
                                segments = ((first_start, first_end), (second_start, second_end))
                                base_cost = work_cost_or_none(e_i, day_key, segments)
                                if base_cost is None:
                                    continue
                                for g_morning in local_groups:
                                    morning_cost = group_cost_or_none(e_i, primary_g, g_morning, first_len)
                                    if morning_cost is None:
                                        continue
                                    for g_afternoon in local_groups:
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
                                            site,
                                            segments,
                                            {0: g_morning, 1: g_afternoon},
                                            duration,
                                            base_cost + morning_cost + afternoon_cost,
                                        )

    bundle.pattern_stats = dict(pattern_stats)
    bundle.pattern_count = len(costs)
    pattern_statistics = {
        "total": len(costs),
        **pattern_stats,
    }
    if progress_callback:
        progress_callback(
            25,
            (
                f"Patrons generes: {len(costs)} "
                f"(continus {pattern_stats['continuous']}, "
                f"coupes {pattern_stats['split']}, "
                f"mixtes {pattern_stats['mixed_group']}, "
                f"remplacements {pattern_stats['replacement']})"
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

    def add_model_row(
        terms: list[tuple[int, float]],
        lb: float,
        ub: float,
    ) -> None:
        for col, val in terms:
            if val:
                cols.append(int(col))
                vals.append(float(val))
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
            for g_i in sorted(allowed_primary_groups[e_i]):
                primary_var = primary_vars[(e_i, g_i)]
                terms = [(p_i, 1.0) for p_i in by_educator_day_primary.get((e_i, d_i, g_i), [])]
                terms.append((primary_var, -1.0))
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
        child_terms = [(p_i, float(pattern_child_duration[p_i])) for p_i in by_educator.get(e_i, [])]
        visible_terms = [(p_i, float(pattern_duration[p_i])) for p_i in by_educator.get(e_i, [])]
        add_model_row(
            child_terms,
            max(0, target - tolerance_slots - the_slots),
            max(0, upper_target - the_slots),
        )
        add_model_row(visible_terms, 0.0, upper_target)
        if hard_max_work_days:
            day_terms = [
                (p_i, 1.0)
                for p_i in by_educator.get(e_i, [])
                if pattern_duration[p_i] > 0
            ]
            add_model_row(
                day_terms,
                0.0,
                float(max_work_days_by_educator[e_i]),
            )

    for d_i in range(len(DAYS)):
        for g_i in range(len(groups)):
            for slot in range(horizon.slots):
                terms = [(p_i, 1.0) for p_i in coverage_terms.get((d_i, g_i, slot), [])]
                demand = group_demand[(d_i, g_i, slot)]
                add_model_row(terms, demand, max(3, demand))
        for (demand_d_i, site, slot), demand in site_demand.items():
            if demand_d_i != d_i:
                continue
            terms = [(p_i, 1.0) for p_i in site_terms.get((d_i, site, slot), [])]
            add_model_row(terms, demand, math.inf)

    for colloque in colloques:
        target_g = int(colloque["group_i"])
        for source_g in range(len(groups)):
            if source_g == target_g:
                continue
            terms = [(p_i, 1.0) for p_i in replacement_terms.get((int(colloque["id"]), source_g), [])]
            add_model_row(terms, 1.0, 1.0)

    if max_weekly_group_exception_days is not None:
        for e_i in range(len(educators)):
            if not attends_colloque_by_educator[e_i]:
                continue
            terms = [
                (p_i, float(pattern_mixed[p_i]))
                for p_i in by_educator.get(e_i, [])
                if pattern_mixed[p_i]
            ]
            if terms:
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
        terms = []
        for p_i, e_i, duration in percentage_terms[site]:
            coeff = -pct * duration
            if educator_types[e_i] in wanted_types:
                coeff += 100.0 * duration
            if coeff:
                terms.append((p_i, coeff))
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
    if progress_callback:
        progress_callback(45, "Resolution rapide des patrons" if feasible_only else "Resolution des patrons")
    objective_costs = np.zeros(len(costs), dtype=float) if feasible_only else np.array(costs)
    result = milp(
        c=objective_costs,
        integrality=np.ones(len(costs), dtype=np.int8),
        bounds=Bounds(np.zeros(len(costs)), np.ones(len(costs))),
        constraints=LinearConstraint(
            matrix,
            np.frombuffer(lower, dtype=np.float64),
            np.frombuffer(upper, dtype=np.float64),
        ),
        options={"time_limit": max(1.0, remaining_seconds()), "mip_rel_gap": 0.03},
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
                display_group = pattern_slot_display_overrides[pattern_id].get(
                    slot,
                    pattern_slot_coverage_overrides[pattern_id].get(
                        slot,
                        pattern_half_groups[pattern_id][half_i],
                    ),
                )
                activity = pattern_slot_activities[pattern_id].get(slot, "")
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
    candidates: list[Path] = []
    seen: set[Path] = set()
    for path in paths:
        if path is None:
            continue
        resolved = path.resolve()
        if resolved not in seen and resolved.exists():
            candidates.append(resolved)
            seen.add(resolved)
        directory = resolved.parent
        if directory.exists():
            for candidate in directory.glob("*.json"):
                candidate = candidate.resolve()
                if candidate not in seen:
                    candidates.append(candidate)
                    seen.add(candidate)

    candidates.sort(key=lambda item: item.stat().st_mtime if item.exists() else 0.0, reverse=True)
    for candidate in candidates:
        try:
            payload = load_json(candidate)
        except Exception:
            continue
        if payload.get("status") == "ok" and isinstance(payload.get("schedule"), dict):
            return payload
    return None


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
    fixed_primary_groups = (
        infer_majority_primary_groups_from_payload(data, latest_payload)
        if fix_primary_groups_from_latest
        else None
    )

    def finish_payload(payload: dict[str, Any], output_bundle: Any) -> int:
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
        write_latest_valid = payload.get("status") == "ok" and isinstance(payload.get("schedule"), dict)
        if latest_output_path and write_latest_valid:
            save_json(latest_output_path, payload)
        if latest_csv_path and write_latest_valid:
            write_csv(latest_csv_path, payload)
        if latest_html_path and write_latest_valid:
            write_html(latest_html_path, payload, output_bundle)
        emit_progress(100, "Termine")
        return 0 if payload["status"] == "ok" else 2

    solver_engine = str(config.get("solver_engine", "scipy")).strip().lower()
    if solver_engine in {"pattern_mip", "pattern-mip", "patterns", "patrons"}:
        emit_progress(10, "Calcul par patrons de journee")
        try:
            payload, output_bundle = make_pattern_mip_payload(
                data,
                time_limit=time_limit,
                type_aliases=aliases,
                min_daily_hours=min_daily_hours,
                enforce_min_daily_hours=enforce_min_daily_hours,
                short_day_penalty_weight=short_day_penalty_weight,
                max_split_gap_minutes=hard_max_split_gap_minutes,
                generation_max_split_gap_minutes=max_split_gap_minutes,
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
                feasible_only=fast_feasible,
                restricted_patterns=restricted_patterns,
                restricted_pattern_mode=restricted_pattern_mode,
                fixed_primary_groups=fixed_primary_groups,
                quality_profile=quality_profile_name,
                quality_profile_label=quality_profile_label,
                primary_group_report_enabled=primary_group_report_enabled,
                primary_group_warning_outside_hours=primary_group_warning_outside_hours,
                primary_group_warning_outside_days=primary_group_warning_outside_days,
                progress_callback=emit_progress,
            )
        except MemoryError:
            horizon = make_horizon(data)
            output_bundle = type(
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
            payload = {
                "status": "infeasible_or_not_solved",
                "solver_message": "Memoire insuffisante pendant la construction du modele de patrons.",
                "warnings": [],
                "diagnostics": [
                    "Le calcul a ete arrete proprement avant saturation de l'application.",
                    "Activez la reutilisation des groupes principaux du dernier planning ou reduisez les patrons.",
                ],
            }
        if fixed_primary_groups:
            warnings = list(payload.get("warnings", []))
            warnings.append(
                "Groupes principaux repris du dernier planning pour eviter les patrons dupliques; "
                "les affectations quotidiennes restent optimisees."
            )
            payload["warnings"] = sorted(set(warnings))
        if (
            payload.get("status") == "infeasible_or_not_solved"
            and hard_max_work_days
            and relax_work_days_if_infeasible
            and "infeasible" in str(payload.get("solver_message", "")).lower()
            and not any(
                str(item).startswith("Capacite enfants insuffisante")
                for item in payload.get("diagnostics", [])
            )
        ):
            relaxed_time_limit = remaining_time_limit()
            timed_out = "time limit" in str(payload.get("solver_message", "")).lower() or "temps limite" in str(
                payload.get("solver_message", "")
            ).lower()
            if timed_out or relaxed_time_limit < 30.0:
                warnings = list(payload.get("warnings", []))
                warnings.append(
                    "Essai avec limite de jours assouplie non lance: temps limite global atteint."
                )
                payload["warnings"] = sorted(set(warnings))
                emit_progress(95, "Temps limite atteint")
            else:
                emit_progress(50, "Diagnostic avec limite de jours assouplie")

                def relaxed_progress(percent: int, message: str) -> None:
                    emit_progress(50 + min(45, int(percent * 0.45)), message)

                try:
                    relaxed_payload, relaxed_bundle = make_pattern_mip_payload(
                        data,
                        time_limit=relaxed_time_limit,
                        type_aliases=aliases,
                        min_daily_hours=min_daily_hours,
                        enforce_min_daily_hours=enforce_min_daily_hours,
                        short_day_penalty_weight=short_day_penalty_weight,
                        max_split_gap_minutes=hard_max_split_gap_minutes,
                        generation_max_split_gap_minutes=max_split_gap_minutes,
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
                        compact_work_day_weight=max(compact_work_day_weight, relaxed_work_day_weight),
                        compact_part_time_priority=compact_part_time_priority,
                        hard_max_work_days=False,
                        feasible_only=fast_feasible,
                        restricted_patterns=restricted_patterns,
                        restricted_pattern_mode=restricted_pattern_mode,
                        fixed_primary_groups=fixed_primary_groups,
                        quality_profile=quality_profile_name,
                        quality_profile_label=quality_profile_label,
                        primary_group_report_enabled=primary_group_report_enabled,
                        primary_group_warning_outside_hours=primary_group_warning_outside_hours,
                        primary_group_warning_outside_days=primary_group_warning_outside_days,
                        progress_callback=relaxed_progress,
                    )
                except MemoryError:
                    relaxed_payload = {
                        "status": "infeasible_or_not_solved",
                        "solver_message": "Memoire insuffisante pendant le diagnostic assoupli.",
                        "warnings": [],
                        "diagnostics": [],
                    }
                    relaxed_bundle = output_bundle
                if relaxed_payload.get("status") == "ok":
                    payload = mark_work_day_diagnostic(relaxed_payload)
                    output_bundle = relaxed_bundle
        emit_progress(96, "Verification et ecriture des fichiers")
        return finish_payload(payload, output_bundle)

    if solver_engine in {"ortools", "cp-sat", "cpsat"}:
        emit_progress(10, "Calcul OR-Tools CP-SAT")
        payload, output_bundle = make_ortools_slot_payload(
            data,
            time_limit=time_limit,
            type_aliases=aliases,
            min_daily_hours=min_daily_hours,
            max_split_gap_minutes=hard_max_split_gap_minutes,
            weekly_hours_tolerance_minutes=weekly_hours_tolerance_minutes,
            half_day_split_time=half_day_split_time,
            max_weekly_group_exception_days=max_weekly_group_exception_days,
            split_shift_weight=split_shift_weight,
            split_gap_weight=split_gap_weight,
            group_switch_day_weight=group_switch_day_weight,
            same_group_week_weight=same_group_week_weight,
            hard_max_work_days=hard_max_work_days,
            progress_callback=emit_progress,
            hint_payload=latest_payload,
        )
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



