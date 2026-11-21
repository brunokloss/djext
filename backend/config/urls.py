"""
URL configuration for config project.

The `urlpatterns` list routes URLs to views. For more information please see:
    https://docs.djangoproject.com/en/6.1/topics/http/urls/
Examples:
Function views
    1. Add an import:  from my_app import views
    2. Add a URL to urlpatterns:  path('', views.home, name='home')
Class-based views
    1. Add an import:  from other_app.views import Home
    2. Add a URL to urlpatterns:  path('', Home.as_view(), name='home')
Including another URLconf
    1. Import the include() function: from django.urls import include, path
    2. Add a URL to urlpatterns:  path('blog/', include('blog.urls'))
"""

from django.conf import settings
from django.contrib import admin
from django.contrib.auth.decorators import login_required
from django.urls import path
from ninja import NinjaAPI

from apps.authd.api import router as authd_router
from apps.core.api import router as core_router
from apps.note.api import router as note_router
from modules.bearer.api import router as bearer_router
from modules.health.api import router as health_router
from modules.oauth.api import router as oauth_router
from modules.sentry.api import router as sentry_router
from modules.session.api import router as session_router
from modules.signup.api import router as signup_router
from modules.throttle.throttles import throttles

# /api/docs and /api/openapi.json are for logged-in users only.
api = NinjaAPI(
    title=settings.API_TITLE,
    docs_decorator=login_required,
    throttle=throttles(
        anon=settings.API_THROTTLE_ANON, user=settings.API_THROTTLE_USER
    ),
)
# Each app has one router, mounted without a prefix (see apps/authd/api.py).
api.add_router("", health_router)
api.add_router("", authd_router)
api.add_router("", core_router)
api.add_router("", note_router)
api.add_router("", session_router)
api.add_router("", oauth_router)
api.add_router("", bearer_router)
api.add_router("", sentry_router)
api.add_router("", signup_router)


urlpatterns = [
    path(f"{settings.DJANGO_ADMIN_PATH}/", admin.site.urls),
    path("api/", api.urls),
]
