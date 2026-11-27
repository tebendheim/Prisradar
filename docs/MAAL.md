# Mål og akseptkriterier (eies av Tom-Elbin – agenter foreslår, men endrer ikke uten godkjenning)

## Hovedmål
Når en bruker søker etter et produkt, skal Prisradar vise prisene fra så mange norske nettbutikker som mulig, korrekt og ferskt.

## Målbare kriterier
1. Dekning: antall aktive butikker i `managed_stores` øker uke for uke (startmål: 100, deretter 500+).
2. Treffrate: minst 60 % av butikk-kjøringer i `store_quality_v1` gir pristilbud for relevante søk.
3. Korrekthet: 0 kjente feilpriser (øre/kr, medlemspris, brukt vare) i stikkprøver.
4. Ferskhet: tilbud som vises øverst er sjekket siste 24 timer.
5. Kostnad: 0 kr ekstra – kun gratis tiers (GitHub Actions innenfor 2000 min/mnd slik at repoet kan være privat, Supabase free, Cloudflare free).
6. Etterlevelse: robots.txt og rate limits respekteres alltid.
