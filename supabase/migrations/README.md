# Database migrations

Current required version: `2026112701`.

For existing installations with `upgrade_20261126.sql` applied, run `2026112701.sql` in the Supabase SQL editor. It includes the recovery SQL and records the version in the same transaction. If it fails, do not mark the version manually. For fresh installations, the original schema, API, crawl control, crawl v2, quota v3, demand v1 and upgrade 20261126 are prerequisites.

Future changes: create a new immutable numbered SQL migration, include its version record in the same transaction, update schema_health_v1 checks, update the required version in functions/api/crawler.js and crawler/demand.py, and update the admin migration link in web/app.js. Apply and verify the database migration before releasing dependent code. The status RPC is restricted to administrators and service_role. The checks verify selected objects and version, not all permissions or function semantics. No database credentials should be committed. Manual starts are blocked before quota reservation when the check fails; scheduled runs still consume startup time.
