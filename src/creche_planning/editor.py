from __future__ import annotations

import argparse
import json
import subprocess
import sys
import threading
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from tkinter import filedialog, messagebox
import tkinter as tk
from tkinter import ttk

from .domain import (
    DAYS as DOMAIN_DAYS,
    build_demands_by_day,
    make_horizon,
    max_work_days_for_educator,
    parse_colloques,
    the_target_slots,
    weekly_tolerance_slots,
)
from .quality import format_quality_summary_lines


DAYS = ["lundi", "mardi", "mercredi", "jeudi", "vendredi"]
DAY_SHORT_LABELS = {
    "lundi": "lun",
    "mardi": "mar",
    "mercredi": "mer",
    "jeudi": "jeu",
    "vendredi": "ven",
}
DAY_ALIASES = {
    "lundi": "lundi",
    "lun": "lundi",
    "monday": "lundi",
    "mardi": "mardi",
    "mar": "mardi",
    "tuesday": "mardi",
    "mercredi": "mercredi",
    "mer": "mercredi",
    "wednesday": "mercredi",
    "jeudi": "jeudi",
    "jeu": "jeudi",
    "thursday": "jeudi",
    "vendredi": "vendredi",
    "ven": "vendredi",
    "friday": "vendredi",
}
POS_NEG = ["positif", "negatif"]
HARD_SOFT = ["hard", "soft"]
MIN_MAX = ["min", "max"]
DEFAULT_DATA = {
    "sites": [],
    "groups": [],
    "educator_types": [
        {"name": "APE", "description": "Autre personnel encadrant"},
        {"name": "ASE", "description": "Assistant socio-educatif"},
        {"name": "EDE", "description": "Educateur de l'enfance"},
    ],
    "educators": [],
    "rules_time": [],
    "rules_group": [],
    "rules_percentage": [],
    "rules_global": {
        "max_weekly_hours": 40.0,
        "max_daily_hours": 8.5,
    },
    "rules_site_schedule": [],
    "rules_colloques": [],
}


@dataclass(frozen=True)
class FieldSpec:
    key: str
    label: str
    field_type: str = "text"
    choices_name: str | None = None


@dataclass(frozen=True)
class TableSpec:
    name: str
    title: str
    fields: tuple[FieldSpec, ...]


TABLE_SPECS = [
    TableSpec(
        "sites",
        "Sites",
        (
            FieldSpec("name", "Nom"),
            FieldSpec("open", "Ouverture", "time"),
            FieldSpec("close", "Fermeture", "time"),
        ),
    ),
    TableSpec(
        "groups",
        "Groupes",
        (
            FieldSpec("name", "Nom"),
            FieldSpec("site", "Site", "choice", "sites"),
            FieldSpec("ratio", "Ratio", "int"),
        ),
    ),
    TableSpec(
        "educator_types",
        "Types",
        (
            FieldSpec("name", "Nom"),
            FieldSpec("description", "Description"),
        ),
    ),
    TableSpec(
        "educators",
        "Educateurs",
        (
            FieldSpec("name", "Nom"),
            FieldSpec("percentage", "Pourcentage", "int"),
            FieldSpec("type", "Type", "choice", "educator_types"),
            FieldSpec("max_work_days", "Max jours", "int_optional"),
        ),
    ),
    TableSpec(
        "rules_time",
        "Regles horaires",
        (
            FieldSpec("pos_neg", "Pos/Neg", "choice_static", "pos_neg"),
            FieldSpec("hard_soft", "Hard/Soft", "choice_static", "hard_soft"),
            FieldSpec("educator", "Educateur", "choice", "educators"),
            FieldSpec("day", "Jour", "choice_static", "days"),
            FieldSpec("start", "Debut", "time"),
            FieldSpec("end", "Fin", "time"),
        ),
    ),
    TableSpec(
        "rules_group",
        "Regles groupes",
        (
            FieldSpec("pos_neg", "Pos/Neg", "choice_static", "pos_neg"),
            FieldSpec("hard_soft", "Hard/Soft", "choice_static", "hard_soft"),
            FieldSpec("educator", "Educateur", "choice", "educators"),
            FieldSpec("group", "Groupe", "choice", "groups"),
        ),
    ),
    TableSpec(
        "rules_percentage",
        "Pourcentages",
        (
            FieldSpec("types", "Types"),
            FieldSpec("minmax", "Min/Max", "choice_static", "min_max"),
            FieldSpec("value", "Valeur %", "int"),
            FieldSpec("site", "Site", "choice", "sites"),
        ),
    ),
    TableSpec(
        "rules_site_schedule",
        "Staffing",
        (
            FieldSpec("site", "Site", "choice", "sites"),
            FieldSpec("days", "Jours", "days"),
            FieldSpec("start", "Debut", "time"),
            FieldSpec("end", "Fin", "time"),
            FieldSpec("group", "Groupe", "choice_plus_all", "groups"),
            FieldSpec("min_staff", "Min staff", "int"),
            FieldSpec("max_staff", "Max staff", "int_optional"),
        ),
    ),
    TableSpec(
        "rules_colloques",
        "Colloques",
        (
            FieldSpec("group", "Groupe", "choice", "groups"),
            FieldSpec("day", "Jour", "choice_static", "days"),
            FieldSpec("start", "Debut", "time"),
            FieldSpec("end", "Fin", "time"),
        ),
    ),
]


def new_data() -> dict:
    return json.loads(json.dumps(DEFAULT_DATA))


def ensure_schema(data: dict) -> dict:
    base = new_data()
    if not isinstance(data, dict):
        data = {}
    for key, value in base.items():
        data.setdefault(key, value)
    if not isinstance(data.get("rules_global"), dict):
        data["rules_global"] = dict(base["rules_global"])
    data["rules_global"].setdefault("max_weekly_hours", 40.0)
    data["rules_global"].setdefault("max_daily_hours", 8.5)
    return data


def load_json(path: Path) -> dict:
    with path.open("r", encoding="utf-8") as handle:
        return ensure_schema(json.load(handle))


def save_json(path: Path, data: dict) -> None:
    with path.open("w", encoding="utf-8") as handle:
        json.dump(data, handle, indent=4, ensure_ascii=False)
        handle.write("\n")


def split_types(value: str) -> list[str]:
    items: list[str] = []
    for raw in value.replace("+", ",").replace(";", ",").split(","):
        item = raw.strip()
        if item:
            items.append(item)
    return items


def normalize_rule_list(row: list | tuple, size: int) -> list:
    values = list(row)
    while len(values) < size:
        values.append("")
    return values[:size]


def parse_days_value(value: object) -> tuple[list[str], list[str]]:
    if value is None:
        return [], []
    if isinstance(value, (list, tuple)):
        raw_items = [str(item).strip() for item in value if str(item).strip()]
    else:
        text = str(value).strip().lower()
        if text in {"", "tous", "tout", "all", "*"}:
            return [], []
        for separator in ("+", ";", "|", "/"):
            text = text.replace(separator, ",")
        raw_items = [item.strip() for item in text.split(",") if item.strip()]

    days: list[str] = []
    unknown: list[str] = []
    for raw_item in raw_items:
        lowered = raw_item.lower()
        if lowered in {"tous", "tout", "all", "*"}:
            return [], []
        day = DAY_ALIASES.get(lowered)
        if day is None:
            unknown.append(raw_item)
            continue
        if day not in days:
            days.append(day)
    if len(days) == len(DAYS) and not unknown:
        return [], []
    return days, unknown


def days_from_value(value: object) -> list[str]:
    days, _unknown = parse_days_value(value)
    return days


def format_days(value: object) -> str:
    days, unknown = parse_days_value(value)
    if not days and not unknown:
        return "tous"
    labels = [DAY_SHORT_LABELS.get(day, day) for day in days]
    labels.extend(unknown)
    return ", ".join(labels)


def rows_from_data(data: dict, spec_name: str) -> list[dict[str, str]]:
    if spec_name in {"sites", "groups", "educator_types", "educators"}:
        rows = []
        for item in data.get(spec_name, []):
            rows.append({key: str(item.get(key, "")) for key in item.keys()})
        return rows

    if spec_name == "rules_time":
        rows = []
        for rule in data.get("rules_time", []):
            pos_neg, hard_soft, educator, day, start, end = normalize_rule_list(rule, 6)
            rows.append(
                {
                    "pos_neg": pos_neg,
                    "hard_soft": hard_soft,
                    "educator": educator,
                    "day": day,
                    "start": start,
                    "end": end,
                }
            )
        return rows

    if spec_name == "rules_group":
        rows = []
        for rule in data.get("rules_group", []):
            pos_neg, hard_soft, educator, group = normalize_rule_list(rule, 4)
            rows.append(
                {
                    "pos_neg": pos_neg,
                    "hard_soft": hard_soft,
                    "educator": educator,
                    "group": group,
                }
            )
        return rows

    if spec_name == "rules_percentage":
        rows = []
        for rule in data.get("rules_percentage", []):
            types, minmax, value, site = normalize_rule_list(rule, 4)
            if isinstance(types, list):
                types_value = ", ".join(str(item) for item in types)
            else:
                types_value = str(types)
            rows.append(
                {
                    "types": types_value,
                    "minmax": minmax,
                    "value": str(value),
                    "site": site,
                }
            )
        return rows

    if spec_name == "rules_site_schedule":
        rows = []
        for rule in data.get("rules_site_schedule", []):
            site = rule.get("site", "")
            for interval in rule.get("time_intervals", []):
                rows.append(
                    {
                        "site": site,
                        "days": format_days(interval.get("days", rule.get("days", ""))),
                        "start": str(interval.get("start", "")),
                        "end": str(interval.get("end", "")),
                        "group": str(interval.get("group", "")),
                        "min_staff": str(interval.get("min_staff", "")),
                        "max_staff": str(interval.get("max_staff", "")),
                    }
                )
        return rows

    if spec_name == "rules_colloques":
        rows = []
        for rule in data.get("rules_colloques", []):
            if isinstance(rule, dict):
                rows.append(
                    {
                        "group": str(rule.get("group", "")),
                        "day": str(rule.get("day", "")),
                        "start": str(rule.get("start", "")),
                        "end": str(rule.get("end", "")),
                    }
                )
            elif isinstance(rule, (list, tuple)):
                group, day, start, end = normalize_rule_list(rule, 4)
                rows.append({"group": group, "day": day, "start": start, "end": end})
        return rows

    return []


