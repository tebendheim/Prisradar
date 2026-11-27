# Backlog (vedlikeholdes av prosjektleder)

## Klar
1. DRY_RUN=1-modus i crawleren: henter og parser, men skriver ikke til Supabase – for trygg lokal testing.
2. Kjør `probe_candidates()` igjen i egen tidsluke i `demand.py` (butikkutvidelse er i dag avslått).
3. `crawler/brreg_seed.py`: hent enheter med næringskode 47 og `hjemmeside` fra data.brreg.no, normaliser vertsnavn, legg i `store_candidates`. Med tester.
4. Hev taket på 500 butikker i `store_adapters.py`.
5. `guard_price_jump`: godta ny pris når samme pris er observert to ganger med minst 1 time imellom (Black Friday-fall holdes ellers tilbake for alltid).
6. Del crawlen i flere parallelle Actions-jobber (`strategy.matrix`) når butikklisten passerer ~100.
7. Shopify `suggest.json`: lagre pris direkte når NOK er bekreftet for butikken.
8. Kall `conditional_prices()` og lagre medlemspriser separat.

## Pågår

## Ferdig
