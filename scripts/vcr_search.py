#!/usr/bin/env python3
"""
Volvo Car Retail (volvocarretail.se) - kombi/wagon-bevakning.

Till skillnad från Bilia respekterar den här sidan INTE query-parametrar
(carType=/facility=) via ett vanligt GET-anrop - filtren är JS-widgets som
inte slår igenom server-side. Det som FAKTISKT filtrerar server-side är
modell-specifika sökvägar (samma mönster som fungerar för Bilia), så vi
hämtar varje kombi-modell för sig och filtrerar pris/anläggning själva.

Körs via GitHub Actions på schema, se .github/workflows/vcr_search.yml.
"""
from __future__ import annotations

import json
import re
import sys
import time
import traceback
from datetime import datetime, timezone
from pathlib import Path

import httpx
from bs4 import BeautifulSoup

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/125.0 Safari/537.36"
)
BASE = "https://www.volvocarretail.se"

# Kombi/wagon-modellerna vi bryr oss om (server-side filtrerande sokvagar)
MODEL_PATHS = [
    "volvo/v60",
    "volvo/v60-cross-country",
    "volvo/v70",
    "volvo/v90",
    "volvo/v90-cross-country",
]

PRICE_TO = 200_000  # Antons uttalade tak for volvocarretail specifikt
TARGET_FACILITY_SUBSTR = "kungsängen"  # matchas mot kortets "facility"-text
MAX_PAGES_PER_MODEL = 4

RESULTS_DIR = Path("results")
CACHE_FILE = RESULTS_DIR / "vcr_cache.json"
OUT_JSON = RESULTS_DIR / "vcr_latest.json"
OUT_MD = RESULTS_DIR / "vcr_latest.md"
ERROR_MD = RESULTS_DIR / "vcr_last_error.md"


def load_cache() -> dict:
    if CACHE_FILE.exists():
        return json.loads(CACHE_FILE.read_text(encoding="utf-8"))
    return {}


def save_cache(cache: dict) -> None:
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    CACHE_FILE.write_text(json.dumps(cache, ensure_ascii=False, indent=2), encoding="utf-8")


def fetch(url: str) -> httpx.Response:
    return httpx.get(url, headers={"User-Agent": USER_AGENT}, follow_redirects=True, timeout=30)


def parse_cards(html: str) -> list[dict]:
    soup = BeautifulSoup(html, "html.parser")
    cards = []
    for li in soup.select("li[data-productname]"):
        link = li.select_one("h2 a")
        if not link or not link.get("href"):
            continue
        href = link["href"]
        code = href.rstrip("/").split("/")[-1]
        model_text = link.get_text(" ", strip=True)
        trim_code = (li.select_one("h2 span") or {}).get_text(strip=True) if li.select_one("h2 span") else ""
        trim_full = (li.select_one(".details p") or li.select_one("p") or {}).get_text(strip=True) if (li.select_one(".details p") or li.select_one("p")) else ""
        facility = (li.select_one(".facility") or {}).get_text(strip=True) if li.select_one(".facility") else None

        year = None
        mileage = None
        inner = li.select_one(".details div div")
        if inner:
            direct_spans = inner.find_all("span", recursive=False)
            if len(direct_spans) >= 1:
                year_txt = direct_spans[0].get_text(strip=True)
                year_m = re.match(r"(19|20)\d{2}$", year_txt)
                year = int(year_txt) if year_m else None
            if len(direct_spans) >= 2:
                strong = direct_spans[1].find("strong")
                if strong:
                    mileage = int(re.sub(r"\D", "", strong.get_text()))

        badge = (li.select_one(".alert") or {}).get_text(strip=True) if li.select_one(".alert") else None

        price_el = li.select_one(".price mark")
        price = int(re.sub(r"\D", "", price_el.get_text())) if price_el else None

        cards.append({
            "code": code,
            "url": BASE + href if href.startswith("/") else href,
            "heading": model_text,
            "trim_code": trim_code,
            "trim": trim_full,
            "facility": facility,
            "year": year,
            "mileage": mileage,
            "badge": badge,
            "price": price,
        })
    return cards


