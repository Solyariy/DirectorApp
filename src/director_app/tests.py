from datetime import datetime
from unittest.mock import patch
from zoneinfo import ZoneInfo

from django.contrib.auth.models import User
from django.core.exceptions import ValidationError
from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient

from src.director_app.models import (
    Job,
    Policy,
    PolicyRuleRelation,
    RegisteredApp,
    Rule,
)
from src.director_app.rules import (
    describe,
    evaluate,
    rule_fields,
    validate_combination,
)
from src.director_app.schemas import RuleContext
from src.inverter_app.models import EnergySnapshot
from src.inverter_app.schemas import EnergySnapshotSchema

# Wednesday 2026-10-14 23:30 in Kyiv (UTC+3), the project TIME_ZONE.
ENERGY = EnergySnapshotSchema(
    id=None,
    timestamp=datetime(
        2026,
        10,
        14,
        20,
        30,
        tzinfo=ZoneInfo("UTC"),
    ),
    solar_power_w=3200,
    load_power_w=900,
    grid_power_w=0,
    battery_power_w=0,
    battery_charge_pct=82,
    battery_voltage_v=52.0,
    grid_voltage_v=230.0,
    pv1_power_w=1500,
    pv2_power_w=700,
)
SUNNY = {"ge": [{"field": "solar_power_w"}, 1500]}
VERY_SUNNY = {"ge": [{"field": "solar_power_w"}, 5000]}
REPORT_URL = "https://example.com/docs/report.pdf"
NIGHT = {
    "or": [
        {"ge": [{"field": "local_time"}, "22:00"]},
        {"lt": [{"field": "local_time"}, "06:00"]},
    ]
}


def create_rule(name, combination, **fields) -> Rule:
    return Rule.objects.create(
        name=name,
        combination=combination,
        **fields,
    )


def attach(policy_id, rule, is_active=True) -> PolicyRuleRelation:
    return PolicyRuleRelation.objects.create(
        policy_id=policy_id,
        rule=rule,
        is_active=is_active,
    )


