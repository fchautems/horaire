from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class PatternSearchAttempt:
    label: str
    fixed_primary_groups: dict[int, int] | None
    restricted_patterns: bool
    restricted_pattern_mode: str
    generation_max_split_gap_minutes: int | None
    generation_time_step_minutes: int | None
    fine_generation_time_step_minutes: int | None
    budget_weight: float


def payload_is_hard_valid(payload: dict[str, Any]) -> bool:
    if payload.get("status") != "ok" or not isinstance(payload.get("schedule"), dict):
        return False
    checks = payload.get("checks")
    if not isinstance(checks, dict):
        return False
    return not checks.get("errors") and not checks.get("hard_errors")


def payload_is_retryable(payload: dict[str, Any]) -> bool:
    if payload.get("status") != "infeasible_or_not_solved":
        return False
    message = str(payload.get("solver_message", "")).lower()
    return any(token in message for token in ("infeasible", "time limit", "temps limite"))


def ensure_verified_status(payload: dict[str, Any]) -> dict[str, Any]:
    if payload.get("status") != "ok" or payload_is_hard_valid(payload):
        return payload
    checks = payload.setdefault("checks", {})
    errors = list(checks.get("errors", []))
    errors.append("Planning refuse: les controles hard finaux ne sont pas tous valides.")
    checks["errors"] = sorted(set(errors))
    checks["hard_errors"] = checks["errors"]
    payload["status"] = "invalid"
    return payload


def release_over_limit_primary_groups(
    data: dict[str, Any],
    latest_payload: dict[str, Any] | None,
    fixed_primary_groups: dict[int, int] | None,
) -> tuple[dict[int, int] | None, list[str]]:
    if not fixed_primary_groups:
        return None, []
    released = dict(fixed_primary_groups)
    released_names: list[str] = []
    checks = latest_payload.get("checks", {}) if isinstance(latest_payload, dict) else {}
    worked_days = checks.get("worked_days_by_educator", {})
    max_days = checks.get("max_work_days", {})
    if not isinstance(worked_days, dict) or not isinstance(max_days, dict):
        return None, []
    for educator_index, educator in enumerate(data.get("educators", [])):
        name = str(educator.get("name", ""))
        actual = worked_days.get(name)
        maximum = max_days.get(name)
        if actual is None or maximum is None:
            continue
        if float(actual) > float(maximum) and educator_index in released:
            released.pop(educator_index)
            released_names.append(name)
    return (released if released_names else None), released_names


def build_candidate_attempts(
    *,
    fixed_primary_groups: dict[int, int] | None,
    targeted_primary_groups: dict[int, int] | None,
    max_split_gap_minutes: int | None,
) -> list[PatternSearchAttempt]:
    attempts: list[PatternSearchAttempt] = []

    def add(
        label: str,
        fixed_groups: dict[int, int] | None,
        restricted: bool,
        gap_minutes: int | None,
        step_minutes: int | None,
        fine_step_minutes: int | None,
        weight: float,
    ) -> None:
        candidate = PatternSearchAttempt(
            label=label,
            fixed_primary_groups=fixed_groups,
            restricted_patterns=restricted,
            restricted_pattern_mode="continuous_halfday_groups",
            generation_max_split_gap_minutes=gap_minutes,
            generation_time_step_minutes=step_minutes,
            fine_generation_time_step_minutes=fine_step_minutes,
            budget_weight=weight,
        )
        signature = (
            tuple(sorted((fixed_groups or {}).items())),
            restricted,
            gap_minutes,
            step_minutes,
            fine_step_minutes,
        )
        if any(
            (
                tuple(sorted((item.fixed_primary_groups or {}).items())),
                item.restricted_patterns,
                item.generation_max_split_gap_minutes,
                item.generation_time_step_minutes,
                item.fine_generation_time_step_minutes,
            )
            == signature
            for item in attempts
        ):
            return
        attempts.append(candidate)

    quick_gap = 60 if max_split_gap_minutes is None else min(60, max_split_gap_minutes)
    guided_groups = targeted_primary_groups or fixed_primary_groups
    if guided_groups:
        add(
            "Reparation rapide en journees continues",
            guided_groups,
            True,
            quick_gap,
            60,
            30,
            2.0,
        )
    add(
        "Candidat libre en journees continues",
        None,
        True,
        quick_gap,
        60,
        30,
        2.5,
    )
    if max_split_gap_minutes is None or max_split_gap_minutes > quick_gap:
        if guided_groups:
            add(
                "Reparation du planning avec coupures completes",
                guided_groups,
                False,
                max_split_gap_minutes,
                30,
                15,
                3.0,
            )
        add(
            "Candidat avec espace de recherche complet",
            None,
            False,
            max_split_gap_minutes,
            15,
            None,
            4.0,
        )
    return attempts


def attempt_budget(
    remaining_seconds: float,
    attempts: list[PatternSearchAttempt],
    attempt_index: int,
    *,
    reserve_fraction: float = 0.25,
) -> float:
    remaining_attempts = attempts[attempt_index:]
    available = max(0.0, remaining_seconds * (1.0 - reserve_fraction))
    total_weight = sum(item.budget_weight for item in remaining_attempts)
    if total_weight <= 0:
        return available
    budget = available * attempts[attempt_index].budget_weight / total_weight
    if attempt_index == 0 and remaining_seconds >= 30.0 and budget < 30.0:
        return available
    return budget


def payload_objective(payload: dict[str, Any]) -> float:
    try:
        return float(payload.get("objective", float("inf")))
    except (TypeError, ValueError):
        return float("inf")


def choose_valid_payload(
    current: dict[str, Any] | None,
    candidate: dict[str, Any] | None,
) -> dict[str, Any] | None:
    if candidate is None or not payload_is_hard_valid(candidate):
        return current
    if current is None or not payload_is_hard_valid(current):
        return candidate
    return candidate if payload_objective(candidate) < payload_objective(current) else current
