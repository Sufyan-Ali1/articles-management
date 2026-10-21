# Implementation report

The backend was implemented directly in an initially empty workspace. Docker access is now available, and the complete dependency set and database workflows have been verified in containers.

**Current state:** PostgreSQL 17 and the API are running and healthy. The project uses the persistent `blog` database; migration `0001` is applied and seven article types are seeded. A separate `blog_test` database is used for destructive integration/migration tests. No administrator account was created automatically.

**Final verification:** **99 tests passed, no skips or warnings**, on **Python 3.12.15** with actual PostgreSQL. Ruff, formatting, mypy, production/test image builds, online migrations, and migration drift/round-trip checks passed. Earlier environment-related failures and skips are superseded by these Docker results. GitHub-hosted CI itself was not invoked.

## 1. Features implemented

- Exactly nine application tables, UUID entities, JSONB/INET/timezone-aware timestamps, relationships, named constraints, and indexes.
- JWT login/current user, Argon2id hashing, admin/editor/author permissions, ownership restrictions, safe user deactivation, concurrent last-admin protection, and secure interactive bootstrap.
- Classification CRUD, nested categories, concurrency-safe cycle prevention, restricted deletion, inactive-record administration, and idempotent article-type seeds.
- Article drafts, partial editing, category/tag linking, publishing/unpublishing/archiving/deletion, preserved publication timestamps, featured filtering, and atomic raw view counts.
- HTML sanitization, safe URLs, SEO fields, bounded structural JSON-LD validation, strict input/response schemas, pagination/search/filtering/allowlisted sorting, and OpenAPI.
- Anonymous article requests with generic responses, honeypots, bounded duplicate/rate controls, private review APIs, flexible status transitions, reviewer assignment, and admin-only deletion.
- Transactional administrative audit records, safe structured logs, bounded async resource usage, health/readiness, and optional post-commit Next.js revalidation.
- Docker deployment, separate least-privilege API/migration database roles, private local configuration, reproducible dependency pins, PostgreSQL-backed tests, CI configuration, and operational documentation.

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
| Deployment | `Dockerfile`, `docker-compose.yml`, `docker-compose.dev.yml`, `docker-compose.test.yml`, `docker/init-db.sh`, `.dockerignore`, `.env.example` |
| Tooling/documentation | `pyproject.toml`, `requirements.txt`, `requirements-dev.txt`, `.gitignore`, `.github/workflows/ci.yml`, `README.md`, this report |

Python package directories also contain `__init__.py` files. The private `.env` was subsequently created with generated local credentials (mode 0600); it is excluded by `.gitignore` and `.dockerignore`. `docker-compose.test.yml` adds a reusable test runner with writable caches confined to `/tmp`. `alembic.ini` now uses `path_separator = os` to remove the Alembic deprecation warning. The local Python 3.11 `.venv` remains available, but full verification uses Python 3.12.15 in Docker.

## 3. Database migration and running databases

Revision `0001` creates `users`, `articles`, `categories`, `tags`, `article_types`, `article_categories`, `article_tags`, `admin_logs`, and `article_requests`. Alembic maintains its additional infrastructure version table. The live `blog` database has all nine application tables, version `0001`, and seven article types.

The initial schema was applied using the `blog_migrator` role. Seed commands were verified both inside the API container and through the local project's configured `DATABASE_URL`. The API uses `blog_api`; both roles were checked to be non-superusers without database/role-creation privileges.

A complete downgrade → upgrade → metadata drift check passed on **blog_test only**. The project `blog` database was never truncated or downgraded. Initial migration adds tables; downgrade drops application data and is intended for disposable databases or an explicitly reviewed recovery procedure.

Local connections:

| Purpose | Address/database | Role / secret location |
|---|---|---|
| Local application | `127.0.0.1:5432/blog` | `blog_api`, `DB_APP_PASSWORD` in `.env` |
| Local migration/testing | `127.0.0.1:5432/blog_test` | `blog_migrator`, `DB_MIGRATION_PASSWORD` in `.env` |
| Container application | `db:5432/blog` | `blog_api`; Compose injects the container URL |
| API | `http://localhost:8000` | `/ready` returns ready; `/docs` provides Swagger |
| Persistent storage | `blog-backend_postgres_data` | Retained across container restarts |

The private `.env` includes the configured local `DATABASE_URL` and `TEST_DATABASE_URL`. Credentials were generated securely and were not printed. Other existing Docker containers were left untouched.

## 4. Implemented endpoints

Base `/api/v1`, except probes:

- `POST /auth/login`; `GET /auth/me`.
- `GET/POST /users`; `GET/PATCH/DELETE /users/{id}` — admin only; DELETE deactivates.
- `GET /articles`; `GET /articles/{slug}` — published only.
- `GET /admin/articles`; `GET /admin/articles/{id}` — authenticated, with author ownership restrictions.
- `POST /articles`; `PATCH/DELETE /articles/{id}`; `POST /articles/{id}/publish`; `POST /articles/{id}/unpublish` — role/state restrictions.
- `GET/POST /categories`, `/tags`, `/article-types`; GET by slug, PATCH/DELETE by UUID — public active reads and admin modifications. `include_inactive=true` requires admin authentication.
- `POST /article-requests` — public, generic 202 response.
- `GET /admin/article-requests`; `GET/PATCH /admin/article-requests/{id}` — admin/editor.
- `DELETE /admin/article-requests/{id}` — admin only.
- `GET /admin-logs`; `GET /admin-logs/{id}` — admin only.
- Root `GET /health`; `GET /ready`.

OpenAPI contains 40 operations. Live readiness, published-article listing, and seven-type listing were checked against the running API. Private state-changing workflows were verified by integration tests against the separate database.