def rows_to_data(data: dict, spec_name: str, rows: list[dict[str, str]]) -> None:
    if spec_name == "sites":
        data["sites"] = [
            {"name": row.get("name", ""), "open": row.get("open", ""), "close": row.get("close", "")}
            for row in rows
        ]
        return

    if spec_name == "groups":
        data["groups"] = [
            {"name": row.get("name", ""), "site": row.get("site", ""), "ratio": parse_int(row.get("ratio"), 1)}
            for row in rows
        ]
        return

    if spec_name == "educator_types":
        data["educator_types"] = [
            {"name": row.get("name", ""), "description": row.get("description", "")}
            for row in rows
        ]
        return

    if spec_name == "educators":
        educators = []
        for row in rows:
            educator = {
                "name": row.get("name", ""),
                "percentage": parse_int(row.get("percentage"), 100),
                "type": row.get("type", ""),
            }
            if str(row.get("max_work_days", "")).strip():
                educator["max_work_days"] = parse_int(row.get("max_work_days"), 0)
            educators.append(educator)
        data["educators"] = educators
        return

    if spec_name == "rules_time":
        data["rules_time"] = [
            [
                row.get("pos_neg", ""),
                row.get("hard_soft", ""),
                row.get("educator", ""),
                row.get("day", ""),
                row.get("start", ""),
                row.get("end", ""),
            ]
            for row in rows
        ]
        return

    if spec_name == "rules_group":
        data["rules_group"] = [
            [row.get("pos_neg", ""), row.get("hard_soft", ""), row.get("educator", ""), row.get("group", "")]
            for row in rows
        ]
        return

    if spec_name == "rules_percentage":
        data["rules_percentage"] = [
            [
                split_types(row.get("types", "")),
                row.get("minmax", ""),
                parse_int(row.get("value"), 0),
                row.get("site", ""),
            ]
            for row in rows
        ]
        return

    if spec_name == "rules_site_schedule":
        data["rules_site_schedule"] = []
        for row in rows:
            interval = {
                "start": row.get("start", ""),
                "end": row.get("end", ""),
                "group": row.get("group", ""),
                "min_staff": parse_int(row.get("min_staff"), 1),
            }
            max_staff = row.get("max_staff", "").strip()
            if max_staff:
                interval["max_staff"] = parse_int(max_staff, 3)
            days = days_from_value(row.get("days", ""))
            if days:
                interval["days"] = days
            data["rules_site_schedule"].append({"site": row.get("site", ""), "time_intervals": [interval]})
        return

    if spec_name == "rules_colloques":
        data["rules_colloques"] = [
            {
                "group": row.get("group", ""),
                "day": row.get("day", ""),
                "start": row.get("start", ""),
                "end": row.get("end", ""),
            }
            for row in rows
        ]
        return


def parse_int(value: object, fallback: int) -> int:
    try:
        if value is None or str(value).strip() == "":
            return fallback
        return int(float(str(value).replace(",", ".")))
    except ValueError:
        return fallback


def parse_float(value: object, fallback: float) -> float:
    try:
        if value is None or str(value).strip() == "":
            return fallback
        return float(str(value).replace(",", "."))
    except ValueError:
        return fallback


def is_time(value: str) -> bool:
    parts = value.split(":")
    if len(parts) != 2:
        return False
    try:
        hour = int(parts[0])
        minute = int(parts[1])
    except ValueError:
        return False
    return 0 <= hour <= 23 and 0 <= minute <= 59 and minute % 15 == 0


def time_minutes(value: str) -> int:
    hour, minute = value.split(":")
    return int(hour) * 60 + int(minute)


def format_minutes(value: int) -> str:
    hour, minute = divmod(value, 60)
    return f"{hour:02d}:{minute:02d}"


class RowDialog(tk.Toplevel):
    def __init__(self, parent: "CrecheEditor", title: str, fields: tuple[FieldSpec, ...], values: dict[str, str] | None):
        super().__init__(parent)
        self.parent = parent
        self.title(title)
        self.resizable(False, False)
        self.result: dict[str, str] | None = None
        self.vars: dict[str, tk.StringVar] = {}
        self.day_vars: dict[str, dict[str, tk.BooleanVar]] = {}

        body = ttk.Frame(self, padding=12)
        body.grid(row=0, column=0, sticky="nsew")

        for row_index, field in enumerate(fields):
            ttk.Label(body, text=field.label).grid(row=row_index, column=0, sticky="w", padx=(0, 10), pady=4)
            var = tk.StringVar(value="" if values is None else str(values.get(field.key, "")))
            if field.field_type == "days":
                selected_days = days_from_value(var.get())
                check_all = not selected_days
                day_frame = ttk.Frame(body)
                day_vars: dict[str, tk.BooleanVar] = {}
                for day in DAYS:
                    day_var = tk.BooleanVar(value=check_all or day in selected_days)
                    day_vars[day] = day_var
                    ttk.Checkbutton(day_frame, text=DAY_SHORT_LABELS[day], variable=day_var).pack(side="left", padx=(0, 8))
                self.day_vars[field.key] = day_vars
                widget = day_frame
            else:
                self.vars[field.key] = var
                choices = parent.choices_for(field)
                if choices is not None:
                    widget = ttk.Combobox(body, textvariable=var, values=choices)
                else:
                    widget = ttk.Entry(body, textvariable=var, width=38)
            widget.grid(row=row_index, column=1, sticky="ew", pady=4)

        buttons = ttk.Frame(body)
        buttons.grid(row=len(fields), column=0, columnspan=2, sticky="e", pady=(12, 0))
        ttk.Button(buttons, text="Annuler", command=self.destroy).pack(side="right")
        ttk.Button(buttons, text="OK", command=self.accept).pack(side="right", padx=(0, 8))

        self.bind("<Return>", lambda _event: self.accept())
        self.bind("<Escape>", lambda _event: self.destroy())
        self.transient(parent)
        self.grab_set()
        self.wait_visibility()
        self.focus()

    def accept(self) -> None:
        result = {key: var.get().strip() for key, var in self.vars.items()}
        for key, day_vars in self.day_vars.items():
            selected_days = [day for day, var in day_vars.items() if var.get()]
            if not selected_days:
                messagebox.showerror("Jours", "Selectionne au moins un jour.")
                return
            result[key] = format_days(selected_days)
        self.result = result
        self.destroy()


