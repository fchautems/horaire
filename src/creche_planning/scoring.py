"""Shared coefficients and schedule evaluation for the compact CP-SAT objective."""
from __future__ import annotations

from typing import Any

from .domain import (DAYS, Horizon, make_horizon, normalize_day, normalize_flag,
                     slot_range_clipped, the_target_slots)


def compact_quality_context(
    data: dict[str, Any], *, split_shift_weight: float = 120.0,
    group_switch_day_weight: float = 8.0, same_group_week_weight: float = 0.4,
    work_day_weight: float = 0.0, the_enabled: bool = True,
    the_percent: float = 10.0,
) -> dict[str, Any]:
    """Compile only scoring inputs; hard constraints stay in the validator."""
    horizon = make_horizon(data)
    educators = {e['name']: e for e in data.get('educators', [])}
    groups = [g['name'] for g in data.get('groups', [])]
    weekly = float(data.get('rules_global', {}).get('max_weekly_hours', 40.0))
    targets = {}
    for name, educator in educators.items():
        target = int(round(float(educator['percentage']) / 100 * weekly * 60 / horizon.step))
        targets[name] = max(0, target - the_target_slots(target, the_percent, enabled=the_enabled))
    primary_preferences: dict[str, str] = {}
    group_rules = []
    for rule in data.get('rules_group', []):
        if len(rule) < 4:
            continue
        pref, strength, name, group = rule[:4]
        if name not in educators or group not in groups or normalize_flag(strength) == 'hard':
            continue
        negative = normalize_flag(pref) in {'negatif', 'negative', 'neg'}
        if not negative:
            primary_preferences.setdefault(name, group)
        group_rules.append([name, group, negative])
    time_rules = []
    for rule in data.get('rules_time', []):
        if len(rule) < 6:
            continue
        pref, strength, name, day, start, end = rule[:6]
        day = normalize_day(day)
        if (name not in educators or day not in dict(DAYS)
                or normalize_flag(strength) == 'hard'):
            continue
        slots = list(slot_range_clipped(horizon, start, end)[0])
        if slots:
            time_rules.append([name, day, slots,
                               normalize_flag(pref) in {'negatif', 'negative', 'neg'}])
    return {
        'version': 'compact-v1',
        'horizon': {'start': horizon.start, 'end': horizon.end, 'step': horizon.step},
        'child_targets': targets, 'primary_preferences': primary_preferences,
        'group_rules': group_rules, 'time_rules': time_rules,
        'weights': {
            'child_slots': 1, 'presence_starts': int(round(split_shift_weight * 100)),
            'worked_days': int(round(work_day_weight * 100)),
            'mixed_days': int(round(group_switch_day_weight * 100)),
            'outside_group_days': int(round(same_group_week_weight * 100)),
            'outside_days': int(round(group_switch_day_weight * 400)),
            'hour_deviation_slots': 2500, 'preferred_primary': -500,
            'negative_time_slots': 45, 'positive_time_slots': -35,
            'group_rule_slots': 18,
        },
    }


def compact_quality_breakdown(payload: dict[str, Any], context: dict[str, Any]) -> dict[str, int]:
    """Recompute from actual assignments, never trust a cached objective value."""
    if context.get('version') != 'compact-v1':
        raise ValueError('Version de score inconnue')
    horizon = Horizon(**context['horizon'])
    counts = dict.fromkeys(context['weights'], 0)
    work: dict[tuple[str, str], set[int]] = {}
    children: dict[tuple[str, str], set[tuple[str, int]]] = {}
    primaries = payload.get('checks', {}).get('primary_groups_by_educator', {})
    for name, target in context['child_targets'].items():
        primary = primaries.get(name)
        if primary is None:
            raise ValueError(f'Groupe principal manquant pour le score: {name}')
        child_count = 0
        counts['preferred_primary'] += int(context['primary_preferences'].get(name) == primary)
        for day, _ in DAYS:
            occupied: set[int] = set()
            assignments: set[tuple[str, int]] = set()
            regular_groups: set[str] = set()
            for block in payload.get('schedule', {}).get(name, {}).get(day, []):
                slots = set(slot_range_clipped(horizon, block['start'], block['end'])[0])
                occupied.update(slots)
                if block.get('activity') != 'colloque':
                    assignments.update((block['group'], t) for t in slots)
                    if block.get('activity') != 'remplacement_colloque' and slots:
                        regular_groups.add(block['group'])
            work[name, day] = occupied
            children[name, day] = assignments
            child_count += len(assignments)
            counts['worked_days'] += int(bool(occupied))
            counts['presence_starts'] += sum(t - 1 not in occupied for t in occupied)
            counts['mixed_days'] += int(len(regular_groups) > 1)
            outside = regular_groups - {primary}
            counts['outside_group_days'] += len(outside)
            counts['outside_days'] += int(bool(outside))
        counts['child_slots'] += child_count
        counts['hour_deviation_slots'] += abs(child_count - target)
    for name, day, slots, negative in context['time_rules']:
        key = 'negative_time_slots' if negative else 'positive_time_slots'
        counts[key] += len(work[name, day].intersection(slots))
    for name, target, negative in context['group_rules']:
        counts['group_rule_slots'] += sum(
            (group == target if negative else group != target)
            for day, _ in DAYS for group, _slot in children[name, day]
        )
    return {key: int(value * context['weights'][key]) for key, value in counts.items()}
