from django.urls import path

from src.director_app.views import (
    AppEvaluateView,
    PolicyAppsView,
    PolicyDetailView,
    PolicyListView,
    RegisteredAppDetailView,
    RegisteredAppListView,
    RotateTokenView,
)

urlpatterns = [
    path("apps/", RegisteredAppListView.as_view()),
    path("apps/<int:app_id>/", RegisteredAppDetailView.as_view()),
    path("apps/<int:app_id>/rotate-token/", RotateTokenView.as_view()),
    path("apps/<int:app_id>/evaluate/", AppEvaluateView.as_view()),
    path("policies/", PolicyListView.as_view()),
    path("policies/<int:policy_id>/", PolicyDetailView.as_view()),
    path("policies/<int:policy_id>/apps/", PolicyAppsView.as_view()),
]
