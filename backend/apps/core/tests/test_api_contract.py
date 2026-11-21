import inspect

from django.test import SimpleTestCase

from config.urls import api

BODY_METHODS = {"post", "put", "patch"}
# Actions that take no input at all. The bearer one is modules/bearer's (a
# missing path here is harmless when that module is removed).
NO_BODY = {
    "POST /api/auth/logout",
    "POST /api/debug/error",
    "POST /api/auth/bearer-key",
    "POST /api/notes/{note_id}/email",
}


class ApiContractTest(SimpleTestCase):
    """Every endpoint must declare typed input and output.

    The frontend types are generated from this schema, so anything untyped here
    turns into `unknown` (or is missing) on the frontend.
    """

    def setUp(self):
        self.schema = api.get_openapi_schema()

    def operations(self):
        for path, item in self.schema["paths"].items():
            for method, operation in item.items():
                yield f"{method.upper()} {path}", method, operation

    def test_there_are_endpoints(self):
        self.assertTrue(list(self.operations()))

    def test_every_response_has_a_schema(self):
        for name, _, operation in self.operations():
            for code, response in operation["responses"].items():
                # No content and redirects have no body.
                if str(code) == "204" or str(code).startswith("3"):
                    continue
                with self.subTest(endpoint=name, status=code):
                    content = response.get("content", {})
                    self.assertIn(
                        "schema",
                        content.get("application/json", {}),
                        "declare response=... on the endpoint",
                    )

    def test_every_body_has_a_schema(self):
        for name, method, operation in self.operations():
            if method not in BODY_METHODS or name in NO_BODY:
                continue
            with self.subTest(endpoint=name):
                body = operation.get("requestBody", {}).get("content", {})
                self.assertTrue(
                    any("schema" in media for media in body.values()),
                    "take a Schema (or Form/File) argument for the request body",
                )

    def test_every_parameter_has_a_type(self):
        # Checked on the view functions, not the schema: Ninja silently turns an
        # unannotated parameter into a `string` query param. `_routers` is
        # private, but it is the only way to reach the view functions.
        for prefix, router in api._routers:
            for path, path_view in router.path_operations.items():
                for operation in path_view.operations:
                    func = operation.view_func
                    params = inspect.signature(func).parameters.values()
                    for param in params:
                        with self.subTest(
                            endpoint=f"{prefix}{path}", function=func.__name__
                        ):
                            self.assertIsNot(
                                param.annotation,
                                inspect.Parameter.empty,
                                f"annotate `{param.name}` with a type",
                            )
