from django.urls import path
from rest_framework.authtoken.views import obtain_auth_token

from src.accounts_app.views import (
    LogoutView,
    RegisterView,
    UserDetailView,
    UserListView,
)

urlpatterns = [
    path("auth/register/", RegisterView.as_view()),
    path("auth/token/", obtain_auth_token),
    path("auth/logout/", LogoutView.as_view()),
    path("users/", UserListView.as_view()),
    path("users/<int:user_id>/", UserDetailView.as_view()),
]
