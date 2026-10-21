# Implementation report

Implemented in the originally empty workspace on 2026-10-21. There was no existing code or Git repository to preserve. All application source, migrations, tests, deployment configuration, and documentation were created directly in this directory. No live database was modified or credentials invented for deployment.

**Status:** implementation is present; full production verification remains blocked by the environment. Local checks used Python 3.11.0 because Python 3.12+ was unavailable. Docker/CI target Python 3.12. Do not interpret the partial test run as proof that all database and HTML workflows have passed.

## 1. Features implemented

- Nine application tables, UUID entities, PostgreSQL JSONB/INET/timezone-aware timestamps, relationships, named constraints, and indexes.
- JWT login/current user, Argon2id hashing, admin/editor/author permissions, resource ownership, user deactivation, concurrent last-admin protection, and secure interactive bootstrap.
- Classification CRUD with nested categories, cycle prevention, reference-safe deletion, inactive-record administration, and idempotent article-type seeds.
- Draft creation, partial editing, category/tag linking, publishing, unpublishing, archiving, deletion, preserved publication timestamps, featured filtering, and atomic raw view counts.
- HTML sanitizer integration, safe URLs, SEO fields, bounded structural JSON-LD validation, strict input schemas, pagination/search/filtering/allowlisted sorting, explicit response contracts, and OpenAPI.
- Anonymous article requests, generic submission responses, honeypot/duplicate/rate controls, private review APIs, flexible status transitions, reviewer assignment, and admin-only deletion.
- Transactional administrative audit records, structured safe logs, bounded concurrency/pools/timeouts, health/readiness, and optional post-commit Next.js cache revalidation.
- Production/development Docker configuration, least-privilege database roles, secret templates, pinned dependencies, PostgreSQL tests, CI configuration, and operational documentation.

## 2. Created files

Main groups:

| Group | Files |
|---|---|
| Application factory | `app/main.py` |
| Core | `app/core/config.py`, `errors.py`, `limits.py`, `logging.py`, `middleware.py`, `rbac.py`, `security.py` |
| Database/models | `app/db/base.py`, `session.py`, `app/models/entities.py` |
| Schemas | `app/schemas/common.py`, `users.py`, `content.py`, `requests.py`, `logs.py` |
| REST API | `app/api/dependencies.py`; `app/api/v1/auth.py`, `users.py`, `classifications.py`, `articles.py`, `requests.py`, `logs.py` |
| Services | `app/services/common.py`, `auth.py`, `users.py`, `classifications.py`, `articles.py`, `requests.py` |
| Queries/integration/utilities | `app/repositories/queries.py`, `app/integrations/nextjs.py`, `app/utils/pagination.py`, `validation.py` |
| Migration | `alembic.ini`, `alembic/env.py`, `alembic/script.py.mako`, `alembic/versions/0001_initial.py` |
| Commands | `scripts/serve.py`, `create_admin.py`, `seed_types.py` |
| Tests | `tests/conftest.py`, `test_security.py`, `test_sanitization.py`, `test_health_and_contract.py`, `test_schema.py`, `test_integration.py`, `test_integration_adapter.py`, `test_submission_guard.py` |
| Deployment | `Dockerfile`, `docker-compose.yml`, `docker-compose.dev.yml`, `docker/init-db.sh`, `.dockerignore`, `.env.example` |
| Tooling/documentation | `pyproject.toml`, `requirements.txt`, `requirements-dev.txt`, `.gitignore`, `.github/workflows/ci.yml`, `README.md`, this report |

Python package directories also contain `__init__.py` files. A local ignored `.venv` was created for partial verification using available Python 3.11 and cached wheels. Recreate a Python 3.12+ environment and install the pinned requirements for full verification. The temporary recovered wheelhouse was removed.

## 3. Database migration

Revision `0001`, no parent: creates `users`, `articles`, `categories`, `tags`, `article_types`, `article_categories`, `article_tags`, `admin_logs`, and `article_requests`. Alembic maintains its separate version table.

