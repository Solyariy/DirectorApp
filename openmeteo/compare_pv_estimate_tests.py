from datetime import datetime, timedelta
from io import StringIO
from unittest import mock

import pandas as pd
from django.core.management import call_command
from django.test import TestCase
from django.utils import timezone

from openmeteo.compare_pv_estimate import Command
from openmeteo.schemas import PvSiteSchema
from src.inverter_app.models import EnergySnapshot
from src.inverter_app.tests import SNAPSHOT_DEFAULTS


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
                "openmeteo.compare_pv_estimate.get_pv_site",
                return_value=self.site,
            ),
            mock.patch(
                "openmeteo.compare_pv_estimate.fetch_satellite_gti",
                return_value=satellite,
            ),
        ):
            call_command(
                Command(),
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
