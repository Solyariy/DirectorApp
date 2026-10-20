from datetime import datetime, time
from unittest.mock import patch
from zoneinfo import ZoneInfo

from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient

from src.director_app.evaluation import find_failed_rules
from src.director_app.models import AppPolicy, Policy, RegisteredApp
from src.inverter_app.models import EnergySnapshot
from src.inverter_app.schemas import EnergySnapshotSchema


class OperatorTestCase(TestCase):
    def setUp(self):
        self.client = APIClient()

    def create_app(self, name="doc-indexer"):
        response = self.client.post(
            "/api/apps/",
            {"name": name, "description": "Nightly embeddings"},
            format="json",
        )
        self.assertEqual(
            response.status_code,
            201,
            response.data,
        )
        return response.data

    def create_policy(self, **fields):
        body = {"name": "Sunny weekdays", **fields}
        response = self.client.post(
            "/api/policies/",
            body,
            format="json",
        )
        self.assertEqual(
            response.status_code,
            201,
            response.data,
        )
        return response.data

    def connect(self, app_id, policy_id, is_active=True):
        return self.client.post(
            f"/api/apps/{app_id}/policies/",
            {"policy": policy_id, "is_active": is_active},
            format="json",
        )


class RegisteredAppTests(OperatorTestCase):
    def test_create_returns_token_once(self):
        app = self.create_app()
        self.assertTrue(app["token"].startswith("tdk_"))
        self.assertEqual(app["active_policies_count"], 0)
        self.assertIsNone(app["last_seen_at"])
        stored = RegisteredApp.objects.get(pk=app["id"])
        self.assertNotEqual(stored.token_hash, app["token"])
        detail = self.client.get(f"/api/apps/{app['id']}/").data
        self.assertNotIn("token", detail)

    def test_duplicate_or_empty_name_is_400(self):
        self.create_app()
        for name in ("doc-indexer", ""):
            response = self.client.post(
                "/api/apps/",
                {"name": name},
                format="json",
            )
            self.assertEqual(response.status_code, 400)
            self.assertIn("name", response.data)

    def test_list_search_and_pagination(self):
        self.create_app("doc-indexer")
        self.create_app("photo-tagger")
        response = self.client.get("/api/apps/", {"search": "photo"})
        self.assertEqual(response.data["count"], 1)
        self.assertEqual(response.data["results"][0]["name"], "photo-tagger")
        self.assertNotIn("token", response.data["results"][0])

    def test_patch_and_delete(self):
        app = self.create_app()
        policy = self.create_policy()
        self.connect(app["id"], policy["id"])
        response = self.client.patch(
            f"/api/apps/{app['id']}/",
            {"description": "Updated"},
            format="json",
        )
        self.assertEqual(response.data["description"], "Updated")
        self.assertEqual(response.data["active_policies_count"], 1)
        response = self.client.delete(f"/api/apps/{app['id']}/")
        self.assertEqual(response.status_code, 204)
        self.assertFalse(AppPolicy.objects.exists())
        self.assertTrue(Policy.objects.filter(pk=policy["id"]).exists())
        response = self.client.get(f"/api/apps/{app['id']}/")
        self.assertEqual(response.status_code, 404)
        self.assertEqual(response.data["detail"], "Not found.")

    def test_rotate_token(self):
        app = self.create_app()
        response = self.client.post(f"/api/apps/{app['id']}/rotate-token/")
        self.assertEqual(response.status_code, 200)
        self.assertNotEqual(response.data["token"], app["token"])


