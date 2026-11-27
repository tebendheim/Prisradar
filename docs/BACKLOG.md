# Backlog (vedlikeholdes av prosjektleder)

## Veikart: bedre enn Prisjakt, innenfor gratisnivåene (målt 2026-11-27)
Status: 11 aktive butikker, 3 med tilbud, 41 tilbud, treffrate 19 % siste 7 dager, 99 av 107 butikkandidater aldri sjekket, database 45 MB av 500 MB.
Prisjakt har tusenvis av butikker, åpent søk uten innlogging, produktsider med prishistorikk, prisvarsel, kategorier, filtrering og butikkvurderinger. Rekkefølgen under gir mest effekt først:
- A. Dekning: sjekk butikkandidater mye raskere (i dag 4 per døgn) og finn flere kandidater.
- B. Treffrate: plattform-API-er (Shopify, WooCommerce, Magento og andre) og bedre søkestier for butikker med «no matching product URLs».
- C. Åpent søk uten innlogging, med misbruksvern (krever brukerens beslutning).
- D. Live-søk i Cloudflare Function (punkt 9), som gir svar på sekunder.
- E. Produktside med delbar URL, prishistorikk og laveste pris siste 30 dager (punkt 1), og SEO for trafikk.
- F. Prisvarsler i appen (punkt 2), filtrering (på lager, frakt inkludert, butikk) og kategorier.
- G. Butikkvurdering basert på egne målinger (ferskhet, treff, feilrate).
- H. Forbruksmåleren for Claude teller ikke (viser 0 %). Må fikses så 20 %-grensen holdes.

## Klar
1. Prishistorikk i UI: RPC `price_history_v1` og «laveste pris siste 30 dager» per produkt (dataene finnes allerede i `price_history`).
2. Prisvarsler i appen: RPC `watch_hits_v1` (lagrede ønsker mot laveste ferske pris), merke og liste ved innlogging. E-post og push er utenfor rammen, fordi det ikke er gratis eller trygt.
4. Mer gjennomstrømning del 2: hopp over uendrede sider (ETag/Last-Modified, krever migrering for `crawl_pages`), og la `adapter_quality` slutte å revurdere de samme butikkene uten tilbud hver kjøring.
5. Medlemspriser også fra feeder, Shopify/Woo-API og mikrodata (i dag bare JSON-LD via `extract()`).
7. Cache GitHub-runs i `functions/api/crawler.js` (15–30 s), slik at admin-UI-polling ikke bruker opp GitHub API- og Cloudflare-kvoter.
8. Flytt de historiske SQL-filene i `supabase/`-roten til `supabase/archive/`, slik at ingen kjører gamle funksjonsversjoner ved et uhell.
9. (Stor, egen sprint, krever brukerens godkjenning av nøkkel i Cloudflare) Live-søk i Cloudflare Function mot butikker med verifisert JSON-søk, robots-status fra Supabase og takt per butikk. Det gir størst fartsgevinst og bruker null Actions-minutter.

## Pågår

## Ferdig
- 2026-11-27 A: Parallell, tidsstyrt butikkoppdagelse (fra 4 til 150+ kandidater per kjøring), 58 kuraterte norske butikker, kandidater fra lenker (maks 10 aktiveringer per kjøring), eksakt butikktak, felles klokke i `discovery_job.py`
- 2026-11-27 B: Plattformdeteksjon og søk (Shopify, WooCommerce, Magento, Squarespace, SearchAction/OpenSearch), slug-lenker, modellnummer-matching, filter for brukt/demo/tilbehør. API-er gir bare URL-er, og prisen verifiseres alltid via produktsidens JSON-LD i NOK
- 2026-11-27 Mer arbeid per Actions-minutt: tidlig avslutning når det ikke er noe å gjøre, tidsstyrt søkeløkke (390 s), lås per host (12 tråder, aldri parallelt mot samme butikk), 20 butikker per katalogkjøring
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