def has_next_page(html: str) -> bool:
    return "Ladda fler" in html or "?page=" in html


def fetch_model_cards(model_path: str) -> list[dict]:
    all_cards: list[dict] = []
    for page in range(1, MAX_PAGES_PER_MODEL + 1):
        url = f"{BASE}/bilar-i-lager/begagnade/{model_path}" + (f"?page={page}" if page > 1 else "")
        resp = fetch(url)
        if resp.status_code != 200:
            break
        cards = parse_cards(resp.text)
        if not cards:
            break
        all_cards.extend(cards)
        if len(cards) < 20:  # kort sida = sista sidan (20 verkar vara standardsidstorleken)
            break
        time.sleep(0.5)
    return all_cards


def run() -> None:
    cache = load_cache()
    all_cards: list[dict] = []
    for model_path in MODEL_PATHS:
        all_cards.extend(fetch_model_cards(model_path))

    seen_codes: set[str] = set()
    deduped = []
    for c in all_cards:
        if c["code"] not in seen_codes:
            seen_codes.add(c["code"])
            deduped.append(c)

    candidates = [
        c for c in deduped
        if c.get("price") is not None and c["price"] <= PRICE_TO
    ]

    now_iso = datetime.now(timezone.utc).isoformat()
    new_cache = {}
    for c in candidates:
        code = c["code"]
        already = code in cache
        entry = {**cache.get(code, {}), **c, "is_new": not already,
                 "is_kungsangen": bool(c.get("facility") and TARGET_FACILITY_SUBSTR in c["facility"].lower())}
        if not already:
            entry["first_seen_at"] = now_iso
        new_cache[code] = entry

    save_cache(new_cache)
    entries = list(new_cache.values())
    entries.sort(key=lambda e: (not e["is_new"], not e["is_kungsangen"], e.get("price") or 0))

    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    OUT_JSON.write_text(json.dumps(entries, ensure_ascii=False, indent=2), encoding="utf-8")
    write_markdown(entries)

    if ERROR_MD.exists():
        ERROR_MD.unlink()


def write_markdown(entries: list[dict]) -> None:
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    new_entries = [e for e in entries if e["is_new"]]
    others = [e for e in entries if not e["is_new"]]

    lines = [
        "# Volvo Car Retail - kombi-bevakning",
        f"_Senast körd: {now} – {len(entries)} bilar (V60/V60CC/V70/V90/V90CC under {PRICE_TO:,} kr)_".replace(",", " "),
        "_📍 = Volvo Car Kungsängen specifikt (din närmaste anläggning)_",
        "",
    ]

    def fmt(e: dict, level: str) -> list[str]:
        loc_tag = " 📍 KUNGSÄNGEN" if e.get("is_kungsangen") else ""
        badge = f" [{e['badge']}]" if e.get("badge") else ""
        out = [f"{level} {e['heading']} {e.get('trim_code','')} – {e['price']} kr – {e.get('facility','?')}{loc_tag}{badge}"]
        out.append(f"{e.get('trim','')} | År: {e.get('year')} | {e.get('mileage')} mil")
        out.append(f"[Öppna annons]({e['url']})")
        out.append("")
        return out

    if new_entries:
        lines.append(f"## 🆕 Nya sedan senast ({len(new_entries)})")
        lines.append("")
        for e in new_entries:
            lines.extend(fmt(e, "###"))
    else:
        lines.append("_Inga nya bilar sedan senaste körning._")
        lines.append("")

    if others:
        lines.append(f"## Övriga just nu ({len(others)})")
        lines.append("")
        for e in others:
            lines.extend(fmt(e, "###"))

    OUT_MD.write_text("\n".join(lines), encoding="utf-8")


def main() -> None:
    try:
        run()
    except Exception:
        RESULTS_DIR.mkdir(parents=True, exist_ok=True)
        ERROR_MD.write_text(
            "# Körningen misslyckades\n\n```\n" + traceback.format_exc() + "\n```\n", encoding="utf-8"
        )
        print(traceback.format_exc(), file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
