from django.urls import path

from src.inverter_app.views import EnergyCurrentView, EnergySnapshotListView

urlpatterns = [
    path("snapshots/", EnergySnapshotListView.as_view()),
    path("current/", EnergyCurrentView.as_view()),
]
