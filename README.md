# Blog backend

FastAPI modular monolith for a Next.js blog and admin dashboard. Python 3.12+, PostgreSQL, async SQLAlchemy/asyncpg, JWT, Argon2id, Alembic, and nine application tables. Includes public topic suggestions, administrative reviews, transactional audit logging, and optional Next.js revalidation. No registration, refresh-token/session table, automatic generation, or automatic publication.

## Quick start with Docker

1. Install a working Docker Engine/Desktop with Compose. Copy `.env.example` to `.env`.
2. Generate **four independent values** using `openssl rand -hex 32`: set `POSTGRES_PASSWORD`, `DB_APP_PASSWORD`, `DB_MIGRATION_PASSWORD`, and `JWT_SECRET`. These URL-safe passwords work in Compose's database URLs. Never commit `.env`.
3. For production set `ENVIRONMENT=production`, use HTTPS CORS origins or `[]`, and configure only the real trusted reverse-proxy IPs/networks.
4. Run:

```sh
docker compose build --pull
docker compose up -d
docker compose run --rm api python -m scripts.seed_types
docker compose run --rm -it api python -m scripts.create_admin
curl --fail http://127.0.0.1:8000/ready
```

Compose waits for PostgreSQL readiness and successful migrations before serving. The bootstrap prompts securely for the password and refuses to run if an active admin exists. Additional accounts are created by an admin through the API. All user DELETE operations deactivate accounts.

The API binds to loopback port 8000; place an HTTPS reverse proxy in front. PostgreSQL has no published port by default. The API runs as a non-root user with a read-only filesystem, dropped capabilities, and process/memory/CPU limits. The database creates separate `blog_migrator` and `blog_api` roles. Only the migration job receives migration credentials; the API receives its own database credential. Initialization runs only for a fresh database volume. Changing `.env` passwords does not rotate existing PostgreSQL roles: rotate those explicitly in PostgreSQL and update the secret store together.

## Local Python development

Use Python 3.12 or later:

```sh
python3.12 -m venv .venv
. .venv/bin/activate
python -m pip install "pip @ https://files.pythonhosted.org/packages/3f/06/3e4420302363fbb71be3c7f35ce042f54bfca330e3e66b3a2e3c4cca579f/pip-26.2.2-py3-none-any.whl#sha256=fd7f4dfa8190e014013b9f08f3e973f4e4c26ffd179a204895533a7254813a70"
pip install -r requirements-dev.txt
docker compose -f docker-compose.yml -f docker-compose.dev.yml up -d db
docker compose run --rm migrate
```

Set `.env`'s `DATABASE_URL` to the local `blog_api` connection using your generated `DB_APP_PASSWORD`. The development override exposes PostgreSQL on **127.0.0.1:5432**. Then run:

```sh
python -m scripts.seed_types
python -m scripts.create_admin
python -m scripts.serve
```

