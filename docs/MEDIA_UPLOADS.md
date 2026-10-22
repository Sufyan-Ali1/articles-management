# Article image uploads

Set `CLOUDINARY_CLOUD_NAME`, `CLOUDINARY_API_KEY`, and `CLOUDINARY_API_SECRET` in the backend environment. Never put the secret in a Vite/frontend environment variable. Run `alembic upgrade head` before starting the updated API, then restart it. The new `media_assets` table tracks uploads, including interrupted uploads and deletion retries.

## API

- `POST /api/v1/media/images`: authenticated admin/editor/author upload. Send raw image bytes with an image Content-Type, not JSON or multipart. Returns `{data: {secure_url, public_id}}`. JPEG, PNG, GIF, and WebP only, default maximum 2 MiB (also bounded by MAX_BODY_BYTES). The server checks file signatures; Cloudinary decodes the uploaded image and enforces allowed formats. SVG is excluded. Existing mutation rate limits apply.
- `POST /api/v1/media/cleanup`: admin-only maintenance endpoint, at most ten assets per call. It also runs automatically every 15 minutes inside each API process when Cloudinary credentials are configured. Database locking coordinates article writes and cleanup across processes.

## Editor behavior

Both featured images and content images upload immediately on file selection, through the authenticated backend to Cloudinary. The backend keeps the API secret private. The editor uses the returned HTTPS URL and prevents article save/publish while an upload is active. Inline images must be inserted after uploading. Saving persists the featured image URL and HTML image URLs using the existing article contract.

Removing an image in the editor never immediately destroys it. Until the article is saved, its saved references are unchanged. After successful create/update/delete, the backend checks both featured and inline image references across all saved articles, including drafts and archived articles. Images used elsewhere remain protected. Replacing the featured image follows the same rules.

Uploads that were never saved, abandoned uploads, and images no longer referenced by any saved article become eligible for deletion after 24 hours (`MEDIA_CLEANUP_GRACE_HOURS`). The worker rechecks all saved references before deletion, requests CDN invalidation, and retains a tombstone so a stale tab cannot save a deleted image URL. A failed provider request stays pending for retry; the article save itself does not depend on Cloudinary deletion succeeding. Failed/rolled-back article saves do not release their existing images. Cleanup only targets assets registered by this API, never arbitrary pasted external URLs or unrelated Cloudinary assets.

Long-lived unsaved drafts can outlive the grace period: if an image expires, upload it again. Cleanup requires the API process to be running; it resumes on restart. Each sweep handles at most ten old unused images; run the authenticated maintenance endpoint to drain a large backlog faster. CDN invalidation is asynchronous.

## Verification

Unit tests mock Cloudinary; no live Cloudinary credentials are needed. Full database tests require the repository's disposable PostgreSQL test database setup. A real upload smoke test requires configured credentials and the applied migration.
