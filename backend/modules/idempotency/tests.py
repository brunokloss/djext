from datetime import timedelta
from io import StringIO

from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.core.management import call_command
from django.test import TestCase, override_settings
from django.urls import path
from django.utils import timezone
from ninja import File, Form, NinjaAPI, Schema, UploadedFile
from ninja.errors import HttpError
from ninja.security import django_auth

from .decorators import HEADER, REPLAYED_HEADER, STALE_AFTER, idempotent
from .models import IdempotencyKey

User = get_user_model()

# A test API: one endpoint per behavior, each counting how often it really ran.
api = NinjaAPI(urls_namespace="idempotency-test", auth=django_auth)
runs: list[str] = []


class ThingIn(Schema):
    name: str


@api.post("/things", response={201: dict})
@idempotent
def create_thing(request, data: ThingIn):
    runs.append(data.name)
    return 201, {"name": data.name, "run": len(runs)}


@api.post("/required", response={201: dict})
@idempotent(required=True)
def required(request):
    runs.append("required")
    return 201, {}


@api.post("/teapot")
@idempotent
def teapot(request):
    runs.append("teapot")
    raise HttpError(418, "no coffee")


@api.post("/broken", response={503: dict})
@idempotent
def broken(request):
    runs.append("broken")
    return 503, {"detail": "down"}


@api.post("/upload", response={201: dict})
@idempotent
def upload(request, name: Form[str], file: File[UploadedFile]):
    runs.append(name)
    return 201, {"size": file.size}


@api.post("/crash")
@idempotent
def crash(request):
    runs.append("crash")
    raise RuntimeError("boom")


@api.post("/anonymous", auth=None, response={201: dict})
@idempotent
def anonymous(request):
    runs.append("anonymous")
    return 201, {}


urlpatterns = [path("api/", api.urls)]


