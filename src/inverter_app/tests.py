from datetime import datetime, timedelta
from io import StringIO
from unittest import mock

import pandas as pd
from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import SimpleTestCase, TestCase
from django.utils import timezone

from src.inverter_app.curtailment import (
    PvState,
    classify,
    estimate_mpp_voltages,
)
from src.inverter_app.inverter_service.manager import (
    InverterManager,
    InverterStats,
)
from src.inverter_app.models import EnergySnapshot
from src.inverter_app.schemas import EnergySnapshotSchema, PvSiteSchema

SNAPSHOT_DEFAULTS = {
    "id": None,
    "solar_power_w": 2000,
    "load_power_w": 500,
    "grid_power_w": 0,
    "battery_power_w": -1500,
    "battery_charge_pct": 60,
    "battery_voltage_v": 52.0,
    "grid_voltage_v": 230.0,
    "pv1_voltage_v": 300.0,
    "pv1_current_a": 6.7,
    "pv1_power_w": 2000,
    "pv2_voltage_v": 0.8,
    "pv2_current_a": 0.0,
    "pv2_power_w": 0,
    "battery_max_charge_current_a": 65,
}


def make_snapshot(**overrides) -> EnergySnapshotSchema:
    fields = {"timestamp": timezone.now(), **SNAPSHOT_DEFAULTS, **overrides}
    return EnergySnapshotSchema(**fields)


class ClassifyTests(SimpleTestCase):
    mpp = {"pv1": 300.0}

    def test_dark(self):
        snapshot = make_snapshot(solar_power_w=10)
        self.assertEqual(classify(snapshot, self.mpp), PvState.DARK)

    def test_battery_headroom_is_unconstrained(self):
        snapshot = make_snapshot(pv1_voltage_v=380.0)
        self.assertEqual(classify(snapshot, self.mpp), PvState.UNCONSTRAINED)

    def test_charging_at_limit_uses_voltage(self):
        # 65 A * 52 V = 3380 W: battery is at its charge limit.
        snapshot = make_snapshot(battery_power_w=-3380, pv1_voltage_v=380.0)
        self.assertEqual(classify(snapshot, self.mpp), PvState.CURTAILED)

    def test_full_battery_high_voltage_is_curtailed(self):
        snapshot = make_snapshot(
            battery_charge_pct=100,
            battery_power_w=0,
            pv1_voltage_v=360.0,
        )
        self.assertEqual(classify(snapshot, self.mpp), PvState.CURTAILED)

    def test_full_battery_at_mpp_is_unconstrained(self):
        snapshot = make_snapshot(battery_charge_pct=100, pv1_voltage_v=310.0)
        self.assertEqual(classify(snapshot, self.mpp), PvState.UNCONSTRAINED)

    def test_full_battery_without_reference_is_unknown(self):
        snapshot = make_snapshot(battery_charge_pct=100)
        self.assertEqual(classify(snapshot, {}), PvState.UNKNOWN)

    def test_missing_charge_limit_falls_back_to_voltage(self):
        snapshot = make_snapshot(
            battery_max_charge_current_a=None,
            pv1_voltage_v=360.0,
        )
        self.assertEqual(classify(snapshot, self.mpp), PvState.CURTAILED)


class EstimateMppVoltagesTests(SimpleTestCase):
    def test_median_over_headroom_samples_only(self):
        snapshots = [
            make_snapshot(pv1_voltage_v=290.0),
            make_snapshot(pv1_voltage_v=300.0),
            make_snapshot(pv1_voltage_v=310.0),
            # Full battery: possibly curtailed, ignored.
            make_snapshot(battery_charge_pct=100, pv1_voltage_v=400.0),
            # Too little power for a stable Vmp, ignored.
            make_snapshot(pv1_voltage_v=250.0, pv1_power_w=50),
        ]
        self.assertEqual(estimate_mpp_voltages(snapshots), {"pv1": 300.0})


