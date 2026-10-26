# Website API access

Configure identical server-side values in the backend (Render or your API host)
and the Next.js website (Vercel or Netlify):

```dotenv
API_USER=askandexplore-website
API_KEY=<a-random-secret-of-at-least-32-characters>
```

API_USER accepts 1–100 visible ASCII characters; API_KEY accepts 32–512. Both
must be set together. Empty values disable public access (503); missing/wrong
request credentials return 401. Comparisons use constant-time functions. Staff
login and admin endpoints continue to work independently. No database migration
is required, and no migrations were run for this change.

Every protected request supplies both headers:

```http
X-API-User: <API_USER>
X-API-Key: <API_KEY>
```

Never put these values in query strings, NEXT_PUBLIC_ variables, VITE_ variables,
or browser code. Generate a strong random key locally (for example, `openssl rand
-hex 32`), then store it in both hosting environments. Rotate both deployments
when changing credentials. Local environment files contain empty placeholders;
production credentials have not been created or configured automatically.

## Scope

Consumer credentials protect:

- GET /api/v1/articles and /api/v1/articles/{slug}
- GET /api/v1/categories, /tags, /article-types and their detail routes
- GET /api/v1/tracking-links/{code}
- POST /api/v1/article-requests, /contact-messages, /subscriptions
- POST /api/v1/analytics/article-views (its existing X-Analytics-Key is also required)

Shared classification GETs alternatively accept an authenticated active staff
bearer token, preserving the dashboard's taxonomy controls. API credentials alone
do not grant inactive taxonomy access, admin actions, user management, media
uploads, or publication rights. Staff endpoints, including staff operations using
/articles, /categories, /users and /media paths, keep their existing bearer/role
authentication and do not require consumer credentials.

/health, /ready, auth/login/refresh/logout, development documentation, and CORS
preflight remain outside the consumer gate. Health checks are needed for service
monitoring; these endpoints do not expose article or subscriber data. OpenAPI
shows the two API headers as an AND requirement, with staff bearer as the taxonomy
alternative. Responses using API credential headers are marked no-store.

## Website integration

The website server attaches credentials to content reads, short-link resolution,
and analytics ingestion. Browser forms call the website's same-origin
/api/v1/{article-requests|contact-messages|subscriptions} gateway, which accepts
POST only to that fixed allowlist. It validates origin, bounds JSON bodies to
64 KiB, strips browser credentials/cookies, attaches server credentials, and
forwards only safe success/validation/rate-limit data. It is not a general proxy
for backend reads or admin actions. Browser requests never carry API_USER/API_KEY.
The existing forms provider now supplies only `/`, not the backend URL.

For IP rate limits, on Vercel the gateway uses the platform's
x-vercel-forwarded-for header; on Netlify it uses x-nf-client-connection-ip. It only
reads those headers when the corresponding platform environment marker is set,
validates the IP, and sends X-Visitor-IP to the backend. The backend trusts that
visitor header only with valid consumer credentials and only on form submissions.
It never trusts an unauthenticated browser-supplied visitor IP. Other hosting
platforms omit forwarding and share connection-IP limits until explicitly integrated.
Vercel header behavior: https://vercel.com/docs/headers/request-headers

The website requires API_BASE_URL plus API_USER/API_KEY at build/deployment time.
Redeploy after changing them. The dashboard needs neither consumer credential;
its website-link setting is now VITE_SITE_URL (formerly VITE_PUBLIC_SITE_URL).
