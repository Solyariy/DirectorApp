from src.director_app.models import Policy, RegisteredApp
from src.director_app.schemas import (
    AppEvaluation,
    PolicyEvaluation,
    RuleContext,
    RuleEvaluation,
)
from src.inverter_app.schemas import EnergySnapshotSchema


def evaluate_policy(
    policy: Policy,
    energy: EnergySnapshotSchema,
) -> PolicyEvaluation:
    context = RuleContext.from_energy(energy)
    rules = [
        RuleEvaluation(
            rule=rule.id,
            name=rule.name,
            passed=rule.passed(context),
        )
        for rule in policy.effective_rules()
    ]
    return PolicyEvaluation(
        policy=policy.id,
        operator=policy.operator,
        passed=policy.combine(rule.passed for rule in rules),
        rules=rules,
    )


def evaluate_app(
    app: RegisteredApp,
    energy: EnergySnapshotSchema,
) -> AppEvaluation:
    policy = app.effective_policy
    result = None if policy is None else evaluate_policy(policy, energy)
    return AppEvaluation(
        can_run=result is not None and result.passed,
        energy=energy,
        policy=result,
    )
