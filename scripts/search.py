#!/usr/bin/env python3
"""
Blocket Volvo V60-bevakning.

Söker begagnade Volvo V60 inom valt område och prisklass, hämtar
annonstext, flaggar kända riskord, och skriver resultat till
results/latest.json + results/latest.md. Detaljer cachas per annons-id
så samma annons inte hämtas i onödan flera körningar i rad.

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
TARGET_MODELS = {"V60"}
PRICE_TO = 120_000
YEAR_TO = 2019

# Hela Stockholms län räknas (alla kommuner/tätorter), oavsett var i länet.
STOCKHOLM_LAN_PLACES = {
    "Stockholm", "Sundbyberg", "Solna", "Järfälla", "Upplands Väsby",
    "Sollentuna", "Sigtuna", "Märsta", "Rosersberg", "Ekerö",
    "Vallentuna", "Upplands-Bro", "Kungsängen", "Bro",
    "Södertälje", "Norrtälje", "Botkyrka", "Tumba", "Danderyd",
    "Haninge", "Handen", "Huddinge", "Segeltorp", "Flemingsberg",
    "Lidingö", "Nacka", "Nykvarn", "Nynäshamn", "Salem", "Rönninge",
    "Tyresö", "Täby", "Vaxholm", "Värmdö", "Gustavsberg", "Österåker",
    "Åkersberga",
}
# Från Uppsala län räknar vi bara dessa två orter denna gång.
UPPSALA_ALLOWED_PLACES = {"Enköping", "Uppsala"}

# Län vi söker brett inom (filtreras sen ner enligt ovan)
SEARCH_LOCATIONS = [
    Location.STOCKHOLM,
    Location.UPPSALA,
]


def is_allowed_place(place: str | None) -> bool:
    if not place:
        return False
    return place in STOCKHOLM_LAN_PLACES or place in UPPSALA_ALLOWED_PLACES


# Ord vi flaggar i annonstexten - bara en varningsflagga, ingen fulldiagnos
RISK_KEYWORDS = [
    "kamrem", "kamkedja", "växellåda", "rost", "ägare", "oljeläck",
    "kompressor", "krockskadad", "ej godkänd", "anmärkning",
]

MAX_DETAIL_FETCHES = 60  # räcker för ett fullt djupdyk över ~50 träffar
DETAIL_FETCH_DELAY_SEC = 1.5

RESULTS_DIR = Path("results")
CACHE_FILE = RESULTS_DIR / "cache.json"  # ad_id -> full enriched entry, persisted between körningar
OUT_JSON = RESULTS_DIR / "latest.json"
OUT_MD = RESULTS_DIR / "latest.md"
ERROR_MD = RESULTS_DIR / "last_error.md"


def load_cache() -> dict:
    if CACHE_FILE.exists():
        return json.loads(CACHE_FILE.read_text(encoding="utf-8"))
    return {}


def save_cache(cache: dict) -> None:
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    CACHE_FILE.write_text(
        json.dumps(cache, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def flag_keywords(text: str) -> list[str]:
    text_l = text.lower()
    return [kw for kw in RISK_KEYWORDS if kw in text_l]


def run() -> None:
    api = BlocketAPI()
    cache = load_cache()  # ad_id (str) -> tidigare sparad, fullständig post

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
        if ad.get("model") in TARGET_MODELS and is_allowed_place(ad.get("location"))
    ]

    new_cache: dict = {}
    detail_fetch_count = 0
    now_iso = datetime.now(timezone.utc).isoformat()

    for ad in candidates:
        ad_id = str(ad["ad_id"])
        already_cached = ad_id in cache
        basics = {
            "ad_id": ad_id,
            "heading": ad.get("heading"),
            "model": ad.get("model"),
            "model_specification": ad.get("model_specification"),
            "year": ad.get("year"),
            "price": (ad.get("price") or {}).get("amount"),
            "mileage": ad.get("mileage"),
            "mileage_unit": ad.get("mileage_unit"),
            "transmission": ad.get("transmission"),
            "fuel": ad.get("fuel"),
            "location": ad.get("location"),
            "regno": ad.get("regno"),
            "seller": ad.get("dealer_segment") or "Privat",
            "url": ad.get("canonical_url"),
            "published_ts": ad.get("timestamp"),
        }

        if already_cached:
            # Behåll tidigare hämtad annonstext/flaggor - hämta inte igen i onödan
            entry = {**cache[ad_id], **basics, "is_new": False}
        else:
            entry = {**basics, "is_new": True, "first_seen_at": now_iso}
            if detail_fetch_count < MAX_DETAIL_FETCHES:
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

        new_cache[ad_id] = entry

    # new_cache innehåller bara ANNONSER SOM FORTFARANDE MATCHAR just nu -
    # sålda/borttagna annonser faller bort automatiskt här.
    save_cache(new_cache)

    entries = list(new_cache.values())
    entries.sort(key=lambda e: (not e["is_new"], e.get("price") or 0))

    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    OUT_JSON.write_text(
        json.dumps(entries, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    write_markdown(entries)

    if ERROR_MD.exists():
        ERROR_MD.unlink()


def _format_entry(e: dict, heading_level: str) -> list[str]:
    lines = [f"{heading_level} {e['heading']} – {e['price']} kr – {e['location']}"]
    mil = e.get("mileage")
    mil_str = f"{mil} mil" if mil is not None else "okänt miltal"
    lines.append(
        f"Modell: {e['model']} | År: {e['year']} | {mil_str} | "
        f"{e.get('transmission', '–')} | {e.get('fuel', '–')}"
    )
    lines.append(f"Regnr: {e.get('regno', '–')} | Säljare: {e['seller']}")
    if e.get("flags"):
        lines.append(f"⚠️ **Flaggade ord:** {', '.join(e['flags'])}")
    if e.get("fetch_error"):
        lines.append(f"_(kunde inte hämta annonstext: {e['fetch_error']})_")
    elif e.get("description"):
        snippet = e["description"][:500].replace("\n", " ")
        lines.append(f"> {snippet}{'...' if len(e['description']) > 500 else ''}")
    lines.append(f"[Öppna annons]({e['url']})")
    lines.append("")
    return lines


def write_markdown(entries: list[dict]) -> None:
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    new_entries = [e for e in entries if e["is_new"]]
    others = [e for e in entries if not e["is_new"]]

    lines = [
        "# Blocket V60-bevakning",
        f"_Senast körd: {now} – {len(entries)} matchande annonser totalt_",
        "",
    ]

    if new_entries:
        lines.append(f"## 🆕 Nya sedan senast ({len(new_entries)})")
        lines.append("")
        for e in new_entries:
            lines.extend(_format_entry(e, "###"))
    else:
        lines.append("_Inga nya annonser sedan senaste körning._")
        lines.append("")

    if others:
        lines.append(f"## Övriga matchande annonser ({len(others)})")
        lines.append("")
        for e in others:
            lines.extend(_format_entry(e, "###"))

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