Development Swagger UI: `/docs`; machine-readable schema: `/openapi.json`. The deployment entry point is `python -m scripts.serve`, or `uvicorn app.main:create_app --factory --workers 1` with equivalent resource/proxy settings. The pinned CA bundle and hash-verified pip bootstrap address the [October 2026 Python CA advisory](https://discuss.python.org/t/information-for-python-users-regarding-emudhra-emsign-ca-certificate-security-incident/109576). Rebuild images with fresh base/system certificates.

The package manifest also supports `pip install -e '.[dev]'`; the requirements files pin the deployment dependency snapshot. The local partial verification used cached packages, as recorded in the report.

## API contract

Prefix: `/api/v1`. UUIDs identify mutable resources; public article/classification detail routes use slugs. Authentication is `Authorization: Bearer <access_token>`. Login accepts JSON `{"email":"...","password":"..."}` and returns `data.access_token`, `data.token_type`, and `data.expires_in`.

| Area | Routes |
|---|---|
| Authentication | `POST /auth/login`, `GET /auth/me` |
| Users, admin only | `GET/POST /users`, `GET/PATCH/DELETE /users/{id}` |
| Public articles | `GET /articles`, `GET /articles/{slug}` |
| Administrative articles | `GET /admin/articles`, `GET /admin/articles/{id}` |
| Article changes | `POST /articles`, `PATCH/DELETE /articles/{id}`, `POST /articles/{id}/publish`, `POST /articles/{id}/unpublish` |
| Categories, tags, types | `GET/POST /categories`, `/tags`, `/article-types`; `GET /{collection}/{slug}`; `PATCH/DELETE /{collection}/{id}` |
| Public suggestions | `POST /article-requests` |
| Request review | `GET /admin/article-requests`, `GET/PATCH/DELETE /admin/article-requests/{id}` |
| Audit, admin only | `GET /admin-logs`, `GET /admin-logs/{id}` |
| Infrastructure, no prefix | `GET /health`, `GET /ready` |

Success is `{"data": ...}`. Lists add `meta: {page,page_size,total,pages}`. Deletions return 204. Errors are `{"error":{"code":"...","message":"...","details":...,"request_id":"..."}}`, without input echoes or SQL details. `X-Request-ID` correlates logs. Authentication/private responses use `Cache-Control: no-store`.

Lists accept `page` (1+), `page_size` (default 20, max 100), `sort` (prefix `-` for descending), and `search`. Search performs a literal, case-insensitive title/name/topic match, escaping SQL wildcard characters. Ties use UUIDs. Large offsets are capped. Unknown sort fields and unknown query inputs are rejected.

Article filters: `category`, `tag`, `article_type` (slugs; categories match direct membership), `is_featured`, `published_from`, and `published_to` (inclusive timezone-aware timestamps). `status` exists only on admin queries. Public defaults to `-published_at`; admin defaults to `-created_at`. Allowed article sorts: title, creation/update/publication timestamps, view count. Lists exclude full HTML/JSON-LD; detail routes include them. Only published articles, including featured articles, are publicly queryable.

Classification GETs expose active records. Admins can use `include_inactive=true` with a bearer token on list/detail routes to manage inactive records. Inactive records retain article links and remain embedded on already-published articles; future publication/relevant published edits require active classifications. Deletion of a referenced classification or parent category returns 409. Category hierarchy edits are serialized and cycle-checked in PostgreSQL.

### Article workflows and permissions

- Admin/editor/author create drafts, with authorship derived from the authenticated account. Authors can edit their own drafts only; administrative reads are limited to their own articles. They cannot set featured flags.
- Admins/editors edit any article and publish/unpublish. Publish validates active author/type/categories/tags and content. The first publication timestamp survives edits and republishing.
- PATCH can archive articles or restore archived articles to draft for admins/editors. Archiving a published article removes public visibility. Publishing and published-to-draft changes use the dedicated endpoints.
- Only admins delete articles, manage classifications/users, or read audit logs. Article deletion removes linking rows and preserves shared classifications and an audit event. Account deactivation preserves articles and audit history. The last active admin cannot be demoted or deactivated, including concurrent attempts.
- PATCH preserves omitted fields; explicit null clears only nullable fields. `category_ids`/`tag_ids` replace their respective sets when supplied. Duplicate and unknown IDs are rejected. Slugs are generated from names/titles if omitted on create; supply an ASCII slug for titles without ASCII letters/digits. Collisions return 409. Changing a title preserves its existing slug.
- HTML is sanitized using nh3, retaining article tables, images, code, and affiliate URLs/relationships while removing executable content and unsafe URLs. Featured images require absolute HTTP(S) URLs. Sanitized HTML permits safe root-relative links/images and fragment anchors. No uploads or URL fetching are performed.
- `schema` accepts a bounded JSON-LD object or graph: Schema.org context, type syntax, safe URL-bearing values, no executable markup, maximum 64 KiB and nesting depth 16. This is structural validation, not complete vocabulary validation or certification for search-engine rich results. Next.js owns rendering, metadata, canonical URLs, and sitemaps; escape `<` when embedding serialized JSON-LD in HTML.
- Each successful public detail request atomically increments `view_count` without changing editorial `updated_at`. These are raw API request counts, including bots, excluding frontend cache hits; they are not unique visitor analytics.

### Article requests

Public JSON accepts required `topic` (1–300 characters), optional `description` (up to 10,000), `name` (up to 150), and valid `email` (up to 255). All text must be plain text; HTML, scripts, encoded markup, and invalid controls are rejected. Optional `website` is a honeypot and must be empty for normal clients. It is not stored.

Stored submissions, honeypots, and short-term duplicates all receive 202 with `{"data":{"message":"Thank you for your suggestion."}}`. No IDs, contact information, review status, or notes are publicly returned. Invalid input returns 422; excess attempts return 429 with `Retry-After`.

Defaults: 5 attempts per 10 minutes and 20 per day per IP, including malformed/honeypot attempts. Duplicate suppression lasts 10 minutes for matching normalized fields from the same IP. Fingerprints are held only in bounded process memory. Concurrent identical submissions coordinate persistence; failed/cancelled writes release the reservation. These controls do not promise protection against distributed bot traffic.

Admins/editors can list and view all requests, filter by status, search topic, and sort by `created_at`, `updated_at`, `topic`, or `status` (default newest first). PATCH accepts only `status` and `admin_notes` (plain text, up to 10,000). Allowed statuses are `pending`, `accepted`, `rejected`, `completed`; any transition, including reopening, is allowed. A real change sets the reviewer server-side and writes an audit event in the same transaction. Submission content is immutable through review APIs. Only admins delete requests. Notes/contact information are excluded from audit details and logs. Requests never generate or publish articles.

## Concurrency and resource bounds

The initial deployment is **one Uvicorn worker, one asyncio event loop**. Independent requests run concurrently while waiting for PostgreSQL/httpx. Every request has its own SQLAlchemy session. Normal handlers use no dedicated request threads. Synchronous Argon2 and potentially expensive HTML processing are offloaded with a two-operation capacity limit.

Defaults: 100 concurrent Uvicorn connections/tasks, TCP backlog 128, keep-alive 5 seconds, graceful shutdown 30 seconds, 16 KiB incomplete HTTP-event buffer, 2 MiB request bodies, and 30-second application request deadline. Excess server concurrency receives 503. The database pool is 10 connections plus 5 overflow, with acquisition timeout 5 seconds, statement timeout 10 seconds, lock timeout 3 seconds, and idle transaction timeout 30 seconds. External httpx uses at most 10 connections and 5 keep-alives. Revalidation has a 5-second total deadline, 2-second connect timeout, no redirects, and no response-body buffering.

Limits use atomic operations under an asyncio lock, monotonic time, bounded queues/maps, and expiry. Defaults also include 5 login attempts per IP/account per minute, 30 total login attempts per IP per minute, and 60 authenticated mutations per user per minute. Exhausted storage fails closed with 429. Both rate limits and duplicate suppression **reset on restart and are not shared across processes**. Do not add workers/replicas until shared rate limiting is implemented. These are conservative initial settings, not a throughput guarantee; measure and tune against your deployment workload.

Cancellation rolls back open transactions and releases sessions. A client disconnect/timeout after a commit cannot undo that commit; inspect resource state before retrying a timed-out mutation. There is no general idempotency-key or durable background-job system.

Terminate HTTPS at a trusted proxy, enforce header/body/connection limits and a finite upstream timeout there, and enable HSTS for your production domain. Configure `TRUSTED_PROXY_IPS` explicitly so spoofed forwarding headers cannot bypass limits. Bearer authentication uses no cookies. Protect tokens on the Next.js side; there is no refresh endpoint or persistent token revocation store. User deactivation/role changes are checked on each authenticated request.

## Next.js revalidation

Disabled by default. Set `NEXTJS_REVALIDATION_ENABLED=true`, an HTTPS `NEXTJS_REVALIDATION_URL` in production, and an independent secret of at least 32 characters in `NEXTJS_REVALIDATION_SECRET` on both services. Do not put the secret in the URL or frontend bundles.

After committed changes to published articles, classifications, or displayed author names, the adapter sends:

```json
{
  "event": "article.update",
  "entity_id": "an-article-uuid",
  "article_id": "an-article-uuid",
  "slugs": ["new-slug", "old-slug"],
  "tags": ["articles", "categories", "tags", "article-types", "article:an-article-uuid", "article:new-slug", "article:old-slug"]
}
```

Header: `Authorization: Bearer <shared secret>`. Non-article events have `article_id: null`. Long slug tags use `article-slug-sha256:<hex digest>` to stay below Next.js's tag length limit. Old/new slugs remain in the payload for route invalidation. Tag all public article fetches with `articles`, classification fetches with their collection tags, and use finite frontend cache lifetimes as a fallback. Private/admin fetches must not be publicly cached.

In the Next.js receiver, validate the bearer secret using a constant-time comparison, validate the payload's tag/slug arrays and size, and invalidate only your allowlisted tags/routes. Use `revalidateTag(tag, { expire: 0 })` for immediate expiry after unpublishing/deletion; stale-while-revalidate would otherwise permit cached unpublished content. Match path invalidation to the actual frontend routing; this backend does not assume a `/blog/...` path. See the [Next.js tag API](https://nextjs.org/docs/app/api-reference/functions/revalidateTag).

The receiver returns a 2xx status after handling the event. HTTP failures/timeouts are safely logged and never roll back committed data. There is no persistent queue or durable retry guarantee. Until the receiver is configured and validated, revalidation is an external dependency; successful API changes cannot guarantee immediate frontend-cache invalidation after network failures. `/api/v1/articles` itself always enforces published visibility.

## Testing, linting, and migrations

Install all development requirements. For real database integration tests, explicitly create a disposable PostgreSQL database whose name ends in `_test`:

```sh
docker compose exec db createdb -U blog_owner -O blog_migrator blog_test
# Set TEST_DATABASE_URL using your actual migration password, loopback host and blog_test.
pytest
ruff check .
ruff format --check .
mypy app
```

Use the development Compose override for local PostgreSQL access. The test fixture upgrades Alembic, checks metadata drift, and truncates the nine application tables between tests. **Never point tests at production or valuable data.** An absent `TEST_DATABASE_URL` skips integration tests; a configured but unreachable server fails. Sanitization tests explicitly skip if nh3 is missing; normal installation and CI require nh3. Skipped tests do not establish production readiness.

Migration commands use the **migration role**, not the API role. For Compose:

```sh
docker compose run --rm migrate
# Review pending migration SQL without applying it:
docker compose run --rm migrate alembic upgrade head --sql
```

For local commands, set `DATABASE_URL` to your actual `blog_migrator` connection, then run `alembic upgrade head` / `alembic check`. Keep application serving credentials separate. The initial revision `0001` creates nine tables and no existing data is modified. Its downgrade drops application data and is suitable only for disposable databases or a verified rollback procedure. Prefer forward corrective migrations for production.

CI is configured for Python 3.12 and PostgreSQL 17, all checks/tests, destructive migration round-trips on its disposable database, and a production Docker build. CI configuration is provided; its successful execution is not assumed. Current local check results and blockers are recorded in `IMPLEMENTATION_REPORT.md`.

## Secrets, backups, and restore

Use your deployment secret manager rather than committed configuration. Rotate independent database/JWT/revalidation secrets, restrict PostgreSQL networking, use verified TLS for remote PostgreSQL, and do not log request bodies, authorization headers, query strings, passwords, or connection URLs. `DATABASE_URL` supports asyncpg TLS query options such as `ssl=verify-full`; use verified TLS settings appropriate to the managed server. Keep the public submission database and backups access-controlled because contact information is private. Establish a retention policy operationally; this implementation adds no automatic deletion workflow.

Take encrypted, access-controlled PostgreSQL backups and retain them off-host. Example logical backup, with private filesystem permissions:

```sh
umask 077
mkdir -p backups
docker compose exec -T db pg_dump -U blog_owner -d blog --format=custom --no-owner > backups/blog.dump
docker compose exec -T db pg_restore --list < backups/blog.dump
```

Encrypt and transfer backups using your approved storage tooling; the commands above produce an unencrypted local file. Back up role/grant definitions or maintain the initialization script and securely stored role secrets. For larger production workloads configure managed snapshots/WAL archiving and point-in-time recovery to meet explicit RPO/RTO targets.

Exercise restore on an **isolated host/project**, with a fresh volume and roles initialized by `docker/init-db.sh`:

```sh
docker compose -p blog-restore up -d db
docker compose -p blog-restore exec -T db pg_restore -U blog_owner --role=blog_migrator -d blog --no-owner --exit-on-error < backups/blog.dump
docker compose -p blog-restore exec -T db psql -U blog_owner -d blog -c 'SELECT version_num FROM alembic_version;'
```

Check application table counts, representative article/relationship/audit records, login, and readiness against the restored environment before considering the exercise successful. Do not start a second API on the same published port as a live deployment. For production recovery, stop writers, preserve the damaged database for investigation, restore into a replacement database, verify schema/data/grants, switch application secrets/connection settings, and perform a controlled readiness/traffic cutover. Do not run destructive restore options against a live database as an unreviewed shortcut. Restore execution remains an operator/environment verification step.
