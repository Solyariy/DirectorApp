from django.contrib.auth.models import User
from rest_framework.authtoken.models import Token
from rest_framework.test import APIClient


def operator_client(username="operator", admin=True) -> APIClient:
    """APIClient sending a real token, like the frontend does.

    `admin=True` makes a staff user (role `admin`), else role `user`.
    """
    user = User.objects.create_user(
        username=username,
        password="secret",
        is_staff=admin,
    )
    token = Token.objects.create(user=user)
    client = APIClient()
    client.credentials(HTTP_AUTHORIZATION=f"Token {token.key}")
    return client
