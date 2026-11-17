from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import (
    OpenApiExample,
    OpenApiParameter,
    OpenApiResponse,
    extend_schema,
    inline_serializer,
)
from rest_framework import pagination, serializers, status, views
from rest_framework.exceptions import NotFound, ValidationError
from rest_framework.response import Response

from src.director_app.evaluation import evaluate_app
from src.director_app.models import Job, Policy, RegisteredApp, Rule
from src.director_app.rules import catalog
from src.director_app.serializers import (
    AppBriefSerializer,
    JobSerializer,
    PolicySerializer,
    RegisteredAppSerializer,
    RuleSerializer,
)
from src.inverter_app.scripts import read_latest_energy_and_save
from src.utils.logs import Logger
from src.utils.permissions import IsAdmin


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


def _policies():
    return Policy.objects.with_counts().prefetch_related(
        "rule_relations__rule"
    )


class RegisteredAppListView(OperatorAPIView):
    serializer_class = RegisteredAppSerializer

    def get(self, request):
        queryset = RegisteredApp.objects.all()
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
        app = serializer.save()
        Logger.info(
            "App created",
            app_id=app.pk,
            name=app.name,
        )
        return Response(
            serializer.data,
            status=status.HTTP_201_CREATED,
        )


class RegisteredAppDetailView(OperatorAPIView):
    serializer_class = RegisteredAppSerializer

    def get(self, request, app_id):
        app = self.get_or_404(RegisteredApp.objects, pk=app_id)
        return Response(RegisteredAppSerializer(app).data)

    def put(self, request, app_id):
        return self._update(
            request,
            app_id,
            partial=False,
        )

    def patch(self, request, app_id):
        return self._update(
            request,
            app_id,
            partial=True,
        )

    def delete(self, request, app_id):
        app = self.get_or_404(RegisteredApp.objects, pk=app_id)
        app.delete()
        Logger.info("App deleted", app_id=app_id)
        return Response(status=status.HTTP_204_NO_CONTENT)

    def _update(self, request, app_id, partial):
        app = self.get_or_404(RegisteredApp.objects, pk=app_id)
        serializer = RegisteredAppSerializer(
            app,
            data=request.data,
            partial=partial,
        )
        serializer.is_valid(raise_exception=True)
        serializer.save()
        Logger.info(
            "App updated",
            app_id=app_id,
            fields=list(request.data),
        )
        return Response(serializer.data)


class AppEvaluateView(OperatorAPIView):
    # A GET, but it reads the inverter live and stores a snapshot.
    permission_classes = [IsAdmin]

    @extend_schema(responses={200: OpenApiTypes.OBJECT, 503: None})
    def get(self, request, app_id):
        app = self.get_or_404(
            RegisteredApp.objects.select_related("policy"),
            pk=app_id,
        )
        try:
            energy = read_latest_energy_and_save()
        except ConnectionError as e:
            Logger.error(
                "Inverter unreachable",
                error=e,
                app_id=app_id,
            )
            return Response(
                {"detail": str(e)},
                status=status.HTTP_503_SERVICE_UNAVAILABLE,
            )
        evaluation = evaluate_app(app, energy)
        Logger.info(
            "App evaluated",
            app_id=app_id,
            can_run=evaluation.can_run,
        )
        return Response(evaluation.model_dump(mode="json"))


RULE_EXAMPLE = {
    "name": "Sunny",
    "description": "Solar above 1.5 kW",
    "combination": {"ge": [{"field": "solar_power_w"}, 1500]},
    "is_active": True,
}
NOT_AUTHENTICATED = OpenApiResponse(description="No or invalid token.")
FORBIDDEN = OpenApiResponse(description="Role `user` may only read.")
NOT_FOUND = OpenApiResponse(description="No rule with this id.")
INVALID = OpenApiResponse(
    description="Validation errors by field, e.g. an invalid "
    "`combination` with the node path."
)