class ConnectionTests(OperatorTestCase):
    def setUp(self):
        super().setUp()
        self.app = self.create_app()
        self.policy = self.create_policy()
        self.url = f"/api/apps/{self.app['id']}/policies/"

    def test_connect_list_and_conflict(self):
        response = self.connect(self.app["id"], self.policy["id"])
        self.assertEqual(response.status_code, 201)
        self.assertEqual(
            response.data["policy"],
            {
                "id": self.policy["id"],
                "name": "Sunny weekdays",
                "is_active": True,
            },
        )
        self.assertTrue(response.data["effective"])
        response = self.connect(self.app["id"], self.policy["id"])
        self.assertEqual(response.status_code, 409)
        self.assertEqual(len(self.client.get(self.url).data), 1)

    def test_unknown_policy_is_400_and_unknown_app_is_404(self):
        self.assertEqual(self.connect(self.app["id"], 999).status_code, 400)
        self.assertEqual(self.connect(999, self.policy["id"]).status_code, 404)

    def test_effective_requires_policy_and_connection_active(self):
        night = self.create_policy(name="Night", is_active=False)
        self.connect(self.app["id"], self.policy["id"])
        self.connect(self.app["id"], night["id"])
        effective = self.client.get(self.url, {"effective": "true"}).data
        self.assertEqual(
            [c["policy"]["id"] for c in effective],
            [self.policy["id"]],
        )
        not_effective = self.client.get(self.url, {"effective": "false"})
        self.assertEqual(
            [c["policy"]["id"] for c in not_effective.data],
            [night["id"]],
        )
        response = self.client.get(self.url, {"is_active": "maybe"})
        self.assertEqual(response.status_code, 400)

    def test_patch_and_delete_connection(self):
        self.connect(self.app["id"], self.policy["id"])
        url = f"{self.url}{self.policy['id']}/"
        response = self.client.patch(
            url,
            {"is_active": False},
            format="json",
        )
        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.data["effective"])
        app = self.client.get(f"/api/apps/{self.app['id']}/").data
        self.assertEqual(app["active_policies_count"], 0)
        self.assertEqual(self.client.delete(url).status_code, 204)
        self.assertEqual(self.client.delete(url).status_code, 404)

    def test_policy_apps_reverse_view(self):
        self.connect(
            self.app["id"],
            self.policy["id"],
            is_active=False,
        )
        response = self.client.get(f"/api/policies/{self.policy['id']}/apps/")
        self.assertEqual(
            response.data[0]["app"],
            {"id": self.app["id"], "name": "doc-indexer"},
        )
        self.assertFalse(response.data[0]["is_active"])


class PolicyTests(OperatorTestCase):
    def test_create_full_policy(self):
        policy = self.create_policy(
            description="Daytime surplus only",
            active_from="2026-10-01T00:00:00Z",
            weekdays=[4, 0, 1, 2, 3, 0],
            time_from="10:00",
            time_to="16:00",
            timezone="Europe/Kyiv",
            min_solar_w=1500,
            battery_floor_pct=30,
            max_grid_import_w=0,
            max_concurrent_jobs=1,
        )
        self.assertEqual(policy["weekdays"], [0, 1, 2, 3, 4])
        self.assertEqual(policy["time_from"], "10:00")
        self.assertEqual(policy["apps_count"], 0)
        self.assertTrue(policy["is_active"])

    def test_validation_errors(self):
        invalid = [
            ({"min_solar_w": -1}, "min_solar_w"),
            ({"battery_floor_pct": 101}, "battery_floor_pct"),
            ({"weekdays": [7]}, "weekdays"),
            ({"weekdays": []}, "weekdays"),
            ({"timezone": "Mars/Base"}, "timezone"),
            ({"time_from": "10:00"}, "time_to"),
            ({"time_from": "10:00", "time_to": "10:00"}, "time_to"),
            (
                {
                    "active_from": "2026-10-02T00:00:00Z",
                    "active_until": "2026-10-01T00:00:00Z",
                },
                "active_until",
            ),
        ]
        for fields, error_field in invalid:
            with self.subTest(fields=fields):
                response = self.client.post(
                    "/api/policies/",
                    {"name": "Bad", **fields},
                    format="json",
                )
                self.assertEqual(response.status_code, 400)
                self.assertIn(error_field, response.data)

    def test_patch_validates_against_stored_values(self):
        policy = self.create_policy(time_from="22:00", time_to="06:00")
        response = self.client.patch(
            f"/api/policies/{policy['id']}/",
            {"time_to": None},
            format="json",
        )
        self.assertEqual(response.status_code, 400)
        response = self.client.patch(
            f"/api/policies/{policy['id']}/",
            {"is_active": False},
            format="json",
        )
        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.data["is_active"])

    def test_list_filters(self):
        self.create_policy(name="Sunny weekdays")
        self.create_policy(name="Night", is_active=False)
        response = self.client.get("/api/policies/", {"is_active": "false"})
        self.assertEqual(
            [p["name"] for p in response.data["results"]],
            ["Night"],
        )
        response = self.client.get("/api/policies/", {"search": "sunny"})
        self.assertEqual(response.data["count"], 1)

    def test_delete_blocked_by_active_connection(self):
        app = self.create_app()
        policy = self.create_policy()
        self.connect(app["id"], policy["id"])
        url = f"/api/policies/{policy['id']}/"
        self.assertEqual(self.client.delete(url).status_code, 409)
        self.client.patch(
            f"/api/apps/{app['id']}/policies/{policy['id']}/",
            {"is_active": False},
            format="json",
        )
        self.assertEqual(self.client.delete(url).status_code, 204)
        self.assertFalse(AppPolicy.objects.exists())


