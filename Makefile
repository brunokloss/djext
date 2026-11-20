.PHONY: help install superuser migrate makemigrations db-up db-reset db-seed sentry sentry-up storage storage-up backend frontend dev prod prod-down prod-superuser prod-reset api-types lint format test test-all test-back test-front test-e2e

help:      ## List the commands
	@grep -E '^[a-z0-9-]+:.*## ' $(MAKEFILE_LIST) | awk -F ':.*## ' '{printf "  \033[36m%-12s\033[0m %s\n", $$1, $$2}'

# The .env files are only created if missing; the backend one gets a fresh SECRET_KEY
# and development master key (CRYPTO_KMS_URI).
install:   ## Install dependencies, create the .env files, start the database and migrate
	git config core.hooksPath .githooks
	cd backend && uv sync
	@test -f backend/.env || { \
		key=$$(cd backend && uv run python -c "from django.core.management.utils import get_random_secret_key as k; print(k())"); \
		kms=$$(cd backend && uv run python manage.py crypto_fake_kms_uri 2>/dev/null); \
		awk -v key="$$key" -v kms="$$kms" '/^SECRET_KEY=/ {print "SECRET_KEY=" key; next} /^CRYPTO_KMS_URI=/ && kms {print kms; next} {print}' backend/.env.example > backend/.env; \
	}
	@$(MAKE) db-up
	cd backend && uv run python manage.py migrate
	cd frontend && npm install && npx playwright install chromium
	@test -f frontend/.env || cp frontend/.env.example frontend/.env

# Usernames are UUIDs (see apps/authd/models.py), so pass a fresh one; Django
# then asks for the email and password.
superuser: db-up ## Create an admin user (asks for email and password)
	cd backend && uv run python manage.py createsuperuser --username "$$(uv run python -c 'from uuid import uuid7; print(uuid7())')"

migrate: db-up ## Apply the pending migrations
	cd backend && uv run python manage.py migrate

makemigrations: ## Create migrations for the model changes
	cd backend && uv run python manage.py makemigrations

# The database Django uses: DATABASE_URL's, plus the folder's name in a git
# worktree (config/settings.py), so a worktree never touches the main one.
DB_NAME = cd backend && uv run python manage.py shell -v 0 -c "from django.conf import settings; print(settings.DATABASES['default']['NAME'])"

# Only when DATABASE_URL is set (in the shell or in backend/.env): without it the
# database is SQLite and there is nothing to start. With it, the Postgres in
# docker-compose.yml, waiting until it accepts connections.
db-up:     ## Start the local Postgres (Docker), if DATABASE_URL is set
	@if [ -n "$$DATABASE_URL" ] || grep -qs '^DATABASE_URL=.' backend/.env; then \
		docker compose up -d --wait db; \
		name=$$($(DB_NAME)); \
		docker compose exec -T db psql -U djext -d postgres -tAc "SELECT 1 FROM pg_database WHERE datname = '$$name'" | grep -q 1 \
			|| docker compose exec -T db psql -U djext -d postgres -c "CREATE DATABASE \"$$name\""; \
	else \
		echo "DATABASE_URL is empty: using SQLite, nothing to start."; \
	fi

# GlitchTip, a small Sentry-compatible server, in docker-compose.yml: its own
# `glitchtip` database in the local Postgres (whatever DATABASE_URL says).
sentry:    ## Start a local Sentry-compatible server (GlitchTip) at http://localhost:8002
	@docker compose up -d --wait db
	@docker compose exec -T db psql -U djext -d postgres -tAc "SELECT 1 FROM pg_database WHERE datname = 'glitchtip'" | grep -q 1 \
		|| docker compose exec -T db psql -U djext -d postgres -c 'CREATE DATABASE glitchtip'
	@docker compose --profile sentry up -d glitchtip
	@echo "GlitchTip: http://localhost:8002 (sign up, create a project per side, copy its DSN)"

# Only when a DSN (in the shell or in backend/.env or frontend/.env) points at it.
sentry-up:
	@if echo "$$SENTRY_DSN $$NEXT_PUBLIC_SENTRY_DSN" | grep -q 'localhost:8002' \
		|| grep -qs '^SENTRY_DSN=.*localhost:8002' backend/.env \
		|| grep -qs '^NEXT_PUBLIC_SENTRY_DSN=.*localhost:8002' frontend/.env; then \
		$(MAKE) --no-print-directory sentry; \
	fi

