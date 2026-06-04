from __future__ import annotations

import csv
import html
from pathlib import Path
from typing import Any

from .domain import DAYS, SolveBundle, build_demands_by_day, format_time, parse_time
from .quality import effective_max_split_gap_minutes, format_quality_summary_lines


def build_rule_summary(data: dict[str, Any], config: dict[str, Any]) -> dict[str, list[dict[str, str]]]:
    rules_global = data.get("rules_global", {})
    weekly_base = float(rules_global.get("max_weekly_hours", 40.0))
    max_daily = float(rules_global.get("max_daily_hours", 8.5))
    absolute_max = config.get("absolute_max_weekly_hours", weekly_base)
    tolerance_percent = float(config.get("weekly_hours_tolerance_percent", 3.0))
    tolerance_step = config.get("weekly_hours_tolerance_step_minutes", 15)
    max_gap = effective_max_split_gap_minutes(config)
    max_group_days = config.get("max_weekly_group_exception_days", 1)
    min_daily = config.get("min_daily_hours", 2)
    the_percent = float(config.get("the_percent", 10.0))

    hard = [
        {
            "code": "coverage_minimum",
            "rule": "Couvrir les besoins minimums par groupe, site et tranche horaire.",
            "source": "gwendo.json / rules_site_schedule",
        },
        {
            "code": "qualification_percentages",
            "rule": "Respecter les pourcentages EDE, ASE et APE par site.",
            "source": "gwendo.json / rules_percentage",
        },
        {
            "code": "time_rules_hard",
            "rule": "Respecter les obligations et interdictions horaires marquees hard.",
            "source": "gwendo.json / rules_time",
        },
        {
            "code": "group_rules_hard",
            "rule": "Respecter les obligations et interdictions de groupe principal marquees hard.",
            "source": "gwendo.json / rules_group",
        },
        {
            "code": "max_daily_hours",
            "rule": f"Ne pas depasser {max_daily:g}h de travail par jour.",
            "source": "gwendo.json / rules_global.max_daily_hours",
        },
        {
            "code": "absolute_weekly_cap",
            "rule": f"Ne jamais depasser {float(absolute_max):g}h de travail par semaine.",
            "source": "solveur_config.json / absolute_max_weekly_hours",
        },
        {
            "code": "weekly_contract_tolerance",
            "rule": (
                f"Rester autour des heures contractuelles avec une tolerance maximale de "
                f"{tolerance_percent:g}% par paliers de {tolerance_step} minutes."
            ),
            "source": "solveur_config.json / weekly_hours_tolerance_percent",
        },
        {
            "code": "the",
            "rule": (
                f"Compter {the_percent:g}% du temps contractuel en THE. Les colloques en font partie; "
                "le THE hors colloque est invisible et ne compte pas dans la couverture enfants."
            ),
            "source": "solveur_config.json / the_percent et gwendo.json / rules_colloques",
        },
        {
            "code": "min_daily_hours",
            "rule": f"Si une personne travaille, eviter les mini-presences: minimum {float(min_daily):g}h.",
            "source": "solveur_config.json / min_daily_hours",
        },
        {
            "code": "half_day_group_stability",
            "rule": "Ne pas changer de groupe dans une meme demi-journee, hors remplacement de colloque.",
            "source": "solveur_config.json / half_day_split_time",
        },
        {
            "code": "weekly_group_exception_limit",
            "rule": f"Avoir au maximum {max_group_days} jour(s) avec changement de groupe par semaine.",
            "source": "solveur_config.json / max_weekly_group_exception_days",
        },
        {
            "code": "split_gap_limit",
            "rule": f"Si une journee est coupee, la coupure ne doit pas depasser {max_gap} minutes.",
            "source": "solveur_config.json / max_pause_between_blocks_minutes",
        },
        {
            "code": "colloques",
            "rule": (
                "Chaque educateur participe au colloque complet de son groupe principal. "
                "Pendant ce colloque, il ne compte plus en couverture; une personne de chaque "
                "autre groupe remplace; les remplacements comptent dans les pourcentages du site."
            ),
            "source": "gwendo.json / rules_colloques",
        },
    ]
    soft = [
        {
            "code": "compact_work_days",
            "rule": "Regrouper les temps partiels sur le moins de jours possible.",
            "source": "solveur_config.json / compact_work_days",
        },
        {
            "code": "avoid_split_days",
            "rule": "Eviter les horaires coupes quand une journee continue est possible.",
            "source": "solveur_config.json / smooth_split_shift_weight",
        },
        {
            "code": "same_group_week",
            "rule": "Garder autant que possible une personne dans le meme groupe sur la semaine.",
            "source": "solveur_config.json / smooth_same_group_week_weight",
        },
        {
            "code": "soft_preferences",
            "rule": "Respecter autant que possible les preferences horaires et de groupe marquees soft.",
            "source": "gwendo.json / rules_time et rules_group",
        },
    ]
    return {"hard": hard, "soft": soft}


