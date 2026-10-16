from rest_framework import serializers
from src.inverter_app.models import EnergySnapshot


class EnergySnapshotSerializer(serializers.ModelSerializer):
    class Meta:
        model = EnergySnapshot
        fields = "__all__"
