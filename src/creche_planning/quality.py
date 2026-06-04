from __future__ import annotations

import copy
from typing import Any

from .domain import (
    DAYS,
    DEFAULT_QUALITY_PROFILES,
    build_demands_by_day,
    format_time,
    normalize_day,
    normalize_flag,
    parse_time,
    slot_range_clipped,
)


def merged_quality_profiles(config: dict[str, Any]) -> dict[str, dict[str, Any]]:
    profiles = copy.deepcopy(DEFAULT_QUALITY_PROFILES)
    custom_profiles = config.get("quality_profiles", {})
    if not isinstance(custom_profiles, dict):
        return profiles

    for name, raw_profile in custom_profiles.items():
        if not isinstance(raw_profile, dict):
            continue
        profile = copy.deepcopy(profiles.get(str(name), {}))
        profile.update({key: value for key, value in raw_profile.items() if key != "weights"})
        weights = dict(profile.get("weights", {}))
        if isinstance(raw_profile.get("weights"), dict):
            weights.update(raw_profile["weights"])
        profile["weights"] = weights
        profiles[str(name)] = profile
    return profiles


def select_quality_profile(
    config: dict[str, Any],
    requested: str | None = None,
) -> tuple[str, str, dict[str, float], list[str]]:
    profiles = merged_quality_profiles(config)
    profile_name = str(requested or config.get("quality_profile") or "equilibre").strip() or "equilibre"
    warnings: list[str] = []
    if profile_name not in profiles:
        warnings.append(f"Profil qualite inconnu '{profile_name}', profil 'equilibre' utilise.")
        profile_name = "equilibre"

    profile = profiles.get(profile_name, profiles["equilibre"])
    label = str(profile.get("label") or profile_name)
    raw_weights = profile.get("weights", {})
    weights: dict[str, float] = {}
    if isinstance(raw_weights, dict):
        for key, value in raw_weights.items():
            try:
                weights[str(key)] = float(value)
            except (TypeError, ValueError):
                warnings.append(f"Poids ignore dans le profil {profile_name}: {key}={value}.")
    return profile_name, label, weights, warnings


def quality_profile_payload(name: str, label: str) -> dict[str, str]:
    return {"name": name, "label": label}


def attach_quality_profile(payload: dict[str, Any], name: str, label: str) -> None:
    profile = quality_profile_payload(name, label)
    payload["quality_profile"] = profile
    checks = payload.get("checks")
    if isinstance(checks, dict):
        checks["quality_profile"] = profile
        summary = checks.get("quality_summary")
        if isinstance(summary, dict):
            summary["profile"] = profile


def effective_max_split_gap_minutes(
    config: dict[str, Any],
    cli_value: int | None = None,
    default: int | None = 90,
) -> int | None:
    if cli_value is not None:
        return int(cli_value)
    for key in (
        "max_pause_between_blocks_minutes",
        "max_split_gap_minutes",
        "smooth_max_split_gap_minutes",
    ):
        if key not in config:
            continue
        value = config.get(key)
        if value is None:
            return None
        return int(value)
    return default


def _normal_child_blocks(blocks: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        block
        for block in blocks
        if block.get("activity") not in {"colloque", "remplacement_colloque"}
    ]


def _soft_time_rule_stats(
    data: dict[str, Any],
    schedule: dict[str, dict[str, list[dict[str, Any]]]],
    horizon: Any,
) -> dict[str, Any]:
    total = 0
    respected = 0
    violated_details: list[str] = []
    matched_minutes = 0
    requested_minutes = 0

    for raw_rule in data.get("rules_time", []):
        if len(raw_rule) < 6:
            continue
        pref_type, strength, educator_name, day_name, start, end = raw_rule[:6]
        if normalize_flag(str(strength)) == "hard" or educator_name not in schedule:
            continue
        day_key = normalize_day(str(day_name))
        if day_key not in schedule[educator_name]:
            continue
        total += 1
        slots = set(slot_range_clipped(horizon, str(start), str(end))[0])
        rule_minutes = len(slots) * horizon.step
        requested_minutes += rule_minutes
        overlap_minutes = 0
        for block in schedule[educator_name][day_key]:
            block_slots = set(slot_range_clipped(horizon, block["start"], block["end"])[0])
            overlap_minutes += len(block_slots & slots) * horizon.step
        matched_minutes += overlap_minutes
        is_negative = normalize_flag(str(pref_type)) in {"negatif", "negative", "neg"}
        ok = overlap_minutes == 0 if is_negative else overlap_minutes > 0
        if ok:
            respected += 1
        else:
            violated_details.append(
                f"{educator_name} {day_key} {start}-{end} "
                f"({'interdiction' if is_negative else 'souhait de presence'})"
            )

    return {
        "total": total,
        "respected": respected,
        "violated": max(0, total - respected),
        "matched_hours": round(matched_minutes / 60.0, 2),
        "requested_hours": round(requested_minutes / 60.0, 2),
        "violated_details": violated_details[:20],
    }