@extend_schema(tags=["rules"])
class RuleListView(OperatorAPIView):
    serializer_class = RuleSerializer

    @extend_schema(
        summary="List rules",
        operation_id="rules_list",
        parameters=[
            OpenApiParameter(
                "is_active",
                bool,
                description="Filter.",
            ),
            OpenApiParameter(
                "search",
                str,
                description="Name contains (case-insensitive).",
            ),
            OpenApiParameter("page", int),
            OpenApiParameter(
                "page_size",
                int,
                description="Default 20, max 100.",
            ),
        ],
        responses={
            200: inline_serializer(
                "PaginatedRuleList",
                fields={
                    "count": serializers.IntegerField(),
                    "next": serializers.URLField(allow_null=True),
                    "previous": serializers.URLField(allow_null=True),
                    "results": RuleSerializer(many=True),
                },
            ),
            400: OpenApiResponse(description="`is_active` is not a bool."),
            401: NOT_AUTHENTICATED,
        },
    )
    def get(self, request):
        queryset = Rule.objects.all()
        is_active = self.parse_bool(request.query_params, "is_active")
        if is_active is not None:
            queryset = queryset.filter(is_active=is_active)
        search = request.query_params.get("search")
        if search:
            queryset = queryset.filter(name__icontains=search)
        return self.paginate(
            request,
            queryset,
            RuleSerializer,
        )

    @extend_schema(
        summary="Create a rule (admin)",
        responses={
            201: RuleSerializer,
            400: INVALID,
            401: NOT_AUTHENTICATED,
            403: FORBIDDEN,
        },
        examples=[
            OpenApiExample(
                "Sunny",
                value=RULE_EXAMPLE,
                request_only=True,
            ),
            OpenApiExample(
                "Created",
                value={"id": 1, **RULE_EXAMPLE},
                response_only=True,
                status_codes=["201"],
            ),
        ],
    )
    def post(self, request):
        serializer = RuleSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        rule = serializer.save()
        Logger.info(
            "Rule created",
            rule_id=rule.pk,
            name=rule.name,
        )
        return Response(
            serializer.data,
            status=status.HTTP_201_CREATED,
        )


@extend_schema(tags=["rules"])
class RuleCatalogView(OperatorAPIView):
    @extend_schema(
        summary="Fields and operators for the rule builder",
        responses={200: OpenApiResponse(description="`rules.catalog()`")},
    )
    def get(self, request):
        return Response(catalog())


@extend_schema(tags=["rules"])
class RuleDetailView(OperatorAPIView):
    serializer_class = RuleSerializer

    @extend_schema(
        summary="Get a rule",
        responses={
            200: RuleSerializer,
            401: NOT_AUTHENTICATED,
            404: NOT_FOUND,
        },
    )
    def get(self, request, rule_id):
        rule = self.get_or_404(Rule.objects, pk=rule_id)
        return Response(RuleSerializer(rule).data)

    @extend_schema(
        summary="Replace a rule (admin)",
        responses={
            200: RuleSerializer,
            400: INVALID,
            401: NOT_AUTHENTICATED,
            403: FORBIDDEN,
            404: NOT_FOUND,
        },
    )
    def put(self, request, rule_id):
        return self._update(
            request,
            rule_id,
            partial=False,
        )

    @extend_schema(
        summary="Update some rule fields (admin)",
        responses={
            200: RuleSerializer,
            400: INVALID,
            401: NOT_AUTHENTICATED,
            403: FORBIDDEN,
            404: NOT_FOUND,
        },
    )
    def patch(self, request, rule_id):
        return self._update(
            request,
            rule_id,
            partial=True,
        )

    @extend_schema(
        summary="Delete a rule (admin)",
        responses={
            204: None,
            401: NOT_AUTHENTICATED,
            403: FORBIDDEN,
            404: NOT_FOUND,
            409: OpenApiResponse(
                description="The rule is linked to policies; "
                "POST .../unlink/ first."
            ),
        },
    )
    def delete(self, request, rule_id):
        rule = self.get_or_404(Rule.objects, pk=rule_id)
        # Dropping a rule silently would change its policies' decisions.
        if rule.policy_relations.exists():
            Logger.warning("Rule delete blocked: linked", rule_id=rule_id)
            return Response(
                {"detail": "The rule is linked to policies; unlink it first."},
                status=status.HTTP_409_CONFLICT,
            )
        rule.delete()
        Logger.info("Rule deleted", rule_id=rule_id)
        return Response(status=status.HTTP_204_NO_CONTENT)

    def _update(self, request, rule_id, partial):
        rule = self.get_or_404(Rule.objects, pk=rule_id)
        serializer = RuleSerializer(
            rule,
            data=request.data,
            partial=partial,
        )
        serializer.is_valid(raise_exception=True)
        serializer.save()
        Logger.info(
            "Rule updated",
            rule_id=rule_id,
            fields=list(request.data),
        )
        return Response(serializer.data)


