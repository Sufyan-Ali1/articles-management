# Traffic tracking: plan and implementation

## Article URLs with UTM parameters (preferred)

Share the actual article URL, for example:

`https://askandexplore.com/articles/your-article?utm_source=linkedin&utm_medium=social`

Admins/editors can generate a URL without creating a tracking-link record:

`POST /api/v1/admin/utm-links`

```json
{
  "article_id": "<published-article-uuid>",
  "source_id": "<configured-source-uuid>",
  "medium": "social",
  "campaign": "launch",
  "content": "comment-01"
}
```

Returns HTTP 200 with `data.article_slug`, `data.relative_url` and the four
`utm_*` fields (optional campaign/content are null when omitted). Join
`relative_url` to the configured public website origin. The backend uses the
actual website route `/articles/{slug}` and URL-encodes query values. There is
no code to choose, database insert, or redirect. Only active configured sources
and published articles can be selected. Existing short-link endpoints remain
available for compatibility.

### Required dashboard and website integration

The dashboard must replace its short-link form with a call to `/admin/utm-links`
and copy the website origin plus `relative_url`. Opening article details can
still list legacy links with `article_id`; this filter is now part of the query
model alongside pagination, preventing an unexpected-field validation error.

The website must read `utm_source`, `utm_medium`, `utm_campaign`, and `utm_content`
from the landing URL and include them in its server-to-server
`POST /api/v1/analytics/article-views` payload. Preserve these values in the signed
30-minute attribution session for later article navigation; a new explicit UTM
landing starts a new attributed session. Do not send `tracking_link_id` together
with UTM attribution. Keep the ingest secret server-only. The current website
short-link collector must be updated before UTM visits will be attributed.

Explicit UTM source takes precedence over referrer matching. Source and medium
are normalized to lowercase; campaign and content retain case. Missing medium
defaults to `social`. Active registered source slugs populate source cards.
Unknown/inactive UTM sources are preserved in grouped reports and counted as
unassigned on source cards. Other UTM fields require `utm_source`. Existing
referrer-only and short-link events retain their behavior. No migration is needed.

## Legacy short-link flow


1. An admin/editor creates a tracking link for a published article and a specific
   sharing placement. Metadata is immutable; create a new code for a new placement.
2. Share `https://askandexplore.com/r/linkedin-comment-01`.
3. The website resolves the code against the backend, sets a signed HttpOnly
   attribution cookie, and returns a temporary 302 to the clean article URL.
4. A browser component sends an event after the page becomes visible and on
   client-side navigation. Requests queue so the first landing establishes its
   session before subsequent article navigation.
5. The website server verifies the cookie and sends events to the backend with a
   server-only ingest key. The backend resolves source metadata itself, stores a
   unique event, and atomically increments the article's view counter.
6. Admin/editor reports summarize views and distinct sessions, with filters and
   pagination. Database migrations are not applied by the app.

The public article API is now read-only. Rendering, metadata fetches, direct API
reads, link previews, and HEAD requests no longer increment view counts. Historical
`view_count` values are preserved; future accepted events increase them. Reports
include only newly collected events, not historical counts whose source is unknown.

## Setup (when ready to deploy)

- Apply the single pending `0005_pending_features` migration after all database
  changes are finalized. It follows `0004_media_deletion_pending` and includes
  scheduling, subscribers, contacts, tracking links, and view events. The previous
  three unapplied feature migrations have been replaced. No migrations were run
  during development of this feature.
- Configure the **same random secret of at least 32 characters** as
  `ANALYTICS_INGEST_SECRET` in the backend and website's server environment. Do not
  use a `NEXT_PUBLIC_` prefix, expose it in browser code, or reuse a login secret.
  Docker Compose passes this setting into the API container.
- The website uses its existing server-only `API_BASE_URL`; no new public API URL
  or CORS change is needed. Use HTTPS in production so cookies are Secure.
- Deploy the matching frontend/backend versions. Without the website secret,
  collection is disabled while short links can still redirect. Backend ingestion
  without a configured key returns 503. Rotation invalidates existing cookies.

