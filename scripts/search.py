#!/usr/bin/env python3
"""
Blocket Volvo V50/V60/V70-bevakning.

Söker begagnade Volvo V50/V60/V70 inom valt område och prisklass, hämtar
annonstext för NYA träffar (jämfört med förra körningen), flaggar kända
riskord, och skriver resultat till results/latest.json + results/latest.md.

Körs via GitHub Actions på schema, se .github/workflows/search.yml.
Bygger på det öppna biblioteket "blocket_api" (pip install blocket-api),
som i sin tur pratar direkt med blocket.se:s egna interna sök-API.
"""
from __future__ import annotations

import json
import sys
import time
import traceback
from datetime import datetime, timezone
from pathlib import Path

from blocket_api import BlocketAPI, CarModel, CarSortOrder, Location
from blocket_api.ad_parser import CarAd

# ---------------------------------------------------------------------------
# Sökkriterier - justera här om du vill ändra pris/år/modeller/område
# ---------------------------------------------------------------------------
TARGET_MODELS = {"V50", "V60", "V70"}
PRICE_TO = 100_000
YEAR_TO = 2018

# Orter vi räknar som "inom ca en timme från Upplands-Bro" (inkl. gränsfall)
ALLOWED_PLACES = {
    "Stockholm", "Sundbyberg", "Solna", "Järfälla", "Upplands Väsby",
    "Sollentuna", "Sigtuna", "Märsta", "Ekerö", "Vallentuna",
    "Upplands-Bro", "Kungsängen", "Bro",
    "Håbo", "Bålsta", "Enköping", "Knivsta", "Uppsala",
    "Södertälje", "Norrtälje",
    "Strängnäs", "Västerås",
}

# Län vi söker brett inom (filtreras sen ner till ALLOWED_PLACES ovan)
SEARCH_LOCATIONS = [
    Location.STOCKHOLM,
    Location.UPPSALA,
    Location.SODERMANLAND,
    Location.VASTMANLAND,
]

# Ord vi flaggar i annonstexten - bara en varningsflagga, ingen fulldiagnos
RISK_KEYWORDS = [
    "kamrem", "kamkedja", "växellåda", "rost", "ägare", "oljeläck",
    "kompressor", "krockskadad", "ej godkänd", "anmärkning",
]

MAX_DETAIL_FETCHES = 15  # var snäll mot blocket.se - hämta inte fulltext på för många per körning
DETAIL_FETCH_DELAY_SEC = 1.5

RESULTS_DIR = Path("results")
STATE_FILE = RESULTS_DIR / "seen_ids.json"
OUT_JSON = RESULTS_DIR / "latest.json"
OUT_MD = RESULTS_DIR / "latest.md"
ERROR_MD = RESULTS_DIR / "last_error.md"


def load_seen() -> set[str]:
    if STATE_FILE.exists():
        return set(json.loads(STATE_FILE.read_text(encoding="utf-8")))
    return set()


def save_seen(seen: set[str]) -> None:
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    STATE_FILE.write_text(
        json.dumps(sorted(seen), ensure_ascii=False, indent=2), encoding="utf-8"
    )


def flag_keywords(text: str) -> list[str]:
    text_l = text.lower()
    return [kw for kw in RISK_KEYWORDS if kw in text_l]


def run() -> None:
    api = BlocketAPI()
    seen = load_seen()

    result = api.search_car(
        models=[CarModel.VOLVO],
        locations=SEARCH_LOCATIONS,
        price_to=PRICE_TO,
        year_to=YEAR_TO,
        sort_order=CarSortOrder.PUBLISHED_DESC,
    )

    docs = result.get("docs", [])

    candidates = [
        ad for ad in docs
        if ad.get("model") in TARGET_MODELS and ad.get("location") in ALLOWED_PLACES
    ]

    new_ids = {str(ad["ad_id"]) for ad in candidates if str(ad["ad_id"]) not in seen}

    enriched = []
    detail_fetch_count = 0

    for ad in candidates:
        ad_id = str(ad["ad_id"])
        is_new = ad_id in new_ids
        entry = {
            "ad_id": ad_id,
            "heading": ad.get("heading"),
            "model": ad.get("model"),
            "year": ad.get("year"),
            "price": (ad.get("price") or {}).get("amount"),
            "location": ad.get("location"),
            "regno": ad.get("regno"),
            "seller": ad.get("dealer_segment") or "Privat",
            "url": ad.get("canonical_url"),
            "is_new": is_new,
        }

        if is_new and detail_fetch_count < MAX_DETAIL_FETCHES:
            try:
                detail = api.get_ad(CarAd(int(ad_id)))
                desc = detail.get("description", "") or ""
                entry["description"] = desc
                entry["flags"] = flag_keywords(desc)
                entry["specifications"] = detail.get("specifications", {})
                detail_fetch_count += 1
                time.sleep(DETAIL_FETCH_DELAY_SEC)
            except Exception as e:  # nätverksfel/sidan ändrad etc - visa men krascha inte
                entry["fetch_error"] = str(e)

        enriched.append(entry)

    seen |= {str(ad["ad_id"]) for ad in candidates}
    save_seen(seen)

    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    OUT_JSON.write_text(
        json.dumps(enriched, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    write_markdown(enriched)

    if ERROR_MD.exists():
        ERROR_MD.unlink()


def write_markdown(entries: list[dict]) -> None:
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    new_entries = [e for e in entries if e["is_new"]]
    others = [e for e in entries if not e["is_new"]]

    lines = ["# Blocket V50/V60/V70-bevakning", f"_Senast körd: {now}_", ""]

    if new_entries:
        lines.append(f"## 🆕 Nya sedan senast ({len(new_entries)})")
        lines.append("")
        for e in new_entries:
            lines.append(f"### {e['heading']} – {e['price']} kr – {e['location']}")
            lines.append(
                f"Modell: {e['model']} | År: {e['year']} | "
                f"Regnr: {e.get('regno', '–')} | Säljare: {e['seller']}"
            )
            if e.get("flags"):
                lines.append(f"⚠️ **Flaggade ord:** {', '.join(e['flags'])}")
            if e.get("fetch_error"):
                lines.append(f"_(kunde inte hämta annonstext: {e['fetch_error']})_")
            elif e.get("description"):
                snippet = e["description"][:500].replace("\n", " ")
                lines.append(f"> {snippet}{'...' if len(e['description']) > 500 else ''}")
            lines.append(f"[Öppna annons]({e['url']})")
            lines.append("")
    else:
        lines.append("_Inga nya annonser sedan senaste körning._")
        lines.append("")

    if others:
        lines.append(f"## Övriga matchande annonser i din bevakning ({len(others)})")
        lines.append("")
        for e in others:
            lines.append(
                f"- {e['heading']} – {e['price']} kr – {e['location']} "
                f"({e['year']}) – [Länk]({e['url']})"
            )

    OUT_MD.write_text("\n".join(lines), encoding="utf-8")


def main() -> None:
    try:
        run()
    except Exception:
        RESULTS_DIR.mkdir(parents=True, exist_ok=True)
        ERROR_MD.write_text(
            "# Körningen misslyckades\n\n```\n" + traceback.format_exc() + "\n```\n",
            encoding="utf-8",
        )
        print(traceback.format_exc(), file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