class TablePage(ttk.Frame):
    def __init__(self, parent: "CrecheEditor", spec: TableSpec):
        super().__init__(parent.notebook)
        self.parent = parent
        self.spec = spec
        self.rows: list[dict[str, str]] = []

        toolbar = ttk.Frame(self, padding=(8, 8, 8, 4))
        toolbar.pack(fill="x")
        ttk.Button(toolbar, text="Ajouter", command=self.add_row).pack(side="left")
        ttk.Button(toolbar, text="Modifier", command=self.edit_selected).pack(side="left", padx=(6, 0))
        ttk.Button(toolbar, text="Dupliquer", command=self.duplicate_selected).pack(side="left", padx=(6, 0))
        ttk.Button(toolbar, text="Supprimer", command=self.delete_selected).pack(side="left", padx=(6, 0))

        columns = [field.key for field in spec.fields]
        self.tree = ttk.Treeview(self, columns=columns, show="headings", selectmode="browse")
        for field in spec.fields:
            self.tree.heading(field.key, text=field.label)
            self.tree.column(field.key, width=130, minwidth=70, stretch=True)
        self.tree.pack(side="left", fill="both", expand=True, padx=(8, 0), pady=(0, 8))
        scrollbar = ttk.Scrollbar(self, orient="vertical", command=self.tree.yview)
        scrollbar.pack(side="right", fill="y", pady=(0, 8), padx=(0, 8))
        self.tree.configure(yscrollcommand=scrollbar.set)
        self.tree.bind("<Double-1>", lambda _event: self.edit_selected())
        self.tree.bind("<Delete>", lambda _event: self.delete_selected())

    def load_from_data(self, data: dict) -> None:
        self.rows = rows_from_data(data, self.spec.name)
        self.refresh()

    def write_to_data(self, data: dict) -> None:
        rows_to_data(data, self.spec.name, self.rows)

    def refresh(self) -> None:
        self.tree.delete(*self.tree.get_children())
        for index, row in enumerate(self.rows):
            values = [row.get(field.key, "") for field in self.spec.fields]
            self.tree.insert("", "end", iid=str(index), values=values)

    def selected_index(self) -> int | None:
        selection = self.tree.selection()
        if not selection:
            return None
        return int(selection[0])

    def add_row(self) -> None:
        values = {field.key: self.default_for(field) for field in self.spec.fields}
        dialog = RowDialog(self.parent, f"Ajouter - {self.spec.title}", self.spec.fields, values)
        self.parent.wait_window(dialog)
        if dialog.result is not None:
            self.rows.append(dialog.result)
            self.refresh()
            self.parent.mark_dirty()

    def edit_selected(self) -> None:
        index = self.selected_index()
        if index is None:
            messagebox.showinfo("Selection", "Selectionne une ligne a modifier.")
            return
        dialog = RowDialog(self.parent, f"Modifier - {self.spec.title}", self.spec.fields, self.rows[index])
        self.parent.wait_window(dialog)
        if dialog.result is not None:
            self.rows[index] = dialog.result
            self.refresh()
            self.parent.mark_dirty()

    def duplicate_selected(self) -> None:
        index = self.selected_index()
        if index is None:
            messagebox.showinfo("Selection", "Selectionne une ligne a dupliquer.")
            return
        self.rows.insert(index + 1, dict(self.rows[index]))
        self.refresh()
        self.parent.mark_dirty()

    def delete_selected(self) -> None:
        index = self.selected_index()
        if index is None:
            messagebox.showinfo("Selection", "Selectionne une ligne a supprimer.")
            return
        if messagebox.askyesno("Supprimer", "Supprimer la ligne selectionnee ?"):
            del self.rows[index]
            self.refresh()
            self.parent.mark_dirty()

    def default_for(self, field: FieldSpec) -> str:
        if field.field_type == "days":
            return "tous"
        if field.field_type == "time":
            return "06:45" if field.key in {"open", "start"} else "18:45"
        if field.field_type in {"int", "int_optional"}:
            if field.key == "percentage":
                return "100"
            if field.key == "ratio":
                return "1"
            if field.key == "min_staff":
                return "1"
            return ""
        choices = self.parent.choices_for(field)
        if choices:
            return choices[0]
        return ""


