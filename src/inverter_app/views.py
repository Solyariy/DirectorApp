from dataclasses import asdict

from django.utils import timezone
from django.utils.dateparse import parse_datetime
from pysolarmanv5 import NoSocketAvailableError, V5FrameError
from rest_framework import pagination, status, views
from rest_framework.exceptions import ValidationError
from rest_framework.response import Response

from src.inverter_app.inverter_service.provider import (
    get_inverter_manager,
)
from src.inverter_app.models import EnergySnapshot
from src.inverter_app.serializers import EnergySnapshotSerializer


class SnapshotPagination(pagination.PageNumberPagination):
    page_size = 20
    page_size_query_param = "page_size"
    max_page_size = 100


class EnergySnapshotListView(views.APIView):
    def get(self, request):
        queryset = self._filter_by_time_range(
            EnergySnapshot.objects.order_by("-timestamp"),
            request.query_params,
        )
        paginator = SnapshotPagination()
        page = paginator.paginate_queryset(queryset, request, view=self)
        serializer = EnergySnapshotSerializer(page, many=True)
        return paginator.get_paginated_response(serializer.data)

    def post(self, request):
        serializer = EnergySnapshotSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response(serializer.data, status=status.HTTP_201_CREATED)

    @staticmethod
    def _filter_by_time_range(queryset, params):
        lookups = {"from": "timestamp__gte", "to": "timestamp__lte"}
        for param, lookup in lookups.items():
            raw = params.get(param)
            if raw is None:
                continue
            value = parse_datetime(raw)
            if value is None:
                raise ValidationError(
                    {param: ["Enter a valid ISO 8601 datetime."]}
                )
            queryset = queryset.filter(**{lookup: value})
        return queryset


class EnergyCurrentView(views.APIView):
    def get(self, request):
        try:
            with get_inverter_manager() as inverter:
                stats = inverter.read_registers()
        except (OSError, V5FrameError, NoSocketAvailableError):
            return Response(
                {"detail": "Inverter is unreachable."},
                status=status.HTTP_503_SERVICE_UNAVAILABLE,
            )
        snapshot: EnergySnapshot = EnergySnapshot.objects.create(
            timestamp=timezone.now(), **asdict(stats)
        )
        surplus_w = snapshot.solar_power_w - snapshot.load_power_w
        data = EnergySnapshotSerializer(snapshot).data
        data["surplus_w"] = surplus_w
        data["has_surplus"] = surplus_w > 0
        return Response(data)