Model metadata contains exactly nine application tables. Both migration directions were rendered without a database: upgrade renders nine application CREATE TABLE statements; downgrade renders nine DROP TABLE statements. The Alembic command's full offline upgrade additionally creates `alembic_version`.

Online upgrade, drift comparison, and destructive migration round-trip have **not passed**. The first two were attempted and denied a local PostgreSQL socket connection; the round-trip was not attempted after that prerequisite failed. Initial upgrade adds tables only. Downgrade destroys application data and must not be applied casually to production.

## 4. Implemented endpoints

Base `/api/v1`, except probes:

- `POST /auth/login`; `GET /auth/me`.
- `GET/POST /users`; `GET/PATCH/DELETE /users/{id}` — admin only; DELETE deactivates.
- `GET /articles`; `GET /articles/{slug}` — published only.
- `GET /admin/articles`; `GET /admin/articles/{id}` — authenticated, with author ownership restrictions.
- `POST /articles`; `PATCH /articles/{id}`; `DELETE /articles/{id}`; `POST /articles/{id}/publish`; `POST /articles/{id}/unpublish` — supplied role/state restrictions.
- `GET/POST /categories`, `/tags`, `/article-types`; GET by slug and PATCH/DELETE by UUID — public active reads, admin modifications. `include_inactive=true` requires admin authentication.
- `POST /article-requests` — public; generic 202 response.
- `GET /admin/article-requests`; `GET/PATCH /admin/article-requests/{id}` — admin/editor.
- `DELETE /admin/article-requests/{id}` — admin only.
- `GET /admin-logs`; `GET /admin-logs/{id}` — admin only.
- Root `GET /health`; `GET /ready`.

The generated OpenAPI document contains 40 HTTP operations, including probes. Swagger UI is available outside production at `/docs`; `/openapi.json` supplies the schema.

## 5. Security controls

Explicit JWT HS256 signature/expiration/issuer/audience/subject validation; 30-minute configurable access tokens; current active-user/role checks; Argon2id with bounded offloading; no default accounts, public registration, or persistent session tables. Strict schemas prevent privileged field assignment. PostgreSQL transaction locks protect hierarchy changes and the last administrator. Database mutations and administrative audit events share transactions.

Rate limiting is bounded and atomic for concurrent asyncio tasks. Public suggestions additionally use a honeypot and bounded transient duplicate fingerprints, without storing client IP/fingerprint columns. Private contact information and notes are not returned publicly or copied into audit details. SQLAlchemy binds parameters; sort fields are allowlisted; HTML uses nh3; URL and JSON-LD input is constrained. Body/pagination/connection/request limits, explicit CORS/proxy trust, non-root containers, separate API/migration database roles, secret validation, and safe error/log formats are implemented.