# RustFS, a small S3-compatible server, in docker-compose.yml, plus its `djext`
# bucket. backend/.env and frontend/.env point at it only when you set
# STORAGE_URL and STORAGE_BUCKET_URL (see their .env.example); `make dev` then
# starts it for you. CORS lets the site (:3000) and Django's own admin (:8000)
# upload straight to the bucket. Uploads left in
# tmp/s3file/ (a form never saved, see django-s3file) expire in a day.
storage:   ## Start a local S3-compatible server (RustFS) at http://localhost:9000 with a `djext` bucket
	@docker compose --profile storage up -d storage
	@until curl -s -o /dev/null http://localhost:9000; do sleep 0.5; done
	@cd backend && uv run python -c "import boto3; \
	s3 = boto3.client('s3', endpoint_url='http://localhost:9000', region_name='us-east-1', \
	    aws_access_key_id='djext', aws_secret_access_key='djext-secret'); \
	names = [b['Name'] for b in s3.list_buckets()['Buckets']]; \
	'djext' in names or s3.create_bucket(Bucket='djext'); \
	s3.put_bucket_cors(Bucket='djext', CORSConfiguration={'CORSRules': [{ \
	    'AllowedOrigins': ['http://localhost:3000', 'http://localhost:8000'], \
	    'AllowedMethods': ['GET', 'HEAD', 'PUT', 'POST'], \
	    'AllowedHeaders': ['*'], 'ExposeHeaders': ['ETag'], 'MaxAgeSeconds': 3000}]}); \
	s3.put_bucket_lifecycle_configuration(Bucket='djext', LifecycleConfiguration={'Rules': [{ \
	    'ID': 'expire-abandoned-uploads', 'Status': 'Enabled', \
	    'Filter': {'Prefix': 'tmp/s3file/'}, 'Expiration': {'Days': 1}}]})"
	@echo "RustFS: http://localhost:9001 (djext / djext-secret), bucket djext"

# Only when STORAGE_URL (in the shell or in backend/.env) points at it.
storage-up:
	@if echo "$$STORAGE_URL" | grep -q 'localhost:9000' || grep -qs '^STORAGE_URL=.*localhost:9000' backend/.env; then \
		$(MAKE) --no-print-directory storage; \
	fi

# Every user and row is gone. SQLite: deletes the file. Postgres (DATABASE_URL set):
# drops and recreates the database; WITH FORCE disconnects whatever is using it,
# `make dev` included.
db-reset: db-up ## Delete the local database, migrate and create the example users
	@if [ -n "$$DATABASE_URL" ] || grep -qs '^DATABASE_URL=.' backend/.env; then \
		name=$$($(DB_NAME)); \
		docker compose exec -T db psql -U djext -d postgres -c "DROP DATABASE IF EXISTS \"$$name\" WITH (FORCE)" -c "CREATE DATABASE \"$$name\""; \
	else \
		rm -f backend/db.sqlite3; \
	fi
	cd backend && uv run python manage.py migrate
	@$(MAKE) db-seed

db-seed: db-up ## Create example users (password "password", DEBUG only) and email templates
	cd backend && uv run python manage.py seed_users && uv run python manage.py seed_email_templates
	@if [ -f backend/seed_local.py ]; then cd backend && uv run python manage.py shell < seed_local.py; fi

backend: db-up ## Run Django at http://localhost:8000
	cd backend && uv run python manage.py runserver 8000

frontend:  ## Run Next.js at http://localhost:3000
	cd frontend && npm run dev

# With DEBUG off Django doesn't serve the admin's CSS/JS; granian serves this
# copy (see STATIC_ROOT). backend/Dockerfile runs it at build.
static:    ## Dump Django's static files (the admin's CSS/JS) into backend/staticfiles
	cd backend && uv run python manage.py collectstatic --noinput --clear

# The production images (backend/Dockerfile, frontend/Dockerfile) in
# docker-compose.yml, on the local Postgres in a `djext_prod` database of their
# own. Builds, migrates, then runs the web, worker, scheduler and Next until
# Ctrl+C. Same ports as `make dev`: stop it first.
prod:      ## Build the production images and run them at http://localhost:3000 (DEBUG off)
	@docker compose up -d --wait db
	@docker compose exec -T db psql -U djext -d postgres -tAc "SELECT 1 FROM pg_database WHERE datname = 'djext_prod'" | grep -q 1 \
		|| docker compose exec -T db psql -U djext -d postgres -c 'CREATE DATABASE djext_prod'
	docker compose --env-file frontend/.env --profile prod up --build --no-attach db

