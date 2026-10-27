from django.utils.dateparse import parse_datetime
from rest_framework import pagination, status, views
from rest_framework.exceptions import ValidationError
from rest_framework.response import Response

from src.inverter_app.models import EnergySnapshot
from src.inverter_app.scripts import read_latest_energy_and_save
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
        page = paginator.paginate_queryset(
            queryset,
            request,
            view=self,
        )
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
            snapshot = read_latest_energy_and_save()
        except ConnectionError as e:
            return Response(
                {"detail": str(e)},
                status=status.HTTP_503_SERVICE_UNAVAILABLE,
            )
        data = EnergySnapshotSerializer(snapshot).data
        return Response(data)