class InverterManagerFormatTests(SimpleTestCase):
    def test_maps_registers(self):
        manager = InverterManager()
        response = [0] * manager.COUNT

        def put(addr, value):
            response[addr - manager.BASE] = value

        put(150, 2270)
        put(169, 65436)  # -100 W: exporting
        put(178, 420)
        put(183, 5300)
        put(184, 80)
        put(186, 1500)
        put(187, 200)
        put(190, 65036)  # -500 W: charging
        put(210, 65)
        pv_response = [3012, 50, 2805, 7]

        stats = manager._format_registers_response(response, pv_response)

        self.assertEqual(
            stats,
            InverterStats(
                solar_power_w=1700,
                load_power_w=420,
                grid_power_w=-100,
                battery_power_w=-500,
                battery_charge_pct=80,
                battery_voltage_v=53.0,
                grid_voltage_v=227.0,
                pv1_voltage_v=301.2,
                pv1_current_a=5.0,
                pv1_power_w=1500,
                pv2_voltage_v=280.5,
                pv2_current_a=0.7,
                pv2_power_w=200,
                battery_max_charge_current_a=65,
            ),
        )


class CollectEnergySnapshotCommandTests(TestCase):
    @mock.patch("src.inverter_app.scripts.read_latest_energy")
    def test_saves_snapshot(self, read_latest_energy):
        fields = dict(SNAPSHOT_DEFAULTS)
        fields.pop("id")
        read_latest_energy.return_value = InverterStats(**fields)

        call_command("collect_energy_snapshot")

        snapshot = EnergySnapshot.objects.get()
        self.assertEqual(snapshot.pv1_voltage_v, 300.0)
        self.assertEqual(snapshot.battery_max_charge_current_a, 65)

    @mock.patch(
        "src.inverter_app.scripts.read_latest_energy",
        side_effect=ConnectionError("Failed to connect to inverter"),
    )
    def test_unreachable_inverter_fails(self, _):
        with self.assertRaises(CommandError):
            call_command("collect_energy_snapshot")
        self.assertFalse(EnergySnapshot.objects.exists())


class ComparePvEstimateCommandTests(TestCase):
    site = PvSiteSchema(
        latitude=50.45,
        longitude=30.52,
        tilt_deg=30,
        azimuth_deg=180,
        peak_power_w=5000,
    )

    def setUp(self):
        tz = timezone.get_current_timezone()
        self.noon = datetime(
            2026,
            6,
            21,
            12,
            0,
            tzinfo=tz,
        )
        fields = dict(SNAPSHOT_DEFAULTS)
        fields.pop("id")
        # Battery charging: measured solar is the available power.
        for minute in range(
            0,
            30,
            5,
        ):
            EnergySnapshot.objects.create(
                timestamp=self.noon + timedelta(minutes=minute),
                **{**fields, "solar_power_w": 3200, "pv1_power_w": 3200},
            )
        # Battery full, strings pushed toward Voc: curtailed.
        for minute in range(
            30,
            60,
            5,
        ):
            EnergySnapshot.objects.create(
                timestamp=self.noon + timedelta(minutes=minute),
                **{
                    **fields,
                    "solar_power_w": 600,
                    "pv1_power_w": 600,
                    "pv1_voltage_v": 370.0,
                    "battery_charge_pct": 100,
                    "battery_power_w": 0,
                },
            )

    def test_reports_calibration_and_curtailment(self):
        index = pd.date_range(
            self.noon - timedelta(hours=1),
            periods=13,
            freq="10min",
        ).tz_convert("UTC")
        satellite = pd.Series(800.0, index=index)
        out = StringIO()
        with (
            mock.patch(
                "src.inverter_app.management.commands."
                "compare_pv_estimate.get_pv_site",
                return_value=self.site,
            ),
            mock.patch(
                "src.inverter_app.management.commands."
                "compare_pv_estimate.fetch_satellite_gti",
                return_value=satellite,
            ),
        ):
            call_command(
                "compare_pv_estimate",
                "--date",
                "2026-06-21",
                stdout=out,
            )

        report = out.getvalue()
        # 3200 W / (800 W/m² / 1000 * 5000 W) = 0.8
        self.assertIn("Performance ratio used: 0.800", report)
        self.assertIn("'unconstrained': 6, 'curtailed': 6", report)
        self.assertIn("MPP reference voltages: {'pv1': 300.0}", report)
        # 3200 W available, 600 W used.
        self.assertIn("mean 2600 W", report)
