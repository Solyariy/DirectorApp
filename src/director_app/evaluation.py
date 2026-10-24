from datetime import datetime, time
from zoneinfo import ZoneInfo

from django.utils import timezone

from src.director_app.models import Policy, RegisteredApp
from src.director_app.schemas import AppEvaluation, PolicyEvaluation
from src.inverter_app.schemas import EnergySnapshotSchema


def _in_date_window(policy: Policy, now: datetime) -> bool:
    if policy.active_from is not None and now < policy.active_from:
        return False
    if policy.active_until is not None and now > policy.active_until:
        return False
    return True


def _in_time_window(policy: Policy, current: time) -> bool:
    start, end = policy.time_from, policy.time_to
    if start is None or end is None:
        return True
    if start < end:
        return start <= current < end
    return current >= start or current < end


def _at_least(value: int, minimum: int | None) -> bool:
    return minimum is None or value >= minimum


def _at_most(value: int, maximum: int | None) -> bool:
    return maximum is None or value <= maximum


def find_failed_rules(
    policy: Policy,
    energy: EnergySnapshotSchema,
    now: datetime,
) -> list[str]:
    local = now.astimezone(ZoneInfo(policy.timezone))
    # max_concurrent_jobs is not checked until jobs are linked to apps.
    checks = {
        "date_window": _in_date_window(policy, now),
        "weekday": (
            policy.weekdays is None or local.weekday() in policy.weekdays
        ),
        "time_window": _in_time_window(policy, local.time()),
        "min_solar_w": _at_least(energy.solar_power_w, policy.min_solar_w),
        "battery_floor_pct": _at_least(
            energy.battery_charge_pct,
            policy.battery_floor_pct,
        ),
        "max_grid_import_w": _at_most(
            # Positive = import from the grid, negative = export.
            max(energy.grid_power_w, 0),
            policy.max_grid_import_w,
        ),
    }
    return [rule for rule, passed in checks.items() if not passed]


def evaluate_app(
    app: RegisteredApp,
    energy: EnergySnapshotSchema,
    now: datetime | None = None,
) -> AppEvaluation:
    now = now or timezone.now()
    connections = (
        app.connections.effective()
        .select_related("policy")
        .order_by("policy_id")
    )
    results = []
    for connection in connections:
        failed = find_failed_rules(
            connection.policy,
            energy,
            now,
        )
        results.append(
            PolicyEvaluation(
                policy=connection.policy_id,
                passed=not failed,
                failed_rules=failed,
            )
        )
    matched = next((r.policy for r in results if r.passed), None)
    return AppEvaluation(
        can_run=matched is not None,
        matched_policy=matched,
        energy=energy,
        policies=results,
    )