class StaffingPage(ttk.Frame):
    def __init__(self, parent: "CrecheEditor", spec: TableSpec):
        super().__init__(parent.notebook)
        self.parent = parent
        self.spec = spec
        self.rows: list[dict[str, str]] = []
        self.site_filter = tk.StringVar(value="Tous")
        self.group_filter = tk.StringVar(value="Tous")
        self.summary = tk.StringVar()

        toolbar = ttk.Frame(self, padding=(8, 8, 8, 4))
        toolbar.pack(fill="x")
        ttk.Button(toolbar, text="Ajouter", command=self.add_row).pack(side="left")
        ttk.Button(toolbar, text="Modifier", command=self.edit_selected).pack(side="left", padx=(6, 0))
        ttk.Button(toolbar, text="Dupliquer", command=self.duplicate_selected).pack(side="left", padx=(6, 0))
        ttk.Button(toolbar, text="Supprimer", command=self.delete_selected).pack(side="left", padx=(6, 0))

        filters = ttk.Frame(self, padding=(8, 0, 8, 6))
        filters.pack(fill="x")
        ttk.Label(filters, text="Site").pack(side="left")
        self.site_combo = ttk.Combobox(filters, textvariable=self.site_filter, state="readonly", width=16)
        self.site_combo.pack(side="left", padx=(6, 14))
        ttk.Label(filters, text="Groupe").pack(side="left")
        self.group_combo = ttk.Combobox(filters, textvariable=self.group_filter, state="readonly", width=18)
        self.group_combo.pack(side="left", padx=(6, 14))
        ttk.Button(filters, text="Tous", command=self.clear_filters).pack(side="left")
        ttk.Label(filters, textvariable=self.summary).pack(side="right")
        self.site_combo.bind("<<ComboboxSelected>>", lambda _event: self.refresh())
        self.group_combo.bind("<<ComboboxSelected>>", lambda _event: self.refresh())

        columns = (
            "site",
            "group",
            "days",
            "start",
            "end",
            "lundi",
            "mardi",
            "mercredi",
            "jeudi",
            "vendredi",
            "max_staff",
        )
        headings = {
            "site": "Site",
            "group": "Groupe",
            "days": "Jours",
            "start": "Debut",
            "end": "Fin",
            "lundi": "Lun",
            "mardi": "Mar",
            "mercredi": "Mer",
            "jeudi": "Jeu",
            "vendredi": "Ven",
            "max_staff": "Max",
        }
        self.tree = ttk.Treeview(self, columns=columns, show="headings", selectmode="browse")
        for column in columns:
            self.tree.heading(column, text=headings[column])
            width = 70 if column in DAYS else 95
            if column in {"site", "start", "end", "max_staff"}:
                width = 80
            if column == "days":
                width = 140
            if column == "group":
                width = 135
            self.tree.column(column, width=width, minwidth=55, stretch=column in {"site", "group"})
        self.tree.pack(side="left", fill="both", expand=True, padx=(8, 0), pady=(0, 8))
        scrollbar = ttk.Scrollbar(self, orient="vertical", command=self.tree.yview)
        scrollbar.pack(side="right", fill="y", pady=(0, 8), padx=(0, 8))
        self.tree.configure(yscrollcommand=scrollbar.set)
        self.tree.bind("<Double-1>", lambda _event: self.edit_selected())
        self.tree.bind("<Delete>", lambda _event: self.delete_selected())
        self.tree.bind("<<TreeviewSelect>>", lambda _event: self.refresh_continuity())

        checks_frame = ttk.LabelFrame(self, text="Continuite des plages", padding=(8, 4))
        checks_frame.pack(fill="x", padx=8, pady=(0, 8))
        self.continuity_text = tk.Text(checks_frame, height=7, wrap="word")
        self.continuity_text.pack(fill="x", expand=True)
        self.continuity_text.configure(state="disabled")

    def load_from_data(self, data: dict) -> None:
        self.rows = rows_from_data(data, self.spec.name)
        self.refresh()

    def write_to_data(self, data: dict) -> None:
        rows_to_data(data, self.spec.name, self.rows)

    def refresh_filters(self) -> None:
        site_values = ["Tous"] + self.parent.names_for("sites")
        group_values = ["Tous"] + self.parent.names_for("groups")
        self.site_combo.configure(values=site_values)
        self.group_combo.configure(values=group_values)
        if self.site_filter.get() not in site_values:
            self.site_filter.set("Tous")
        if self.group_filter.get() not in group_values:
            self.group_filter.set("Tous")

    def refresh(self) -> None:
        self.refresh_filters()
        self.tree.delete(*self.tree.get_children())
        displayed_rows: list[dict[str, str]] = []
        indexed_rows = sorted(enumerate(self.rows), key=lambda item: self.sort_key(item[1], item[0]))
        for index, row in indexed_rows:
            if not self.row_matches_filters(row):
                continue
            displayed_rows.append(row)
            self.tree.insert("", "end", iid=str(index), values=self.display_values(row))
        self.update_summary(displayed_rows)
        self.refresh_continuity(displayed_rows)

    def sort_key(self, row: dict[str, str], index: int) -> tuple[str, str, tuple[int, ...], int, int, int]:
        try:
            start = time_minutes(row.get("start", ""))
        except Exception:
            start = 9999
        try:
            end = time_minutes(row.get("end", ""))
        except Exception:
            end = 9999
        selected_days = days_from_value(row.get("days", ""))
        active_days = DAYS if not selected_days else selected_days
        day_key = tuple(DAYS.index(day) for day in active_days if day in DAYS)
        return (
            row.get("site", ""),
            row.get("group", ""),
            day_key,
            start,
            end,
            index,
        )

    def row_matches_filters(self, row: dict[str, str]) -> bool:
        site = self.site_filter.get()
        group = self.group_filter.get()
        if site != "Tous" and row.get("site", "") != site:
            return False
        if group != "Tous" and row.get("group", "") != group:
            return False
        return True

    def display_values(self, row: dict[str, str]) -> tuple[str, ...]:
        selected_days = set(days_from_value(row.get("days", "")))
        active_days = set(DAYS) if not selected_days else selected_days
        min_staff = row.get("min_staff", "")
        max_staff = row.get("max_staff", "")
        return (
            row.get("site", ""),
            row.get("group", ""),
            format_days(row.get("days", "")),
            row.get("start", ""),
            row.get("end", ""),
            *(min_staff if day in active_days else "" for day in DAYS),
            max_staff,
        )

    def update_summary(self, rows: list[dict[str, str]]) -> None:
        total_hours = 0.0
        for row in rows:
            try:
                duration = max(0, time_minutes(row.get("end", "")) - time_minutes(row.get("start", ""))) / 60.0
            except Exception:
                duration = 0.0
            days = days_from_value(row.get("days", ""))
            day_count = len(days) if days else len(DAYS)
            total_hours += duration * day_count * parse_int(row.get("min_staff"), 0)
        weekly_base = parse_float(self.parent.data.get("rules_global", {}).get("max_weekly_hours"), 40.0)
        educator_hours = sum(
            parse_float(educator.get("percentage"), 0.0) * weekly_base / 100.0
            for educator in self.parent.data.get("educators", [])
        )
        self.summary.set(
            f"{len(rows)} plage(s), {total_hours:.2f} h minimum affichees, "
            f"{educator_hours:.2f} h educatrices/semaine"
        )

    def focused_continuity_rows(self, displayed_rows: list[dict[str, str]] | None = None) -> list[dict[str, str]]:
        index = self.selected_index()
        if index is not None and 0 <= index < len(self.rows):
            selected = self.rows[index]
            site = selected.get("site", "")
            group = selected.get("group", "")
            return [
                row
                for row in self.rows
                if row.get("site", "") == site and row.get("group", "") == group
            ]
        if self.group_filter.get() != "Tous":
            source = displayed_rows if displayed_rows is not None else self.rows
            return [row for row in source if self.row_matches_filters(row)]
        return []

    def refresh_continuity(self, displayed_rows: list[dict[str, str]] | None = None) -> None:
        self.update_continuity(self.focused_continuity_rows(displayed_rows))

    def update_continuity(self, rows: list[dict[str, str]]) -> None:
        if not rows:
            self.set_continuity_text(
                "Selectionne une ligne, ou filtre un groupe, pour voir la continuite jour par jour."
            )
            return

        warnings: list[str] = []
        lines: list[str] = []
        by_key: dict[tuple[str, str, str], list[tuple[int, int, int]]] = {}
        for row in rows:
            try:
                start = time_minutes(row.get("start", ""))
                end = time_minutes(row.get("end", ""))
            except Exception:
                continue
            if end <= start:
                warnings.append(
                    f"{row.get('site', '')}/{row.get('group', '')}: plage invalide "
                    f"{row.get('start', '')}-{row.get('end', '')}."
                )
                continue
            selected_days = days_from_value(row.get("days", ""))
            active_days = DAYS if not selected_days else selected_days
            staff = parse_int(row.get("min_staff"), 0)
            for day in active_days:
                by_key.setdefault((row.get("site", ""), row.get("group", ""), day), []).append((start, end, staff))

        current_header: tuple[str, str] | None = None
        for (site, group, day), intervals in sorted(
            by_key.items(),
            key=lambda item: (item[0][0], item[0][1], DAYS.index(item[0][2])),
        ):
            header = (site, group)
            if header != current_header:
                if current_header is not None:
                    lines.append("")
                lines.append(f"{site}/{group}")
                current_header = header
            timeline, day_issues = self.effective_day_timeline(intervals)
            warnings.extend(f"{site}/{group} {DAY_SHORT_LABELS[day]}: {issue}" for issue in day_issues)
            lines.append(f"- {DAY_SHORT_LABELS[day]}: {timeline}")

        text = "\n".join(lines)
        if warnings:
            text += "\n\nWarnings:\n" + "\n".join(f"- {warning}" for warning in warnings[:10])
            if len(warnings) > 10:
                text += f"\n- ... {len(warnings) - 10} autre(s) warning(s)."
        else:
            text += "\n\nWarnings: aucun trou ni chevauchement detecte."
        self.set_continuity_text(text)

    def effective_day_timeline(self, intervals: list[tuple[int, int, int]]) -> tuple[str, list[str]]:
        intervals = sorted(intervals, key=lambda item: (item[0], item[1]))
        points = sorted({value for start, end, _staff in intervals for value in (start, end)})
        if len(points) < 2:
            return "aucune plage", ["aucune plage"]

        raw_segments: list[tuple[int, int, int, int]] = []
        issues: list[str] = []
        for start, end in zip(points, points[1:]):
            if end <= start:
                continue
            active = [staff for row_start, row_end, staff in intervals if row_start <= start and row_end >= end]
            staff = max(active) if active else 0
            raw_segments.append((start, end, staff, len(active)))
            if staff == 0:
                issues.append(f"TROU {format_minutes(start)}-{format_minutes(end)}")
            elif len(active) > 1:
                issue_detail = ", ".join(str(value) for value in sorted(active))
                issues.append(
                    f"CHEVAUCHEMENT {format_minutes(start)}-{format_minutes(end)} "
                    f"({len(active)} plages: {issue_detail}; besoin retenu {staff})"
                )

        merged: list[tuple[int, int, int, int]] = []
        for start, end, staff, active_count in raw_segments:
            if (
                not merged
                or merged[-1][2] != staff
                or merged[-1][3] != active_count
                or merged[-1][1] != start
            ):
                merged.append((start, end, staff, active_count))
            else:
                previous_start, _previous_end, previous_staff, previous_count = merged[-1]
                merged[-1] = (previous_start, end, previous_staff, previous_count)

        visible_parts = [
            f"{format_minutes(start)}-{format_minutes(end)}: {staff}"
            if staff
            else f"{format_minutes(start)}-{format_minutes(end)}: TROU"
            for start, end, staff, _active_count in merged
        ]
        return " | ".join(visible_parts), issues

    def set_continuity_text(self, text: str) -> None:
        self.continuity_text.configure(state="normal")
        self.continuity_text.delete("1.0", "end")
        self.continuity_text.insert("1.0", text)
        self.continuity_text.configure(state="disabled")

    def selected_index(self) -> int | None:
        selection = self.tree.selection()
        if not selection:
            return None
        return int(selection[0])

    def clear_filters(self) -> None:
        self.site_filter.set("Tous")
        self.group_filter.set("Tous")
        self.refresh()

    def add_row(self) -> None:
        values = {field.key: self.default_for(field) for field in self.spec.fields}
        dialog = RowDialog(self.parent, f"Ajouter - {self.spec.title}", self.spec.fields, values)
        self.parent.wait_window(dialog)
        if dialog.result is not None:
            self.rows.append(dialog.result)
            self.refresh()
            self.parent.mark_dirty()

    def edit_selected(self) -> None:
        index = self.selected_index()
        if index is None:
            messagebox.showinfo("Selection", "Selectionne une plage a modifier.")
            return
        dialog = RowDialog(self.parent, f"Modifier - {self.spec.title}", self.spec.fields, self.rows[index])
        self.parent.wait_window(dialog)
        if dialog.result is not None:
            self.rows[index] = dialog.result
            self.refresh()
            self.parent.mark_dirty()

    def duplicate_selected(self) -> None:
        index = self.selected_index()
        if index is None:
            messagebox.showinfo("Selection", "Selectionne une plage a dupliquer.")
            return
        self.rows.insert(index + 1, dict(self.rows[index]))
        self.refresh()
        self.parent.mark_dirty()

    def delete_selected(self) -> None:
        index = self.selected_index()
        if index is None:
            messagebox.showinfo("Selection", "Selectionne une plage a supprimer.")
            return
        if messagebox.askyesno("Supprimer", "Supprimer la plage selectionnee ?"):
            del self.rows[index]
            self.refresh()
            self.parent.mark_dirty()

    def default_for(self, field: FieldSpec) -> str:
        if field.key == "site" and self.site_filter.get() != "Tous":
            return self.site_filter.get()
        if field.key == "group" and self.group_filter.get() != "Tous":
            return self.group_filter.get()
        if field.field_type == "days":
            return "tous"
        if field.field_type == "time":
            return "06:45" if field.key == "start" else "18:45"
        if field.key == "min_staff":
            return "1"
        if field.key == "max_staff":
            return ""
        choices = self.parent.choices_for(field)
        if choices:
            return choices[0]
        return ""


class GlobalRulesPage(ttk.Frame):
    def __init__(self, parent: "CrecheEditor"):
        super().__init__(parent.notebook, padding=14)
        self.parent = parent
        self.weekly = tk.StringVar()
        self.daily = tk.StringVar()

        ttk.Label(self, text="Heures max semaine pour 100%").grid(row=0, column=0, sticky="w", pady=6)
        ttk.Entry(self, textvariable=self.weekly, width=12).grid(row=0, column=1, sticky="w", pady=6)
        ttk.Label(self, text="Heures max jour").grid(row=1, column=0, sticky="w", pady=6)
        ttk.Entry(self, textvariable=self.daily, width=12).grid(row=1, column=1, sticky="w", pady=6)
        ttk.Button(self, text="Appliquer", command=self.apply_to_parent).grid(row=2, column=1, sticky="e", pady=(14, 0))

    def load_from_data(self, data: dict) -> None:
        rules = data.get("rules_global", {})
        self.weekly.set(str(rules.get("max_weekly_hours", 40.0)))
        self.daily.set(str(rules.get("max_daily_hours", 8.5)))

    def write_to_data(self, data: dict) -> None:
        data["rules_global"] = {
            "max_weekly_hours": parse_float(self.weekly.get(), 40.0),
            "max_daily_hours": parse_float(self.daily.get(), 8.5),
        }

    def apply_to_parent(self) -> None:
        self.parent.mark_dirty()
        self.parent.collect_from_pages()
        self.parent.update_summary()


