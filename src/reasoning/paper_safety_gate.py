from __future__ import annotations

from typing import Any


REFINEMENT_ACTIONS = {
    "REFINE_THROAT",
    "REFINE_GRADIENT_REGION",
}


def _nested_get(data: Any, *path: str) -> Any:
    current = data
    for key in path:
        if not isinstance(current, dict):
            return None
        current = current.get(key)
    return current


def mass_imbalance_percent(
    diagnostics: dict[str, Any] | None,
) -> float | None:
    if not isinstance(diagnostics, dict):
        return None

    candidates = (
        ("flow", "mass_imbalance_pct"),
        ("flow", "mass_imbalance_percent"),
        ("conservation", "mass_imbalance_pct"),
        ("conservation", "mass_imbalance_percent"),
        ("mass_imbalance_pct",),
        ("mass_imbalance_percent",),
    )

    for path in candidates:
        value = _nested_get(diagnostics, *path)
        if value is None:
            continue
        try:
            return float(value)
        except (TypeError, ValueError):
            pass

    return None


def recent_mass_imbalance_history(
    history: list[dict[str, Any]] | None,
    limit: int = 2,
) -> list[float]:
    values: list[float] = []

    if not history:
        return values

    for record in reversed(history):
        if not isinstance(record, dict):
            continue

        value = mass_imbalance_percent(
            record.get("diagnostics")
        )

        if value is None:
            continue

        values.append(value)

        if len(values) >= limit:
            break

    values.reverse()
    return values


def _contains_resolution_failure(value: Any) -> bool:
    keys = {
        "mesh_resolution_inadequate",
        "local_resolution_inadequate",
        "local_resolution_failure",
        "resolution_inadequate",
        "underresolved",
        "under_resolved",
        "mesh_convergence_failed",
    }

    if isinstance(value, dict):
        for key, child in value.items():
            if str(key).lower() in keys and child is True:
                return True

            if _contains_resolution_failure(child):
                return True

    elif isinstance(value, list):
        return any(
            _contains_resolution_failure(item)
            for item in value
        )

    return False


def apply_decision_safety_gate(
    *,
    requested_action: str,
    diagnostics: dict[str, Any],
    history: list[dict[str, Any]] | None,
    min_relative_improvement_pct: float = 5.0,
    severe_worsening_pct: float = 25.0,
) -> tuple[str, dict[str, Any]]:

    requested = str(requested_action).strip().upper()

    current = mass_imbalance_percent(
        diagnostics
    )

    previous_values = recent_mass_imbalance_history(
        history,
        limit=2,
    )

    previous = (
        previous_values[-1]
        if previous_values
        else None
    )

    relative_improvement = None

    if (
        current is not None
        and previous is not None
        and previous > 0.0
    ):
        relative_improvement = (
            100.0
            * (previous - current)
            / previous
        )

    series = list(previous_values)

    if current is not None:
        series.append(current)

    worsening_steps = []
    two_severe_worsenings = False

    if len(series) >= 3:
        a, b, c = series[-3:]

        if a > 0.0 and b > 0.0:
            w1 = 100.0 * (b - a) / a
            w2 = 100.0 * (c - b) / b

            worsening_steps = [w1, w2]

            two_severe_worsenings = (
                w1 >= severe_worsening_pct
                and
                w2 >= severe_worsening_pct
            )

    resolution_failure = (
        _contains_resolution_failure(
            diagnostics
        )
    )

    result = {
        "requested_action": requested,
        "effective_action": requested,
        "overridden": False,
        "current_mass_imbalance_pct": current,
        "previous_mass_imbalance_pct": previous,
        "recent_mass_imbalance_series_pct": series,
        "relative_improvement_pct": relative_improvement,
        "worsening_steps_pct": worsening_steps,
        "two_consecutive_severe_worsenings": two_severe_worsenings,
        "explicit_deterministic_resolution_failure": resolution_failure,
        "reason": (
            "No higher-priority safety override required."
        ),
    }

    if (
        requested == "CONTINUE_RUN"
        and two_severe_worsenings
    ):
        result.update(
            {
                "effective_action": "REQUEST_DIAGNOSTIC",
                "overridden": True,
                "reason": (
                    "Blind continuation blocked. Mass imbalance "
                    "worsened severely across two consecutive "
                    "same-mesh continuations "
                    f"({series[-3]:.6g}% -> "
                    f"{series[-2]:.6g}% -> "
                    f"{series[-1]:.6g}%). "
                    "No remeshing or field mapping occurred. "
                    "Deterministic diagnostics are required "
                    "before advancing the solver."
                ),
            }
        )

        return "REQUEST_DIAGNOSTIC", result

    if requested not in REFINEMENT_ACTIONS:
        return requested, result

    if (
        relative_improvement is not None
        and relative_improvement
        >= min_relative_improvement_pct
    ):
        result.update(
            {
                "effective_action": "CONTINUE_RUN",
                "overridden": True,
                "reason": (
                    "Premature refinement blocked. Same-mesh "
                    "mass conservation is materially improving "
                    f"({previous:.6g}% -> {current:.6g}%). "
                    "Strong throat gradients are expected "
                    "nozzle physics and do not alone prove "
                    "mesh underresolution."
                ),
            }
        )

        return "CONTINUE_RUN", result

    if not resolution_failure:
        result.update(
            {
                "effective_action": "REQUEST_DIAGNOSTIC",
                "overridden": True,
                "reason": (
                    "Refinement blocked because no explicit "
                    "quantitative deterministic resolution "
                    "failure is present."
                ),
            }
        )

        return "REQUEST_DIAGNOSTIC", result

    return requested, result
