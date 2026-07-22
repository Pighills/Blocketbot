# Blocketbot

Bevakar Blocket automatiskt efter begagnade Volvo V50/V60/V70 inom valt
pris, årsmodell och område, och flaggar kända riskord i annonstexten
(kamrem, växellåda, rost m.m.).

## Hur det funkar

- `.github/workflows/search.yml` kör `scripts/search.py` en gång per dag
  via GitHub Actions (helt automatiskt, ingen manuell körning behövs).
- Scriptet söker via [blocket_api](https://pypi.org/project/blocket-api/),
  ett öppet Python-bibliotek som pratar med Blockets egna sök-API.
- Resultatet skrivs till `results/latest.md` (läsbar sammanfattning) och
  `results/latest.json` (strukturerad data), och committas tillbaka
  automatiskt av workflowet.
- `results/seen_ids.json` håller koll på vilka annonser som redan visats,
  så bara nya annonser flaggas som "nya" vid varje körning.

## Justera sökkriterier

Ändra konstanterna högst upp i `scripts/search.py`:

- `TARGET_MODELS` – vilka modeller (default V50/V60/V70)
- `PRICE_TO` / `YEAR_TO` – pris- och årstak
- `ALLOWED_PLACES` – vilka orter som räknas som "inom räckhåll"
- `RISK_KEYWORDS` – vilka ord som flaggas i annonstexten

## Köra manuellt

Gå till fliken **Actions** i repot → **Blocket Volvo-bevakning** →
**Run workflow**, för att köra en sökning direkt istället för att vänta
på schemat.

## Not

Det här bygger på ett inofficiellt, öppet bibliotek – inte en officiell
Blocket-integration. Om Blocket ändrar sin sajt kan sökningen eller
annonstext-hämtningen sluta fungera tillfälligt tills biblioteket
uppdateras.
