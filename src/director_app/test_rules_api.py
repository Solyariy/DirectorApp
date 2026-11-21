import pytest

from conftest import SUNNY
from src.director_app.models import Rule

BODY = {
    "name": "Night",
    "combination": {"lt": [{"field": "local_time"}, "06:00"]},
}
MISSING = 999999


def detail(rule_id):
    return f"/api/rules/{rule_id}/"


# (method, url builder, body) for every Rules operation.
WRITES = [
    ("post", lambda _: "/api/rules/", BODY),
    ("put", detail, BODY),
    ("patch", detail, {"is_active": False}),
    ("delete", detail, None),
    ("post", lambda pk: f"/api/rules/{pk}/unlink/", None),
]
READS = [
    ("get", lambda _: "/api/rules/", None),
    ("get", detail, None),
]


def call(client, method, url, body):
    return getattr(client, method)(
        url,
        body,
        format="json",
    )


@pytest.mark.parametrize(("method", "url", "body"), READS + WRITES)
def test_anonymous_is_401(anon_api, rule, method, url, body):
    response = call(
        anon_api,
        method,
        url(rule.pk),
        body,
    )
    assert response.status_code == 401


@pytest.mark.parametrize(("method", "url", "body"), READS)
def test_user_role_can_read(user_api, rule, method, url, body):
    assert (
        call(
            user_api,
            method,
            url(rule.pk),
            body,
        ).status_code
        == 200
    )


@pytest.mark.parametrize(("method", "url", "body"), WRITES)
def test_user_role_cannot_write(user_api, rule, method, url, body):
    response = call(
        user_api,
        method,
        url(rule.pk),
        body,
    )
    assert response.status_code == 403
    assert Rule.objects.get(pk=rule.pk).combination == SUNNY


@pytest.mark.parametrize(
    ("method", "url", "body"),
    READS[1:] + WRITES[1:],
)
def test_missing_rule_is_404(admin_api, method, url, body):
    assert (
        call(
            admin_api,
            method,
            url(MISSING),
            body,
        ).status_code
        == 404
    )


def test_admin_creates_rule(admin_api):
    response = admin_api.post(
        "/api/rules/",
        BODY,
        format="json",
    )
    assert response.status_code == 201
    assert response.data["is_active"] is True
    assert Rule.objects.filter(name="Night").exists()


@pytest.mark.parametrize(
    "combination",
    [None, {"nope": []}, {"ge": [{"field": "unknown"}, 1]}],
)
def test_invalid_combination_is_400(admin_api, combination):
    body = {"name": "Bad", "combination": combination}
    response = admin_api.post(
        "/api/rules/",
        body,
        format="json",
    )
    assert response.status_code == 400
    assert "combination" in response.data


def test_linked_rule_delete_is_409_until_unlinked(admin_api, linked_rule):
    url = detail(linked_rule.pk)
    assert admin_api.delete(url).status_code == 409
    assert admin_api.post(f"{url}unlink/").status_code == 204
    assert admin_api.delete(url).status_code == 204
    assert not Rule.objects.filter(pk=linked_rule.pk).exists()


@pytest.mark.parametrize("url", ["/api/schema/", "/api/docs/", "/api/redoc/"])
def test_api_docs_are_served(anon_api, db, url):
    assert anon_api.get(url).status_code == 200
