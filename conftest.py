import pytest
from rest_framework.test import APIClient

from src.director_app.models import Policy, PolicyRuleRelation, Rule
from src.utils.testing import operator_client

SUNNY = {"ge": [{"field": "solar_power_w"}, 1500]}


@pytest.fixture
def anon_api():
    return APIClient()


@pytest.fixture
def admin_api(db):
    return operator_client("admin", admin=True)


@pytest.fixture
def user_api(db):
    return operator_client("viewer", admin=False)


@pytest.fixture
def rule(db):
    return Rule.objects.create(name="Sunny", combination=SUNNY)


@pytest.fixture
def linked_rule(rule):
    policy = Policy.objects.create(name="Sunny weekdays")
    PolicyRuleRelation.objects.create(policy=policy, rule=rule)
    return rule
