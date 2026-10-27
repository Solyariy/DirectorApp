from rest_framework import pagination, status, views
from rest_framework.exceptions import NotFound, ValidationError
from rest_framework.response import Response

from src.director_app.evaluation import evaluate_app
from src.director_app.models import Job, Policy, RegisteredApp, Rule
from src.director_app.serializers import (
    AppBriefSerializer,
    JobSerializer,
    PolicySerializer,
    RegisteredAppSerializer,
    RuleSerializer,
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


def _policies():
    return Policy.objects.with_counts().prefetch_related(
        "rule_relations__rule"
    )


class RegisteredAppListView(OperatorAPIView):
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
        serializer.save()
        return Response(
            serializer.data,
            status=status.HTTP_201_CREATED,
        )


class RegisteredAppDetailView(OperatorAPIView):
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
        return Response(serializer.data)


class AppEvaluateView(OperatorAPIView):
    def get(self, request, app_id):
        app = self.get_or_404(
            RegisteredApp.objects.select_related("policy"),
            pk=app_id,
        )
        try:
            energy = read_latest_energy_and_save()
        except ConnectionError as e:
            return Response(
                {"detail": str(e)},
                status=status.HTTP_503_SERVICE_UNAVAILABLE,
            )
        evaluation = evaluate_app(app, energy)
        return Response(evaluation.model_dump(mode="json"))


class RuleListView(OperatorAPIView):
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

    def post(self, request):
        serializer = RuleSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response(
            serializer.data,
            status=status.HTTP_201_CREATED,
        )


class RuleDetailView(OperatorAPIView):
    def get(self, request, rule_id):
        rule = self.get_or_404(Rule.objects, pk=rule_id)
        return Response(RuleSerializer(rule).data)

    def put(self, request, rule_id):
        return self._update(
            request,
            rule_id,
            partial=False,
        )

    def patch(self, request, rule_id):
        return self._update(
            request,
            rule_id,
            partial=True,
        )

    def delete(self, request, rule_id):
        rule = self.get_or_404(Rule.objects, pk=rule_id)
        # Dropping a rule silently would change its policies' decisions.
        if rule.policy_relations.exists():
            return Response(
                {"detail": "The rule is linked to policies; unlink it first."},
                status=status.HTTP_409_CONFLICT,
            )
        rule.delete()
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
        return Response(serializer.data)


class RuleUnlinkView(OperatorAPIView):
    def post(self, request, rule_id):
        rule = self.get_or_404(Rule.objects, pk=rule_id)
        rule.policy_relations.all().delete()
        return Response(status=status.HTTP_204_NO_CONTENT)


class PolicyListView(OperatorAPIView):
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
        policy = _policies().get(pk=policy.pk)
        return Response(
            PolicySerializer(policy).data,
            status=status.HTTP_201_CREATED,
        )


class PolicyDetailView(OperatorAPIView):
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
            return Response(
                {
                    "detail": "The policy is assigned to apps; "
                    "move them to another policy first."
                },
                status=status.HTTP_409_CONFLICT,
            )
        policy.delete()
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
        # Reload: the prefetched rule links may have changed.
        policy = _policies().get(pk=policy.pk)
        return Response(PolicySerializer(policy).data)


class PolicyAppsView(OperatorAPIView):
    def get(self, request, policy_id):
        policy = self.get_or_404(Policy.objects, pk=policy_id)
        return Response(AppBriefSerializer(policy.apps.all(), many=True).data)


class JobListView(OperatorAPIView):
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
        serializer.save()
        return Response(
            serializer.data,
            status=status.HTTP_201_CREATED,
        )


class JobDetailView(OperatorAPIView):
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
        return Response(status=status.HTTP_204_NO_CONTENT)

    def _update(self, request, job_id, partial):
        job = self.get_or_404(Job.objects, pk=job_id)
        serializer = JobSerializer(
            job,
            data=request.data,
            partial=partial,
        )
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response(serializer.data)
