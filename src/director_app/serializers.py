from django.db import transaction
from rest_framework import serializers

from src.director_app.models import (
    Job,
    Policy,
    PolicyRuleRelation,
    RegisteredApp,
    Rule,
    validate_http_url,
)


class RuleSerializer(serializers.ModelSerializer):
    class Meta:
        model = Rule
        fields = [
            "id",
            "name",
            "description",
            "combination",
            "is_active",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["id", "created_at", "updated_at"]


class RuleBriefSerializer(serializers.ModelSerializer):
    class Meta:
        model = Rule
        fields = ["id", "name", "is_active"]


class PolicyRuleSerializer(serializers.ModelSerializer):
    # Written as a rule id, read as a brief rule.
    rule = serializers.PrimaryKeyRelatedField(queryset=Rule.objects.all())
    effective = serializers.BooleanField(read_only=True)

    class Meta:
        model = PolicyRuleRelation
        fields = ["rule", "is_active", "effective"]

    def validate(self, attrs):
        # A partial policy update must not make link fields optional.
        if "rule" not in attrs:
            raise serializers.ValidationError(
                {"rule": ["This field is required."]}
            )
        attrs.setdefault("is_active", True)
        return attrs

    def to_representation(self, instance):
        data = super().to_representation(instance)
        data["rule"] = RuleBriefSerializer(instance.rule).data
        return data


class PolicySerializer(serializers.ModelSerializer):
    apps_count = serializers.IntegerField(read_only=True)
    # When sent, the list replaces the policy's rule links.
    rules = PolicyRuleSerializer(
        source="rule_relations",
        many=True,
        required=False,
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

    def validate_rules(self, links):
        rules = [link["rule"] for link in links]
        if len(set(rules)) != len(rules):
            raise serializers.ValidationError(
                "A rule can be linked to a policy only once."
            )
        return links

    def create(self, validated_data):
        links = validated_data.pop("rule_relations", [])
        with transaction.atomic():
            policy = super().create(validated_data)
            self._set_rules(policy, links)
        return policy

    def update(self, instance, validated_data):
        links = validated_data.pop("rule_relations", None)
        with transaction.atomic():
            policy = super().update(instance, validated_data)
            if links is not None:
                self._set_rules(policy, links)
        return policy

    @staticmethod
    def _set_rules(policy, links):
        # Links that stay are updated in place and keep their created_at.
        policy.rule_relations.exclude(
            rule__in=[link["rule"] for link in links],
        ).delete()
        for link in links:
            PolicyRuleRelation.objects.update_or_create(
                policy=policy,
                rule=link["rule"],
                defaults={"is_active": link["is_active"]},
            )


class RegisteredAppSerializer(serializers.ModelSerializer):
    class Meta:
        model = RegisteredApp
        fields = [
            "id",
            "name",
            "description",
            "policy",
            "created_at",
        ]
        read_only_fields = ["id", "created_at"]


class AppBriefSerializer(serializers.ModelSerializer):
    class Meta:
        model = RegisteredApp
        fields = ["id", "name"]


class JobSerializer(serializers.ModelSerializer):
    # Declared because DRF drops a model URLField's URL validators.
    data = serializers.ListField(
        child=serializers.URLField(
            max_length=2048,
            validators=[validate_http_url],
        ),
        allow_empty=False,
    )

    class Meta:
        model = Job
        fields = [
            "id",
            "app",
            "model",
            "data",
            "prompt",
            "status",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["id", "created_at", "updated_at"]
