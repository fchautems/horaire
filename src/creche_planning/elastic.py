"""Experimental Phase I: minimize coverage deficits before strict optimization.

Method reference: Gurobi's published workforce4 example. No Gurobi dependency.
Deficits describe requirement rows, not unique missing employee-hours.
"""
from __future__ import annotations

from typing import Any


class CoverageRelaxation:
    def __init__(self, model: Any, step_minutes: int) -> None:
        self.model = model
        self.step_minutes = step_minutes
        self.entries: list[tuple[Any, Any, dict[str, Any]]] = []

    def add_minimum(self, presence: Any, required: int, **location: Any) -> None:
        if required <= 0:
            self.model.Add(presence >= required)
            return
        deficit = self.model.NewIntVar(0, required, f"coverage_deficit_{len(self.entries)}")
        # Exact magnitudes also make diagnostics reliable for nonoptimal incumbents.
        self.model.AddMaxEquality(deficit, [0, required - presence])
        self.model.Add(presence + deficit >= required)
        self.entries.append((deficit, presence, dict(location, required=required)))

    @property
    def objective(self) -> Any:
        return sum(var for var, _presence, _location in self.entries)

    def describe(self, solution: Any) -> dict[str, Any]:
        rows = []
        for var, presence, location in self.entries:
            missing = int(solution.Value(var))
            if missing:
                rows.append(dict(location, present=int(solution.Value(presence)), missing=missing))
        return {
            "total_deficit_slots": sum(row["missing"] for row in rows),
            "deficit_requirement_minutes": self.step_minutes * sum(row["missing"] for row in rows),
            "deficits": rows,
            "requirements_count": len(self.entries),
            "unit": "person-slot per requirement row; overlapping group/site rows are not deduplicated",
        }