The deployment pins `certifi==2026.10.19` and bootstraps hash-verified pip 26.2.2 in response to the [Python CA security advisory](https://discuss.python.org/t/information-for-python-users-regarding-emudhra-emsign-ca-certificate-security-incident/109576). Those updated packages could not be downloaded into the local verification environment; local tests used cached certifi 2026.7.22 and did not contact external HTTPS services. Docker builds refresh system certificates and use the patched pins. A fresh dependency installation/build remains required.

## 6. Executed checks and actual outcomes

| Command/check | Actual outcome |
|---|---|
| `.venv/bin/pytest -q` | **65 passed, 25 skipped**, Python **3.11.0** |
| `.venv/bin/ruff check .` | Passed |
| `.venv/bin/ruff format --check .` | Passed |
| `.venv/bin/mypy app` | Passed: 44 application source files |
| `.venv/bin/mypy scripts` | Passed: 4 script source files |
| `.venv/bin/python -m pip check` | No broken requirements among installed cached packages; this does not verify the project/pinned deployment installation |
| OpenAPI generation | Passed; 40 operations |
| Model metadata validation | Passed; nine application tables and timezone-aware timestamps |
| `alembic upgrade head --sql` | Passed offline: 6,450 SQL bytes, nine application tables plus Alembic version table |
| Upgrade/downgrade operation SQL rendering | Passed offline in both directions; not applied to a database |
| `alembic upgrade head` | Failed: PostgreSQL connection denied (`PermissionError: Operation not permitted`) |
| `alembic check` | Failed: same connection restriction; no live metadata comparison established |
| Production `docker compose config --quiet` | Passed, using generated temporary validation-only secrets, not deployment credentials |
| Development Compose configuration | Passed, with the development override and temporary validation-only values |
| `docker build --target production -t blog-backend:verification .` | Failed: Docker socket permission denied / no accessible daemon |
| Dependency download | Shell DNS/network unavailable; nh3 absent from local caches; browser download fallback was cancelled/unavailable |

The **25 skips** comprise 24 PostgreSQL test cases without `TEST_DATABASE_URL`, and one sanitization module skipped before collecting its ten cases because nh3 was unavailable. Tests exercise real PostgreSQL business operations when configured; no database business logic was mocked. HTTP adapter tests use httpx mock transports.

PostgreSQL coverage is written for authentication, CRUD, roles/ownership, publication, references, hierarchy/concurrent cycles, duplicate slugs, transaction rollback, last-admin races, requests/reviews/spam/audit, view concurrency, and revalidation failures. Its execution remains pending. CI is configured to install all dependencies and run those cases on PostgreSQL/Python 3.12, but CI was not executed here.

## 7. Required configuration

Required for serving: `DATABASE_URL` using `postgresql+asyncpg`, and a unique `JWT_SECRET` of at least 32 characters. Compose additionally requires independently generated `POSTGRES_PASSWORD`, `DB_APP_PASSWORD`, and `DB_MIGRATION_PASSWORD`.

Set `ENVIRONMENT`, explicit `CORS_ORIGINS` and `TRUSTED_PROXY_IPS`, and optionally JWT issuer/audience/expiration, database pooling/statement/lock limits, request/body limits, and rate-limit settings. `.env.example` enumerates every setting and default.

Optional integration: `NEXTJS_REVALIDATION_ENABLED`, `NEXTJS_REVALIDATION_URL`, `NEXTJS_REVALIDATION_SECRET`. HTTPS and a strong shared secret are required when enabled in production. PostgreSQL testing requires a disposable `TEST_DATABASE_URL` ending in `_test`.

## 8. Deployment instructions

Follow `README.md`: create `.env` from the example, generate independent secrets, configure production HTTPS origins/proxy trust, build with a fresh base image, and start Compose. Migrations run as a separate prerequisite job. Run the idempotent seed and interactive first-admin commands. Verify readiness and place the loopback-bound API behind HTTPS. Instructions include local Python development, isolated PostgreSQL tests, migration review, restricted deployment credentials, encrypted/off-host backups, and restore/cutover procedures.

No actual administrator, deployment credentials, Next.js receiver, deployment, database backup, or restore was created/run. Restore procedures are documented, not claimed tested.

## 9. Remaining verification and external dependencies

- Install Python 3.12+ and the complete patched dependency set, including nh3.
- Supply an accessible disposable PostgreSQL instance and run the integration suite, online migrations/drift check, and migration round-trip.
- Supply an accessible Docker daemon and verify the production build and Compose startup/health checks.
- Configure the actual Next.js receiver/shared secret and confirm route/tag mapping against the real frontend. The adapter is optional and remains disabled by default.
- Execute a restore exercise and workload/resource measurements in the deployment environment.

One-worker rate limits and duplicate suppression reset on restart and are not shared across processes. The Next.js adapter has no persistent queue or durable retries. Public database queries enforce published status, while frontend cache invalidation can still fail during an external outage; finite cache lifetimes and operational handling remain necessary. No automatic generation/publication, CAPTCHA service, Redis, analytics subsystem, or extra application table was added.