## Managed traffic sources

Administrators create sources before generating links:

`POST /api/v1/admin/traffic-sources`

```json
{"name":"LinkedIn","slug":"linkedin","referrer_domains":["linkedin.com","lnkd.in"]}
```

The name is editable; the slug is a permanent unique key. Referrer domains are
optional hostnames, up to 20 per source, and match exact hosts plus subdomains.
Overlapping domains between sources return 409, including inactive sources.
This prevents ambiguous attribution. Domains are normalized to lowercase.

- Admins/editors: `GET /api/v1/admin/traffic-sources`, with standard pagination,
  name search, and name/slug/created_at/updated_at sorting.
- Admins: `PATCH /api/v1/admin/traffic-sources/{id}` accepts name, referrer_domains,
  and is_active. Deactivation stops new links, short-link redirects, and automatic
  referrer matching. Existing short-link sessions retain attribution. Referrer-only
  sessions are classified for each new event using the current registry.
- Admins: `DELETE /api/v1/admin/traffic-sources/{id}` deletes unused sources.
  Sources referenced by any link or view event return 409; deactivate instead.
  Foreign keys also protect history against concurrent writes.

No sources are fabricated or seeded. Create the platforms you use in the dashboard's
Traffic Sources section. Configured sources appear even when their count is zero;
unmatched referrers and direct visits remain visible in a separate bucket.

## Create and manage links

`POST /api/v1/admin/tracking-links`, using an admin/editor Bearer token:

```json
{
  "article_id": "<published-article-uuid>",
  "code": "linkedin-comment-01",
  "source_id": "<configured-source-uuid>",
  "medium": "social",
  "campaign": "laptop-guide-launch",
  "content": "comment-01"
}
```

Returns HTTP 201 with a standard `data` object containing the ID, code, article,
source metadata, active flag, and creation date. Use its `code` in the website's
`/r/{code}` URL. Codes must be unique lowercase words/numbers separated by hyphens,
3–80 characters. Duplicate codes return 409. Only published articles can be linked.

- `GET /api/v1/admin/tracking-links`: pagination, code search, sorting by
  `created_at`, `code`, or `source`; optional `article_id` scopes results to one blog.
- `PATCH /api/v1/admin/tracking-links/{id}` with `{"is_active":false}` disables
  future redirects; use `true` to reactivate. Existing session attribution is kept.
- `GET /api/v1/tracking-links/{code}` is the public resolver used by the website;
  inactive/missing links, inactive sources, or unpublished/deleted articles return 404.

Use separate codes for LinkedIn comments, Instagram bio links, newsletters, etc.
Tracking parameters are not added to either the shared URL or destination URL.

## Measurement and attribution

The signed `ae_traffic` cookie holds a random session UUID, optional tracking-link
ID, optional referring hostname, and expiry. It is HttpOnly, SameSite=Lax, Secure
on HTTPS, and expires after **30 minutes of inactivity**. Each tracked navigation
refreshes the expiry. A new explicit `/r/` link starts a new attributed session.

For a normal clean URL without an existing session, an external referring hostname
becomes the source (`medium=referral`). No referrer means `direct_or_unknown`.
For short links, internal navigation retains the source selected by the link.
For referrer-only sessions, the initial referring hostname is retained and mapped
to an active configured source for each event. Otherwise it remains a hostname
in legacy grouped reports and is counted as unassigned in source cards. Adding a
source/domain does not retroactively rewrite recorded events. Search engines are
not automatically classified as organic traffic.
UTM parsing is not needed for this short-link flow and is not implemented.

A page view is one visible article navigation. Reloads and revisiting an article
count as new views; client rerenders/StrictMode don't. One network retry reuses the
same event UUID; a unique database constraint prevents double counting even across
API workers. Distinct sessions are not unique people and can span several articles.
Requests blocked by browser settings, networking, disabled cookies, JavaScript
restrictions, or Do Not Track/Global Privacy Control affect accuracy. Signed
cookies reduce tampering but cannot prove a visitor is human or prevent someone
from sharing a tagged short link on a different platform.

