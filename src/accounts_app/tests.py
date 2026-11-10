from django.contrib.auth.models import User
from django.test import TestCase
from rest_framework.authtoken.models import Token
from rest_framework.test import APIClient

from src.utils.testing import operator_client

NO_CREDENTIALS = "Authentication credentials were not provided."
FORBIDDEN = "You do not have permission to perform this action."
GOOD_PASSWORD = "solar-panel-42"


class RegisterTests(TestCase):
    def register(self, **body):
        return APIClient().post(
            "/api/auth/register/",
            {"username": "alice", "password": GOOD_PASSWORD, **body},
            format="json",
        )

    def test_register_creates_read_only_user(self):
        response = self.register()
        self.assertEqual(
            response.status_code,
            201,
            response.data,
        )
        self.assertEqual(response.json()["username"], "alice")
        self.assertEqual(response.json()["role"], "user")
        self.assertNotIn("password", response.json())
        user = User.objects.get(username="alice")
        self.assertFalse(user.is_staff)
        self.assertTrue(user.check_password(GOOD_PASSWORD))

    def test_role_in_body_is_ignored(self):
        response = self.register(role="admin", is_staff=True)
        self.assertEqual(
            response.status_code,
            201,
            response.data,
        )
        self.assertEqual(response.json()["role"], "user")
        self.assertFalse(User.objects.get(username="alice").is_staff)

    def test_weak_password(self):
        response = self.register(password="123")
        self.assertEqual(response.status_code, 400)
        self.assertIn("password", response.json())

    def test_duplicate_username(self):
        self.register()
        response = self.register()
        self.assertEqual(response.status_code, 400)
        self.assertEqual(
            response.json(),
            {"username": ["A user with that username already exists."]},
        )

    def test_stale_token_header_does_not_block(self):
        client = APIClient()
        client.credentials(HTTP_AUTHORIZATION="Token stale")
        response = client.post(
            "/api/auth/register/",
            {"username": "alice", "password": GOOD_PASSWORD},
            format="json",
        )
        self.assertEqual(response.status_code, 201)


class LoginLogoutTests(TestCase):
    def setUp(self):
        User.objects.create_user(username="operator", password="secret")

    def login(self, password="secret"):
        return APIClient().post(
            "/api/auth/token/",
            {"username": "operator", "password": password},
            format="json",
        )

    def test_login_returns_working_token(self):
        response = self.login()
        self.assertEqual(response.status_code, 200)
        client = APIClient()
        client.credentials(
            HTTP_AUTHORIZATION=f"Token {response.json()['token']}"
        )
        self.assertEqual(client.get("/api/apps/").status_code, 200)

    def test_login_token_is_stable(self):
        self.assertEqual(
            self.login().json()["token"],
            self.login().json()["token"],
        )

    def test_wrong_password(self):
        response = self.login(password="nope")
        self.assertEqual(response.status_code, 400)
        self.assertEqual(
            response.json(),
            {
                "non_field_errors": [
                    "Unable to log in with provided credentials.",
                ],
            },
        )

    def test_logout_revokes_token(self):
        token = self.login().json()["token"]
        client = APIClient()
        client.credentials(HTTP_AUTHORIZATION=f"Token {token}")
        self.assertEqual(client.post("/api/auth/logout/").status_code, 204)
        self.assertFalse(Token.objects.exists())
        response = client.get("/api/apps/")
        self.assertEqual(response.status_code, 401)
        self.assertEqual(response.json(), {"detail": "Invalid token."})
        # A new login issues a new token.
        self.assertNotEqual(self.login().json()["token"], token)

    def test_logout_needs_token(self):
        response = APIClient().post("/api/auth/logout/")
        self.assertEqual(response.status_code, 401)


class AuthRequiredTests(TestCase):
    def test_every_endpoint_requires_token(self):
        paths = [
            "/api/users/",
            "/api/users/1/",
            "/api/apps/",
            "/api/apps/1/",
            "/api/apps/1/evaluate/",
            "/api/rules/",
            "/api/rules/catalog/",
            "/api/rules/1/",
            "/api/policies/",
            "/api/policies/1/",
            "/api/policies/1/apps/",
            "/api/jobs/",
            "/api/jobs/1/",
            "/api/energy/snapshots/",
            "/api/energy/current/",
        ]
        for path in paths:
            with self.subTest(path=path):
                response = APIClient().get(path)
                self.assertEqual(response.status_code, 401)
                self.assertEqual(response["WWW-Authenticate"], "Token")
                self.assertEqual(
                    response.json(),
                    {"detail": NO_CREDENTIALS},
                )

    def test_invalid_token(self):
        client = APIClient()
        client.credentials(HTTP_AUTHORIZATION="Token wrong")
        response = client.post("/api/rules/1/unlink/")
        self.assertEqual(response.status_code, 401)
        self.assertEqual(response.json(), {"detail": "Invalid token."})


