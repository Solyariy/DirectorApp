import hashlib
import secrets

from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models

TOKEN_PREFIX = "tdk_"

EFFECTIVE_CONNECTION = models.Q(is_active=True, policy__is_active=True)


def generate_token() -> str:
    return TOKEN_PREFIX + secrets.token_hex(16)


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


class PolicyQuerySet(models.QuerySet):
    def with_counts(self):
        # Aggregation drops Meta.ordering, so order explicitly.
        return self.annotate(apps_count=models.Count("connections")).order_by(
            "id"
        )


class Policy(models.Model):
    name = models.CharField(max_length=100, unique=True)
    description = models.TextField(blank=True, default="")
    is_active = models.BooleanField(default=True)
    active_from = models.DateTimeField(null=True, blank=True)
    active_until = models.DateTimeField(null=True, blank=True)
    # Allowed days, 0 = Monday ... 6 = Sunday; null = every day.
    weekdays = models.JSONField(null=True, blank=True)
    # Daily window; time_from > time_to wraps over midnight.
    time_from = models.TimeField(null=True, blank=True)
    time_to = models.TimeField(null=True, blank=True)
    timezone = models.CharField(max_length=64, default="UTC")
    min_solar_w = models.PositiveIntegerField(null=True, blank=True)
    battery_floor_pct = models.PositiveSmallIntegerField(
        null=True,
        blank=True,
        validators=[MaxValueValidator(100)],
    )
    max_grid_import_w = models.PositiveIntegerField(null=True, blank=True)
    max_concurrent_jobs = models.PositiveIntegerField(
        null=True,
        blank=True,
        validators=[MinValueValidator(1)],
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    objects = PolicyQuerySet.as_manager()

    class Meta:
        ordering = ["id"]
        verbose_name_plural = "policies"

    def __str__(self):
        return self.name


class RegisteredAppQuerySet(models.QuerySet):
    def with_counts(self):
        return self.annotate(
            active_policies_count=models.Count(
                "connections",
                filter=models.Q(
                    connections__is_active=True,
                    connections__policy__is_active=True,
                ),
            )
        ).order_by("id")


class RegisteredApp(models.Model):
    name = models.CharField(max_length=100, unique=True)
    description = models.TextField(blank=True, default="")
    # Only the hash is stored; the token is shown once on create / rotate.
    token_hash = models.CharField(
        max_length=64,
        unique=True,
        editable=False,
    )
    policies = models.ManyToManyField(
        Policy,
        through="AppPolicy",
        related_name="apps",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    last_seen_at = models.DateTimeField(null=True, blank=True)

    objects = RegisteredAppQuerySet.as_manager()

    class Meta:
        ordering = ["id"]

    def __str__(self):
        return self.name


class AppPolicyQuerySet(models.QuerySet):
    def effective(self):
        return self.filter(EFFECTIVE_CONNECTION)


class AppPolicy(models.Model):
    app = models.ForeignKey(
        RegisteredApp,
        on_delete=models.CASCADE,
        related_name="connections",
    )
    policy = models.ForeignKey(
        Policy,
        on_delete=models.CASCADE,
        related_name="connections",
    )
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    objects = AppPolicyQuerySet.as_manager()

    class Meta:
        ordering = ["id"]
        constraints = [
            models.UniqueConstraint(
                fields=["app", "policy"],
                name="unique_app_policy",
            ),
        ]

    @property
    def effective(self) -> bool:
        return self.is_active and self.policy.is_active
