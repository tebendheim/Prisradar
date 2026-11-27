# Oppsett av Prisradar

Se README.md for oversikt og CLAUDE.md for arbeidsregler.

## 1. Database (Supabase Free)
Rekkefølge, både for ny og eksisterende database. Kjør i Supabase SQL Editor:
1. Ny database: kjør `supabase/schema.sql` én gang. Eksisterende database: hopp over dette.
2. Kjør deretter alle filer i `supabase/migrations/` i nummerrekkefølge (`2026112701.sql`, `2026112702.sql` ...). Filene er idempotente. Hvis en feiler: rett årsaken og kjør samme fil på nytt.
3. Løse `.sql`-filer i `supabase/`-roten (for eksempel `upgrade_20261126.sql`, `search_v2.sql`, `recovery_20261127.sql`) er historiske og skal ikke kjøres på nytt, bortsett fra det `supabase/migrations/README.md` eksplisitt krever for eldre databaser.
4. Slå av offentlig registrering under Authentication, opprett en bruker og legg brukerens UUID i `public.members` med rolle `admin` (eksempel nederst i `schema.sql`).
5. Verifiser: `schema_health_v1` skal returnere `ready: true` og siste versjon. Crawler og admin-siden nekter å kjøre ellers.

Legg Supabase-prosjektets URL og publishable key i `web/config.js` (offentlige verdier). Service role-nøkkelen skal aldri inn i kode.

## 2. GitHub Actions
Secrets (Settings > Secrets and variables > Actions):
- `SUPABASE_URL`
- `SUPABASE_SERVICE_ROLE_KEY`
- `AFFILIATE_FEEDS_JSON` (valgfri, kun for partnerfeeder du har tillatelse til å bruke)

Uten de to første hoppes crawl over (regnes ikke som vellykket).

## 3. Cloudflare Pages (Free)
Koble repoet, branch `main`, ingen build-kommando, output-mappe `web`. Funksjonene i `functions/` brukes automatisk. Sett disse miljøvariablene (Settings > Variables and Secrets), hemmelige som Secret:
- `SUPABASE_URL`
- `SUPABASE_PUBLISHABLE_KEY`
- `GITHUB_APP_ID`
- `GITHUB_INSTALLATION_ID`
- `GITHUB_APP_PRIVATE_KEY` (Secret, PEM)

Sett Site URL i Supabase Auth til den publiserte HTTPS-adressen.

## 4. GitHub App (for admin-knappen "Start indeksering")
Opprett en GitHub App med repository-tillatelsen Actions: Read and write (`actions:write`). Installer den på dette repoet, og bruk App ID, installasjons-ID og privat nøkkel i Cloudflare-variablene over.

## 5. Timeplan og Actions-budsjett
- Bounded crawl (`crawl.yml`): hver 4. time (`17 */4 * * *`), timeout 8 min.
- Store discovery (`store-discovery.yml`): daglig (`43 4 * * *`), timeout 6 min.
- Offline quality checks (`quality.yml`): ved push til `main` og pull request, timeout 3 min.

Privat repo har 2000 gratis min/mnd. Verste fall planlagt: 1488 + 186 = 1674 min. Manuelle kjøringer: maks 10 per 30 dager à 8 min = 80 min (begrenses i databasen, se siste migrering). Til sammen maks 1760, og 240 min er igjen til quality. `crawler/test_actions_budget.py` stopper CI hvis dette overskrides. Mer kapasitet skal komme fra mer effektive kjøringer, ikke flere.

## 6. Når repoet gjøres privat
- Cloudflare Pages: gi Cloudflare GitHub-tilgang til det private repoet (GitHub-integrasjonen), og sjekk at prosjektet fortsatt bygger og deployer.
- GitHub App: kontroller at installasjonen dekker det private repoet og har `actions:write`.
- Repo-navnet i `functions/api/crawler.js` (`repo`-konstanten, nå `tebendheim/Prisradar`) må stemme med faktisk eier/navn; lenker i `web/app.js` bør samsvare.
- Sjekk at Actions-secrets finnes, og kjør "Bounded crawl" manuelt én gang.

## 7. Verifisering
Test med en anonym forespørsel, en innlogget ikke-medlem og et invitert medlem før du stoler på oppsettet.

Begrensninger: ingen sjekk av kasse, ingen dynamisk rendering, ingen automatisk prisvarsling (kun lagrede ønsker), frakt er ukjent med mindre den er dokumentert.