@override_settings(ROOT_URLCONF=__name__)
class IdempotentTest(TestCase):
    def setUp(self):
        runs.clear()
        self.ana = User.objects.create_user(email="ana@example.com", password="x")
        self.client.force_login(self.ana)

    def post(self, url, body=None, key="k-1", **headers):
        if key is not None:
            headers[HEADER] = key
        return self.client.post(
            url, body or {}, content_type="application/json", headers=headers
        )

    def test_a_retry_gets_the_first_response_without_running_again(self):
        first = self.post("/api/things", {"name": "a"})
        again = self.post("/api/things", {"name": "a"})

        self.assertEqual(first.status_code, 201)
        self.assertEqual(again.status_code, 201)
        self.assertEqual(again.json(), first.json())
        self.assertEqual(again[REPLAYED_HEADER], "true")
        self.assertNotIn(REPLAYED_HEADER, first)
        self.assertEqual(runs, ["a"])

    def test_the_structured_header_form_is_the_same_key(self):
        self.post("/api/things", {"name": "a"}, key="k-1")
        again = self.post("/api/things", {"name": "a"}, key='"k-1"')
        self.assertEqual(again[REPLAYED_HEADER], "true")
        self.assertEqual(runs, ["a"])

    def test_without_a_key_it_runs_every_time(self):
        self.post("/api/things", {"name": "a"}, key=None)
        self.post("/api/things", {"name": "a"}, key=None)
        self.assertEqual(runs, ["a", "a"])
        self.assertFalse(IdempotencyKey.objects.exists())

    def test_other_keys_run(self):
        self.post("/api/things", {"name": "a"}, key="k-1")
        self.post("/api/things", {"name": "a"}, key="k-2")
        self.assertEqual(runs, ["a", "a"])

    def test_same_key_other_body_is_422(self):
        self.post("/api/things", {"name": "a"})
        response = self.post("/api/things", {"name": "b"})
        self.assertEqual(response.status_code, 422)
        self.assertEqual(runs, ["a"])

    def test_same_key_other_path_is_422(self):
        self.post("/api/things", {"name": "a"})
        response = self.post("/api/required")
        self.assertEqual(response.status_code, 422)
        self.assertEqual(runs, ["a"])

    def test_keys_belong_to_their_user(self):
        self.post("/api/things", {"name": "a"})
        bia = User.objects.create_user(email="bia@example.com", password="x")
        self.client.force_login(bia)
        response = self.post("/api/things", {"name": "a"})
        self.assertNotIn(REPLAYED_HEADER, response)
        self.assertEqual(runs, ["a", "a"])

    def test_while_the_first_still_runs_it_is_409(self):
        self.post("/api/things", {"name": "a"})
        IdempotencyKey.objects.update(state=IdempotencyKey.State.PROCESSING)
        response = self.post("/api/things", {"name": "a"})
        self.assertEqual(response.status_code, 409)
        self.assertEqual(runs, ["a"])

    def test_a_key_left_processing_by_a_dead_request_is_taken_over(self):
        self.post("/api/things", {"name": "a"})
        IdempotencyKey.objects.update(
            state=IdempotencyKey.State.PROCESSING,
            updated_at=timezone.now() - STALE_AFTER - timedelta(seconds=1),
        )
        response = self.post("/api/things", {"name": "a"})
        self.assertEqual(response.status_code, 201)
        self.assertEqual(runs, ["a", "a"])
        self.assertEqual(IdempotencyKey.objects.get().state, IdempotencyKey.State.DONE)

    @override_settings(IDEMPOTENCY_TTL_HOURS=1)
    def test_an_expired_key_runs_again(self):
        self.post("/api/things", {"name": "a"})
        IdempotencyKey.objects.update(created_at=timezone.now() - timedelta(hours=2))
        response = self.post("/api/things", {"name": "b"})
        self.assertEqual(response.status_code, 201)
        self.assertEqual(runs, ["a", "b"])

    def test_required_without_a_key_is_400(self):
        response = self.post("/api/required", key=None)
        self.assertEqual(response.status_code, 400)
        self.assertEqual(runs, [])

    def test_a_too_long_key_is_400(self):
        response = self.post("/api/things", {"name": "a"}, key="k" * 256)
        self.assertEqual(response.status_code, 400)
        self.assertEqual(runs, [])

    def test_a_4xx_from_the_endpoint_is_stored(self):
        first = self.post("/api/teapot")
        again = self.post("/api/teapot")
        self.assertEqual(first.status_code, 418)
        self.assertEqual(again.status_code, 418)
        self.assertEqual(again.json(), first.json())
        self.assertEqual(runs, ["teapot"])

    def test_a_5xx_frees_the_key(self):
        self.post("/api/broken")
        response = self.post("/api/broken")
        self.assertEqual(response.status_code, 503)
        self.assertNotIn(REPLAYED_HEADER, response)
        self.assertEqual(runs, ["broken", "broken"])
        self.assertFalse(IdempotencyKey.objects.exists())

    def upload(self, name, content, key="k-1"):
        # A new boundary each time, like a browser retrying the form.
        return self.client.post(
            "/api/upload",
            {"name": name, "file": SimpleUploadedFile("a.txt", content)},
            headers={HEADER: key},
        )

    def test_a_multipart_retry_is_the_same_request(self):
        first = self.upload("a", b"hello")
        again = self.upload("a", b"hello")
        self.assertEqual(first.status_code, 201)
        self.assertEqual(again[REPLAYED_HEADER], "true")
        self.assertEqual(runs, ["a"])

    def test_a_multipart_with_another_file_is_422(self):
        self.upload("a", b"hello")
        self.assertEqual(self.upload("a", b"other").status_code, 422)
        self.assertEqual(self.upload("b", b"hello").status_code, 422)
        self.assertEqual(runs, ["a"])

    def test_a_crash_frees_the_key(self):
        self.client.raise_request_exception = False
        self.post("/api/crash")
        self.post("/api/crash")
        self.assertEqual(runs, ["crash", "crash"])
        self.assertFalse(IdempotencyKey.objects.exists())

    def test_a_bad_body_never_claims_the_key(self):
        response = self.post("/api/things", {"wrong": "field"})
        self.assertEqual(response.status_code, 422)
        self.assertFalse(IdempotencyKey.objects.exists())
        # Fixed, the same key goes through.
        self.assertEqual(self.post("/api/things", {"name": "a"}).status_code, 201)

    def test_anonymous_requests_ignore_the_key(self):
        self.client.logout()
        self.post("/api/anonymous")
        self.post("/api/anonymous")
        self.assertEqual(runs, ["anonymous", "anonymous"])
        self.assertFalse(IdempotencyKey.objects.exists())

    def test_the_header_is_in_the_schema(self):
        schema = api.get_openapi_schema()
        params = schema["paths"]["/api/things"]["post"]["parameters"]
        header = next(p for p in params if p["name"] == HEADER)
        self.assertEqual(header["in"], "header")
        self.assertFalse(header["required"])
        params = schema["paths"]["/api/required"]["post"]["parameters"]
        self.assertTrue(next(p for p in params if p["name"] == HEADER)["required"])


class MisuseTest(TestCase):
    def test_above_the_router_decorator_raises(self):
        other = NinjaAPI(urls_namespace="idempotency-misuse")
        with self.assertRaises(TypeError):

            @idempotent
            @other.post("/x")
            def view(request):
                return {}

    def test_an_async_view_raises(self):
        with self.assertRaises(TypeError):

            @idempotent
            async def view(request):
                return {}


class PurgeTest(TestCase):
    @override_settings(IDEMPOTENCY_TTL_HOURS=24)
    def test_deletes_only_the_expired_keys(self):
        ana = User.objects.create_user(email="ana@example.com", password="x")
        old = IdempotencyKey.objects.create(user=ana, key="old", fingerprint="x")
        new = IdempotencyKey.objects.create(user=ana, key="new", fingerprint="x")
        IdempotencyKey.objects.filter(pk=old.pk).update(
            created_at=timezone.now() - timedelta(hours=25)
        )

        call_command("idempotency_purge", stdout=StringIO())

        self.assertEqual(list(IdempotencyKey.objects.all()), [new])
