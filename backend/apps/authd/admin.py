from django import forms
from django.conf import settings
from django.contrib import admin, messages
from django.contrib.admin.options import ActionLocation
from django.contrib.auth.admin import UserAdmin as DjangoUserAdmin
from django.core.exceptions import PermissionDenied
from django.http import Http404
from django.shortcuts import redirect
from django.template.defaultfilters import pluralize
from django.template.response import TemplateResponse
from django.urls import path, reverse
from django.utils.html import format_html
from django.views.decorators.http import require_POST
from phonenumber_field.modelfields import PhoneNumberField

from apps.authd.api.auth import email_login_limit
from apps.authd.models import User
from modules.bearer.admin import BearerKeyInline
from modules.bearer.keys import revoke
from modules.bearer.models import BearerKey
from modules.crypto.admin import KeysetInline
from modules.phone.widgets import IntlTelInputWidget
from modules.session.models import Session
from modules.session.sessions import end_sessions
from modules.signals.signals import action_performed
from modules.throttle.throttles import FailureLimit, hashed


class SessionInline(admin.TabularInline):
    """Where the user is logged in. Deleting one logs that session out."""

    model = Session
    fields = ("logged_in_at", "ip", "user_agent", "expire_date")
    readonly_fields = fields
    ordering = ("-logged_in_at",)
    extra = 0

    def get_queryset(self, request):
        return super().get_queryset(request).live()

    def has_add_permission(self, request, obj=None):
        return False

    def has_change_permission(self, request, obj=None):
        return False


