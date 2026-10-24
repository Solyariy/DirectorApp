from rest_framework import serializers

from src.director_app.models import (
    Policy,
    PolicyRuleRelation,
    RegisteredApp,
    Rule,
)


class RuleBriefSerializer(serializers.ModelSerializer):
    class Meta:
        model = Rule
        fields = ["id", "name", "is_active"]


class PolicyRuleSerializer(serializers.ModelSerializer):
    rule = RuleBriefSerializer(read_only=True)
    effective = serializers.BooleanField(read_only=True)

    class Meta:
        model = PolicyRuleRelation
        fields = ["rule", "is_active", "effective"]


class PolicySerializer(serializers.ModelSerializer):
    apps_count = serializers.IntegerField(read_only=True)
    # Rules are managed in the admin; the API only lists them.
    rules = PolicyRuleSerializer(
        source="rule_relations",
        many=True,
        read_only=True,
    )

    class Meta:
        model = Policy
        fields = [
            "id",
            "name",
            "description",
            "operator",
            "is_active",
            "max_concurrent_jobs",
            "apps_count",
            "rules",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["id", "created_at", "updated_at"]


class RegisteredAppSerializer(serializers.ModelSerializer):
    class Meta:
        model = RegisteredApp
        fields = [
            "id",
            "name",
            "description",
            "policy",
            "created_at",
            "last_seen_at",
        ]
        read_only_fields = ["id", "created_at", "last_seen_at"]


class AppBriefSerializer(serializers.ModelSerializer):
    class Meta:
        model = RegisteredApp
        fields = ["id", "name"]
