"""System › Runtime in the admin: the versions, the settings (secrets masked)
and the migrations applied. Superusers only.

A plain view hooked into admin.site, not an admin model: there is no
model to register, and this way it shows up in the admin's home and
sidebar without overriding their templates.
"""

import platform
import sys
from urllib.parse import quote

import django
from django.conf import settings
from django.contrib import admin
from django.db import connection
from django.db.migrations.recorder import MigrationRecorder
from django.http import Http404
from django.shortcuts import render
from django.urls import path, reverse

# How much of each setting to show.
FULL = "full"  # as it is: nothing secret
FLAG = "flag"  # "(set, N chars)" or "(not set)": a secret

# The settings shown, a fixed list: a setting added later stays hidden
# until someone decides how much of it can be seen.
SECTIONS: list[tuple[str, list[tuple[str, str]]]] = [
    (
        "Django",
        [
            ("DEBUG", FULL),
            ("ALLOWED_HOSTS", FULL),
            ("CSRF_TRUSTED_ORIGINS", FULL),
            ("TIME_ZONE", FULL),
            ("LANGUAGE_CODE", FULL),
            ("USE_TZ", FULL),
            ("STATIC_URL", FULL),
            ("DJANGO_ADMIN_PATH", FULL),
            ("SECRET_KEY", FLAG),
        ],
    ),
    ("API", [("API_TITLE", FULL)]),
    (
        "Auth",
        [
            ("AUTH_PASSWORD", FULL),
            ("AUTH_GOOGLE_CLIENT_ID", FULL),
            ("AUTH_GOOGLE_CLIENT_SECRET", FLAG),
            ("AUTH_MICROSOFT_CLIENT_ID", FULL),
            ("AUTH_MICROSOFT_CLIENT_SECRET", FLAG),
            ("AUTH_MOCK_URL", FULL),
        ],
    ),
    ("Logging", [("LOG_LEVEL", FULL)]),
]


def show(value, level: str) -> str:
    if value is None:
        return "(not set)"
    if isinstance(value, list | tuple):
        return ", ".join(str(v) for v in value) if value else "(empty)"
    text = str(value)
    if not text:
        return "(not set)"
    if level == FULL:
        return text
    return f"(set, {len(text)} chars)"


def setting(name: str, level: str) -> str:
    return show(getattr(settings, name, None), level)


def database() -> list[tuple[str, str]]:
    """The default database as a URL, without the password."""
    db = settings.DATABASES["default"]
    vendor = connection.vendor
    if vendor == "sqlite":
        url = f"sqlite:///{db['NAME']}"
    else:
        user = quote(str(db.get("USER") or ""))
        auth = f"{user}:****@" if db.get("PASSWORD") else (f"{user}@" if user else "")
        port = f":{db['PORT']}" if db.get("PORT") else ""
        url = f"{vendor}://{auth}{db.get('HOST') or ''}{port}/{db['NAME']}"
    return [
        ("DATABASE_URL", url),
        ("CONN_MAX_AGE", show(db.get("CONN_MAX_AGE"), FULL)),
    ]


def versions() -> list[tuple[str, str]]:
    return [
        ("Django", django.get_version()),
        ("Python", platform.python_version()),
        (
            "Implementation",
            f"{platform.python_implementation()} {sys.version.split()[0]}",
        ),
    ]


def runtime_view(request):
    if not request.user.is_superuser:
        raise Http404
    sections = [
        (title, [(name, setting(name, level)) for name, level in rows])
        for title, rows in SECTIONS
    ]
    sections.insert(1, ("Database", database()))
    migrations = MigrationRecorder.Migration.objects.order_by("-applied", "app", "name")
    return render(
        request,
        "runtime/runtime.html",
        {
            **admin.site.each_context(request),
            "title": "Runtime",
            "versions": versions(),
            "sections": sections,
            "migrations": migrations,
        },
    )


def install():
    """Adds the page to admin.site's URLs, and System › Runtime to its app
    list (the home page and the sidebar), for superusers."""
    site = admin.site
    get_urls = site.get_urls
    get_app_list = site.get_app_list

    def urls():
        view = site.admin_view(runtime_view)
        return [path("runtime/", view, name="runtime"), *get_urls()]

    def app_list(request, app_label=None):
        apps = get_app_list(request, app_label)
        if not request.user.is_superuser or app_label not in (None, "system"):
            return apps
        runtime = {
            "name": "Runtime",
            "object_name": "Runtime",
            "perms": {"add": False, "change": False, "delete": False, "view": True},
            "admin_url": reverse("admin:runtime"),
            "add_url": None,
            "view_only": True,
        }
        # Inside another group if the settings say so (ADMIN_APP_GROUPS["system"]),
        # else a group of its own.
        group = settings.ADMIN_APP_GROUPS.get("system")
        target = next((app for app in apps if app["app_label"] == group), None)
        if target is not None:
            target["models"] = sorted(
                [*target["models"], runtime], key=lambda model: model["name"]
            )
            return apps
        system = {
            "name": "System",
            "app_label": "system",
            "app_url": "",
            "has_module_perms": True,
            "models": [runtime],
        }
        return [*apps, system]

    site.get_urls = urls
    site.get_app_list = app_list