class EvaluateTests(OperatorTestCase):
    def setUp(self):
        super().setUp()
        self.app = self.create_app()
        self.url = f"/api/apps/{self.app['id']}/evaluate/"

    def read_energy(self, **kwargs):
        """Patch the live inverter read with a stored snapshot."""
        if "side_effect" not in kwargs:
            kwargs["return_value"] = EnergySnapshot.objects.create(
                timestamp=timezone.now(),
                solar_power_w=3200,
                load_power_w=900,
                grid_power_w=0,
                battery_power_w=0,
                battery_charge_pct=82,
                battery_voltage_v=52.0,
                grid_voltage_v=230.0,
            )
        reader = patch(
            "src.director_app.views.read_latest_energy_and_save",
            **kwargs,
        )
        reader.start()
        self.addCleanup(reader.stop)

    def test_inverter_unreachable_is_503(self):
        self.read_energy(side_effect=ConnectionError("Inverter offline"))
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.data["detail"], "Inverter offline")

    def test_any_effective_policy_may_pass(self):
        self.read_energy()
        strict = self.create_policy(name="Strict", min_solar_w=5000)
        relaxed = self.create_policy(name="Relaxed", battery_floor_pct=50)
        off = self.create_policy(name="Off", is_active=False)
        for policy in (strict, relaxed, off):
            self.connect(self.app["id"], policy["id"])
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.data["can_run"])
        self.assertEqual(response.data["matched_policy"], relaxed["id"])
        self.assertEqual(response.data["energy"]["solar_power_w"], 3200)
        self.assertEqual(
            response.data["policies"],
            [
                {
                    "policy": strict["id"],
                    "passed": False,
                    "failed_rules": ["min_solar_w"],
                },
                {"policy": relaxed["id"], "passed": True, "failed_rules": []},
            ],
        )

    def test_without_effective_policies(self):
        self.read_energy()
        response = self.client.get(self.url)
        self.assertFalse(response.data["can_run"])
        self.assertIsNone(response.data["matched_policy"])
        self.assertEqual(response.data["policies"], [])


class RuleTests(TestCase):
    energy = EnergySnapshotSchema(
        id=None,
        timestamp=datetime(2026, 10, 14, 20, 30, tzinfo=ZoneInfo("UTC")),
        solar_power_w=3200,
        load_power_w=900,
        grid_power_w=0,
        battery_power_w=0,
        battery_charge_pct=82,
        battery_voltage_v=52.0,
        grid_voltage_v=230.0,
    )
    # Wednesday 2026-10-14 23:30 in Kyiv (UTC+3).
    now = datetime(
        2026,
        10,
        14,
        20,
        30,
        tzinfo=ZoneInfo("UTC"),
    )

    def failed(self, **fields):
        return find_failed_rules(
            Policy(name="p", **fields),
            self.energy,
            self.now,
        )

    def test_empty_policy_passes(self):
        self.assertEqual(self.failed(), [])

    def test_time_window_uses_timezone_and_wraps_midnight(self):
        night = {"time_from": time(22), "time_to": time(6)}
        self.assertEqual(self.failed(timezone="Europe/Kyiv", **night), [])
        self.assertEqual(self.failed(**night), ["time_window"])

    def test_weekday_and_date_window(self):
        self.assertEqual(self.failed(weekdays=[2]), [])
        self.assertEqual(self.failed(weekdays=[5, 6]), ["weekday"])
        self.assertEqual(
            self.failed(
                active_until=datetime(
                    2026,
                    10,
                    1,
                    tzinfo=ZoneInfo("UTC"),
                )
            ),
            ["date_window"],
        )

    def test_energy_rules(self):
        self.assertEqual(
            self.failed(
                min_solar_w=4000,
                battery_floor_pct=90,
            ),
            ["min_solar_w", "battery_floor_pct"],
        )
        importing = self.energy.model_copy(update={"grid_power_w": 300})
        policy = Policy(name="p", max_grid_import_w=0)
        self.assertEqual(
            find_failed_rules(
                policy,
                importing,
                self.now,
            ),
            ["max_grid_import_w"],
        )
