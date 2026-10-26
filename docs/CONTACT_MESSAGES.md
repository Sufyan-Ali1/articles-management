# Contact form submissions

The live contact page and local frontend contact schema were inspected. The form
uses these fields:

| Field | Rules |
| --- | --- |
| `name` | Optional plain text, up to 150 characters; blank stored as null |
| `email` | Required email, up to 255 characters, normalized to lowercase |
| `reason` | Required: `general`, `correction`, or `privacy` |
| `article_url` | Optional HTTP(S) URL without credentials, up to 2048 characters; stored only for corrections |
| `message` | Required plain text, up to 5000 characters |
| `bot-field` | Optional honeypot; leave empty; submissions with a value are silently discarded |
| `form-name` | Optional hidden field; if supplied, must be `contact` |

## Public endpoint

`POST /api/v1/contact-messages` accepts `application/json` and
`application/x-www-form-urlencoded` with the same field names.

```json
{
  "name": "Reader",
  "email": "reader@example.com",
  "reason": "correction",
  "article_url": "https://askandexplore.com/articles/example",
  "message": "Please check this passage.",
  "bot-field": "",
  "form-name": "contact"
}
```

Success: HTTP 202, `{"data":{"message":"Thank you for getting in touch."}}`.
Invalid data returns 422; unsupported content types return 415. URL-encoded forms
with duplicate keys are rejected. JSON is recommended for API integrations.

The existing submission limits apply independently to contact submissions per IP
(default: 5 per ten minutes, 20 per day). Rate limits include invalid submissions.
Repeated identical submissions from the same IP are suppressed for ten minutes
within one API process using the existing bounded SubmissionGuard. This is not
a permanent or distributed uniqueness guarantee; different messages are retained.

Messages store a UUID, name, email, reason, optional article URL, message, and
creation timestamp. Hidden fields and IP addresses are not stored. Contact messages
do not subscribe the sender, create a user account, or trigger outgoing email.

## Admin access

Admin authentication is required for both endpoints:

- `GET /api/v1/admin/contact-messages`: paginated list. Supports `page`,
  `page_size`, `search` across name/email/message, and `sort` by `created_at`,
  `name`, `email`, or `reason` (prefix `-` for descending).
- `GET /api/v1/admin/contact-messages/{id}`: message detail, or 404 if missing.

## Frontend integration and migration

The frontend posts JSON to its same-origin form gateway. The gateway calls this
backend endpoint with API_USER/API_KEY headers held on the website server. See
[public API access](PUBLIC_API_ACCESS.md) for configuration, visitor-IP handling,
and the exact protected route scope. Configure API_BASE_URL on the website server;
no consumer credentials are sent by the browser.
The frontend has a local math challenge; no CAPTCHA answer is sent or verified
by this backend. The old Netlify form and contact enable flag have been removed.

The combined migration `0005_pending_features` includes this feature and was not
run. Apply all pending migrations together when ready before deploying this
backend version.
