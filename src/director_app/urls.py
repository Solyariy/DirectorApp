from django.urls import path

from src.director_app.views import (
    AppEvaluateView,
    JobDetailView,
    JobListView,
    PolicyAppsView,
    PolicyDetailView,
    PolicyListView,
    RegisteredAppDetailView,
    RegisteredAppListView,
    RuleDetailView,
    RuleListView,
    RuleUnlinkView,
)

urlpatterns = [
    path("apps/", RegisteredAppListView.as_view()),
    path("apps/<int:app_id>/", RegisteredAppDetailView.as_view()),
    path("apps/<int:app_id>/evaluate/", AppEvaluateView.as_view()),
    path("rules/", RuleListView.as_view()),
    path("rules/<int:rule_id>/", RuleDetailView.as_view()),
    path("rules/<int:rule_id>/unlink/", RuleUnlinkView.as_view()),
    path("policies/", PolicyListView.as_view()),
    path("policies/<int:policy_id>/", PolicyDetailView.as_view()),
    path("policies/<int:policy_id>/apps/", PolicyAppsView.as_view()),
    path("jobs/", JobListView.as_view()),
    path("jobs/<int:job_id>/", JobDetailView.as_view()),
]
