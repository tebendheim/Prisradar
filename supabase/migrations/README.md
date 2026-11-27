# Database migrations

Current required version: `2026112708`.

Procedure: run the numbered migrations (`2026112701.sql` onwards) in order in the Supabase SQL Editor. Each file records its version in the same transaction. If one fails, do not mark the version manually; fix the cause and rerun that file. The files are idempotent. For fresh installations, the original schema, API, crawl control, crawl v2, quota v3, demand v1 and upgrade 20261126 are prerequisites.

`2026112708.sql` limits manual crawl starts to 3 per 24 hours (5 with extra) and 10 per 30 days, to keep GitHub Actions within 2000 min/month for a private repo (scheduled jobs up to 1674 min plus 10 manual runs of up to 8 min). The first line `-- actions-budget: manual_runs_per_30d=10 minutes_per_run=8` is read by crawler/test_actions_budget.py.

Future changes: create a new immutable numbered SQL migration, include its version record in the same transaction, update schema_health_v1 checks, update the required version in functions/api/crawler.js and crawler/demand.py, and update the admin migration link in web/app.js. Apply and verify the database migration before releasing dependent code. The status RPC is restricted to administrators and service_role. The checks verify selected objects and version, not all permissions or function semantics. No database credentials should be committed. Manual starts are blocked before quota reservation when the check fails; scheduled runs still consume startup time.
