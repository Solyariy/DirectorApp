from datetime import UTC, date, datetime, time, timedelta

import pandas as pd
from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from src.inverter_app.curtailment import (
    PvState,
    classify,
    estimate_mpp_voltages,
    voltage_ratios,
)
from src.inverter_app.irradiance import (
    clear_sky_gti,
    fetch_satellite_gti,
    get_pv_site,
    gti_to_power_w,
)
from src.inverter_app.models import EnergySnapshot
from src.inverter_app.schemas import EnergySnapshotSchema

# Below this GTI the PV/irradiance ratio is dominated by noise.
CALIBRATION_MIN_GTI = 100
BUCKET = "10min"


class Command(BaseCommand):
    help = (
        "Proof of concept: compare one day of EnergySnapshots with "
        "satellite (Open-Meteo) and clear-sky (pvlib) irradiance, and "
        "classify each reading as curtailed or unconstrained."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--date",
            type=date.fromisoformat,
            default=timezone.localdate(),
            help="Local day to analyse, YYYY-MM-DD (default: today).",
        )
        parser.add_argument(
            "--reference-days",
            type=int,
            default=14,
            help="History window for per-string MPP reference voltages.",
        )
        parser.add_argument("--csv", help="Also write per-reading rows.")

    def handle(self, *args, **options):
        site = get_pv_site()
        tz = timezone.get_current_timezone()
        day_start = datetime.combine(
            options["date"],
            time.min,
            tzinfo=tz,
        )
        day_end = day_start + timedelta(days=1)

        snapshots = self._load(day_start, day_end)
        if not snapshots:
            raise CommandError(f"No snapshots on {options['date']}")
        history_start = day_end - timedelta(days=options["reference_days"])
        mpp_voltages = estimate_mpp_voltages(
            self._load(history_start, day_end)
        )

        df = self._classify(snapshots, mpp_voltages)
        satellite = fetch_satellite_gti(
            site,
            day_start.astimezone(UTC).date(),
            day_end.astimezone(UTC).date(),
        )
        df["satellite_gti"] = self._interpolate(satellite, df.index)
        df["clear_sky_gti"] = clear_sky_gti(site, df.index)

        ratio = self._calibrate_performance_ratio(df, site.peak_power_w)
        df["satellite_estimate_w"] = gti_to_power_w(
            df["satellite_gti"],
            site,
            ratio,
        )
        df["clear_sky_ceiling_w"] = gti_to_power_w(
            df["clear_sky_gti"],
            site,
            ratio,
        )

        self._report(
            df,
            mpp_voltages,
            ratio or site.performance_ratio,
        )
        if options["csv"]:
            df.to_csv(options["csv"])
            self.stdout.write(f"Rows written to {options['csv']}")

    @staticmethod
    def _load(start, end) -> list[EnergySnapshotSchema]:
        queryset = EnergySnapshot.objects.filter(
            timestamp__gte=start,
            timestamp__lt=end,
        ).order_by("timestamp")
        return [EnergySnapshotSchema.model_validate(s) for s in queryset]

    @staticmethod
    def _classify(snapshots, mpp_voltages) -> pd.DataFrame:
        rows = []
        for snapshot in snapshots:
            ratios = voltage_ratios(snapshot, mpp_voltages)
            rows.append(
                {
                    "timestamp": snapshot.timestamp,
                    "solar_w": snapshot.solar_power_w,
                    "load_w": snapshot.load_power_w,
                    "grid_w": snapshot.grid_power_w,
                    "battery_w": snapshot.battery_power_w,
                    "battery_pct": snapshot.battery_charge_pct,
                    "pv1_v": snapshot.pv1_voltage_v,
                    "pv2_v": snapshot.pv2_voltage_v,
                    "max_v_ratio": max(ratios.values(), default=None),
                    "state": classify(snapshot, mpp_voltages).value,
                }
            )
        df = pd.DataFrame(rows).set_index("timestamp")
        df.index = pd.DatetimeIndex(df.index).tz_convert("UTC")
        return df

    @staticmethod
    def _interpolate(series: pd.Series, index: pd.DatetimeIndex):
        combined = series.reindex(series.index.union(index))
        return combined.interpolate(method="time").reindex(index)

    @staticmethod
    def _calibrate_performance_ratio(df, peak_power_w) -> float | None:
        """Median measured/ideal power over unconstrained daylight rows."""
        rows = df[
            (df["state"] == PvState.UNCONSTRAINED)
            & (df["satellite_gti"] >= CALIBRATION_MIN_GTI)
        ]
        if rows.empty:
            return None
        ideal_w = rows["satellite_gti"] / 1000 * peak_power_w
        return float((rows["solar_w"] / ideal_w).median())

    def _report(self, df, mpp_voltages, ratio):
        local = df.tz_convert(timezone.get_current_timezone())
        numeric = local.drop(columns="state").resample(BUCKET).mean()
        numeric["state"] = (
            local["state"]
            .resample(BUCKET)
            .agg(lambda s: s.mode().iat[0] if not s.empty else None)
        )
        table = numeric.dropna(subset=["solar_w"]).round(2)
        self.stdout.write(table.to_string())

        unconstrained = df[df["state"] == PvState.UNCONSTRAINED]
        curtailed = df[df["state"] == PvState.CURTAILED]
        error = (
            unconstrained["satellite_estimate_w"] - unconstrained["solar_w"]
        )
        headroom = curtailed["satellite_estimate_w"] - curtailed["solar_w"]
        self.stdout.write("")
        self.stdout.write(
            f"Readings by state: {df['state'].value_counts().to_dict()}"
        )
        self.stdout.write(f"MPP reference voltages: {mpp_voltages or 'n/a'}")
        self.stdout.write(f"Performance ratio used: {ratio:.3f}")
        if not unconstrained.empty:
            self.stdout.write(
                "Satellite estimate vs measured (unconstrained): "
                f"bias {error.mean():.0f} W, MAE {error.abs().mean():.0f} W"
            )
        if not curtailed.empty:
            self.stdout.write(
                "Estimated unused PV while curtailed: "
                f"mean {headroom.mean():.0f} W, max {headroom.max():.0f} W"
            )