## 5. Security controls

JWT HS256 signature/expiration/issuer/audience/subject validation; configurable short-lived tokens; current active-user/role checks; Argon2id with bounded offloading; no default accounts, public registration, or session tables. Strict schemas prevent privileged field assignment. Transaction locks protect category hierarchies and the last admin. Business changes and administrative audit records commit together.

Rate limits are bounded and atomic across asyncio tasks. Suggestions add honeypots and transient hashed duplicate fingerprints, without extra IP/fingerprint columns. Private contact data/notes are excluded from public responses and audit details. Queries are parameterized and sorting is allowlisted. nh3 sanitization, safe URLs, structural JSON-LD validation, body/pagination/connection/time limits, explicit CORS/proxy trust, safe logs/errors, and non-root read-only containers are implemented.

The pinned dependency set, including `nh3==0.3.7`, `certifi==2026.10.19`, and the hash-verified pip 26.2.2 bootstrap, installed successfully in Docker. The CA updates follow the [Python security advisory](https://discuss.python.org/t/information-for-python-users-regarding-emudhra-emsign-ca-certificate-security-incident/109576).

## 6. Executed checks and actual results

Final checks ran in the refreshed `blog-backend:test` image with the pinned dependencies and Python 3.12.15:

| Check | Actual result |
|---|---|
| `pytest -q -p no:cacheprovider` | **99 passed in 11.69s; no skips or warnings** |
| `ruff check .` | Passed |
| `ruff format --check .` | Passed; 59 Python files in the test image |
| `mypy app scripts` | Passed; 48 source files |
| `alembic upgrade head` | Passed on project `blog` and isolated `blog_test` |
| `alembic downgrade base` → `alembic upgrade head` | Passed on **blog_test only** |
| `alembic check` | Passed: no new upgrade operations detected |
| Production image build | Passed; `blog-backend:local` |
| Development/test image build | Passed; `blog-backend:test` |
| Compose startup | PostgreSQL and API healthy; migration service exited successfully |
| Actual schema/seed inspection | Nine application tables plus Alembic infrastructure; revision `0001`; seven article types |
| Local `.env` database connection | Passed through the idempotent seed CLI |
| Live API checks | `/ready` ready; public article listing 0; public article types 7 |
| Database role inspection | API/migrator roles have no superuser, create-database, or create-role privilege |

Tests exercise actual database operations and cover authentication, roles/ownership, CRUD/publication, references, category cycles/concurrent edits, duplicates, sanitization, JSON-LD/SEO, filters/sorts/pagination, rollback/audit, last-admin races, requests/reviews/spam, view concurrency, revalidation failures, and health/readiness. Only external HTTP is mocked. No core database business logic was mocked.

The first complete run had two Alembic deprecation warnings; `path_separator = os` was added, images refreshed, and all checks rerun successfully without warnings. The test container's Ruff/mypy caches are confined to `/tmp` so verification works with its read-only application filesystem.

Repeat the complete verification (existing `blog_test` is disposable):

```sh
docker compose -f docker-compose.yml -f docker-compose.test.yml run --rm --build tests sh -c 'ruff check . && ruff format --check . && mypy app scripts && pytest -q -p no:cacheprovider && alembic downgrade base && alembic upgrade head && alembic check'
```

## 7. Environment configuration

The generated local `.env` contains independent database/JWT secrets and real connection URLs. `DATABASE_URL` is the application-role URL. `TEST_DATABASE_URL` uses the migration role against `blog_test`. Compose overrides container connection hosts to `db`.

Required values: `DATABASE_URL`, `JWT_SECRET`; Compose also requires `POSTGRES_PASSWORD`, `DB_APP_PASSWORD`, and `DB_MIGRATION_PASSWORD`. Configure `ENVIRONMENT`, explicit CORS/proxy trust, and optional token/pool/time/body/rate settings as listed in `.env.example`.

Optional Next.js integration uses `NEXTJS_REVALIDATION_ENABLED`, `NEXTJS_REVALIDATION_URL`, and `NEXTJS_REVALIDATION_SECRET`. It remains disabled locally because no real receiver/shared secret was supplied.

## 8. Deployment and local startup

The local API and database are already running. Preserve the generated `.env`. Restart while keeping the loopback PostgreSQL port published:

```sh
docker compose -f docker-compose.yml -f docker-compose.dev.yml up -d --no-build --wait api
```

No administrator credentials were chosen on the user's behalf. Create the first admin interactively when needed:

```sh
docker compose run --rm -it api python -m scripts.create_admin
```

Use `README.md` for fresh environments, image rebuilds, production HTTPS, secret rotation, explicit migrations, backups, and recovery. Stopping containers preserves the named volume; deleting it destroys the data. Production Compose without the development override does not publish PostgreSQL to the host.

## 9. Remaining external/operator steps

There are no remaining local database, test-suite, migration, or Docker-build blockers.

- Choose first-admin credentials through the secure CLI.
- Supply and validate the real Next.js receiver/shared secret if cache revalidation is wanted.
- Configure production HTTPS/origins/proxy trust and production secret management before public exposure.
- Perform an encrypted backup/restore exercise and workload/resource measurements in the deployment environment. Procedures are documented; a production restore was not performed.
- GitHub CI is configured but was not run as a hosted job during this session.

One-worker rate limits and duplicate suppression reset on restart and are not shared between processes. Revalidation has no persistent queue/durable retries; external cache failures can delay frontend invalidation despite correct published-only database queries. No automatic generation/publication, Redis, CAPTCHA service, analytics subsystem, or extra application table was added.