Only hostnames are stored as referrers; full URLs, IPs, names, and emails are not
stored in analytics records. The privacy page explains this collection. No
third-party analytics script or cookie is added. The operator manages retention;
there is no automatic purge job. Deleting an article cascades its link/event rows.

## Dashboard and per-blog cards

`GET /api/v1/admin/analytics/sources` requires an admin/editor token. Optional
`article_id` limits every count to one article (missing articles return 404).
Optional timezone-aware `start` and `end` bound the tracked metrics; start is
inclusive, end exclusive. Omitting both returns all recorded traffic.

The response includes `views`, distinct `sessions`, `lifetime_views`, `legacy_views`,
all configured `sources` with views/sessions (including inactive and zero-count
sources), `unassigned_views`, and `unassigned_sessions`. A single SQL statement
provides a consistent count snapshot. Lifetime views ignore date filters and
include older counter-only views; legacy_views explains the difference between
that counter and all retained events. Sessions are not people and should not be
summed across source cards to derive the global distinct-session total.

The dashboard has a Traffic Sources management page, source cards on the overview,
and article-specific totals/cards plus a short-link builder on saved article pages.
Admins manage the registry; editors can view it and generate links. Authors do not
receive global analytics access. Set `VITE_PUBLIC_SITE_URL` in the dashboard to the
public website origin when using a domain other than askandexplore.com.

## Reporting

`GET /api/v1/admin/analytics/traffic` requires an admin/editor token.

Query parameters:

- `start`, `end`: timezone-aware timestamps; inclusive start, exclusive end.
  Defaults to the last 30 days; maximum range is 366 days.
- Optional `article_id`, `source`, `campaign`, `tracking_link_id` filters.
- `group_by`: `source` (default), `article`, `campaign`, `link`, or `day` (UTC).
- `page`, `page_size`: defaults 1 and 20, at most 100 groups per page.

Examples:

```text
/api/v1/admin/analytics/traffic?group_by=source
/api/v1/admin/analytics/traffic?group_by=link&campaign=laptop-guide-launch
/api/v1/admin/analytics/traffic?group_by=day&article_id=<uuid>
```

Response `data` contains total `views`, distinct `sessions`, paginated `groups`
(each has `key`, `views`, `sessions`), `total_groups`, `page`, and `page_size`.
Article and link grouping keys are UUIDs, resolved using the existing article
and tracking-link endpoints. A session visiting several articles contributes to
several article groups but only once to the overall session total. The dashboard consumes the source overview above; no public analytics dashboard is added.

## Ingestion and protections

The website sends `POST /api/v1/analytics/article-views` with `X-Analytics-Key` and
`event_id`, `session_id`, `article_slug`, optional `tracking_link_id`, and optional
`referrer_domain`. Success (including a duplicate event) returns 204. Unpublished
articles return 404. The secret is compared in constant time. Process-local rate
limits cap ingestion at 6,000 events/minute and 120/minute per session; the resolver
allows 6,000 requests/minute per connecting IP (website servers may share an IP).

The website gateway bounds bodies to 4 KiB, requires JSON and a same-origin
request, validates all fields, and verifies cookie signatures/expiry. Redirects
use validated local article paths only and are marked private/no-store/noindex.
Collection failures never block reading; redirect resolution failures show a
503 so a broken destination isn't guessed. Limits are process-local, as with the
rest of this application, and are not a distributed anti-bot system.

## Verification

Backend tests cover authentication, validation, idempotency, atomic counter updates,
and rejection of unpublished articles. Database integration tests additionally
cover concurrent duplicate ingestion, link lifecycle, and every report grouping;
they are deferred until migrations can run against a disposable test database.
Frontend tests cover signatures/expiry, clean redirects, referral fallback,
session continuity, opt-out, cross-site rejection, retries, and client navigation.

All data API requests now also require API_USER/API_KEY credentials. Website server calls, including short-link resolution and analytics ingestion, attach these automatically; see [public API access](PUBLIC_API_ACCESS.md). Staff dashboard routes retain bearer authentication.