class JsonPage(ttk.Frame):
    def __init__(self, parent: "CrecheEditor"):
        super().__init__(parent.notebook)
        self.parent = parent
        toolbar = ttk.Frame(self, padding=8)
        toolbar.pack(fill="x")
        ttk.Button(toolbar, text="Rafraichir depuis tables", command=self.refresh_from_data).pack(side="left")
        ttk.Button(toolbar, text="Valider JSON", command=self.validate_json_text).pack(side="left", padx=(6, 0))
        ttk.Button(toolbar, text="Appliquer aux tables", command=self.apply_to_tables).pack(side="left", padx=(6, 0))

        self.json_dirty = False
        self.text = tk.Text(self, wrap="none", undo=True)
        self.text.pack(fill="both", expand=True, padx=8, pady=(0, 8))
        self.text.bind("<<Modified>>", self.on_text_modified)

    def refresh_from_data(self) -> None:
        self.parent.collect_from_pages()
        self.text.delete("1.0", "end")
        self.text.insert("1.0", json.dumps(self.parent.data, indent=4, ensure_ascii=False))
        self.json_dirty = False
        self.text.edit_modified(False)

    def on_text_modified(self, _event: tk.Event) -> None:
        if not self.text.edit_modified():
            return
        self.json_dirty = True
        self.parent.mark_dirty()
        self.text.edit_modified(False)

    def apply_text_to_data(self, *, show_error: bool = True) -> bool:
        try:
            data = ensure_schema(json.loads(self.text.get("1.0", "end")))
        except json.JSONDecodeError as exc:
            if show_error:
                messagebox.showerror("JSON invalide", f"{exc.msg}\nligne {exc.lineno}, colonne {exc.colno}")
            return False
        self.parent.data = data
        self.json_dirty = False
        return True

    def validate_json_text(self) -> None:
        try:
            json.loads(self.text.get("1.0", "end"))
        except json.JSONDecodeError as exc:
            messagebox.showerror("JSON invalide", f"{exc.msg}\nligne {exc.lineno}, colonne {exc.colno}")
            return
        messagebox.showinfo("JSON", "JSON valide.")

    def apply_to_tables(self) -> None:
        if not self.apply_text_to_data(show_error=True):
            return
        self.parent.load_pages()
        self.parent.mark_dirty()


class PlanningPage(ttk.Frame):
    def __init__(self, parent: "CrecheEditor"):
        super().__init__(parent.notebook)
        self.parent = parent
        toolbar = ttk.Frame(self, padding=8)
        toolbar.pack(fill="x")
        ttk.Button(toolbar, text="Charger dernier planning", command=lambda: self.load_latest_planning(show_message=True)).pack(side="left")
        ttk.Button(toolbar, text="Charger planning JSON", command=self.load_planning).pack(side="left")
        self.text = tk.Text(self, wrap="word")
        self.text.pack(fill="both", expand=True, padx=8, pady=(0, 8))

    def clear(self) -> None:
        self.text.delete("1.0", "end")

    def load_latest_planning(self, *, show_message: bool = False) -> bool:
        path = find_latest_planning(self.parent.path)
        if path is None:
            if show_message:
                messagebox.showinfo("Planning", "Aucun planning calcule trouve.")
            return False
        self.load_planning(path)
        return True

    def load_planning(self, path: Path | None = None) -> None:
        if path is None:
            initial = self.parent.path.with_name("planning_gwendo_smooth.json") if self.parent.path else Path.cwd()
            selected = filedialog.askopenfilename(
                title="Charger un planning",
                initialdir=str(initial.parent if initial.is_file() else initial),
                filetypes=[("JSON", "*.json"), ("Tous", "*.*")],
            )
            if not selected:
                return
            path = Path(selected)
        try:
            payload = load_json_any(path)
        except Exception as exc:
            messagebox.showerror("Planning", f"Impossible de charger le planning:\n{exc}")
            return
        self.text.delete("1.0", "end")
        self.text.insert("1.0", render_planning(payload))
        self.parent.set_status(f"Planning charge: {path}")


def load_json_any(path: Path) -> dict:
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def render_planning(payload: dict) -> str:
    lines = []
    lines.append(f"Status: {payload.get('status', '?')}")
    if payload.get("solver_message"):
        lines.append(f"Solveur: {payload.get('solver_message')}")
    checks = payload.get("checks", {})
    errors = checks.get("errors", [])
    alerts = checks.get("alerts", [])
    diagnostics = payload.get("diagnostics", [])
    if checks:
        lines.append(f"Erreurs verification: {len(errors)}")
    else:
        lines.append("Erreurs verification: non calculees (aucun planning)")
    if diagnostics:
        lines.append("")
        lines.append("Diagnostics:")
        for diagnostic in diagnostics:
            lines.append(f"- {diagnostic}")
    if payload.get("warnings"):
        lines.append("")
        lines.append("Avertissements:")
        for warning in payload["warnings"]:
            lines.append(f"- {warning}")
    quality_lines = format_quality_summary_lines(checks.get("quality_summary"))
    if quality_lines:
        lines.append("")
        lines.append("Qualite du planning:")
        lines.extend(quality_lines)
    if checks.get("hours_by_educator"):
        lines.append("")
        lines.append("Heures:")
        for name, hours in checks["hours_by_educator"].items():
            target = checks.get("weekly_targets", {}).get(name, "?")
            if checks.get("total_the_hours_by_educator"):
                child = checks.get("child_hours_by_educator", {}).get(name, 0)
                the_total = checks.get("total_the_hours_by_educator", {}).get(name, 0)
                colloque = checks.get("colloque_the_hours_by_educator", {}).get(name, 0)
                invisible = checks.get("invisible_the_hours_by_educator", {}).get(name, 0)
                lines.append(
                    f"- {name}: {hours} / {target} h "
                    f"(enfants {child} h, THE {the_total} h, "
                    f"colloque {colloque} h, invisible {invisible} h)"
                )
            else:
                lines.append(f"- {name}: {hours} / {target} h")
    if checks.get("primary_groups_by_educator"):
        lines.append("")
        lines.append("Groupes principaux:")
        for name, group_name in checks["primary_groups_by_educator"].items():
            lines.append(f"- {name}: {group_name}")
    schedule = payload.get("schedule", {})
    if schedule:
        lines.append("")
        lines.append("Planning:")
        for educator, by_day in schedule.items():
            lines.append("")
            lines.append(educator)
            for day in DAYS:
                blocks = by_day.get(day, [])
                if not blocks:
                    lines.append(f"  {day}: OFF")
                else:
                    text = ", ".join(
                        f"{block.get('start')}-{block.get('end')} {block.get('site')}/{block.get('group')}"
                        + (
                            " (colloque)"
                            if block.get("activity") == "colloque"
                            else " (remplacement colloque)"
                            if block.get("activity") == "remplacement_colloque"
                            else ""
                        )
                        for block in blocks
                    )
                    lines.append(f"  {day}: {text}")
    if errors:
        lines.append("")
        lines.append("Erreurs:")
        lines.extend(f"- {error}" for error in errors)
    if alerts:
        lines.append("")
        lines.append("Alertes non bloquantes:")
        lines.extend(f"- {alert}" for alert in alerts)
    return "\n".join(lines)


def load_solver_config(path: Path) -> dict:
    if not path.exists():
        return {}
    with path.open("r", encoding="utf-8") as handle:
        loaded = json.load(handle)
    return loaded if isinstance(loaded, dict) else {}


def find_project_root(data_path: Path | None = None) -> Path:
    candidates: list[Path] = []
    if data_path is not None:
        data_path = data_path.resolve()
        candidates.extend([data_path.parent, *data_path.parent.parents])
    module_root = Path(__file__).resolve().parents[2]
    candidates.extend([module_root, *module_root.parents])
    for candidate in candidates:
        if (candidate / "src" / "creche_planning").exists() or (candidate / "solveur_v2.py").exists():
            return candidate
    return module_root


def find_solver_script(data_path: Path | None = None) -> Path:
    project_root = find_project_root(data_path)
    candidates = [project_root / "solveur_v2.py", project_root / "creche_solver.py"]
    if data_path is not None:
        candidates.append(data_path.resolve().with_name("solveur_v2.py"))
    for candidate in candidates:
        if candidate.exists():
            return candidate
    return candidates[0]


def find_solver_config(data_path: Path | None = None) -> Path:
    project_root = find_project_root(data_path)
    candidates = [project_root / "config" / "solveur_config.json", project_root / "solveur_config.json"]
    if data_path is not None:
        candidates.append(data_path.resolve().with_name("solveur_config.json"))
    for candidate in candidates:
        if candidate.exists():
            return candidate
    return candidates[0]


def resolve_local_path(value: object, base_dir: Path, fallback: str) -> Path:
    text = str(value if value not in {None, ""} else fallback)
    path = Path(text)
    if path.is_absolute():
        return path.resolve()
    return (base_dir / path).resolve()


def find_latest_planning(data_path: Path | None) -> Path | None:
    if data_path is None:
        return None
    config_path = find_solver_config(data_path)
    base_dir = config_path.parent if config_path.exists() else data_path.parent
    config = load_solver_config(config_path)
    candidates: list[Path] = []

    latest_path = resolve_local_path(
        config.get("latest_output_json"),
        base_dir,
        "planning_gwendo_latest.json",
    )
    if latest_path.exists():
        candidates.append(latest_path)

    output_path = resolve_local_path(
        config.get("output_json"),
        base_dir,
        f"{data_path.stem}_planning.json",
    )
    if output_path.exists():
        candidates.append(output_path)

    pattern = f"{output_path.stem}_*.json"
    candidates.extend(path for path in output_path.parent.glob(pattern) if path.is_file())

    if not candidates:
        return None
    return max(candidates, key=lambda path: path.stat().st_mtime)


