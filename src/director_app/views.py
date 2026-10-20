from rest_framework import pagination, status, views
from rest_framework.exceptions import NotFound, ValidationError
from rest_framework.response import Response

from src.director_app.evaluation import evaluate_app
from src.director_app.models import (
    EFFECTIVE_CONNECTION,
    AppPolicy,
    Policy,
    RegisteredApp,
    generate_token,
    hash_token,
)
from src.director_app.serializers import (
    AppPolicyCreateSerializer,
    AppPolicySerializer,
    PolicyAppSerializer,
    PolicySerializer,
    RegisteredAppSerializer,
)
from src.inverter_app.scripts import read_latest_energy_and_save


class DirectorPagination(pagination.PageNumberPagination):
    page_size = 20
    page_size_query_param = "page_size"
    max_page_size = 100


class OperatorAPIView(views.APIView):
    @staticmethod
    def get_or_404(queryset, **lookup):
        obj = queryset.filter(**lookup).first()
        if obj is None:
            raise NotFound()
        return obj

    @staticmethod
    def parse_bool(params, name):
        raw = params.get(name)
        if raw is None:
            return None
        value = raw.lower()
        if value in ("true", "1"):
            return True
        if value in ("false", "0"):
            return False
        raise ValidationError({name: ["Must be true or false."]})

    def paginate(self, request, queryset, serializer_class):
        paginator = DirectorPagination()
        page = paginator.paginate_queryset(
            queryset,
            request,
            view=self,
        )
        serializer = serializer_class(page, many=True)
        return paginator.get_paginated_response(serializer.data)


def _app_with_token(app: RegisteredApp, token: str) -> dict:
    app = RegisteredApp.objects.with_counts().get(pk=app.pk)
    return {**RegisteredAppSerializer(app).data, "token": token}


class RegisteredAppListView(OperatorAPIView):
    def get(self, request):
        queryset = RegisteredApp.objects.with_counts()
        search = request.query_params.get("search")
        if search:
            queryset = queryset.filter(name__icontains=search)
        return self.paginate(
            request,
            queryset,
            RegisteredAppSerializer,
        )

    def post(self, request):
        serializer = RegisteredAppSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        token = generate_token()
        app = serializer.save(token_hash=hash_token(token))
        return Response(
            _app_with_token(app, token),
            status=status.HTTP_201_CREATED,
        )


class RegisteredAppDetailView(OperatorAPIView):
    def get(self, request, app_id):
        app = self.get_or_404(RegisteredApp.objects.with_counts(), pk=app_id)
        return Response(RegisteredAppSerializer(app).data)

    def patch(self, request, app_id):
        app = self.get_or_404(RegisteredApp.objects.with_counts(), pk=app_id)
        serializer = RegisteredAppSerializer(
            app,
            data=request.data,
            partial=True,
        )
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response(serializer.data)

    def delete(self, request, app_id):
        app = self.get_or_404(RegisteredApp.objects, pk=app_id)
        app.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)


class RotateTokenView(OperatorAPIView):
    def post(self, request, app_id):
        app = self.get_or_404(RegisteredApp.objects, pk=app_id)
        token = generate_token()
        app.token_hash = hash_token(token)
        app.save(update_fields=["token_hash"])
        return Response(_app_with_token(app, token))


class AppPolicyListView(OperatorAPIView):
    def get(self, request, app_id):
        app = self.get_or_404(RegisteredApp.objects, pk=app_id)
        queryset = app.connections.select_related("policy")
        is_active = self.parse_bool(request.query_params, "is_active")
        if is_active is not None:
            queryset = queryset.filter(is_active=is_active)
        effective = self.parse_bool(request.query_params, "effective")
        if effective is True:
            queryset = queryset.filter(EFFECTIVE_CONNECTION)
        elif effective is False:
            queryset = queryset.exclude(EFFECTIVE_CONNECTION)
        return Response(AppPolicySerializer(queryset, many=True).data)

    def post(self, request, app_id):
        app = self.get_or_404(RegisteredApp.objects, pk=app_id)
        serializer = AppPolicyCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        policy = serializer.validated_data["policy"]
        if app.connections.filter(policy=policy).exists():
            return Response(
                {"detail": "The policy is already connected to this app."},
                status=status.HTTP_409_CONFLICT,
            )
        connection = AppPolicy.objects.create(
            app=app,
            policy=policy,
            is_active=serializer.validated_data["is_active"],
        )
        return Response(
            AppPolicySerializer(connection).data,
            status=status.HTTP_201_CREATED,
        )


class AppPolicyDetailView(OperatorAPIView):
    def get_connection(self, app_id, policy_id):
        return self.get_or_404(
            AppPolicy.objects.select_related("policy"),
            app_id=app_id,
            policy_id=policy_id,
        )

    def patch(self, request, app_id, policy_id):
        connection = self.get_connection(app_id, policy_id)
        serializer = AppPolicySerializer(
            connection,
            data=request.data,
            partial=True,
        )
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response(serializer.data)

    def delete(self, request, app_id, policy_id):
        self.get_connection(app_id, policy_id).delete()
        return Response(status=status.HTTP_204_NO_CONTENT)


class AppEvaluateView(OperatorAPIView):
    def get(self, request, app_id):
        app = self.get_or_404(RegisteredApp.objects, pk=app_id)
        try:
            energy = read_latest_energy_and_save()
        except ConnectionError as e:
            return Response(
                {"detail": str(e)},
                status=status.HTTP_503_SERVICE_UNAVAILABLE,
            )
        evaluation = evaluate_app(app, energy)
        return Response(evaluation.model_dump(mode="json"))


class PolicyListView(OperatorAPIView):
    def get(self, request):
        queryset = Policy.objects.with_counts()
        is_active = self.parse_bool(request.query_params, "is_active")
        if is_active is not None:
            queryset = queryset.filter(is_active=is_active)
        search = request.query_params.get("search")
        if search:
            queryset = queryset.filter(name__icontains=search)
        return self.paginate(
            request,
            queryset,
            PolicySerializer,
        )

    def post(self, request):
        serializer = PolicySerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        policy = serializer.save()
        policy = Policy.objects.with_counts().get(pk=policy.pk)
        return Response(
            PolicySerializer(policy).data,
            status=status.HTTP_201_CREATED,
        )


class PolicyDetailView(OperatorAPIView):
    def get(self, request, policy_id):
        policy = self.get_or_404(Policy.objects.with_counts(), pk=policy_id)
        return Response(PolicySerializer(policy).data)

    def put(self, request, policy_id):
        return self._update(
            request,
            policy_id,
            partial=False,
        )

    def patch(self, request, policy_id):
        return self._update(
            request,
            policy_id,
            partial=True,
        )

    def delete(self, request, policy_id):
        policy = self.get_or_404(Policy.objects, pk=policy_id)
        if policy.connections.filter(is_active=True).exists():
            return Response(
                {
                    "detail": "The policy has active connections to apps; "
                    "deactivate or disconnect them first."
                },
                status=status.HTTP_409_CONFLICT,
            )
        policy.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)

    def _update(self, request, policy_id, partial):
        policy = self.get_or_404(Policy.objects.with_counts(), pk=policy_id)
        serializer = PolicySerializer(
            policy,
            data=request.data,
            partial=partial,
        )
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response(serializer.data)


class PolicyAppsView(OperatorAPIView):
    def get(self, request, policy_id):
        policy = self.get_or_404(Policy.objects, pk=policy_id)
        connections = policy.connections.select_related("app")
        return Response(PolicyAppSerializer(connections, many=True).data)
