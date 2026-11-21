from src.inverter_app.models import EnergySnapshot
from src.utils.serializers import UTCModelSerializer


class EnergySnapshotSerializer(UTCModelSerializer):
    class Meta:
        model = EnergySnapshot
        fields = "__all__"