def write_csv(path: Path, payload: dict[str, Any]) -> None:
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle, delimiter=";")
        writer.writerow(["educator", "day", "site", "group", "start", "end", "hours", "activity"])
        schedule = payload.get("schedule")
        if not schedule:
            writer.writerow(["", "", "", "AUCUN_PLANNING_VALIDE", "", "", "0", payload.get("solver_message", "")])
            for diagnostic in payload.get("diagnostics", []):
                writer.writerow(["", "", "", "DIAGNOSTIC", "", "", "0", diagnostic])
            return
        for educator, by_day in schedule.items():
            for day, blocks in by_day.items():
                if not blocks:
                    writer.writerow([educator, day, "", "OFF", "", "", "0", ""])
                for block in blocks:
                    writer.writerow(
                        [
                            educator,
                            day,
                            block["site"],
                            block["group"],
                            block["start"],
                            block["end"],
                            block["hours"],
                            block.get("activity", ""),
                        ]
                    )


def write_html(path: Path, payload: dict[str, Any], bundle: SolveBundle) -> None:
    palette = [
        "#2563eb", "#dc2626", "#16a34a", "#9333ea", "#ea580c", "#0891b2",
        "#be123c", "#4f46e5", "#0f766e", "#a16207", "#7c3aed", "#15803d",
        "#b91c1c", "#0369a1", "#c2410c", "#6d28d9",
    ]
    educator_names = [educator["name"] for educator in bundle.educators]
    colors = {name: palette[i % len(palette)] for i, name in enumerate(educator_names)}
    group_demand, _ = build_demands_by_day(bundle.data, bundle.groups, bundle.horizon)
    schedule = payload.get("schedule", {})

    def esc(value: Any) -> str:
        return html.escape(str(value), quote=True)

    if "schedule" not in payload:
        diagnostics = payload.get("diagnostics", [])
        warnings = payload.get("warnings", [])
        hard_rules = payload.get("rule_summary", {}).get("hard", [])
        diagnostic_items = "".join(f"<li>{esc(item)}</li>" for item in diagnostics)
        warning_items = "".join(f"<li>{esc(item)}</li>" for item in warnings)
        rule_items = "".join(
            f"<li><strong>{esc(item.get('code', ''))}</strong> - {esc(item.get('rule', ''))}</li>"
            for item in hard_rules
        )
        path.write_text(
            f"""<!doctype html>
<html lang="fr">
<head>
<meta charset="utf-8">
<title>Resultat du solveur</title>
<style>
  body {{ margin: 24px; font-family: Arial, sans-serif; color: #172033; background: #f6f8fb; }}
  h1 {{ margin-top: 0; }}
  section {{ background: white; border: 1px solid #d7dde8; border-radius: 8px; padding: 12px; margin-bottom: 12px; }}
  .invalid {{ border-color: #fecdd3; background: #fff1f2; color: #9f1239; }}
  li {{ margin-bottom: 5px; }}
</style>
</head>
<body>
<h1>Resultat du solveur</h1>
<section class="invalid">
  <h2>{esc(payload.get('status', ''))}</h2>
  <p>{esc(payload.get('solver_message', ''))}</p>
</section>
{f'<section><h2>Diagnostics</h2><ul>{diagnostic_items}</ul></section>' if diagnostic_items else ''}
{f'<section><h2>Avertissements</h2><ul>{warning_items}</ul></section>' if warning_items else ''}
{f'<section><h2>Regles hard controlees</h2><ul>{rule_items}</ul></section>' if rule_items else ''}
</body>
</html>
""",
            encoding="utf-8",
        )
        return

    def short_name(name: str) -> str:
        clean = "".join(part[:1] for part in name.replace("-", " ").split() if part)
        return (clean or name[:2]).upper()

    def active_for(day_key: str, group_name: str, t_i: int) -> list[str]:
        minute = bundle.horizon.start + t_i * bundle.horizon.step
        active: list[str] = []
        for educator, by_day in schedule.items():
            for block in by_day.get(day_key, []):
                if block.get("activity") == "colloque":
                    continue
                if block.get("group") != group_name:
                    continue
                if parse_time(block["start"]) <= minute < parse_time(block["end"]):
                    active.append(educator)
                    break
        return active

    time_cells = []
    for t_i in range(bundle.horizon.slots):
        minute = bundle.horizon.start + t_i * bundle.horizon.step
        label = format_time(minute) if minute % 60 == 0 or t_i == 0 else ""
        time_cells.append(f'<div class="time-cell">{esc(label)}</div>')

    legend = "\n".join(
        f'<span class="legend-item"><span class="swatch" style="background:{colors[name]}"></span>{esc(name)}</span>'
        for name in educator_names
    )

    day_sections: list[str] = []
    for d_i, (day_key, day_label) in enumerate(DAYS):
        rows: list[str] = []
        for g_i, group in enumerate(bundle.groups):
            group_name = group["name"]
            cells: list[str] = []
            for t_i in range(bundle.horizon.slots):
                active = active_for(day_key, group_name, t_i)
                required = group_demand[(d_i, g_i, t_i)]
                maximum = max(3, required)
                cls = "under" if len(active) < required else "over" if len(active) > maximum else "ok"
                badges = "".join(
                    f'<span class="badge" title="{esc(name)}" style="background:{colors[name]}">{esc(short_name(name))}</span>'
                    for name in active
                )
                count = f"{len(active)}/{required}" if required else str(len(active))
                cells.append(f'<div class="slot {cls}"><div class="count">{esc(count)}</div>{badges}</div>')
            rows.append(
                '<div class="row-label">'
                f'<strong>{esc(group["site"])}</strong><br>{esc(group_name)}'
                '</div>'
                + "".join(cells)
            )
        day_sections.append(
            f'''
            <section class="day">
              <h2>{esc(day_label)}</h2>
              <div class="grid">
                <div class="corner"></div>
                {''.join(time_cells)}
                {''.join(rows)}
              </div>
            </section>
            '''
        )

    errors = payload.get("checks", {}).get("errors", [])
    alerts = payload.get("checks", {}).get("alerts", [])
    diagnostics = payload.get("diagnostics", [])
    checks = payload.get("checks", {})
    quality_summary = checks.get("quality_summary", {})
    status_label = "Planning valide" if payload.get("status") == "ok" else "Planning invalide"
    status_class = "valid" if payload.get("status") == "ok" else "invalid"
    error_html = f'<section class="status {status_class}"><h2>{esc(status_label)}</h2></section>'
    if quality_summary:
        profile = quality_summary.get("profile", {})
        rows = "".join(
            "<tr>"
            f"<td>{esc(item.get('label', ''))}</td>"
            f"<td>{esc(item.get('value', ''))}</td>"
            f"<td>{'OK' if item.get('ok') else 'A surveiller'}</td>"
            "</tr>"
            for item in quality_summary.get("scorecard", [])
        )
        notes = "".join(f"<li>{esc(note)}</li>" for note in quality_summary.get("notes", []))
        notes_html = f"<ul>{notes}</ul>" if notes else ""
        error_html += (
            "<section class=\"quality-summary\"><h2>Qualite du planning</h2>"
            f"<p>Profil: <strong>{esc(profile.get('label', profile.get('name', '')))}</strong></p>"
            "<table><thead><tr><th>Indicateur</th><th>Valeur</th><th>Lecture</th></tr></thead>"
            f"<tbody>{rows}</tbody></table>"
            f"{notes_html}"
            "</section>"
        )
    if errors:
        items = "".join(f"<li>{esc(error)}</li>" for error in errors)
        error_html += f"<section class=\"errors\"><h2>Controles hard a corriger</h2><ul>{items}</ul></section>"
    if alerts:
        items = "".join(f"<li>{esc(alert)}</li>" for alert in alerts)
        error_html += f"<section class=\"alerts\"><h2>Alertes non bloquantes</h2><ul>{items}</ul></section>"
    if diagnostics:
        items = "".join(f"<li>{esc(diagnostic)}</li>" for diagnostic in diagnostics)
        error_html += f"<section class=\"alerts\"><h2>Diagnostics</h2><ul>{items}</ul></section>"
    if checks.get("total_the_hours_by_educator"):
        rows = []
        for name, total in checks.get("hours_by_educator", {}).items():
            rows.append(
                "<tr>"
                f"<td>{esc(name)}</td>"
                f"<td>{esc(checks.get('primary_groups_by_educator', {}).get(name, ''))}</td>"
                f"<td>{float(total):.2f}h</td>"
                f"<td>{float(checks.get('weekly_targets', {}).get(name, 0.0)):.2f}h</td>"
                f"<td>{float(checks.get('child_hours_by_educator', {}).get(name, 0.0)):.2f}h</td>"
                f"<td>{float(checks.get('total_the_hours_by_educator', {}).get(name, 0.0)):.2f}h</td>"
                f"<td>{float(checks.get('colloque_the_hours_by_educator', {}).get(name, 0.0)):.2f}h</td>"
                f"<td>{float(checks.get('invisible_the_hours_by_educator', {}).get(name, 0.0)):.2f}h</td>"
                "</tr>"
            )
        error_html += (
            "<section class=\"hours-summary\"><h2>Heures et THE</h2>"
            "<table><thead><tr>"
            "<th>Educateur</th><th>Groupe principal</th><th>Total</th><th>Contrat</th><th>Enfants</th>"
            "<th>THE total</th><th>Colloque</th><th>THE invisible</th>"
            "</tr></thead><tbody>"
            f"{''.join(rows)}"
            "</tbody></table></section>"
        )
    hard_rules = payload.get("rule_summary", {}).get("hard", [])
    if hard_rules:
        items = "".join(
            f"<li><strong>{esc(item.get('code', ''))}</strong> - {esc(item.get('rule', ''))}</li>"
            for item in hard_rules
        )
        error_html += (
            "<section class=\"rule-summary\"><h2>Regles hard controlees</h2>"
            f"<ul>{items}</ul></section>"
        )

    content = f"""<!doctype html>
<html lang="fr">
<head>
<meta charset="utf-8">
<title>Planning visuel</title>
<style>
  :root {{ --slot-min: 20px; --line: #d7dde8; --text: #172033; }}
  * {{ box-sizing: border-box; }}
  body {{ margin: 16px; font-family: Arial, sans-serif; color: var(--text); background: #f6f8fb; }}
  h1 {{ margin: 0 0 8px; font-size: 24px; }}
  h2 {{ margin: 14px 0 8px; font-size: 16px; }}
  .meta {{ margin-bottom: 10px; color: #526070; }}
  .legend {{ display: flex; flex-wrap: wrap; gap: 6px 12px; margin: 10px 0 16px; font-size: 11px; }}
  .legend-item {{ display: inline-flex; align-items: center; gap: 4px; }}
  .swatch {{ width: 10px; height: 10px; border-radius: 2px; display: inline-block; }}
  .day {{ background: white; border: 1px solid var(--line); border-radius: 8px; padding: 10px; margin-bottom: 12px; page-break-inside: avoid; }}
  .grid {{ display: grid; grid-template-columns: 112px repeat({bundle.horizon.slots}, minmax(var(--slot-min), 1fr)); border-top: 1px solid var(--line); border-left: 1px solid var(--line); overflow-x: auto; }}
  .corner, .time-cell, .row-label, .slot {{ border-right: 1px solid var(--line); border-bottom: 1px solid var(--line); }}
  .time-cell {{ min-height: 22px; padding-top: 4px; text-align: center; font-size: 9px; color: #5c697a; background: #eef2f7; }}
  .row-label {{ min-height: 42px; padding: 7px 6px; font-size: 11px; background: #f8fafc; position: sticky; left: 0; z-index: 1; }}
  .slot {{ min-height: 42px; padding: 2px; overflow: hidden; }}
  .slot.ok {{ background: #f8fff9; }}
  .slot.under {{ background: #fee2e2; }}
  .slot.over {{ background: #ffedd5; }}
  .count {{ font-size: 8px; color: #64748b; line-height: 1; margin-bottom: 2px; }}
  .badge {{ display: block; color: white; border-radius: 3px; padding: 1px 2px; margin-bottom: 1px; font-size: 8px; line-height: 1.1; text-align: center; white-space: nowrap; }}
  .errors {{ background: #fff1f2; border: 1px solid #fecdd3; padding: 10px; border-radius: 8px; margin-bottom: 12px; }}
  .errors h2 {{ color: #be123c; margin-top: 0; }}
  .alerts {{ background: #fff7ed; border: 1px solid #fed7aa; padding: 10px; border-radius: 8px; margin-bottom: 12px; }}
  .alerts h2 {{ color: #c2410c; margin-top: 0; }}
  .hours-summary {{ background: white; border: 1px solid var(--line); padding: 10px; border-radius: 8px; margin-bottom: 12px; }}
  .hours-summary h2 {{ margin-top: 0; color: #334155; }}
  .hours-summary table {{ width: 100%; border-collapse: collapse; font-size: 11px; }}
  .hours-summary th, .hours-summary td {{ border-bottom: 1px solid var(--line); padding: 4px 6px; text-align: left; }}
  .hours-summary th {{ background: #eef2f7; }}
  .quality-summary {{ background: white; border: 1px solid var(--line); padding: 10px; border-radius: 8px; margin-bottom: 12px; }}
  .quality-summary h2 {{ margin-top: 0; color: #334155; }}
  .quality-summary table {{ width: 100%; border-collapse: collapse; font-size: 11px; margin-bottom: 8px; }}
  .quality-summary th, .quality-summary td {{ border-bottom: 1px solid var(--line); padding: 4px 6px; text-align: left; }}
  .quality-summary th {{ background: #eef2f7; }}
  .rule-summary {{ background: #f8fafc; border: 1px solid #dbe3ef; padding: 10px; border-radius: 8px; margin-bottom: 12px; }}
  .rule-summary h2 {{ margin-top: 0; color: #334155; }}
  .rule-summary li {{ margin-bottom: 4px; }}
  .status {{ padding: 9px 10px; border-radius: 8px; margin-bottom: 12px; border: 1px solid; }}
  .status h2 {{ margin: 0; }}
  .status.valid {{ background: #ecfdf5; border-color: #bbf7d0; color: #166534; }}
  .status.invalid {{ background: #fff1f2; border-color: #fecdd3; color: #be123c; }}
  @media print {{
    body {{ margin: 6mm; background: white; }}
    .day {{ break-inside: avoid; }}
    :root {{ --slot-min: 12px; }}
    .badge {{ font-size: 6px; }}
    .count {{ font-size: 6px; }}
  }}
</style>
</head>
<body>
<h1>Planning visuel</h1>
<div class="meta">Chaque case affiche <strong>personnes presentes / besoin minimum</strong>. Rouge = sous-couvert, orange = au-dessus du maximum usuel.</div>
<div class="legend">{legend}</div>
{error_html}
{''.join(day_sections)}
</body>
</html>
"""
    path.write_text(content, encoding="utf-8")


