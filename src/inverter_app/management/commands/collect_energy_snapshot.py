from django.core.management.base import BaseCommand, CommandError

from src.inverter_app.scripts import read_latest_energy_and_save
from src.utils.logs import Logger


class Command(BaseCommand):
    help = (
        "Read the inverter once and store an EnergySnapshot. "
        "Meant to run from cron (e.g. every minute)."
    )

    def handle(self, *args, **options):
        try:
            snapshot = read_latest_energy_and_save()
        except ConnectionError as e:
            Logger.warning(f"Snapshot skipped: {e}")
            raise CommandError(str(e)) from e
        Logger.info("Snapshot collected", **snapshot.model_dump())