def _soft_group_rule_stats(
    data: dict[str, Any],
    schedule: dict[str, dict[str, list[dict[str, Any]]]],
) -> dict[str, Any]:
    total = 0
    respected = 0
    violated_details: list[str] = []

    for raw_rule in data.get("rules_group", []):
        if len(raw_rule) < 4:
            continue
        pref_type, strength, educator_name, group_name = raw_rule[:4]
        if normalize_flag(str(strength)) == "hard" or educator_name not in schedule:
            continue
        total += 1
        blocks = [
            block
            for day_blocks in schedule[educator_name].values()
            for block in _normal_child_blocks(day_blocks)
        ]
        is_negative = normalize_flag(str(pref_type)) in {"negatif", "negative", "neg"}
        if is_negative:
            ok = all(block.get("group") != group_name for block in blocks)
        else:
            ok = bool(blocks) and all(block.get("group") == group_name for block in blocks)
        if ok:
            respected += 1
        else:
            violated_details.append(
                f"{educator_name}: {'eviter' if is_negative else 'preferer'} {group_name}"
            )

    return {
        "total": total,
        "respected": respected,
        "violated": max(0, total - respected),
        "violated_details": violated_details[:20],
    }


def build_quality_summary(
    bundle: Any,
    schedule: dict[str, dict[str, list[dict[str, Any]]]],
    *,
    profile_name: str = "equilibre",
    profile_label: str = "Equilibre",
    hard_error_count: int = 0,
    soft_warning_count: int = 0,
    max_split_gap_minutes: int | None = 90,
    max_weekly_group_exception_days: int | None = 1,
    primary_groups_by_educator: dict[str, str] | None = None,
) -> dict[str, Any]:
    primary_groups_by_educator = primary_groups_by_educator or {}
    split_days: list[str] = []
    split_gaps: list[int] = []
    group_change_days: dict[str, list[str]] = {}
    group_change_transitions = 0
    replacement_count = 0
    replacement_minutes = 0
    primary_outside_days: set[tuple[str, str]] = set()
    primary_outside_minutes = 0

    for educator_name, by_day in schedule.items():
        for day_key, blocks in by_day.items():
            sorted_blocks = sorted(blocks, key=lambda item: parse_time(item["start"]))
            day_gaps: list[int] = []
            for previous, current in zip(sorted_blocks, sorted_blocks[1:]):
                gap = parse_time(current["start"]) - parse_time(previous["end"])
                if gap > 0:
                    day_gaps.append(gap)
            if day_gaps:
                split_days.append(f"{educator_name} {day_key}")
                split_gaps.extend(day_gaps)

            normal_blocks = sorted(_normal_child_blocks(blocks), key=lambda item: parse_time(item["start"]))
            ordered_groups = [str(block.get("group", "")) for block in normal_blocks if block.get("group")]
            changed_groups = {group for group in ordered_groups if group}
            if len(changed_groups) > 1:
                group_change_days.setdefault(educator_name, []).append(day_key)
            for previous_group, current_group in zip(ordered_groups, ordered_groups[1:]):
                if previous_group and current_group and previous_group != current_group:
                    group_change_transitions += 1

            primary_group = primary_groups_by_educator.get(educator_name)
            for block in normal_blocks:
                if primary_group and block.get("group") != primary_group:
                    primary_outside_days.add((educator_name, day_key))
                    primary_outside_minutes += parse_time(block["end"]) - parse_time(block["start"])
            for block in blocks:
                if block.get("activity") == "remplacement_colloque":
                    replacement_count += 1
                    replacement_minutes += parse_time(block["end"]) - parse_time(block["start"])

    weekly_group_limit_violations = {
        educator: days
        for educator, days in group_change_days.items()
        if max_weekly_group_exception_days is not None and len(days) > max_weekly_group_exception_days
    }

    group_demand, _site_demand = build_demands_by_day(bundle.data, bundle.groups, bundle.horizon)
    group_by_name = {group["name"]: i for i, group in enumerate(bundle.groups)}
    excess_slots = 0
    overstaffed_slots = 0
    for d_i, (day_key, _day_label) in enumerate(DAYS):
        counts = {
            (g_i, t_i): 0
            for g_i in range(len(bundle.groups))
            for t_i in range(bundle.horizon.slots)
        }
        for by_day in schedule.values():
            for block in by_day.get(day_key, []):
                if block.get("activity") == "colloque" or block.get("group") not in group_by_name:
                    continue
                g_i = group_by_name[block["group"]]
                start_slot = (parse_time(block["start"]) - bundle.horizon.start) // bundle.horizon.step
                end_slot = (parse_time(block["end"]) - bundle.horizon.start) // bundle.horizon.step
                for t_i in range(max(0, start_slot), min(bundle.horizon.slots, end_slot)):
                    counts[(g_i, t_i)] += 1
        for g_i in range(len(bundle.groups)):
            for t_i in range(bundle.horizon.slots):
                demand = group_demand[(d_i, g_i, t_i)]
                actual = counts[(g_i, t_i)]
                if actual > demand:
                    overstaffed_slots += 1
                    excess_slots += actual - demand

    soft_time = _soft_time_rule_stats(bundle.data, schedule, bundle.horizon)
    soft_group = _soft_group_rule_stats(bundle.data, schedule)
    max_gap_found = max(split_gaps) if split_gaps else 0
    split_gap_violations = (
        0
        if max_split_gap_minutes is None
        else sum(1 for gap in split_gaps if gap > max_split_gap_minutes)
    )

    metrics = {
        "hard_error_count": hard_error_count,
        "soft_warning_count": soft_warning_count,
        "split_days_count": len(split_days),
        "split_gaps_count": len(split_gaps),
        "total_split_gap_hours": round(sum(split_gaps) / 60.0, 2),
        "max_split_gap_minutes_found": max_gap_found,
        "max_split_gap_minutes_allowed": max_split_gap_minutes,
        "split_gap_violations": split_gap_violations,
        "group_change_days_count": sum(len(days) for days in group_change_days.values()),
        "group_change_transitions_count": group_change_transitions,
        "educators_with_group_changes_count": len(group_change_days),
        "weekly_group_limit_violations_count": len(weekly_group_limit_violations),
        "primary_group_outside_days_count": len(primary_outside_days),
        "primary_group_outside_hours": round(primary_outside_minutes / 60.0, 2),
        "replacement_colloque_blocks": replacement_count,
        "replacement_colloque_hours": round(replacement_minutes / 60.0, 2),
        "overstaffed_slots_count": overstaffed_slots,
        "overstaffing_extra_hours": round(excess_slots * bundle.horizon.step / 60.0, 2),
        "soft_time_rules": soft_time,
        "soft_group_rules": soft_group,
    }

    def ratio(stats: dict[str, Any]) -> str:
        total = int(stats.get("total", 0))
        if total == 0:
            return "aucune"
        return f"{int(stats.get('respected', 0))}/{total}"

    scorecard = [
        {
            "label": "Regles hard",
            "value": "OK" if hard_error_count == 0 else f"{hard_error_count} erreur(s)",
            "ok": hard_error_count == 0,
        },
        {
            "label": "Coupures",
            "value": f"{len(split_days)} jour(s), plus grande {max_gap_found} min",
            "ok": split_gap_violations == 0,
        },
        {
            "label": "Changements de groupe",
            "value": (
                f"{metrics['group_change_days_count']} jour(s), "
                f"{metrics['group_change_transitions_count']} transition(s)"
            ),
            "ok": metrics["weekly_group_limit_violations_count"] == 0,
        },
        {
            "label": "Hors groupe principal",
            "value": (
                f"{metrics['primary_group_outside_days_count']} jour(s), "
                f"{metrics['primary_group_outside_hours']}h"
            ),
            "ok": metrics["primary_group_outside_days_count"] == 0,
        },
        {
            "label": "Preferences horaires soft",
            "value": ratio(soft_time),
            "ok": int(soft_time.get("violated", 0)) == 0,
        },
        {
            "label": "Preferences groupes soft",
            "value": ratio(soft_group),
            "ok": int(soft_group.get("violated", 0)) == 0,
        },
        {
            "label": "Remplacements colloque",
            "value": f"{replacement_count} bloc(s), {round(replacement_minutes / 60.0, 2)}h",
            "ok": True,
        },
        {
            "label": "Surplus vs minimum",
            "value": f"{metrics['overstaffing_extra_hours']}h-personne",
            "ok": True,
        },
    ]

    return {
        "profile": quality_profile_payload(profile_name, profile_label),
        "scorecard": scorecard,
        "metrics": metrics,
        "split_day_details": split_days[:30],
        "group_change_day_details": {
            educator: days[:5] for educator, days in group_change_days.items()
        },
        "weekly_group_limit_violations": weekly_group_limit_violations,
        "notes": [
            "Les remplacements de colloque sont exclus des changements de groupe.",
            "Le surplus compare les personnes presentes au besoin minimum; ce n'est pas une erreur hard.",
        ],
    }


def format_quality_summary_lines(summary: dict[str, Any] | None) -> list[str]:
    if not summary:
        return []
    profile = summary.get("profile", {})
    lines = [f"Profil qualite: {profile.get('label', profile.get('name', '?'))}"]
    for item in summary.get("scorecard", []):
        lines.append(f"- {item.get('label', '?')}: {item.get('value', '')}")
    for note in summary.get("notes", []):
        lines.append(f"- Note: {note}")
    return lines
