from django import forms

from src.director_app.rules import catalog


class RuleCombinationWidget(forms.Textarea):
    """Rule builder over the raw JSON textarea, which stays the value."""

    template_name = "director_app/widgets/rule_combination.html"

    class Media:
        css = {"all": ["director_app/rule_builder.css"]}
        js = ["director_app/rule_builder.js"]

    def get_context(self, name, value, attrs):
        context = super().get_context(
            name,
            value,
            attrs,
        )
        widget = context["widget"]
        widget["catalog"] = catalog()
        widget["catalog_id"] = f"{widget['attrs']['id']}_catalog"
        return context