def timestamped_path(path: Path, timestamp: str | None) -> Path:
    if not timestamp:
        return path
    if "{timestamp}" in str(path):
        return Path(str(path).replace("{timestamp}", timestamp))
    return path.with_name(f"{path.stem}_{timestamp}{path.suffix}")


class SolverProgressDialog(tk.Toplevel):
    def __init__(self, parent: tk.Tk, output: Path):
        super().__init__(parent)
        self.title("Resolution du planning")
        self.geometry("560x360")
        self.resizable(False, False)
        self.transient(parent)
        self.running = True
        self.started_at = datetime.now()
        self.percent = tk.DoubleVar(value=0)
        self.message = tk.StringVar(value="Demarrage du solveur...")
        self.elapsed = tk.StringVar(value="Temps ecoule: 0 s")
        self.output = output

        frame = ttk.Frame(self, padding=16)
        frame.pack(fill="both", expand=True)

        ttk.Label(frame, text="Generation du planning", font=("", 13, "bold")).pack(anchor="w")
        ttk.Label(frame, textvariable=self.message, padding=(0, 8, 0, 4)).pack(anchor="w")
        self.progress = ttk.Progressbar(frame, maximum=100, variable=self.percent, length=520)
        self.progress.pack(fill="x")

        meta = ttk.Frame(frame)
        meta.pack(fill="x", pady=(8, 10))
        ttk.Label(meta, textvariable=self.elapsed).pack(side="left")
        self.percent_label = ttk.Label(meta, text="0 %")
        self.percent_label.pack(side="right")

        log_frame = ttk.LabelFrame(frame, text="Journal")
        log_frame.pack(fill="both", expand=True)
        self.log = tk.Text(log_frame, height=8, wrap="word", state="disabled")
        self.log.pack(fill="both", expand=True, padx=6, pady=6)

        buttons = ttk.Frame(frame)
        buttons.pack(fill="x", pady=(10, 0))
        self.close_button = ttk.Button(buttons, text="Fermer", command=self.destroy, state="disabled")
        self.close_button.pack(side="right")

        self.protocol("WM_DELETE_WINDOW", self.close_requested)
        self.after(500, self.tick)

    def tick(self) -> None:
        if self.running:
            elapsed = int((datetime.now() - self.started_at).total_seconds())
            self.elapsed.set(f"Temps ecoule: {elapsed} s")
            self.after(500, self.tick)

    def close_requested(self) -> None:
        if self.running:
            messagebox.showinfo("Solveur", "Le calcul est encore en cours.")
            return
        self.destroy()

    def update_progress(self, percent: int, message: str) -> None:
        self.percent.set(percent)
        self.percent_label.config(text=f"{percent} %")
        self.message.set(message)
        self.append_log(message)

    def append_log(self, text: str) -> None:
        clean = text.strip()
        if not clean:
            return
        self.log.configure(state="normal")
        self.log.insert("end", clean + "\n")
        self.log.see("end")
        self.log.configure(state="disabled")

    def finish(self, success: bool, message: str) -> None:
        self.running = False
        self.percent.set(100 if success else self.percent.get())
        if success:
            self.percent_label.config(text="100 %")
        self.message.set(message)
        self.append_log(message)
        self.close_button.configure(state="normal")


