from pydantic import BaseModel

from src.inverter_app.schemas import EnergySnapshotSchema


class PolicyEvaluation(BaseModel):
    policy: int
    passed: bool
    failed_rules: list[str]


class AppEvaluation(BaseModel):
    can_run: bool
    matched_policy: int | None
    energy: EnergySnapshotSchema
    policies: list[PolicyEvaluation]
