"""Structural checks shared by imports, the editor and solver entry points."""
from __future__ import annotations
import math
from typing import Any
from .domain import DAYS, normalize_day, normalize_day_list, normalize_flag, normalize_colloque_list, parse_time


def _data_errors(data: Any) -> list[str]:
    errors: list[str] = []
    if not isinstance(data, dict):
        return ['Donnees: objet JSON attendu.']
    def number(value, label, low=0, high=None):
        try:
            n = float(value)
            if not math.isfinite(n) or n < low or (high is not None and n > high):
                raise ValueError()
        except (TypeError, ValueError, OverflowError):
            errors.append(f'{label}: nombre fini entre {low} et {high} attendu.')
    def interval(start, end, label):
        try:
            a, b = parse_time(start), parse_time(end)
            if b <= a or a % 15 or b % 15:
                raise ValueError()
        except (TypeError, ValueError, AttributeError):
            errors.append(f'{label}: plage horaire invalide ou non alignee a 15 minutes.')
    names = {}
    for key in ('sites', 'groups', 'educators', 'educator_types'):
        rows = data.get(key, [])
        if not isinstance(rows, list) or any(not isinstance(r, dict) for r in rows):
            errors.append(f'{key}: liste d’objets attendue.')
            names[key] = set()
            continue
        seen = set()
        for row in rows:
            name = row.get('name')
            if not isinstance(name, str) or not name.strip() or name in seen:
                errors.append(f'{key}: nom vide ou duplique: {name}.')
            else:
                seen.add(name)
        names[key] = seen
    if errors:
        return errors
    for s in data.get('sites', []):
        interval(s.get('open', '06:45'), s.get('close', '18:45'), f"Site {s['name']}")
    for g in data.get('groups', []):
        if g.get('site') not in names['sites']:
            errors.append(f"Groupe {g['name']}: site inconnu {g.get('site')}.")
    for e in data.get('educators', []):
        number(e.get('percentage', 0), f"{e['name']}: percentage", high=100)
        if e.get('max_work_days') not in (None, ''):
            number(e['max_work_days'], f"{e['name']}: max_work_days", high=5)
            try:
                if float(e['max_work_days']) % 1:
                    errors.append(f"{e['name']}: max_work_days entier attendu.")
            except (ValueError, TypeError, OverflowError):
                pass
        if str(e.get('attends_colloque', True)).lower() not in {'true','false','oui','non','yes','no','1','0','vrai','faux','y','n','none'}:
            errors.append(f"{e['name']}: attends_colloque inconnu.")
        if names['educator_types'] and e.get('type') not in names['educator_types']:
            errors.append(f"{e['name']}: type inconnu {e.get('type')}.")
    global_rules = data.get('rules_global', {})
    if not isinstance(global_rules, dict):
        errors.append('rules_global: objet attendu.')
    else:
        for key, default in (('max_weekly_hours', 40), ('max_daily_hours', 8.5)):
            number(global_rules.get(key, default), f'rules_global.{key}', low=.0001)
    for key, size in (('rules_time', 6), ('rules_group', 4), ('rules_percentage', 4)):
        rows = data.get(key, [])
        if not isinstance(rows, list):
            errors.append(f'{key}: liste attendue.'); continue
        for i, row in enumerate(rows):
            label = f'{key}[{i}]'
            if not isinstance(row, (list, tuple)) or len(row) < size:
                errors.append(f'{label}: regle incomplete.'); continue
            if key == 'rules_percentage':
                if normalize_flag(str(row[1])) not in {'min','max'} or row[3] not in names['sites']:
                    errors.append(f'{label}: min/max ou site inconnu.')
                number(row[2], label, high=100)
                if not isinstance(row[0], (list, tuple)):
                    errors.append(f'{label}: liste de types attendue.')
                continue
            if normalize_flag(str(row[0])) not in {'positif','positive','pos','negatif','negative','neg'} or normalize_flag(str(row[1])) not in {'hard','soft'}:
                errors.append(f'{label}: drapeau inconnu.')
            if row[2] not in names['educators']:
                errors.append(f'{label}: educateur inconnu {row[2]}.')
            if key == 'rules_group':
                if row[3] not in names['groups']:
                    errors.append(f'{label}: groupe inconnu {row[3]}.')
            else:
                if normalize_day(str(row[3])) not in dict(DAYS):
                    errors.append(f'{label}: jour inconnu {row[3]}.')
                interval(row[4], row[5], label)
    group_site = {g['name']: g['site'] for g in data.get('groups', [])}
    for rule in data.get('rules_site_schedule', []):
        if not isinstance(rule, dict) or rule.get('site') not in names['sites']:
            errors.append('Staffing: site inconnu ou regle invalide.'); continue
        for row in rule.get('time_intervals', []):
            if not isinstance(row, dict):
                errors.append('Staffing: intervalle invalide.'); continue
            interval(row.get('start'), row.get('end'), 'Staffing')
            try:
                normalize_day_list(row.get('days', rule.get('days')))
            except ValueError as exc:
                errors.append(str(exc))
            group = row.get('group', 'tous')
            if group != 'tous' and group_site.get(group) != rule['site']:
                errors.append(f'Staffing: groupe/site incoherent {group}.')
            number(row.get('min_staff', 0), 'min_staff')
            for key in ('min_staff', 'max_staff'):
                if row.get(key) not in (None, ''):
                    try:
                        if float(row[key]) % 1:
                            errors.append(f'Staffing: {key} entier attendu.')
                    except (ValueError, TypeError, OverflowError):
                        errors.append(f'Staffing: {key} invalide.')
            maximum = row.get('max_staff')
            if maximum not in (None, ''):
                number(maximum, 'max_staff')
                try:
                    if float(maximum) < float(row.get('min_staff', 0)):
                        errors.append('Staffing: max_staff < min_staff.')
                except (TypeError, ValueError):
                    pass
    meeting_slots = set()
    for raw in data.get('rules_colloques', []):
        row = normalize_colloque_list(raw)
        label = f"Colloque {row['group']}"
        if row['group'] not in names['groups'] or normalize_day(str(row['day'])) not in dict(DAYS):
            errors.append(f'{label}: groupe ou jour inconnu.')
        interval(row['start'], row['end'], label)
        try:
            for minute in range(parse_time(row['start']), parse_time(row['end']), 15):
                key = (row['group'], normalize_day(row['day']), minute)
                if key in meeting_slots:
                    errors.append(f'{label}: colloques du meme groupe se chevauchent.'); break
                meeting_slots.add(key)
        except (ValueError, TypeError, AttributeError):
            pass
    return errors


