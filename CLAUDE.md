# Prisradar – arbeidsregler for Claude Code

## Mål
Finne flest mulig korrekte, ferske NOK-priser hos norske nettbutikker for produktene brukerne søker etter.
Detaljerte mål og akseptkriterier: `docs/MAAL.md`. Arbeidsliste: `docs/BACKLOG.md`.

## Arkitektur
- `crawler/` – Python 3.12, kun standardbibliotek. Kjøres av GitHub Actions (`.github/workflows/crawl.yml`) hver 4. time; butikkoppdagelse én gang i døgnet.
- `supabase/migrations/` – SQL-migreringer, nummerert `YYYYMMDDNN.sql`. `schema_health_v1` og `demand.py` krever siste versjon.
- `functions/` – Cloudflare Pages Functions. `web/` – frontend (Cloudflare Pages).

## Faste regler (brytes aldri)
- Respekter robots.txt, Crawl-delay og 401/403/429. Ingen omgåelse av botbeskyttelse, ingen falsk nettleser-identitet, ingen proxyer.
- Lagre aldri gjettede priser. Kun eksplisitt NOK, `price_kind` = `exact` eller `from`.
- Ingen hemmeligheter i kode, logger eller commits. `.env` leses aldri av agenter.
- Ingen nye betalte tjenester, API-er eller avhengigheter. Ikke kjør Claude Code i GitHub Actions (krever API-nøkkel = kostnad).
- GitHub Actions: repoet skal kunne være privat (2000 gratis min/mnd, hver jobb rundes opp til hele minutter). `crawler/test_actions_budget.py` stopper CI hvis planlagte workflows kan bruke mer enn 1700 min/mnd i verste fall. Hver jobb må ha `timeout-minutes`. Mer kapasitet hentes ved å gjøre hver kjøring mer effektiv, ikke ved flere kjøringer eller parallelle jobber.
- Hver endring: tester først/samtidig. `python -m unittest discover -s crawler` skal være grønn før commit (CI stopper ellers crawleren).
- Ny databaseendring = ny migreringsfil + oppdatert `schema_health_v1` + oppdatert versjonskrav i `demand.py` og `functions/api/crawler.js`.

## Arbeidsflyt
Start med `claude --agent prosjektleder` (eller `/sprint` i en vanlig økt). Spesialister i `.claude/agents/`:
- `prosjektleder` – planlegger, delegerer, committer (hovedøkten)
- `implementerer` – kode i `crawler/`, `functions/`, `web/` med tester
- `database-utvikler` – migreringer, RPC-er og RLS i `supabase/`
- `tester` – kjører/skriver tester, GODKJENT/AVVIST, endrer ikke produksjonskode
- `sikkerhet` – sikkerhetsgjennomgang, GODKJENT/AVVIST, endrer ikke kode
- `forbruksvakt` – rapporterer Claude-forbruk mot grensen

## Claude-forbruk (maks 20 % av ukeforbruket)
Statuslinjen viser `Prisradar X%/20% av uka`. Hooks i `.claude/settings.json` varsler ved 75 % av budsjettet og blokkerer nye meldinger og underagenter ved 100 %. Logg: `.claude/usage/ledger.json` (gitignored). Rapport: `python3 .claude/hooks/usage_tracker.py report`. Overstyr midlertidig: `touch .claude/usage/override`. Endre grense: miljøvariabel `PRISRADAR_USAGE_LIMIT`.

## Lokal kjøring
- Offline tester: `python -m unittest discover -s crawler`
- Mot ekte Supabase: legg `SUPABASE_URL` og `SUPABASE_SERVICE_ROLE_KEY` i `.env` (gitignored), kjør `set -a; . ./.env; set +a; PAGE_BUDGET=20 python crawler/demand.py`

## Supabase via MCP
`.mcp.json` kobler Claude til Supabase-prosjektet (OAuth, ingen nøkler i repo). Første gang: kjør `/mcp` og logg inn.
- Lesing (`list_tables`, `list_migrations`, `get_advisors`, `get_logs`, `search_docs`) er tillatt uten spørsmål.
- `apply_migration` og `execute_sql` krever brukerens godkjenning hver gang. Bare prosjektleder anvender migreringer, og bare filer fra `supabase/migrations/` som er godkjent av `tester` og `sikkerhet`.
- Rekkefølge: migrering anvendes og `schema_health_v1` er `ready` → først da pushes kode som krever ny versjon.
- Aldri `execute_sql` for å slette eller endre data eller skjema. All skjemaendring går via migreringsfil.
