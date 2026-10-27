# Author profiles

Author profiles are separate from login accounts. An article's `author_id` now
selects an `authors` row; `created_by_id` records the account that created it.
Author-role account access continues to be restricted by `created_by_id`, so
selecting another public author never grants ownership of another user's article.

Authenticated staff can list profiles for the article dropdown:

`GET /api/v1/admin/authors?sort=name&page=1&page_size=100`

Only active profiles are returned by default; `include_inactive=true` includes
archived profiles. Pagination and name search use the standard API conventions.
Admins and editors can create/update/delete profiles:

- `POST /api/v1/admin/authors`: `{"name":"Jane Doe","specialization":"AI and technology"}`
- `PATCH /api/v1/admin/authors/{id}`: name, specialization, and/or is_active.
- `DELETE /api/v1/admin/authors/{id}`: unused profiles only; returns 409 for profiles
  referenced by articles. Deactivate referenced profiles instead.

Specialization is free text, not a category relationship. New articles require
`author_id`. Article updates can select another active profile. Missing/inactive
profiles are rejected. Publishing or scheduling also requires an active profile.
Deactivation prevents future selection/publication but preserves existing bylines.

Public article responses keep the `author` object, now populated from the selected
profile with its name and specialization. The website already displays
`article.author.name`, so it will display the chosen profile instead of the creator.
The dashboard article editor includes the dropdown and an inline New author form
for admins/editors.

Migration `0006_author_profiles` is prepared after `0005_pending_features` and has
**not been run**. It renames the old user-linked author column to `created_by_id`,
creates profiles for existing bylines with specialization `General`, and adds the
new author reference. Change those generated specializations after deployment.
Deploy the matching dashboard/backend versions together after explicitly applying
the pending migrations. The new backend requires the new schema to serve articles.