def data_errors(data: Any) -> list[str]:
    try:
        return _data_errors(data)
    except (TypeError, ValueError, KeyError, AttributeError, OverflowError) as exc:
        return [f'Structure de donnees invalide: {exc}.']


def require_valid_data(data: Any) -> None:
    errors = data_errors(data)
    if errors:
        raise ValueError('Donnees invalides: ' + '; '.join(errors))


def schedule_errors(data: dict, schedule: Any, horizon: Any) -> list[str]:
    if not isinstance(schedule, dict):
        return ['Planning: objet attendu.']
    errors = []
    people = {e['name'] for e in data.get('educators', [])}
    groups = {g['name']: g['site'] for g in data.get('groups', [])}
    for extra in set(schedule) - people:
        errors.append(f'Educateur inconnu dans le planning: {extra}.')
    for name in people:
        by_day = schedule.get(name)
        if not isinstance(by_day, dict):
            errors.append(f'{name}: planning absent ou invalide.'); continue
        for extra in set(by_day) - set(dict(DAYS)):
            errors.append(f'{name}: jour inconnu {extra}.')
        for day, _ in DAYS:
            blocks = by_day.get(day)
            if not isinstance(blocks, list):
                errors.append(f'{name} {day}: liste de blocs absente.'); continue
            for block in blocks:
                try:
                    if not isinstance(block, dict):
                        raise ValueError('objet bloc attendu')
                    a, b = parse_time(block['start']), parse_time(block['end'])
                    if b <= a:
                        raise ValueError('plage horaire invalide')
                    if a < horizon.start or b > horizon.end or (a-horizon.start) % horizon.step or (b-horizon.start) % horizon.step:
                        raise ValueError('plage hors horizon ou non alignee')
                    if block['group'] not in groups or block['site'] != groups[block['group']]:
                        raise ValueError('groupe/site incoherent')
                    if not math.isfinite(float(block['hours'])):
                        raise ValueError('duree non finie')
                    if block.get('activity', 'children') not in {'children','colloque','remplacement_colloque'}:
                        raise ValueError('activite inconnue')
                except (KeyError, TypeError, ValueError, AttributeError, OverflowError) as exc:
                    errors.append(f'{name} {day}: bloc invalide: {exc}.')
    return errors
