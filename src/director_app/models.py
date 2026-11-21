from collections.abc import Iterable

from django.contrib.postgres.fields import ArrayField
from django.core.validators import MinValueValidator, URLValidator
from django.db import models

from src.director_app.rules import evaluate, validate_combination
from src.director_app.schemas import RuleContext
from src.inverter_app.schemas import EnergySnapshotSchema
from src.inverter_app.scripts import read_latest_energy_and_save
from src.utils.db import apps_table

# Job inputs are fetched over the web.
validate_http_url = URLValidator(schemes=["http", "https"])


class Rule(models.Model):
    name = models.CharField(max_length=100, unique=True)
    description = models.TextField(blank=True, default="")
    # Expression tree over RuleContext fields; grammar in rules.py.
    combination = models.JSONField(validators=[validate_combination])
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = apps_table("director_app_rule")
        ordering = ["id"]

    def __str__(self):
        return self.name

    def passed(self, energy: EnergySnapshotSchema | None = None) -> bool:
        if energy is None:
            energy = read_latest_energy_and_save()
        context = RuleContext.from_energy(energy)
        # Unknown (None) fails like False.
        return evaluate(self.combination, context) is True


class PolicyQuerySet(models.QuerySet):
    def with_counts(self):
        # Aggregation drops Meta.ordering, so order explicitly.
        return self.annotate(apps_count=models.Count("apps")).order_by("id")


class Policy(models.Model):
    class Operator(models.TextChoices):
        AND = "and"
        OR = "or"

    name = models.CharField(max_length=100, unique=True)
    description = models.TextField(blank=True, default="")
    is_active = models.BooleanField(default=True)
    # Combines the results of the policy's effective rules.
    operator = models.CharField(
        max_length=3,
        choices=Operator.choices,
        default=Operator.AND,
    )
    rules = models.ManyToManyField(
        Rule,
        through="PolicyRuleRelation",
        related_name="policies",
    )
    max_concurrent_jobs = models.PositiveIntegerField(
        null=True,
        blank=True,
        validators=[MinValueValidator(1)],
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    objects = PolicyQuerySet.as_manager()

    class Meta:
        db_table = apps_table("director_app_policy")
        ordering = ["id"]
        verbose_name_plural = "policies"

    def __str__(self):
        return self.name

    def effective_rules(self) -> models.QuerySet:
        return Rule.objects.filter(
            is_active=True,
            policy_relations__policy=self,
            policy_relations__is_active=True,
        ).order_by("id")

    def combine(self, results: Iterable[bool]) -> bool:
        results = list(results)
        # No effective rules fails closed instead of allowing any time.
        if not results:
            return False
        if self.operator == self.Operator.OR:
            return any(results)
        return all(results)

    def passed(self, energy: EnergySnapshotSchema | None = None) -> bool:
        # One reading for every rule, so they all judge the same moment.
        if energy is None:
            energy = read_latest_energy_and_save()
        context = RuleContext.from_energy(energy)
        return self.combine(
            rule.passed(context) for rule in self.effective_rules()
        )


class PolicyRuleRelation(models.Model):
    policy = models.ForeignKey(
        Policy,
        on_delete=models.CASCADE,
        related_name="rule_relations",
    )
    rule = models.ForeignKey(
        Rule,
        on_delete=models.CASCADE,
        related_name="policy_relations",
    )
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = apps_table("director_app_policyrulerelation")
        ordering = ["id"]
        constraints = [
            models.UniqueConstraint(
                fields=["policy", "rule"],
                name="unique_policy_rule",
            ),
        ]

    def __str__(self):
        return f"{self.policy} → {self.rule}"

    @property
    def effective(self) -> bool:
        return self.is_active and self.rule.is_active


class RegisteredApp(models.Model):
    name = models.CharField(max_length=100, unique=True)
    description = models.TextField(blank=True, default="")
    # One policy per app; a policy serves many apps.
    policy = models.ForeignKey(
        Policy,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="apps",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = apps_table("director_app_registeredapp")
        ordering = ["id"]

    def __str__(self):
        return self.name

    @property
    def effective_policy(self) -> Policy | None:
        policy = self.policy
        return policy if policy is not None and policy.is_active else None


class Job(models.Model):
    class Status(models.TextChoices):
        QUEUED = "queued"
        IN_PROCESS = "in-process"
        SUCCESS = "success"
        FAILED = "failed"

    # Kept when the app is unregistered, so job history stays.
    app = models.ForeignKey(
        RegisteredApp,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="jobs",
    )
    # LLM model name.
    model = models.CharField(max_length=200)
    # Public URLs of the job input.
    data = ArrayField(
        models.URLField(
            max_length=2048,
            validators=[validate_http_url],
        ),
    )
    prompt = models.TextField()
    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.QUEUED,
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = apps_table("director_app_job")
        ordering = ["id"]

    def __str__(self):
        return f"{self.model} #{self.pk}"