@admin.register(User)
class UserAdmin(DjangoUserAdmin):
    # Stock add form, asking for the email instead of the username.
    add_fieldsets = (
        (
            None,
            {
                "classes": ("wide",),
                "fields": (
                    "email",
                    "phone_number",
                    "usable_password",
                    "password1",
                    "password2",
                ),
            },
        ),
    )
    search_fields = ("email", "first_name", "last_name", "phone_number")
    formfield_overrides = {PhoneNumberField: {"widget": IntlTelInputWidget}}
    # Generated, never edited (it is the public id).
    readonly_fields = (
        "username",
        "last_login",
        "date_joined",
        "updated_at",
        "login_lock",
    )
    actions = ["log_out_everywhere", "anonymize_user"]

    def get_inlines(self, request, obj):
        # A user being added has no sessions nor keys.
        return [SessionInline, BearerKeyInline, KeysetInline] if obj else []

    def get_fieldsets(self, request, obj=None):
        fieldsets = super().get_fieldsets(request, obj)
        if obj is None:
            return fieldsets
        extra = {
            # In Django's "Personal info", after the email.
            "email": ("phone_number",),
            # In Django's "Important dates", next to last_login.
            "last_login": ("updated_at", "login_lock"),
        }
        return [
            (name, {**opts, "fields": add_after(opts["fields"], extra)})
            for name, opts in fieldsets
        ]

    @admin.display(description="login lock")
    def login_lock(self, obj):
        """Failed logins counted for this email (AUTH_LOGIN_THROTTLE_EMAIL),
        and a button to lift the lock when there is one. The IP limit isn't
        shown: an IP isn't the user's, and nothing here knows theirs."""
        limit = email_login_limit()
        if limit is None:
            return "Off (AUTH_LOGIN_THROTTLE_EMAIL is empty)"
        failures, wait = limit.status(hashed(obj.email))
        counted = (
            f"{failures} failed login{pluralize(failures)} "
            f"in the last {limit.duration // 60} min"
        )
        if wait is None:
            text = f"Not locked by email ({counted})."
            if rate := settings.AUTH_LOGIN_THROTTLE_IP:
                minutes = FailureLimit("login_ip", rate).duration // 60
                text += f" A lock by IP clears by itself within {minutes} min."
            return text
        url = reverse("admin:authd_user_unlock_login", args=[obj.pk])
        # `formaction` posts the change form (with its CSRF token) to the
        # unlock view instead of saving: a form can't hold another form.
        return format_html(
            "Locked for {} more min ({}) "
            '<button type="submit" formaction="{}" class="button">Unlock</button>',
            -(-wait // 60),
            counted,
            url,
        )

    # In the list (for the selected users) and on a user's page (for them).
    @admin.action(
        description="Log out everywhere",
        permissions=["change"],
        location=[ActionLocation.CHANGE_LIST, ActionLocation.CHANGE_FORM],
    )
    def log_out_everywhere(self, request, queryset):
        """Ends every session of the selected users (they log in again; their
        password stays). Your own, but for the one you are using."""
        for user in queryset:
            count = end_sessions(request, user, keep_current=user == request.user)
            self.message_user(
                request,
                f"{user.email} was logged out of {count} session{pluralize(count)}.",
                messages.SUCCESS,
            )

    # One user at a time, from their page only. Irreversible like a delete,
    # so it asks for the delete permission.
    @admin.action(
        description="Anonymize",
        permissions=["delete"],
        location=[ActionLocation.CHANGE_FORM],
    )
    def anonymize_user(self, request, queryset):
        """Erases the user's personal data (User.anonymize()), once their
        email and the last 4 characters of their id are typed in. Not
        yourself: you would be logged out mid-way."""
        user = queryset.get()
        if user == request.user:
            self.message_user(request, "You can't anonymize yourself.", messages.ERROR)
            return None
        form = AnonymizeForm(user, request.POST if "confirm" in request.POST else None)
        if not form.is_valid():
            return TemplateResponse(
                request,
                "admin/authd/user/anonymize_confirmation.html",
                {
                    **self.admin_site.each_context(request),
                    "title": "Anonymize user",
                    "opts": self.opts,
                    "original": user,
                    "form": form,
                    "action_field": f"{ActionLocation.CHANGE_FORM.value}-action",
                },
            )
        email = user.email
        user.anonymize(request)
        self.message_user(request, f"Anonymized {email}.", messages.SUCCESS)
        return None

    def save_formset(self, request, form, formset, change):
        if formset.model not in (Session, BearerKey):
            return super().save_formset(request, form, formset, change)
        # These inlines only delete: through end_sessions and revoke, like the API.
        formset.save(commit=False)
        for deleted in formset.deleted_objects:
            if isinstance(deleted, Session):
                end_sessions(request, form.instance, public_id=deleted.public_id)
            else:
                revoke(request, form.instance)

    def get_urls(self):
        return [
            path(
                "<path:object_id>/unlock-login/",
                self.admin_site.admin_view(require_POST(self.unlock_login_view)),
                name="authd_user_unlock_login",
            ),
            *super().get_urls(),
        ]

    def unlock_login_view(self, request, object_id):
        user = self.get_object(request, object_id)
        if user is None:
            raise Http404
        if not self.has_change_permission(request, user):
            raise PermissionDenied
        if limit := email_login_limit():
            limit.clear(hashed(user.email))
        action_performed.send(
            None,
            request=request,
            name="auth.unlock_login",
            target=user,
        )
        self.message_user(request, f"{user.email} can log in again.", messages.SUCCESS)
        return redirect("admin:authd_user_change", user.pk)


class AnonymizeForm(forms.Form):
    """What the person anonymizing a user types, to show it is that one."""

    email = forms.CharField(label="Their email")
    id_end = forms.CharField(label="The last 4 characters of their id", max_length=4)

    def __init__(self, user, *args, **kwargs):
        self.user = user
        super().__init__(*args, **kwargs)

    def clean_email(self):
        email = User.objects.normalize_email(self.cleaned_data["email"])
        if email != self.user.email:
            raise forms.ValidationError("This is not their email.")
        return email

    def clean_id_end(self):
        end = self.cleaned_data["id_end"].strip().lower()
        if end != self.user.username[-4:].lower():
            raise forms.ValidationError("These are not the last 4 characters.")
        return end


def add_after(fields, extra):
    """`fields` with each `extra[field]` right after that field."""
    return tuple(name for field in fields for name in (field, *extra.get(field, ())))