class UserRoleTests(TestCase):
    """Role `user` reads; writes and live inverter reads are admin-only."""

    def setUp(self):
        self.client = operator_client(username="reader", admin=False)

    def test_user_can_read(self):
        for path in [
            "/api/apps/",
            "/api/rules/",
            "/api/rules/catalog/",
            "/api/policies/",
            "/api/jobs/",
            "/api/energy/snapshots/",
        ]:
            with self.subTest(path=path):
                self.assertEqual(self.client.get(path).status_code, 200)

    def test_user_cannot_write(self):
        requests = [
            ("post", "/api/apps/"),
            ("put", "/api/apps/1/"),
            ("patch", "/api/apps/1/"),
            ("delete", "/api/apps/1/"),
            ("post", "/api/rules/"),
            ("post", "/api/rules/1/unlink/"),
            ("post", "/api/policies/"),
            ("delete", "/api/policies/1/"),
            ("post", "/api/jobs/"),
            ("patch", "/api/jobs/1/"),
            ("post", "/api/energy/snapshots/"),
        ]
        for method, path in requests:
            with self.subTest(method=method, path=path):
                response = getattr(self.client, method)(
                    path,
                    {},
                    format="json",
                )
                self.assertEqual(response.status_code, 403)
                self.assertEqual(response.json(), {"detail": FORBIDDEN})

    def test_user_cannot_read_inverter_live(self):
        for path in ["/api/apps/1/evaluate/", "/api/energy/current/"]:
            with self.subTest(path=path):
                self.assertEqual(self.client.get(path).status_code, 403)

    def test_user_cannot_manage_users(self):
        self.assertEqual(self.client.get("/api/users/").status_code, 403)

    def test_user_can_logout(self):
        self.assertEqual(
            self.client.post("/api/auth/logout/").status_code,
            204,
        )


class UserAdminTests(TestCase):
    def setUp(self):
        self.client = operator_client(username="boss")
        self.admin = User.objects.get(username="boss")
        self.reader = User.objects.create_user(
            username="reader",
            password="secret",
        )

    def test_list(self):
        response = self.client.get("/api/users/")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["count"], 2)
        self.assertEqual(
            response.json()["results"],
            [
                {"id": self.admin.id, "username": "boss", "role": "admin"},
                {"id": self.reader.id, "username": "reader", "role": "user"},
            ],
        )

    def test_search(self):
        response = self.client.get("/api/users/?search=read")
        self.assertEqual(response.json()["count"], 1)

    def test_get(self):
        response = self.client.get(f"/api/users/{self.reader.id}/")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["role"], "user")

    def test_get_missing(self):
        response = self.client.get("/api/users/999/")
        self.assertEqual(response.status_code, 404)

    def test_promote_and_demote(self):
        url = f"/api/users/{self.reader.id}/"
        response = self.client.patch(
            url,
            {"role": "admin"},
            format="json",
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["role"], "admin")
        self.reader.refresh_from_db()
        self.assertTrue(self.reader.is_staff)
        response = self.client.patch(
            url,
            {"role": "user"},
            format="json",
        )
        self.assertEqual(response.json()["role"], "user")
        self.reader.refresh_from_db()
        self.assertFalse(self.reader.is_staff)

    def test_username_is_read_only(self):
        response = self.client.patch(
            f"/api/users/{self.reader.id}/",
            {"username": "renamed"},
            format="json",
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["username"], "reader")

    def test_invalid_role(self):
        response = self.client.patch(
            f"/api/users/{self.reader.id}/",
            {"role": "owner"},
            format="json",
        )
        self.assertEqual(response.status_code, 400)
        self.assertEqual(
            response.json(),
            {"role": ['"owner" is not a valid choice.']},
        )

    def test_delete(self):
        response = self.client.delete(f"/api/users/{self.reader.id}/")
        self.assertEqual(response.status_code, 204)
        self.assertFalse(User.objects.filter(pk=self.reader.id).exists())

    def test_cannot_change_self(self):
        url = f"/api/users/{self.admin.id}/"
        conflict = {
            "detail": "You can't change your own role or delete yourself.",
        }
        response = self.client.patch(
            url,
            {"role": "user"},
            format="json",
        )
        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.json(), conflict)
        response = self.client.delete(url)
        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.json(), conflict)
        self.admin.refresh_from_db()
        self.assertTrue(self.admin.is_staff)

    def test_put_not_allowed(self):
        response = self.client.put(
            f"/api/users/{self.reader.id}/",
            {"role": "admin"},
            format="json",
        )
        self.assertEqual(response.status_code, 405)
