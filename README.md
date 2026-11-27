# Prisradar

Prisradar finner de beste prisene hos norske nettbutikker, raskt og uten systemkostnader. Kun eksplisitte NOK-priser lagres (`price_kind` er `exact` eller `from`), aldri gjettede priser. Medlemspriser lagres separat og blir aldri hovedpris.

## Arkitektur
- `crawler/`: Python 3.12, kun standardbibliotek. Kjøres av GitHub Actions (crawl hver 4. time, butikkoppdagelse daglig). Respekterer robots.txt, Crawl-delay og 401/403/429.
- `supabase/`: Postgres med RLS, SQL-migreringer i `supabase/migrations/` og RPC-er. Supabase Free.
- `functions/`: Cloudflare Pages Functions (admin-API som starter crawl via GitHub App).
- `web/`: statisk frontend uten byggesteg, publisert på Cloudflare Pages.

Alt holdes innenfor gratisnivåene til GitHub Actions, Supabase og Cloudflare.

## Kom i gang
- Installasjon og drift: [SETUP.md](SETUP.md)
- Arbeidsregler og utviklerflyt: [CLAUDE.md](CLAUDE.md)
- Offline tester: `python3 -m unittest discover -s crawler`
