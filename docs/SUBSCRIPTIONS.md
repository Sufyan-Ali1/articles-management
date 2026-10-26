# Subscriptions

Public signup:

```http
POST /api/v1/subscriptions
Content-Type: application/json

{"email": "reader@example.com"}
```

Returns HTTP 202 with `{"data":{"message":"Thank you for subscribing."}}` after
saving the email. The same response is returned for an existing subscriber.
Invalid or missing emails return 422. Emails are trimmed, validated, and normalized
to lowercase. A unique database constraint prevents duplicate rows even for
concurrent signups. Repeated signup preserves the original subscription time.

Only the email, a generated UUID, and `created_at` are stored. This does not create
a user account. No confirmation email or blog notifications are sent.

`GET /api/v1/admin/subscriptions` requires an admin token and returns the standard
paginated response. It supports `page`, `page_size`, email `search`, and sorting
by `email` or `created_at` (prefix with `-` for descending).

Public signups use the existing `SUBMISSIONS_PER_TEN_MINUTES` and
`SUBMISSIONS_PER_DAY` per-IP limits (defaults: 5 per ten minutes, 20 per day),
with separate counters from article requests. Exceeding a limit returns 429 and
`Retry-After`.

The combined migration `0005_pending_features` includes this feature and has not
been run; apply pending migrations together when ready,
before deploying the updated API.

The website uses this endpoint through its same-origin server gateway from every
signup placement. Set API_BASE_URL and matching API_USER/API_KEY on the website
server and backend, as documented in [public API access](PUBLIC_API_ACCESS.md).
Browser success requires a valid 202 envelope; failures retain the address and
429 responses display a Retry-After countdown. Browser clients do not receive
backend API credentials.
