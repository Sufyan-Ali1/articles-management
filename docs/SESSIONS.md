# Persistent browser authentication

Deploy the API and dashboard together. Apply `alembic upgrade head` using migration credentials, then restart the API. This adds `refresh_sessions`; it does not modify existing content. Existing logins need to sign in once to obtain the new cookie.

Configuration:

- `CORS_ORIGINS`: explicitly list dashboard origins, including the port for development. Never use `*` with credentials.
- `REFRESH_SESSION_DAYS=7`: absolute lifetime; rotation does not extend it.
- `REFRESH_COOKIE_SAMESITE=lax`: recommended when API and dashboard share the same site. Use `none` only for genuinely cross-site HTTPS hosting; browsers may block third-party cookies. Prefer custom domains sharing a site or a same-origin proxy.
- `ENVIRONMENT=production`: enables Secure cookies. Production requires HTTPS.
- Development: use `localhost` for both frontend and API, or `127.0.0.1` for both. Do not mix the hostnames.

## Contract

All three POST endpoints require `X-CSRF-Protection: 1`. An Origin, when supplied, must match the API origin or CORS allowlist. The custom header forces browser CORS preflight; it is not a secret. The API allows credentialed CORS for the configured origins only.

- `POST /api/v1/auth/login`: existing JSON credentials and token response, plus `blog_refresh` cookie (HttpOnly, host-only, scoped to `/api/v1/auth`).
- `POST /api/v1/auth/refresh`: no body; sends cookie and returns the existing token envelope. Rotates the opaque refresh token under a database row lock. Only its SHA-256 hash is stored. Previously rotated tokens return 401. Refresh requests are rate limited.
- `GET /api/v1/auth/me`: existing Bearer contract.
- `POST /api/v1/auth/logout`: no body; revokes the cookie's session and clears the cookie, returns 204 even when no session exists.

Use `credentials: "include"` for login, refresh, and logout. Keep access tokens in memory. On startup, refresh and fetch identity before deciding to redirect. A temporary network/server error should offer retry; 401 requires login. Serialize cookie-changing requests across browser tabs (the dashboard uses Web Locks when available), and share refresh attempts within each tab.

New access tokens contain a session ID. Authenticated requests verify the backing session still exists, is unexpired, belongs to an active user, and matches the user's password fingerprint. Logout invalidates these access tokens immediately. Password changes invalidate existing sessions. Legacy access tokens without a session ID remain supported until their normal expiration; they cannot be revoked by the new logout endpoint.

Schedule periodic cleanup of expired rows with `DELETE FROM refresh_sessions WHERE expires_at < now();`. Expired rows are rejected even before cleanup. Rotation rejects old refresh credentials; this implementation does not retain token history or implement refresh-token reuse detection for revoking an entire token family.

Never run integration tests against production. Set `TEST_DATABASE_URL` to a disposable PostgreSQL database ending in `_test`, then run `pytest`; fixtures migrate and truncate test data.