# Only the prod profile's containers: the Postgres (and `make dev` on it) keeps running.
prod-down: ## Stop and remove the containers of `make prod`
	docker compose --profile prod rm --stop --force migrate backend worker scheduler frontend

# In a one-off container of the backend image, so it works with `make prod`
# running or not (it needs a `make prod` once, for the image and migrations).
# The UUID username is made inside it: Python 3.14 has uuid7.
prod-superuser: ## Create an admin user in the `make prod` database (asks for email and password)
	@docker compose up -d --wait db
	docker compose --profile prod run --rm --no-deps backend python -c "import os, uuid; os.execvp('python', ['python', 'manage.py', 'createsuperuser', '--username', str(uuid.uuid7())])"

# Stops the prod containers and drops `djext_prod`; the next `make prod`
# creates it again and migrates. No example users (seed_users is DEBUG only):
# `make prod-superuser`.
prod-reset: prod-down ## Delete the `make prod` database; the next `make prod` migrates a fresh one
	@docker compose up -d --wait db
	docker compose exec -T db psql -U djext -d postgres -c 'DROP DATABASE IF EXISTS djext_prod WITH (FORCE)'

# Regenerate after changing the API. Both files are committed, and CI fails if
# they are out of date.
api-types: ## Export the OpenAPI schema and regenerate the frontend API types
	cd backend && uv run python manage.py export_openapi_schema --indent 2 --sorted --output ../frontend/lib/api/openapi.json
	cd frontend && npm run api:types

lint:      ## Lint, format-check and typecheck both sides (what CI runs)
	cd backend && uv run ruff check . && uv run ruff format --check . && uv run lint-imports
	cd frontend && npx biome ci && npm run typecheck

format:    ## Auto-fix lint issues and format both sides
	cd backend && uv run ruff check --fix . && uv run ruff format .
	cd frontend && npx biome check --write

test:      ## Run backend and frontend tests
	@$(MAKE) test-back
	@$(MAKE) test-front

test-all:  ## Run backend, frontend and end-to-end tests
	@$(MAKE) test-back
	@$(MAKE) test-front
	@$(MAKE) test-e2e

test-back: db-up ## Run backend tests (manage.py test --parallel) with coverage
	cd backend && uv run coverage run manage.py test --parallel && uv run coverage combine -q && uv run coverage report

test-front: ## Run frontend unit tests (Vitest)
	cd frontend && npm run test

# Playwright reuses `make dev` if it is running; otherwise it starts both servers.
test-e2e: db-up ## Run end-to-end tests (Playwright)
	cd frontend && npm run e2e

# Each process runs in a subshell that, when it exits (error or not), runs
# `kill 0` on the whole group: if one dies, everything dies. The trap does the
# same on Ctrl+C and disarms itself first so it doesn't re-enter. `python -u` +
# `fflush()` in awk keep the prefixed logs live (no pipe buffering).
dev: db-up sentry-up storage-up ## Run backend, frontend and, with the modules, the mock login provider and the task worker + scheduler; if one dies, all stop
	@trap 'trap - INT TERM EXIT; kill 0' INT TERM EXIT; \
	(cd backend && uv run python -u manage.py runserver 8000 2>&1 | awk '{print "\033[1;36m[BCK]\033[0m " $$0; fflush()}'; kill 0) & \
	(cd frontend && npm run dev 2>&1 | awk '{print "\033[1;32m[FRT]\033[0m " $$0; fflush()}'; kill 0) & \
	if [ -d backend/modules/oauth ]; then \
		(cd backend && uv run python -u manage.py oauth_mock 2>&1 | awk '{print "\033[1;33m[MCK]\033[0m " $$0; fflush()}'; kill 0) & \
	fi; \
	if [ -d backend/modules/cron ]; then \
		(cd backend && uv run python -u manage.py db_worker --queue-name default,scheduled_tasks 2>&1 | awk '{print "\033[1;35m[WRK]\033[0m " $$0; fflush()}'; kill 0) & \
		(cd backend && uv run python -u manage.py db_scheduler 2>&1 | awk '{print "\033[1;34m[SCH]\033[0m " $$0; fflush()}'; kill 0) & \
	fi; \
	wait
