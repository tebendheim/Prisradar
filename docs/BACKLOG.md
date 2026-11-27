# Backlog (vedlikeholdes av prosjektleder)

## Klar
1. Prishistorikk i UI: RPC `price_history_v1` og «laveste pris siste 30 dager» per produkt (dataene finnes allerede i `price_history`).
2. Prisvarsler i appen: RPC `watch_hits_v1` (lagrede ønsker mot laveste ferske pris), merke og liste ved innlogging. E-post og push er utenfor rammen, fordi det ikke er gratis eller trygt.
4. Mer gjennomstrømning per Actions-minutt (ikke parallelle jobber, fordi de ganger minuttforbruket): flere butikker per kjøring innenfor samme timeout, hopp over uendrede sider (ETag/Last-Modified), og la en planlagt kjøring avslutte tidlig når det ikke er noe å gjøre.
5. Medlemspriser også fra feeder, Shopify/Woo-API og mikrodata (i dag bare JSON-LD via `extract()`).
7. Cache GitHub-runs i `functions/api/crawler.js` (15–30 s), slik at admin-UI-polling ikke bruker opp GitHub API- og Cloudflare-kvoter.
8. Flytt de historiske SQL-filene i `supabase/`-roten til `supabase/archive/`, slik at ingen kjører gamle funksjonsversjoner ved et uhell.
9. (Stor, egen sprint, krever brukerens godkjenning av nøkkel i Cloudflare) Live-søk i Cloudflare Function mot butikker med verifisert JSON-søk, robots-status fra Supabase og takt per butikk. Det gir størst fartsgevinst og bruker null Actions-minutter.

## Pågår

## Ferdig
- 2026-11-27 `DRY_RUN=1`: crawleren henter og parser, men alle skrivinger til Supabase blokkeres og logges uten hemmeligheter
- 2026-11-27 Butikktaket hevet fra 500 til 2000 (`MAX_STORES`), og butikklister leses med paginering (`db_all`) forbi PostgREST-grensen på 1000 rader
- 2026-11-27 Claude Code-team (prosjektleder, implementerer, database-utvikler, tester, sikkerhet, forbruksvakt) og 20 %-forbruksgrense
- 2026-11-27 Actions-budsjett for privat repo: crawl hver 4. time, oppdagelse daglig, maks 10 manuelle kjøringer per 30 dager (migrering 2026112708), budsjettest i CI
- 2026-11-27 Versjonskrav synkronisert (2026112708) med test, og `schema_health_v1` sjekker offers-kolonnene
- 2026-11-27 Medlemspriser lagres fra JSON-LD (`conditional_prices()`)
- 2026-11-27 Kanttilfelle-tester (50 → 225) og 3 parserfeil rettet (`offers: null`, ikke-ASCII-sifre, rabattkode med stor forbokstav)
- 2026-11-27 CSP i `web/_headers`, quality.yml kjører ikke to ganger, SETUP.md og README skrevet om
- 2026-11-27 probe_candidates i egen workflow (e92adc2)
- 2026-11-27 BRREG-seeding av kandidater (f3aa297)
- 2026-11-27 guard_price_jump godtar gjentatt pris etter 1 time (f18714a, migrering 2026112707)
- 2026-11-27 Shopify suggest.json / plattform-API-er i søkerangering (6840b2f)
