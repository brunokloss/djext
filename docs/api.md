# API

Built with Django Ninja and mounted at `/api/`. See the endpoints at http://localhost:3000/api/docs (OpenAPI schema at `/api/openapi.json`). Both require login and redirect to the frontend's `/login`, so open them through the frontend.

Each app has one router in its `api.py`, mounted without a prefix, with the full path in every decorator (`@router.get("/users/me")`), so searching for a URL finds its code. When it grows, `api.py` becomes a package with one file per path, like `apps/authd/api/` (`auth.py`, `users.py`), whose `__init__.py` joins them into the app's router.

Every endpoint must have typed input and output. `apps/core/tests/test_api_contract.py` fails when an endpoint:

- has a response without a schema (declare `response=...`),
- is a POST/PUT/PATCH without a typed body (take a `Schema`, `Form` or `File` argument),
- has a parameter without a type annotation, including `request: HttpRequest`.

Untyped parts would become `unknown`, or be missing, in the generated frontend types.

To make a POST safe to retry, see [`modules/idempotency`](../backend/modules/idempotency/README.md).

## Typed API client

The frontend talks to the API through a typed client generated from the OpenAPI schema, so a backend change that breaks the frontend fails at compile time.

```
backend (Ninja) ──export──> frontend/lib/api/openapi.json (not committed) ──openapi-typescript──> frontend/lib/api/schema.ts
```

- After changing the API, run `make api-types` and commit both generated files. CI fails if they are out of date.
- Use the client from `frontend/lib/api/client.ts` (built on [openapi-fetch](https://openapi-ts.dev/openapi-fetch/)):

  ```ts
  import { api } from "@/lib/api/client";

  const { data, error } = await api.GET("/api/health");
  // data is typed as { status: "ok"; time: string }
  ```

- **On the server** (Server Components) it calls Django directly at `BACKEND_URL`.
- **In the browser** it uses relative URLs, so requests go through the Next proxy (same origin, so cookies and CSRF just work).
- **In Client Components**, read data with `useApi` from `lib/api/hooks.ts` ([swr-openapi](https://openapi-ts.dev/swr-openapi/)), typed the same way: `const { data, error, isLoading } = useApi("/api/users/me")`.
- **The SWR cache** lives as long as the tab. Login and logout empty it (`useClearApiCache`), so a new user never sees the last one's data.

Browser POST/PUT/PATCH/DELETE requests get Django's CSRF token added by the client (`lib/api/csrf.ts`).
