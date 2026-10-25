from django.contrib import admin
from django.db import models

from director_app.widgets import RuleCombinationWidget
from src.director_app.models import Policy, PolicyRuleRelation, Rule
from src.director_app.rules import describe


class RulePolicyInline(admin.TabularInline):
    """Policies that use the rule, on the rule page."""

    model = PolicyRuleRelation
    extra = 0
    autocomplete_fields = ["policy"]
    verbose_name = "policy"
    verbose_name_plural = "used by policies"


class PolicyRuleInline(admin.TabularInline):
    """Rules of the policy, on the policy page."""

    model = PolicyRuleRelation
    extra = 0
    autocomplete_fields = ["rule"]
    fields = ["rule", "is_active", "expression"]
    readonly_fields = ["expression"]
    verbose_name = "rule"
    verbose_name_plural = "rules"

    @admin.display(description="Expression")
    def expression(self, relation):
        return describe(relation.rule.combination) if relation.rule_id else ""


@admin.register(Rule)
class RuleAdmin(admin.ModelAdmin):
    list_display = ["name", "expression", "is_active", "updated_at"]
    list_filter = ["is_active"]
    search_fields = ["name", "description"]
    formfield_overrides = {
        models.JSONField: {"widget": RuleCombinationWidget},
    }
    inlines = [RulePolicyInline]

    @admin.display(description="Expression")
    def expression(self, rule):
        return describe(rule.combination)


@admin.register(Policy)
class PolicyAdmin(admin.ModelAdmin):
    list_display = ["name", "operator", "is_active", "updated_at"]
    list_filter = ["operator", "is_active"]
    search_fields = ["name", "description"]
    inlines = [PolicyRuleInline]
