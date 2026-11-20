from django.core.checks import Warning, register

from . import log


@register()
def undecided_models(app_configs, **kwargs):
    """Nothing is audited unless a model says so, so one that nobody decided
    about would go unlogged without anyone noticing: warn until it does."""
    return [
        Warning(
            f"{model._meta.label} is not in the audit log.",
            hint=(
                "Add a nested `class Audit` to the model, or an entry in "
                "settings.AUDIT_MODELS if you can't edit it. `skip = True` "
                "there says it should not be audited."
            ),
            obj=model,
            id="audit.W001",
        )
        for model in log.undecided()
    ]
