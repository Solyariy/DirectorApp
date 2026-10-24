from dataclasses import asdict

from django.utils import timezone

from inverter_app.schemas import EnergySnapshotSchema
from src.inverter_app.inverter_service.provider import read_latest_energy
from src.inverter_app.models import EnergySnapshot


def read_latest_energy_and_save() -> EnergySnapshotSchema:
    stats = read_latest_energy()
    snapshot = EnergySnapshot.objects.create(
        timestamp=timezone.now(), **asdict(stats)
    )
    energy = EnergySnapshotSchema.model_validate(snapshot)
    return energy
