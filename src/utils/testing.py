from django.contrib.auth.models import User
from rest_framework.authtoken.models import Token
from rest_framework.test import APIClient


def operator_client(username="operator") -> APIClient:
    """APIClient sending a real operator token, like the frontend does."""
    user = User.objects.create_user(username=username, password="secret")
    token = Token.objects.create(user=user)
    client = APIClient()
    client.credentials(HTTP_AUTHORIZATION=f"Token {token.key}")
    return client
