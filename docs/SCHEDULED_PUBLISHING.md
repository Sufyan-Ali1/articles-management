# Scheduled publishing

Migration `0005_pending_features` adds a nullable timezone-aware timestamp,
status constraint and due-date index. It has not been run. Apply it with your
other pending migrations before deploying this version.

Admins and editors can schedule an existing draft (or reschedule an existing
schedule):

```http
POST /api/v1/articles/{id}/schedule
Content-Type: application/json
Authorization: Bearer <token>
X-CSRF-Protection: 1

{"scheduled_publish_at": "2026-12-01T09:00:00+05:00"}
```

The timestamp must include a timezone and be in the future. It is normalized to
UTC. The response uses the existing admin article shape, with `status: scheduled`
and `scheduled_publish_at`. Admin list and detail responses include this field;
admin lists accept `status=scheduled`. Scheduled articles are hidden from public
endpoints. Authors cannot schedule or edit scheduled articles.

`DELETE /api/v1/articles/{id}/schedule` cancels a schedule and returns the article
to draft. The existing publish endpoint can publish it immediately, clearing its
schedule. Updating status to draft or archived also clears its schedule. Scheduling
published or archived articles returns 409; unpublish or restore to draft first.
Use the schedule endpoint rather than setting `status=scheduled` through PATCH.

The API runs a background poller automatically. `ARTICLE_SCHEDULER_ENABLED`
defaults to `true`; `ARTICLE_SCHEDULER_INTERVAL_SECONDS` defaults to `30`.
Publication normally happens within one polling interval, subject to database
availability and workload (100 articles are checked per poll). Keep at least one
API process running. Overdue schedules are processed after a restart. Database
locks prevent concurrent processes from publishing the same schedule twice.

Publication readiness is checked when scheduling, when editing scheduled content,
and again when the schedule is due. If the author or classifications have become
inactive, the article stays scheduled and a warning is logged; repair the cause,
reschedule, or cancel it. Failed attempts retry on later polls. Automatic publication
writes an `article.publish` audit entry with `details.scheduled=true` and no acting
user, and sends the existing Next.js revalidation notification. As with manual
publishing, a previously published article retains its original `published_at`.
