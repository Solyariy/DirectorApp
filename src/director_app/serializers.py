from functools import cache
from zoneinfo import available_timezones

from rest_framework import serializers

from src.director_app.models import AppPolicy, Policy, RegisteredApp


@cache
def _timezones() -> frozenset[str]:
    return frozenset(available_timezones())


class PolicySerializer(serializers.ModelSerializer):
    weekdays = serializers.ListField(
        child=serializers.IntegerField(min_value=0, max_value=6),
        allow_null=True,
        required=False,
    )
    time_from = serializers.TimeField(
        format="%H:%M",
        allow_null=True,
        required=False,
    )
    time_to = serializers.TimeField(
        format="%H:%M",
        allow_null=True,
        required=False,
    )
    apps_count = serializers.IntegerField(read_only=True)

    class Meta:
        model = Policy
        fields = [
            "id",
            "name",
            "description",
            "is_active",
            "active_from",
            "active_until",
            "weekdays",
            "time_from",
            "time_to",
            "timezone",
            "min_solar_w",
            "battery_floor_pct",
            "max_grid_import_w",
            "max_concurrent_jobs",
            "apps_count",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["id", "created_at", "updated_at"]

    def validate_weekdays(self, value):
        if value is None:
            return None
        if not value:
            raise serializers.ValidationError(
                "Select at least one weekday or use null for every day."
            )
        return sorted(set(value))

    def validate_timezone(self, value):
        if value not in _timezones():
            raise serializers.ValidationError("Unknown time zone.")
        return value

    def validate(self, attrs):
        def current(field):
            if field in attrs:
                return attrs[field]
            return getattr(
                self.instance,
                field,
                None,
            )

        active_from = current("active_from")
        active_until = current("active_until")
        if active_from and active_until and active_until <= active_from:
            raise serializers.ValidationError(
                {"active_until": ["Must be after active_from."]}
            )
        time_from, time_to = current("time_from"), current("time_to")
        if (time_from is None) != (time_to is None):
            raise serializers.ValidationError(
                {"time_to": ["Set time_from and time_to together."]}
            )
        if time_from is not None and time_from == time_to:
            raise serializers.ValidationError(
                {"time_to": ["Must differ from time_from."]}
            )
        return attrs


class RegisteredAppSerializer(serializers.ModelSerializer):
    active_policies_count = serializers.IntegerField(read_only=True)

    class Meta:
        model = RegisteredApp
        fields = [
            "id",
            "name",
            "description",
            "active_policies_count",
            "created_at",
            "last_seen_at",
        ]
        read_only_fields = ["id", "created_at", "last_seen_at"]


class PolicyBriefSerializer(serializers.ModelSerializer):
    class Meta:
        model = Policy
        fields = ["id", "name", "is_active"]


class AppBriefSerializer(serializers.ModelSerializer):
    class Meta:
        model = RegisteredApp
        fields = ["id", "name"]


class AppPolicySerializer(serializers.ModelSerializer):
    policy = PolicyBriefSerializer(read_only=True)
    effective = serializers.BooleanField(read_only=True)

    class Meta:
        model = AppPolicy
        fields = ["policy", "is_active", "effective", "created_at"]
        read_only_fields = ["created_at"]


class AppPolicyCreateSerializer(serializers.Serializer):
    policy = serializers.PrimaryKeyRelatedField(queryset=Policy.objects.all())
    is_active = serializers.BooleanField(default=True)


class PolicyAppSerializer(serializers.ModelSerializer):
    app = AppBriefSerializer(read_only=True)

    class Meta:
        model = AppPolicy
        fields = ["app", "is_active", "created_at"]