class CrecheEditor(tk.Tk):
    def __init__(self, path: Path | None):
        super().__init__()
        self.title("Creche JSON editor")
        self.geometry("1180x760")
        self.minsize(980, 620)
        self.path = path
        self.data = load_json(path) if path and path.exists() else new_data()
        self.dirty = False
        self.pages: dict[str, TablePage | StaffingPage] = {}

        self.create_menu()
        self.create_toolbar()
        self.status = tk.StringVar()
        self.notebook = ttk.Notebook(self)
        self.notebook.pack(fill="both", expand=True)

        self.summary = tk.Text(self.notebook, wrap="word")
        self.notebook.add(self.summary, text="Resume")

        for spec in TABLE_SPECS:
            page = StaffingPage(self, spec) if spec.name == "rules_site_schedule" else TablePage(self, spec)
            self.pages[spec.name] = page
            self.notebook.add(page, text=spec.title)

        self.global_page = GlobalRulesPage(self)
        self.notebook.add(self.global_page, text="Global")

        self.json_page = JsonPage(self)
        self.notebook.add(self.json_page, text="JSON brut")

        self.planning_page = PlanningPage(self)
        self.notebook.add(self.planning_page, text="Planning")

        ttk.Label(self, textvariable=self.status, anchor="w", padding=(8, 4)).pack(fill="x")
        self.load_pages()
        self.after(100, self.planning_page.load_latest_planning)
        self.protocol("WM_DELETE_WINDOW", self.on_close)

    def create_menu(self) -> None:
        menu = tk.Menu(self)
        file_menu = tk.Menu(menu, tearoff=False)
        file_menu.add_command(label="Nouveau", command=self.new_file)
        file_menu.add_command(label="Ouvrir", command=self.open_file)
        file_menu.add_command(label="Enregistrer", command=self.save_file)
        file_menu.add_command(label="Enregistrer sous", command=self.save_as)
        file_menu.add_separator()
        file_menu.add_command(label="Quitter", command=self.on_close)
        menu.add_cascade(label="Fichier", menu=file_menu)

        tools_menu = tk.Menu(menu, tearoff=False)
        tools_menu.add_command(label="Valider", command=self.show_validation)
        tools_menu.add_command(label="Enregistrer + lancer solveur", command=self.run_solver)
        menu.add_cascade(label="Outils", menu=tools_menu)
        self.config(menu=menu)

    def create_toolbar(self) -> None:
        toolbar = ttk.Frame(self, padding=8)
        toolbar.pack(fill="x")
        ttk.Button(toolbar, text="Ouvrir", command=self.open_file).pack(side="left")
        ttk.Button(toolbar, text="Enregistrer", command=self.save_file).pack(side="left", padx=(6, 0))
        ttk.Button(toolbar, text="Valider", command=self.show_validation).pack(side="left", padx=(6, 0))
        ttk.Button(toolbar, text="Enregistrer + lancer solveur", command=self.run_solver).pack(side="left", padx=(6, 0))

    def load_pages(self) -> None:
        for page in self.pages.values():
            page.load_from_data(self.data)
        self.global_page.load_from_data(self.data)
        self.json_page.refresh_from_data()
        self.update_summary()
        self.set_status()

    def collect_from_pages(self) -> None:
        for page in self.pages.values():
            page.write_to_data(self.data)
        self.global_page.write_to_data(self.data)

    def choices_for(self, field: FieldSpec) -> list[str] | None:
        if field.field_type == "choice_static":
            if field.choices_name == "pos_neg":
                return POS_NEG
            if field.choices_name == "hard_soft":
                return HARD_SOFT
            if field.choices_name == "days":
                return DAYS
            if field.choices_name == "min_max":
                return MIN_MAX
        if field.field_type in {"choice", "choice_plus_all"}:
            names = self.names_for(field.choices_name or "")
            if field.field_type == "choice_plus_all":
                return ["tous"] + names
            return names
        return None

    def names_for(self, key: str) -> list[str]:
        if key == "sites":
            return [item.get("name", "") for item in self.data.get("sites", []) if item.get("name")]
        if key == "groups":
            return [item.get("name", "") for item in self.data.get("groups", []) if item.get("name")]
        if key == "educators":
            return [item.get("name", "") for item in self.data.get("educators", []) if item.get("name")]
        if key == "educator_types":
            return [item.get("name", "") for item in self.data.get("educator_types", []) if item.get("name")]
        return []

    def mark_dirty(self) -> None:
        self.dirty = True
        self.set_status()

    def set_status(self, message: str | None = None) -> None:
        path_text = str(self.path) if self.path else "(nouveau fichier)"
        dirty = " *" if self.dirty else ""
        self.status.set(message or f"{path_text}{dirty}")

    def new_file(self) -> None:
        if not self.confirm_discard():
            return
        self.path = None
        self.data = new_data()
        self.dirty = True
        self.load_pages()
        self.planning_page.clear()

    def open_file(self) -> None:
        if not self.confirm_discard():
            return
        selected = filedialog.askopenfilename(
            title="Ouvrir gwendo.json",
            filetypes=[("JSON", "*.json"), ("Tous", "*.*")],
        )
        if not selected:
            return
        try:
            self.path = Path(selected)
            self.data = load_json(self.path)
            self.dirty = False
            self.load_pages()
            self.planning_page.load_latest_planning()
        except Exception as exc:
            messagebox.showerror("Ouverture", f"Impossible d'ouvrir le fichier:\n{exc}")

    def save_file(self, *, show_confirmation: bool = True) -> bool:
        if self.path is None:
            return self.save_as()
        if self.json_page.json_dirty:
            if not self.json_page.apply_text_to_data(show_error=True):
                return False
            self.load_pages()
        else:
            self.collect_from_pages()
        validation_warnings, validation_errors = self.validate_data()
        if validation_errors:
            message = (
                f"Le fichier contient {len(validation_errors)} erreur(s) de validation.\n"
                "Voir l'onglet Resume pour le detail."
            )
            if not show_confirmation:
                messagebox.showerror("Validation", message)
                return False
            if not messagebox.askyesno("Validation", f"{message}\n\nEnregistrer quand meme ?"):
                return False
        try:
            save_json(self.path, self.data)
        except Exception as exc:
            messagebox.showerror("Enregistrement", f"Impossible d'enregistrer:\n{exc}")
            return False
        self.dirty = False
        self.json_page.refresh_from_data()
        self.update_summary()
        self.set_status(f"JSON enregistre: {self.path}")
        if show_confirmation:
            warning_text = (
                f"\n\nAttention: {len(validation_warnings)} avertissement(s) dans l'onglet Resume."
                if validation_warnings
                else ""
            )
            messagebox.showinfo("Enregistrement", f"JSON enregistre:\n{self.path}{warning_text}")
        return True

    def save_as(self) -> bool:
        selected = filedialog.asksaveasfilename(
            title="Enregistrer sous",
            defaultextension=".json",
            filetypes=[("JSON", "*.json"), ("Tous", "*.*")],
        )
        if not selected:
            return False
        self.path = Path(selected)
        return self.save_file()

    def confirm_discard(self) -> bool:
        if not self.dirty:
            return True
        answer = messagebox.askyesnocancel("Modifications", "Enregistrer les modifications avant de continuer ?")
        if answer is None:
            return False
        if answer:
            return self.save_file()
        return True

    def validate_data(self) -> tuple[list[str], list[str]]:
        self.collect_from_pages()
        warnings: list[str] = []
        errors: list[str] = []
        sites = set(self.names_for("sites"))
        groups = set(self.names_for("groups"))
        educators = set(self.names_for("educators"))
        educator_types = set(self.names_for("educator_types"))

        for site in self.data.get("sites", []):
            if not site.get("name"):
                errors.append("Site sans nom.")
            for key in ("open", "close"):
                if not is_time(str(site.get(key, ""))):
                    errors.append(f"Site {site.get('name', '?')}: heure {key} invalide.")

        for group in self.data.get("groups", []):
            if group.get("site") not in sites:
                errors.append(f"Groupe {group.get('name', '?')}: site inconnu {group.get('site')}.")

        for educator in self.data.get("educators", []):
            if educator.get("type") not in educator_types:
                errors.append(f"Educateur {educator.get('name', '?')}: type inconnu {educator.get('type')}.")
            percentage = parse_int(educator.get("percentage"), -1)
            if percentage < 0 or percentage > 100:
                errors.append(f"Educateur {educator.get('name', '?')}: pourcentage invalide.")
            if "max_work_days" in educator:
                max_work_days = parse_int(educator.get("max_work_days"), -1)
                if max_work_days < 0 or max_work_days > 5:
                    errors.append(f"Educateur {educator.get('name', '?')}: max jours invalide.")

        for rule in self.data.get("rules_time", []):
            pos_neg, hard_soft, educator, day, start, end = normalize_rule_list(rule, 6)
            if pos_neg not in POS_NEG:
                errors.append(f"Regle horaire: pos/neg invalide {pos_neg}.")
            if hard_soft not in HARD_SOFT:
                errors.append(f"Regle horaire: hard/soft invalide {hard_soft}.")
            if educator not in educators:
                errors.append(f"Regle horaire: educateur inconnu {educator}.")
            if str(day).lower() not in DAYS:
                errors.append(f"Regle horaire: jour inconnu {day}.")
            if not is_time(str(start)) or not is_time(str(end)):
                errors.append(f"Regle horaire {educator}: heures invalides {start}-{end}.")
            elif pos_neg == "positif" and hard_soft == "hard":
                if time_minutes(str(end)) <= time_minutes(str(start)):
                    errors.append(f"Regle horaire {educator}: plage positive hard vide {start}-{end}.")

        for rule in self.data.get("rules_group", []):
            pos_neg, hard_soft, educator, group = normalize_rule_list(rule, 4)
            if educator not in educators:
                errors.append(f"Regle groupe: educateur inconnu {educator}.")
            if group not in groups:
                errors.append(f"Regle groupe: groupe inconnu {group}.")
            if pos_neg not in POS_NEG or hard_soft not in HARD_SOFT:
                errors.append(f"Regle groupe invalide: {rule}.")

        for rule in self.data.get("rules_percentage", []):
            types, minmax, value, site = normalize_rule_list(rule, 4)
            raw_types = types if isinstance(types, list) else split_types(str(types))
            for item in raw_types:
                for type_name in split_types(str(item)):
                    if type_name not in educator_types:
                        warnings.append(f"Type inconnu dans une regle pourcentage: {type_name}.")
            if minmax not in MIN_MAX:
                errors.append(f"Regle pourcentage: min/max invalide {minmax}.")
            if site not in sites:
                errors.append(f"Regle pourcentage: site inconnu {site}.")
            if parse_int(value, -1) < 0:
                errors.append(f"Regle pourcentage: valeur invalide {value}.")

        for rule in self.data.get("rules_site_schedule", []):
            site = rule.get("site", "")
            if site not in sites:
                errors.append(f"Staffing: site inconnu {site}.")
            for interval in rule.get("time_intervals", []):
                group = interval.get("group", "")
                if group != "tous" and group not in groups:
                    errors.append(f"Staffing: groupe inconnu {group}.")
                _days, unknown_days = parse_days_value(interval.get("days", ""))
                for unknown_day in unknown_days:
                    errors.append(f"Staffing {site}/{group}: jour inconnu {unknown_day}.")
                if not is_time(str(interval.get("start", ""))) or not is_time(str(interval.get("end", ""))):
                    errors.append(f"Staffing {site}/{group}: heures invalides.")
                if parse_int(interval.get("min_staff"), -1) < 0:
                    errors.append(f"Staffing {site}/{group}: min_staff invalide.")

        for rule in self.data.get("rules_colloques", []):
            if isinstance(rule, dict):
                group = str(rule.get("group", ""))
                day = str(rule.get("day", ""))
                start = str(rule.get("start", ""))
                end = str(rule.get("end", ""))
            else:
                group, day, start, end = normalize_rule_list(rule, 4)
            if group not in groups:
                errors.append(f"Colloque: groupe inconnu {group}.")
            if str(day).lower() not in DAYS:
                errors.append(f"Colloque: jour inconnu {day}.")
            if not is_time(start) or not is_time(end):
                errors.append(f"Colloque {group}: heures invalides.")

        if not errors:
            coherence_warnings, coherence_errors = self.validate_constraint_coherence()
            warnings.extend(coherence_warnings)
            errors.extend(coherence_errors)

        return warnings, errors

    def validate_constraint_coherence(self) -> tuple[list[str], list[str]]:
        warnings: list[str] = []
        errors: list[str] = []
        groups = list(self.data.get("groups", []))
        educators = list(self.data.get("educators", []))
        if not groups or not educators:
            return warnings, errors
        try:
            horizon = make_horizon(self.data)
            group_demand, site_demand = build_demands_by_day(self.data, groups, horizon)
            config_path = find_solver_config(self.path)
            config = load_solver_config(config_path)
            weekly_base = float(self.data.get("rules_global", {}).get("max_weekly_hours", 40.0))
            step_hours = horizon.step / 60.0
            absolute_max = config.get("absolute_max_weekly_hours", 40.0)
            absolute_max_slots = None if absolute_max is None else int(float(absolute_max) / step_hours)
            tolerance_percent = float(config.get("weekly_hours_tolerance_percent", 3.0))
            tolerance_minutes = config.get("weekly_hours_tolerance_minutes")
            tolerance_step = config.get("weekly_hours_tolerance_step_minutes", 15)
            the_enabled = bool(config.get("the_enabled", True))
            the_percent = float(config.get("the_percent", 10.0))

            demand_slots = 0
            group_by_site = {
                site: [g_i for g_i, group in enumerate(groups) if group.get("site") == site]
                for site in {str(group.get("site", "")) for group in groups}
            }
            for d_i in range(len(DOMAIN_DAYS)):
                for g_i in range(len(groups)):
                    for slot in range(horizon.slots):
                        demand_slots += group_demand[(d_i, g_i, slot)]
                for (site_d_i, site, slot), site_minimum in site_demand.items():
                    if site_d_i != d_i:
                        continue
                    group_total = sum(
                        group_demand[(d_i, g_i, slot)]
                        for g_i in group_by_site.get(site, [])
                    )
                    demand_slots += max(0, int(site_minimum) - group_total)

            capacity_slots = 0
            for educator in educators:
                target_hours = parse_float(educator.get("percentage"), 0.0) / 100.0 * weekly_base
                target_slots = int(round(target_hours / step_hours))
                tolerance_slots = weekly_tolerance_slots(
                    target_hours,
                    horizon,
                    percent=tolerance_percent,
                    minutes=None if tolerance_minutes is None else int(tolerance_minutes),
                    step_minutes=None if tolerance_step is None else int(tolerance_step),
                )
                upper_slots = target_slots + tolerance_slots
                if absolute_max_slots is not None:
                    upper_slots = min(upper_slots, absolute_max_slots)
                the_slots = the_target_slots(target_slots, the_percent, enabled=the_enabled)
                capacity_slots += max(0, upper_slots - the_slots)

            margin_slots = capacity_slots - demand_slots
            demand_hours = demand_slots * step_hours
            capacity_hours = capacity_slots * step_hours
            margin_hours = margin_slots * step_hours
            if margin_slots < 0:
                errors.append(
                    "Capacite enfants insuffisante: "
                    f"besoin minimum {demand_hours:.2f}h, capacite max estimee {capacity_hours:.2f}h."
                )
            elif demand_slots and margin_slots < max(40, int(demand_slots * 0.05)):
                warnings.append(
                    "Marge de couverture tres faible: "
                    f"{margin_hours:.2f}h au-dessus du minimum. "
                    "Si une ligne de staffing est trop haute, le solveur peut devenir impossible."
                )

            colloque_parse_warnings: list[str] = []
            colloques = parse_colloques(self.data, horizon, groups, colloque_parse_warnings)
            warnings.extend(colloque_parse_warnings)
            for colloque in colloques:
                target_g = int(colloque["group_i"])
                d_i = int(colloque["day_i"])
                for slot in colloque["slots"]:
                    for source_g in range(len(groups)):
                        if source_g == target_g:
                            continue
                        source_demand = group_demand[(d_i, source_g, int(slot))]
                        needed_with_replacement = source_demand + 1
                        solver_group_cap = max(3, source_demand)
                        if needed_with_replacement > solver_group_cap:
                            errors.append(
                                "Colloque impossible: "
                                f"{groups[target_g]['name']} demande un remplacement depuis "
                                f"{groups[source_g]['name']}, mais ce groupe a deja besoin de "
                                f"{source_demand} personne(s) au meme moment."
                            )
        except Exception as exc:
            warnings.append(f"Controle de coherence non calcule: {exc}")
        return warnings, errors

    def update_summary(self) -> None:
        warnings, errors = self.validate_data()
        lines = []
        lines.append("Resume du fichier")
        lines.append("")
        lines.append(f"Sites: {len(self.data.get('sites', []))}")
        lines.append(f"Groupes: {len(self.data.get('groups', []))}")
        lines.append(f"Types: {len(self.data.get('educator_types', []))}")
        lines.append(f"Educateurs: {len(self.data.get('educators', []))}")
        lines.append(f"Regles horaires: {len(self.data.get('rules_time', []))}")
        lines.append(f"Regles groupes: {len(self.data.get('rules_group', []))}")
        lines.append(f"Regles pourcentage: {len(self.data.get('rules_percentage', []))}")
        lines.append(f"Regles staffing: {sum(len(rule.get('time_intervals', [])) for rule in self.data.get('rules_site_schedule', []))}")
        lines.append(f"Colloques: {len(self.data.get('rules_colloques', []))}")
        lines.append("")
        total_hours = sum(parse_float(item.get("percentage"), 0.0) * 40.0 / 100.0 for item in self.data.get("educators", []))
        lines.append(f"Heures educateurs cible: {total_hours:.2f} h/semaine")
        lines.append("")
        lines.append("Validation")
        if not warnings and not errors:
            lines.append("OK")
        for warning in warnings:
            lines.append(f"Attention: {warning}")
        for error in errors:
            lines.append(f"Erreur: {error}")

        self.summary.delete("1.0", "end")
        self.summary.insert("1.0", "\n".join(lines))

    def show_validation(self) -> None:
        self.update_summary()
        warnings, errors = self.validate_data()
        if errors:
            messagebox.showerror("Validation", f"{len(errors)} erreur(s), {len(warnings)} avertissement(s). Voir l'onglet Resume.")
        elif warnings:
            messagebox.showwarning("Validation", f"0 erreur, {len(warnings)} avertissement(s). Voir l'onglet Resume.")
        else:
            messagebox.showinfo("Validation", "Tout est coherent.")

    def run_solver(self) -> None:
        if self.path is None:
            messagebox.showinfo("Solveur", "Enregistre d'abord le fichier JSON.")
            return
        if not self.save_file(show_confirmation=False):
            return
        self.path = self.path.resolve()
        project_root = find_project_root(self.path)
        solver = find_solver_script(self.path)
        if not solver.exists():
            messagebox.showerror("Solveur", f"solveur_v2.py introuvable:\n{solver}")
            return
        config_path = find_solver_config(self.path)
        config_dir = config_path.parent if config_path.exists() else self.path.parent
        config = load_solver_config(config_path)
        timestamp_enabled = bool(config.get("timestamp_outputs", True))
        timestamp_format = str(config.get("timestamp_format", "%Y-%m-%d_%H-%M-%S"))
        timestamp = datetime.now().strftime(timestamp_format) if timestamp_enabled else None
        output = timestamped_path(
            resolve_local_path(config.get("output_json"), config_dir, f"{self.path.stem}_planning.json"),
            timestamp,
        )
        csv_output = timestamped_path(
            resolve_local_path(config.get("csv_output"), config_dir, f"{self.path.stem}_planning.csv"),
            timestamp,
        )
        html_output = timestamped_path(
            resolve_local_path(config.get("html_output"), config_dir, f"{self.path.stem}_planning.html"),
            timestamp,
        )
        output.parent.mkdir(parents=True, exist_ok=True)
        csv_output.parent.mkdir(parents=True, exist_ok=True)
        html_output.parent.mkdir(parents=True, exist_ok=True)
        command = [
            sys.executable,
            str(solver.resolve()),
            str(self.path.resolve()),
        ]
        if config_path.exists():
            command.extend(["--config", str(config_path.resolve())])
        else:
            command.extend(["--smooth", "--min-daily-hours", "2", "--time-limit", "60", "--smooth-time-limit", "20"])
        command.extend([
            "--output",
            str(output),
            "--csv",
            str(csv_output),
            "--html",
            str(html_output),
            "--no-timestamp-outputs",
        ])
        self.set_status("Solveur en cours...")
        dialog = SolverProgressDialog(self, output)
        dialog.update_progress(0, "Lancement du solveur")
        thread = threading.Thread(target=self._run_solver_thread, args=(command, output, dialog, project_root), daemon=True)
        thread.start()

    def _run_solver_thread(self, command: list[str], output: Path, dialog: SolverProgressDialog, cwd: Path) -> None:
        lines: list[str] = []
        try:
            process = subprocess.Popen(
                command,
                cwd=str(cwd),
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                bufsize=1,
            )
            assert process.stdout is not None
            for raw_line in process.stdout:
                line = raw_line.rstrip()
                if line.startswith("PROGRESS|"):
                    parts = line.split("|", 2)
                    if len(parts) == 3:
                        try:
                            percent = int(parts[1])
                        except ValueError:
                            percent = 0
                        message = parts[2]
                        self.after(0, lambda p=percent, m=message: dialog.update_progress(p, m))
                    continue
                lines.append(line)
                if line.startswith("Status:") or line.startswith("Verification:") or line.startswith("Erreurs"):
                    self.after(0, lambda m=line: dialog.append_log(m))
            returncode = process.wait(timeout=5)
        except Exception as exc:
            self.after(0, lambda: dialog.finish(False, f"Erreur: {exc}"))
            self.after(0, lambda: messagebox.showerror("Solveur", str(exc)))
            self.after(0, lambda: self.set_status())
            return

        def done() -> None:
            self.set_status()
            if output.exists():
                status = "?"
                try:
                    status = str(load_json_any(output).get("status", "?"))
                except Exception:
                    pass
                self.planning_page.load_planning(output)
                self.notebook.select(self.planning_page)
                if returncode == 0:
                    dialog.finish(True, f"Planning genere: {output.name}")
                    messagebox.showinfo("Solveur", f"Planning genere:\n{output}")
                    return
                dialog.finish(False, f"Planning genere avec statut {status}: {output.name}")
                messagebox.showwarning(
                    "Solveur",
                    "Le solveur a produit un planning, mais il n'est pas valide.\n"
                    "Consulte l'onglet Planning pour voir les erreurs.\n\n"
                    f"Fichier:\n{output}",
                )
            elif returncode == 0:
                dialog.finish(True, f"Planning genere: {output.name}")
                messagebox.showinfo("Solveur", f"Planning genere:\n{output}")
            else:
                dialog.finish(False, "Le solveur n'a pas trouve de planning valide.")
                messagebox.showerror("Solveur", "\n".join(lines))

        self.after(0, done)

    def on_close(self) -> None:
        if self.confirm_discard():
            self.destroy()


def check_file(path: Path) -> int:
    data = load_json(path)
    print(json.dumps(
        {
            "status": "ok",
            "sites": len(data.get("sites", [])),
            "groups": len(data.get("groups", [])),
            "educators": len(data.get("educators", [])),
            "rules_site_schedule": len(data.get("rules_site_schedule", [])),
            "rules_colloques": len(data.get("rules_colloques", [])),
        },
        ensure_ascii=False,
    ))
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Editeur Tkinter pour les fichiers JSON de creche.")
    parser.add_argument("json_path", nargs="?", type=Path, help="Fichier JSON a ouvrir.")
    parser.add_argument("--check", action="store_true", help="Charge le JSON sans lancer l'interface.")
    args = parser.parse_args()

    if args.check:
        if args.json_path is None:
            print("--check demande un fichier JSON.", file=sys.stderr)
            return 2
        return check_file(args.json_path)

    app = CrecheEditor(args.json_path)
    app.mainloop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
