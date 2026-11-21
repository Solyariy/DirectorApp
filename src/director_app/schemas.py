from datetime import time

from django.utils import timezone
from pydantic import BaseModel, computed_field

from src.inverter_app.schemas import EnergySnapshotSchema


class RuleContext(EnergySnapshotSchema):
    """An energy reading plus the local-time fields schedule rules use."""

    # Local time is settings.TIME_ZONE (the default current time zone).
    @computed_field(description="0 = Monday ... 6 = Sunday, local time")
    @property
    def weekday(self) -> int:
        return timezone.localtime(self.timestamp).weekday()

    @computed_field(description="Time of day of the reading, local time")
    @property
    def local_time(self) -> time:
        return timezone.localtime(self.timestamp).time()

    @classmethod
    def from_energy(cls, energy: EnergySnapshotSchema) -> "RuleContext":
        if isinstance(energy, cls):
            return energy
        return cls.model_validate(energy, from_attributes=True)


class RuleEvaluation(BaseModel):
    rule: int
    name: str
    passed: bool


class PolicyEvaluation(BaseModel):
    policy: int
    operator: str
    passed: bool
    rules: list[RuleEvaluation]


class AppEvaluation(BaseModel):
    can_run: bool
    energy: EnergySnapshotSchema
    policy: PolicyEvaluation | None