@extend_schema(tags=["rules"])
class RuleUnlinkView(OperatorAPIView):
    @extend_schema(
        summary="Remove the rule from all policies (admin)",
        request=None,
        responses={
            204: None,
            401: NOT_AUTHENTICATED,
            403: FORBIDDEN,
            404: NOT_FOUND,
        },
    )
    def post(self, request, rule_id):
        rule = self.get_or_404(Rule.objects, pk=rule_id)
        removed, _ = rule.policy_relations.all().delete()
        Logger.info(
            "Rule unlinked",
            rule_id=rule_id,
            links_removed=removed,
        )
        return Response(status=status.HTTP_204_NO_CONTENT)


class PolicyListView(OperatorAPIView):
    serializer_class = PolicySerializer

    def get(self, request):
        queryset = _policies()
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
        Logger.info(
            "Policy created",
            policy_id=policy.pk,
            name=policy.name,
        )
        policy = _policies().get(pk=policy.pk)
        return Response(
            PolicySerializer(policy).data,
            status=status.HTTP_201_CREATED,
        )


class PolicyDetailView(OperatorAPIView):
    serializer_class = PolicySerializer

    def get(self, request, policy_id):
        policy = self.get_or_404(_policies(), pk=policy_id)
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
        if policy.apps.exists():
            Logger.warning(
                "Policy delete blocked: assigned to apps",
                policy_id=policy_id,
            )
            return Response(
                {
                    "detail": "The policy is assigned to apps; "
                    "move them to another policy first."
                },
                status=status.HTTP_409_CONFLICT,
            )
        policy.delete()
        Logger.info("Policy deleted", policy_id=policy_id)
        return Response(status=status.HTTP_204_NO_CONTENT)

    def _update(self, request, policy_id, partial):
        policy = self.get_or_404(_policies(), pk=policy_id)
        serializer = PolicySerializer(
            policy,
            data=request.data,
            partial=partial,
        )
        serializer.is_valid(raise_exception=True)
        policy = serializer.save()
        Logger.info(
            "Policy updated",
            policy_id=policy_id,
            fields=list(request.data),
        )
        # Reload: the prefetched rule links may have changed.
        policy = _policies().get(pk=policy.pk)
        return Response(PolicySerializer(policy).data)


class PolicyAppsView(OperatorAPIView):
    serializer_class = AppBriefSerializer

    def get(self, request, policy_id):
        policy = self.get_or_404(Policy.objects, pk=policy_id)
        return Response(AppBriefSerializer(policy.apps.all(), many=True).data)


class JobListView(OperatorAPIView):
    serializer_class = JobSerializer

    def get(self, request):
        queryset = Job.objects.all()
        job_status = request.query_params.get("status")
        if job_status is not None:
            if job_status not in Job.Status.values:
                raise ValidationError(
                    {"status": [f"Must be one of {Job.Status.values}."]}
                )
            queryset = queryset.filter(status=job_status)
        return self.paginate(
            request,
            queryset,
            JobSerializer,
        )

    def post(self, request):
        serializer = JobSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        job = serializer.save()
        Logger.info(
            "Job created",
            job_id=job.pk,
            model=job.model,
        )
        return Response(
            serializer.data,
            status=status.HTTP_201_CREATED,
        )


class JobDetailView(OperatorAPIView):
    serializer_class = JobSerializer

    def get(self, request, job_id):
        job = self.get_or_404(Job.objects, pk=job_id)
        return Response(JobSerializer(job).data)

    def put(self, request, job_id):
        return self._update(
            request,
            job_id,
            partial=False,
        )

    def patch(self, request, job_id):
        return self._update(
            request,
            job_id,
            partial=True,
        )

    def delete(self, request, job_id):
        job = self.get_or_404(Job.objects, pk=job_id)
        job.delete()
        Logger.info("Job deleted", job_id=job_id)
        return Response(status=status.HTTP_204_NO_CONTENT)

    def _update(self, request, job_id, partial):
        job = self.get_or_404(Job.objects, pk=job_id)
        serializer = JobSerializer(
            job,
            data=request.data,
            partial=partial,
        )
        serializer.is_valid(raise_exception=True)
        job = serializer.save()
        Logger.info(
            "Job updated",
            job_id=job_id,
            status=job.status,
        )
        return Response(serializer.data)