class OperatorTestCase(TestCase):
    def setUp(self):
        self.client = APIClient()

    def create_app(self, name="doc-indexer", **fields):
        response = self.client.post(
            "/api/apps/",
            {"name": name, "description": "Nightly embeddings", **fields},
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

    def assign(self, app_id, policy_id):
        return self.client.patch(
            f"/api/apps/{app_id}/",
            {"policy": policy_id},
            format="json",
        )


class RegisteredAppTests(OperatorTestCase):
    def test_create(self):
        app = self.create_app()
        self.assertEqual(app["name"], "doc-indexer")
        self.assertIsNone(app["policy"])
        self.assertTrue(RegisteredApp.objects.filter(pk=app["id"]).exists())

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

    def test_assign_one_policy(self):
        policy = self.create_policy()
        app = self.create_app(policy=policy["id"])
        self.assertEqual(app["policy"], policy["id"])
        other = self.create_app("photo-tagger")
        response = self.assign(other["id"], policy["id"])
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["policy"], policy["id"])
        response = self.assign(other["id"], None)
        self.assertIsNone(response.data["policy"])
        response = self.assign(other["id"], 999)
        self.assertEqual(response.status_code, 400)
        self.assertIn("policy", response.data)

    def test_update_and_delete(self):
        policy = self.create_policy()
        app = self.create_app(policy=policy["id"])
        url = f"/api/apps/{app['id']}/"
        response = self.client.patch(
            url,
            {"description": "Updated"},
            format="json",
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["description"], "Updated")
        self.assertEqual(response.data["policy"], policy["id"])
        response = self.client.put(
            url,
            {"description": "Renamed"},
            format="json",
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn("name", response.data)
        self.create_app("photo-tagger")
        response = self.client.put(
            url,
            {"name": "photo-tagger", "description": "Renamed"},
            format="json",
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn("name", response.data)
        response = self.client.put(
            url,
            {"name": "wiki-indexer", "description": "Renamed", "policy": None},
            format="json",
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["name"], "wiki-indexer")
        self.assertEqual(response.data["description"], "Renamed")
        self.assertIsNone(response.data["policy"])
        self.assertEqual(response.data["created_at"], app["created_at"])
        response = self.client.delete(url)
        self.assertEqual(response.status_code, 204)
        self.assertTrue(Policy.objects.filter(pk=policy["id"]).exists())
        response = self.client.get(url)
        self.assertEqual(response.status_code, 404)
        self.assertEqual(response.data["detail"], "Not found.")
        self.assertEqual(self.client.patch(url, {}).status_code, 404)
        self.assertEqual(self.client.put(url, {}).status_code, 404)


class RuleTests(OperatorTestCase):
    def create_rule(self, name="Sunny", combination=SUNNY, **fields):
        response = self.client.post(
            "/api/rules/",
            {"name": name, "combination": combination, **fields},
            format="json",
        )
        self.assertEqual(
            response.status_code,
            201,
            response.data,
        )
        return response.data

    def test_create_rule(self):
        rule = self.create_rule(description="Solar above 1.5 kW")
        self.assertEqual(rule["combination"], SUNNY)
        self.assertEqual(rule["description"], "Solar above 1.5 kW")
        self.assertTrue(rule["is_active"])
        self.assertTrue(Rule.objects.get(pk=rule["id"]).passed(ENERGY))
        night = self.create_rule(
            "Night",
            NIGHT,
            is_active=False,
        )
        self.assertFalse(night["is_active"])
        self.assertEqual(night["description"], "")

    def test_validation_errors(self):
        self.create_rule("Taken")
        invalid = [
            ({"name": "Taken"}, "name"),
            ({"name": ""}, "name"),
            ({"combination": None}, "combination"),
            ({"combination": {"nope": []}}, "combination"),
            (
                {"combination": {"add": [{"field": "solar_power_w"}, 1]}},
                "combination",
            ),
        ]
        for fields, error_field in invalid:
            with self.subTest(fields=fields):
                response = self.client.post(
                    "/api/rules/",
                    {"name": "Bad", "combination": SUNNY, **fields},
                    format="json",
                )
                self.assertEqual(response.status_code, 400)
                self.assertIn(error_field, response.data)
        response = self.client.post(
            "/api/rules/",
            {"name": "Bad"},
            format="json",
        )
        self.assertIn("combination", response.data)
        response = self.client.post(
            "/api/rules/",
            {
                "name": "Bad",
                "combination": {
                    "and": [SUNNY, {"ge": [{"field": "nope"}, 1]}]
                },
            },
            format="json",
        )
        self.assertEqual(
            response.data["combination"],
            ["and[1].ge[0].field: unknown field 'nope'"],
        )

    def test_list_filters(self):
        self.create_rule("Sunny")
        self.create_rule(
            "Night",
            NIGHT,
            is_active=False,
        )
        response = self.client.get("/api/rules/", {"is_active": "false"})
        self.assertEqual(
            [r["name"] for r in response.data["results"]],
            ["Night"],
        )
        response = self.client.get("/api/rules/", {"search": "sun"})
        self.assertEqual(response.data["count"], 1)
        response = self.client.get("/api/rules/", {"is_active": "maybe"})
        self.assertEqual(response.status_code, 400)

    def test_get_update_and_delete(self):
        rule = self.create_rule()
        url = f"/api/rules/{rule['id']}/"
        self.assertEqual(self.client.get(url).data, rule)
        response = self.client.patch(
            url,
            {"is_active": False},
            format="json",
        )
        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.data["is_active"])
        self.assertEqual(response.data["combination"], SUNNY)
        response = self.client.put(
            url,
            {"name": "Very sunny"},
            format="json",
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn("combination", response.data)
        response = self.client.patch(
            url,
            {"combination": {"nope": []}},
            format="json",
        )
        self.assertEqual(response.status_code, 400)
        response = self.client.put(
            url,
            {"name": "Very sunny", "combination": VERY_SUNNY},
            format="json",
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["name"], "Very sunny")
        self.assertEqual(response.data["combination"], VERY_SUNNY)
        self.assertEqual(self.client.delete(url).status_code, 204)
        self.assertEqual(self.client.get(url).status_code, 404)
        self.assertEqual(self.client.patch(url, {}).status_code, 404)
        self.assertEqual(self.client.delete(url).status_code, 404)
        response = self.client.post(f"{url}unlink/")
        self.assertEqual(response.status_code, 404)

    def test_delete_blocked_while_linked_and_unlink(self):
        rule = self.create_rule()
        first = self.create_policy(rules=[{"rule": rule["id"]}])
        second = self.create_policy(
            name="Night",
            rules=[{"rule": rule["id"], "is_active": False}],
        )
        url = f"/api/rules/{rule['id']}/"
        response = self.client.delete(url)
        self.assertEqual(response.status_code, 409)
        self.assertIn("unlink", response.data["detail"])
        self.assertEqual(PolicyRuleRelation.objects.count(), 2)
        response = self.client.post(f"{url}unlink/")
        self.assertEqual(response.status_code, 204)
        for policy in (first, second):
            response = self.client.get(f"/api/policies/{policy['id']}/")
            self.assertEqual(response.data["rules"], [])
        self.assertEqual(self.client.get(url).status_code, 200)
        self.assertEqual(self.client.post(f"{url}unlink/").status_code, 204)
        self.assertEqual(self.client.delete(url).status_code, 204)
        self.assertEqual(Policy.objects.count(), 2)


class PolicyTests(OperatorTestCase):
    def test_create_policy(self):
        policy = self.create_policy(
            description="Daytime surplus only",
            operator="or",
            max_concurrent_jobs=1,
        )
        self.assertEqual(policy["operator"], "or")
        self.assertEqual(policy["rules"], [])
        self.assertEqual(policy["apps_count"], 0)
        self.assertTrue(policy["is_active"])
        self.assertEqual(self.create_policy(name="Plain")["operator"], "and")

    def test_validation_errors(self):
        self.create_policy(name="Taken")
        invalid = [
            ({"operator": "xor"}, "operator"),
            ({"max_concurrent_jobs": 0}, "max_concurrent_jobs"),
            ({"name": "Taken"}, "name"),
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

    def test_set_rules(self):
        sunny = create_rule("Sunny", SUNNY)
        night = create_rule(
            "Night",
            NIGHT,
            is_active=False,
        )
        policy = self.create_policy(
            rules=[
                {"rule": sunny.id},
                {"rule": night.id, "is_active": False},
            ],
        )
        self.assertEqual(
            policy["rules"],
            [
                {
                    "rule": {
                        "id": sunny.id,
                        "name": "Sunny",
                        "is_active": True,
                    },
                    "is_active": True,
                    "effective": True,
                },
                {
                    "rule": {
                        "id": night.id,
                        "name": "Night",
                        "is_active": False,
                    },
                    "is_active": False,
                    "effective": False,
                },
            ],
        )
        url = f"/api/policies/{policy['id']}/"
        night_link = PolicyRuleRelation.objects.get(rule=night)
        response = self.client.patch(
            url,
            {"operator": "or"},
            format="json",
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["operator"], "or")
        self.assertEqual(len(response.data["rules"]), 2)
        response = self.client.patch(
            url,
            {"rules": [{"rule": night.id}]},
            format="json",
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            [
                (r["rule"]["id"], r["is_active"])
                for r in response.data["rules"]
            ],
            [(night.id, True)],
        )
        link = PolicyRuleRelation.objects.get(rule=night)
        self.assertEqual(link.pk, night_link.pk)
        self.assertEqual(link.created_at, night_link.created_at)
        self.assertTrue(Rule.objects.filter(pk=sunny.pk).exists())
        response = self.client.put(
            url,
            {"name": "Sunny weekdays", "rules": []},
            format="json",
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["rules"], [])
        self.assertEqual(self.client.get(url).data["rules"], [])

    def test_rules_validation_errors(self):
        sunny = create_rule("Sunny", SUNNY)
        policy = self.create_policy(rules=[{"rule": sunny.id}])
        invalid = [
            [{"rule": 999}],
            [{"rule": sunny.id}, {"rule": sunny.id, "is_active": False}],
            [{"is_active": True}],
            {"rule": sunny.id},
        ]
        for rules in invalid:
            with self.subTest(rules=rules):
                response = self.client.patch(
                    f"/api/policies/{policy['id']}/",
                    {"rules": rules},
                    format="json",
                )
                self.assertEqual(response.status_code, 400)
                self.assertIn("rules", response.data)
                response = self.client.post(
                    "/api/policies/",
                    {"name": "Bad", "rules": rules},
                    format="json",
                )
                self.assertEqual(response.status_code, 400)
                self.assertIn("rules", response.data)
        self.assertEqual(
            list(PolicyRuleRelation.objects.values_list("rule", flat=True)),
            [sunny.id],
        )
        self.assertFalse(Policy.objects.filter(name="Bad").exists())

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
        response = self.client.get("/api/policies/", {"is_active": "maybe"})
        self.assertEqual(response.status_code, 400)

    def test_apps_and_delete_blocked_while_assigned(self):
        policy = self.create_policy()
        app = self.create_app(policy=policy["id"])
        url = f"/api/policies/{policy['id']}/"
        self.assertEqual(self.client.get(url).data["apps_count"], 1)
        response = self.client.get(f"{url}apps/")
        self.assertEqual(
            response.data,
            [{"id": app["id"], "name": "doc-indexer"}],
        )
        self.assertEqual(self.client.delete(url).status_code, 409)
        self.assign(app["id"], None)
        self.assertEqual(self.client.delete(url).status_code, 204)
        self.assertEqual(self.client.get(url).status_code, 404)


class JobTests(OperatorTestCase):
    def create_job(self, **fields):
        body = {
            "model": "llama3.1:8b",
            "data": [REPORT_URL],
            "prompt": "Summarize the document.",
            **fields,
        }
        response = self.client.post(
            "/api/jobs/",
            body,
            format="json",
        )
        self.assertEqual(
            response.status_code,
            201,
            response.data,
        )
        return response.data

    def test_create_job_is_queued(self):
        app = self.create_app()
        job = self.create_job(app=app["id"])
        self.assertEqual(job["app"], app["id"])
        self.assertEqual(job["model"], "llama3.1:8b")
        self.assertEqual(job["data"], [REPORT_URL])
        self.assertEqual(job["status"], Job.Status.QUEUED)
        self.assertIsNotNone(job["created_at"])
        self.assertIsNotNone(job["updated_at"])
        self.assertIsNone(self.create_job()["app"])

    def test_validation_errors(self):
        valid = {
            "model": "llama3.1:8b",
            "data": [REPORT_URL],
            "prompt": "Summarize the document.",
        }
        cases = [
            ("model", {**valid, "model": ""}),
            ("prompt", {**valid, "prompt": ""}),
            ("data", {**valid, "data": []}),
            ("data", {**valid, "data": ["not-a-url"]}),
            ("data", {**valid, "data": [REPORT_URL, "ftp://example.com/x"]}),
            ("status", {**valid, "status": "running"}),
            ("app", {**valid, "app": 999}),
        ]
        # Each required field missing.
        for field in valid:
            body = {k: v for k, v in valid.items() if k != field}
            cases.append((field, body))
        for field, body in cases:
            with self.subTest(body=body):
                response = self.client.post(
                    "/api/jobs/",
                    body,
                    format="json",
                )
                self.assertEqual(response.status_code, 400)
                self.assertIn(field, response.data)

    def test_list_status_filter_and_pagination(self):
        self.create_job()
        self.create_job(status=Job.Status.FAILED)
        self.assertEqual(self.client.get("/api/jobs/").data["count"], 2)
        response = self.client.get(
            "/api/jobs/",
            {"status": "failed"},
        )
        self.assertEqual(response.data["count"], 1)
        self.assertEqual(response.data["results"][0]["status"], "failed")
        response = self.client.get(
            "/api/jobs/",
            {"page_size": 1},
        )
        self.assertEqual(len(response.data["results"]), 1)
        self.assertIsNotNone(response.data["next"])
        response = self.client.get(
            "/api/jobs/",
            {"status": "running"},
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn("status", response.data)

    def test_get_update_and_delete(self):
        job = self.create_job()
        url = f"/api/jobs/{job['id']}/"
        self.assertEqual(self.client.get(url).data, job)
        response = self.client.patch(
            url,
            {"status": "in-process"},
            format="json",
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["status"], "in-process")
        self.assertEqual(response.data["prompt"], job["prompt"])
        response = self.client.put(
            url,
            {"model": "qwen2.5:14b", "prompt": "Translate."},
            format="json",
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn("data", response.data)
        response = self.client.put(
            url,
            {
                "model": "qwen2.5:14b",
                "data": [REPORT_URL, "http://example.com/b.txt"],
                "prompt": "Translate.",
                "status": "success",
            },
            format="json",
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["model"], "qwen2.5:14b")
        self.assertEqual(len(response.data["data"]), 2)
        self.assertEqual(self.client.delete(url).status_code, 204)
        self.assertEqual(self.client.get(url).status_code, 404)
        self.assertEqual(self.client.patch(url, {}).status_code, 404)
        self.assertEqual(self.client.delete(url).status_code, 404)

    def test_deleting_app_keeps_its_jobs(self):
        app = self.create_app()
        job = self.create_job(app=app["id"])
        self.client.delete(f"/api/apps/{app['id']}/")
        response = self.client.get(f"/api/jobs/{job['id']}/")
        self.assertEqual(response.status_code, 200)
        self.assertIsNone(response.data["app"])


class EvaluateTests(OperatorTestCase):
    def setUp(self):
        super().setUp()
        self.app = self.create_app()
        self.url = f"/api/apps/{self.app['id']}/evaluate/"

    def read_energy(self, **kwargs):
        """Patch the live inverter read with a stored snapshot."""
        if "side_effect" not in kwargs:
            snapshot = EnergySnapshot.objects.create(
                timestamp=timezone.now(),
                solar_power_w=3200,
                load_power_w=900,
                grid_power_w=0,
                battery_power_w=0,
                battery_charge_pct=82,
                battery_voltage_v=52.0,
                grid_voltage_v=230.0,
            )
            kwargs["return_value"] = EnergySnapshotSchema.model_validate(
                snapshot
            )
        reader = patch(
            "src.director_app.views.read_latest_energy_and_save",
            **kwargs,
        )
        reader.start()
        self.addCleanup(reader.stop)

    def policy_with_rules(self, operator, *rules, **fields):
        policy = self.create_policy(operator=operator, **fields)
        for rule in rules:
            attach(policy["id"], rule)
        self.assign(self.app["id"], policy["id"])
        return policy

    def test_inverter_unreachable_is_503(self):
        self.read_energy(side_effect=ConnectionError("Inverter offline"))
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.data["detail"], "Inverter offline")

    def test_and_policy_needs_every_rule(self):
        self.read_energy()
        sunny = create_rule("Sunny", SUNNY)
        very_sunny = create_rule("Very sunny", VERY_SUNNY)
        policy = self.policy_with_rules(
            "and",
            sunny,
            very_sunny,
        )
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.data["can_run"])
        self.assertEqual(response.data["energy"]["solar_power_w"], 3200)
        self.assertEqual(
            response.data["policy"],
            {
                "policy": policy["id"],
                "operator": "and",
                "passed": False,
                "rules": [
                    {"rule": sunny.id, "name": "Sunny", "passed": True},
                    {
                        "rule": very_sunny.id,
                        "name": "Very sunny",
                        "passed": False,
                    },
                ],
            },
        )

    def test_or_policy_needs_one_rule(self):
        self.read_energy()
        self.policy_with_rules(
            "or",
            create_rule("Sunny", SUNNY),
            create_rule("Very sunny", VERY_SUNNY),
        )
        response = self.client.get(self.url)
        self.assertTrue(response.data["can_run"])
        self.assertTrue(response.data["policy"]["passed"])

    def test_without_effective_policy(self):
        self.read_energy()
        response = self.client.get(self.url)
        self.assertFalse(response.data["can_run"])
        self.assertIsNone(response.data["policy"])
        self.policy_with_rules(
            "and",
            create_rule("Sunny", SUNNY),
            is_active=False,
        )
        response = self.client.get(self.url)
        self.assertFalse(response.data["can_run"])
        self.assertIsNone(response.data["policy"])


class RuleEngineTests(TestCase):
    context = RuleContext.from_energy(ENERGY)

    def test_fields_come_from_the_energy_schema(self):
        fields = rule_fields()
        schema_fields = set(EnergySnapshotSchema.model_fields) - {"id"}
        self.assertEqual(
            set(fields), schema_fields | {"weekday", "local_time"}
        )
        self.assertEqual(fields["solar_power_w"].type, "number")
        self.assertTrue(fields["pv1_voltage_v"].nullable)
        self.assertEqual(fields["timestamp"].type, "datetime")
        self.assertEqual(fields["local_time"].type, "time")

    def test_validation_errors(self):
        invalid = [
            ({"ge": [{"field": "nope"}, 1]}, "unknown field 'nope'"),
            ({"xor": [SUNNY, NIGHT]}, "unknown operator 'xor'"),
            ({"ge": [1, 2]}, "compare at least one field"),
            ({"ge": [{"field": "local_time"}, 5]}, "cannot compare time"),
            ({"ge": [{"field": "local_time"}, "25:00"]}, "invalid time"),
            ({"le": [{"field": "timestamp"}, "soon"]}, "invalid datetime"),
            ({"in": [{"field": "weekday"}, []]}, "non-empty list"),
            ({"in": [{"field": "weekday"}, ["Mon"]]}, "expected a number"),
            ({"add": [{"field": "solar_power_w"}, 1]}, "must be a condition"),
            ({"and": []}, "at least one condition"),
            ({"not": [SUNNY, NIGHT]}, "expects one condition"),
            ({"and": [SUNNY, {"field": "solar_power_w"}]}, "and[1]"),
            ({"eq": [SUNNY, 1]}, "cannot compare conditions"),
            ({"ge": [{"field": "solar_power_w"}, True]}, "ge[1]"),
            (
                {"gt": [{"add": [{"field": "local_time"}, 1]}, 1]},
                "gt[0].add[0]: expected a number",
            ),
        ]
        for combination, message in invalid:
            with self.subTest(combination=combination):
                with self.assertRaises(ValidationError) as caught:
                    validate_combination(combination)
                self.assertIn(message, caught.exception.messages[0])

    def test_schedule_and_arithmetic(self):
        combination = {
            "and": [
                {"in": [{"field": "weekday"}, [0, 1, 2, 3, 4]]},
                NIGHT,
                {
                    "gt": [
                        {
                            "add": [
                                {"field": "pv1_power_w"},
                                {"field": "pv2_power_w"},
                            ]
                        },
                        2000,
                    ]
                },
                {"le": [{"field": "timestamp"}, "2026-10-15T00:00"]},
            ]
        }
        validate_combination(combination)
        self.assertTrue(evaluate(combination, self.context))
        self.assertEqual(
            describe(combination),
            "weekday in [0, 1, 2, 3, 4] AND "
            "(local_time ≥ 22:00 OR local_time < 06:00) AND "
            "(pv1_power_w + pv2_power_w) > 2000 AND "
            "timestamp ≤ 2026-10-15T00:00",
        )

    def test_local_fields_use_project_time_zone(self):
        self.assertEqual(self.context.weekday, 2)
        self.assertEqual(self.context.local_time.hour, 23)
        self.assertTrue(evaluate(NIGHT, self.context))
        daytime = {"lt": [{"field": "local_time"}, "22:00"]}
        self.assertFalse(evaluate(daytime, self.context))
        # A naive datetime constant is local time too: 23:00 Kyiv.
        after = {"gt": [{"field": "timestamp"}, "2026-10-14T23:00"]}
        self.assertTrue(evaluate(after, self.context))

    def test_unknown_reading_fails_closed(self):
        missing = {"gt": [{"field": "pv1_voltage_v"}, 100]}
        self.assertIsNone(evaluate(missing, self.context))
        self.assertIsNone(evaluate({"not": [missing]}, self.context))
        self.assertTrue(evaluate({"or": [SUNNY, missing]}, self.context))
        self.assertFalse(
            evaluate({"and": [VERY_SUNNY, missing]}, self.context)
        )
        by_zero = {"gt": [{"div": [{"field": "solar_power_w"}, 0]}, 1]}
        self.assertIsNone(evaluate(by_zero, self.context))
        for combination in (missing, {"not": [missing]}, by_zero):
            rule = Rule(name="r", combination=combination)
            self.assertFalse(rule.passed(ENERGY))

    def test_model_validates_combination(self):
        rule = Rule(name="Broken", combination={"ge": [1, 2]})
        with self.assertRaises(ValidationError) as caught:
            rule.full_clean()
        self.assertIn("combination", caught.exception.message_dict)


class PolicyModelTests(TestCase):
    def setUp(self):
        self.policy = Policy.objects.create(name="p")
        self.sunny = create_rule("Sunny", SUNNY)
        self.very_sunny = create_rule("Very sunny", VERY_SUNNY)

    def test_operator_combines_effective_rules(self):
        attach(self.policy.id, self.sunny)
        attach(self.policy.id, self.very_sunny)
        self.assertFalse(self.policy.passed(ENERGY))
        self.policy.operator = Policy.Operator.OR
        self.assertTrue(self.policy.passed(ENERGY))

    def test_inactive_rule_or_relation_is_skipped(self):
        attach(self.policy.id, self.sunny)
        relation = attach(
            self.policy.id,
            self.very_sunny,
            is_active=False,
        )
        self.assertTrue(self.policy.passed(ENERGY))
        relation.is_active = True
        relation.save()
        self.very_sunny.is_active = False
        self.very_sunny.save()
        self.assertEqual(list(self.policy.effective_rules()), [self.sunny])
        self.assertTrue(self.policy.passed(ENERGY))

    def test_relation_of_another_policy_does_not_count(self):
        other = Policy.objects.create(name="other")
        attach(
            self.policy.id,
            self.sunny,
            is_active=False,
        )
        attach(other.id, self.sunny)
        self.assertEqual(list(self.policy.effective_rules()), [])

    def test_no_effective_rules_fails_closed(self):
        for operator in Policy.Operator:
            with self.subTest(operator=operator):
                self.policy.operator = operator
                self.assertFalse(self.policy.passed(ENERGY))

    def test_reads_energy_once_when_not_given(self):
        attach(self.policy.id, self.sunny)
        attach(self.policy.id, create_rule("Night", NIGHT))
        with patch(
            "src.director_app.models.read_latest_energy_and_save",
            return_value=ENERGY,
        ) as reader:
            self.assertTrue(self.policy.passed())
            reader.assert_called_once()
            self.assertTrue(self.sunny.passed())
            self.assertEqual(reader.call_count, 2)


class RuleAdminTests(TestCase):
    add_url = "/admin/director_app/rule/add/"

    def setUp(self):
        admin = User.objects.create_superuser(
            "admin",
            "a@example.com",
            "pw",
        )
        self.client.force_login(admin)

    def post_rule(self, combination):
        return self.client.post(
            self.add_url,
            {
                "name": "Sunny",
                "description": "",
                "combination": combination,
                "is_active": "on",
                "policy_relations-TOTAL_FORMS": "0",
                "policy_relations-INITIAL_FORMS": "0",
            },
        )

    def test_add_page_renders_builder_with_catalog(self):
        response = self.client.get(self.add_url)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'class="rule-builder"')
        self.assertContains(response, "director_app/rule_builder.js")
        for name in rule_fields():
            self.assertContains(response, f'"name": "{name}"')

    def test_save_validates_combination(self):
        response = self.post_rule('{"ge": [{"field": "nope"}, 1]}')
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "unknown field")
        self.assertFalse(Rule.objects.exists())
        response = self.post_rule('{"ge": [{"field": "solar_power_w"}, 1]}')
        self.assertEqual(response.status_code, 302)
        self.assertEqual(
            Rule.objects.get().combination,
            {
                "ge": [{"field": "solar_power_w"}, 1],
            },
        )

    def test_policy_page_shows_rule_expression(self):
        policy = Policy.objects.create(name="p")
        attach(policy.id, create_rule("Sunny", SUNNY))
        response = self.client.get(
            f"/admin/director_app/policy/{policy.id}/change/"
        )
        self.assertContains(response, "solar_power_w ≥ 1500")