def print_report(payload: dict[str, Any]) -> None:
    print(f"Status: {payload['status']}")
    if payload.get("solver_message"):
        print(f"Solveur: {payload['solver_message']}")
    for warning in payload.get("warnings", []):
        print(f"Attention: {warning}")
    for diagnostic in payload.get("diagnostics", []):
        print(f"Diagnostic: {diagnostic}")
    if "schedule" not in payload:
        return

    if payload["status"] == "ok":
        print(f"Objectif: {payload['objective']}")
    else:
        print(f"Objectif: {payload.get('objective', '')}")
    checks = payload["checks"]
    quality_lines = format_quality_summary_lines(checks.get("quality_summary"))
    if quality_lines:
        print("\nQualite du planning:")
        for line in quality_lines:
            print(f"  {line}" if line.startswith("-") else line)

    print("\nHeures par educateur:")
    for name, hours in checks["hours_by_educator"].items():
        target = checks["weekly_targets"][name]
        if checks.get("total_the_hours_by_educator"):
            child = checks.get("child_hours_by_educator", {}).get(name, 0.0)
            the_total = checks.get("total_the_hours_by_educator", {}).get(name, 0.0)
            colloque = checks.get("colloque_the_hours_by_educator", {}).get(name, 0.0)
            invisible = checks.get("invisible_the_hours_by_educator", {}).get(name, 0.0)
            print(
                f"  {name}: {hours:.2f}h / {target:.2f}h "
                f"(enfants {child:.2f}h, THE {the_total:.2f}h "
                f"dont colloque {colloque:.2f}h, invisible {invisible:.2f}h)"
            )
        else:
            print(f"  {name}: {hours:.2f}h / {target:.2f}h")
    if checks.get("primary_groups_by_educator"):
        print("\nGroupes principaux:")
        for name, group_name in checks["primary_groups_by_educator"].items():
            print(f"  {name}: {group_name}")
    if checks.get("worked_days_by_educator"):
        print("\nJours travailles:")
        for name, days in checks["worked_days_by_educator"].items():
            target_days = checks.get("target_work_days", {}).get(name)
            max_days = checks.get("max_work_days", {}).get(name)
            if target_days is None and max_days is None:
                print(f"  {name}: {days}j")
            elif max_days is None:
                print(f"  {name}: {days}j / cible min {target_days}j")
            else:
                print(f"  {name}: {days}j / max {max_days}j")

    print("\nPlanning par educateur:")
    for educator, by_day in payload["schedule"].items():
        print(f"\n{educator}")
        for day_key, day_label in DAYS:
            blocks = by_day[day_key]
            if not blocks:
                print(f"  {day_label}: OFF")
                continue
            rendered = ", ".join(
                f"{block['start']}-{block['end']} {block['site']}/{block['group']}"
                + (
                    " (colloque)"
                    if block.get("activity") == "colloque"
                    else " (remplacement colloque)"
                    if block.get("activity") == "remplacement_colloque"
                    else ""
                )
                for block in blocks
            )
            print(f"  {day_label}: {rendered}")

    print("\nRegles de pourcentage:")
    for item in checks["percentage_rules"]:
        marker = "OK" if item["ok"] else "KO"
        print(
            f"  {marker} {item['site']} {item['types']} "
            f"{item['rule']} {item['target_percent']}% -> {item['actual_percent']}%"
        )
    if checks["errors"]:
        print("\nErreurs de verification:")
        for error in checks["errors"]:
            print(f"  - {error}")
    else:
        print("\nVerification: OK")
    if checks.get("alerts"):
        print("\nAlertes non bloquantes:")
        for alert in checks["alerts"]:
            print(f"  - {alert}")

