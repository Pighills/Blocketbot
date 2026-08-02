#!/usr/bin/env python3
"""
Bilia Volvo V60-bevakning.

Söker begagnade Volvo V60 hos Bilia (etablerad handlare - "kvalitetssäkrade"
bilar), filtrerar på pris, och hämtar detaljerad, strukturerad data per bil
via Bilias inbäddade Schema.org JSON-LD (pris, miltal, motor, VIN,
återförsäljarens geo-koordinater m.m.) - ingen skör HTML-skrapning behövs
för detaljsidan, bara för listkorten.

Körs via GitHub Actions på schema, se .github/workflows/bilia_search.yml.
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
BASE = "https://www.bilia.se"
SEARCH_URL = f"{BASE}/bilar/sok-bil/volvo/v60/"

PRICE_TO = 150_000  # Antons uttalade tak för Bilia specifikt (annan klass än Blocket-taket)
MAX_DETAIL_FETCHES = 40
DETAIL_FETCH_DELAY_SEC = 1.0

RESULTS_DIR = Path("results")
CACHE_FILE = RESULTS_DIR / "bilia_cache.json"
OUT_JSON = RESULTS_DIR / "bilia_latest.json"
OUT_MD = RESULTS_DIR / "bilia_latest.md"
ERROR_MD = RESULTS_DIR / "bilia_last_error.md"


def load_cache() -> dict:
    if CACHE_FILE.exists():
        return json.loads(CACHE_FILE.read_text(encoding="utf-8"))
    return {}


def save_cache(cache: dict) -> None:
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    CACHE_FILE.write_text(json.dumps(cache, ensure_ascii=False, indent=2), encoding="utf-8")


def fetch(url: str) -> httpx.Response:
    return httpx.get(url, headers={"User-Agent": USER_AGENT}, follow_redirects=True, timeout=30)


def parse_search_cards(html: str) -> list[dict]:
    soup = BeautifulSoup(html, "html.parser")
    cards = []
    for li in soup.select("li.listlayout__item"):
        link = li.select_one("a.car-card__link")
        if not link or not link.get("href"):
            continue
        href = link["href"]
        code = href.rstrip("/").split("/")[-1].upper()
        brand_span = link.select_one(".car-card__brand")
        full_text = link.get_text(" ", strip=True)
        model_text = full_text.replace(brand_span.get_text(strip=True), "", 1).strip() if brand_span else full_text
        trim = (li.select_one(".car-card__description") or {}).get_text(strip=True) if li.select_one(".car-card__description") else ""
        branch = (li.select_one(".car-card__branch") or {}).get_text(strip=True) if li.select_one(".car-card__branch") else None
        status = (li.select_one(".car-card__car-info .pill__title") or {}).get_text(strip=True) if li.select_one(".car-card__car-info .pill__title") else None

        pills = [p.get_text(strip=True) for p in li.select(".pill-collection__pills .pill__title")]
        fuel = pills[0] if len(pills) > 0 else None
        transmission = pills[1] if len(pills) > 1 else None
        mileage_txt = pills[2] if len(pills) > 2 else None
        year_txt = pills[3] if len(pills) > 3 else None
        mileage = int(re.sub(r"\D", "", mileage_txt)) if mileage_txt else None
        year = int(re.sub(r"\D", "", year_txt)) if year_txt and re.sub(r"\D", "", year_txt) else None

        price_el = li.select_one(".prices__main-price .value")
        price = int(re.sub(r"\D", "", price_el.get_text())) if price_el else None

        cards.append({
            "code": code,
            "url": BASE + href if href.startswith("/") else href,
            "heading": full_text,
            "trim": trim,
            "branch": branch,
            "status": status,
            "fuel": fuel,
            "transmission": transmission,
            "mileage": mileage,
            "year": year,
            "price": price,
        })
    return cards


def parse_detail(html: str) -> dict | None:
    """Extraherar Bilias Schema.org Car-block (JSON-LD) - ren, strukturerad
    data direkt från sidan: pris, miltal (km), motor, VIN, säljare+geo m.m."""
    for m in re.finditer(r'<script[^>]*type="application/ld\+json"[^>]*>(.*?)</script>', html, re.DOTALL):
        try:
            data = json.loads(m.group(1))
        except json.JSONDecodeError:
            continue
        if data.get("@type") == "Car":
            return data
    return None


def has_tow_hitch(meta_desc: str) -> bool:
    return "dragkrok" in (meta_desc or "").lower()


def get_meta_description(html: str) -> str:
    m = re.search(r'<meta name="description" content="([^"]*)"', html)
    return m.group(1) if m else ""


def fetch_all_cards() -> list[dict]:
    resp = fetch(SEARCH_URL)
    resp.raise_for_status()
    return parse_search_cards(resp.text)


def run() -> None:
    cache = load_cache()
    cards = fetch_all_cards()

    candidates = [c for c in cards if c.get("price") is not None and c["price"] <= PRICE_TO]

    new_cache: dict = {}
    detail_fetch_count = 0
    now_iso = datetime.now(timezone.utc).isoformat()

    for c in candidates:
        code = c["code"]
        already_cached = code in cache
        entry = {**cache.get(code, {}), **c, "is_new": not already_cached}
        if not already_cached:
            entry["first_seen_at"] = now_iso

        if detail_fetch_count < MAX_DETAIL_FETCHES:
            try:
                resp = fetch(c["url"])
                detail_fetch_count += 1
                time.sleep(DETAIL_FETCH_DELAY_SEC)
                if resp.status_code == 404:
                    continue  # borttagen/sald - hoppa, lagg inte i new_cache
                resp.raise_for_status()
                html = resp.text
                schema = parse_detail(html)
                meta_desc = get_meta_description(html)
                entry["has_tow_hitch"] = has_tow_hitch(meta_desc)
                entry["equipment_tags"] = [t.strip() for t in meta_desc.split(";")[1:] if t.strip()]
                if schema:
                    entry["vin"] = schema.get("vehicleIdentificationNumber")
                    entry["body_type"] = schema.get("bodyType")
                    entry["drivetrain"] = schema.get("driveWheelConfiguration")
                    entry["color"] = schema.get("color")
                    odometer = schema.get("mileageFromOdometer") or {}
                    if odometer.get("value"):
                        entry["mileage_km"] = odometer["value"]
                    engine = schema.get("vehicleEngine") or {}
                    entry["engine_power_hp"] = (engine.get("enginePower") or {}).get("value")
                    entry["engine_displacement_l"] = (engine.get("engineDisplacement") or {}).get("value")
                    seller = (schema.get("offers") or {}).get("seller") or {}
                    addr = seller.get("address") or {}
                    entry["dealer_address"] = ", ".join(
                        filter(None, [addr.get("streetAddress"), addr.get("postalCode"), addr.get("addressLocality")])
                    )
            except Exception as e:
                entry["fetch_error"] = str(e)

        new_cache[code] = entry

    save_cache(new_cache)
    entries = list(new_cache.values())
    entries.sort(key=lambda e: (not e.get("is_new"), not e.get("has_tow_hitch"), e.get("price") or 0))

    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    OUT_JSON.write_text(json.dumps(entries, ensure_ascii=False, indent=2), encoding="utf-8")
    write_markdown(entries)

    if ERROR_MD.exists():
        ERROR_MD.unlink()


def write_markdown(entries: list[dict]) -> None:
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    new_entries = [e for e in entries if e.get("is_new")]
    others = [e for e in entries if not e.get("is_new")]

    lines = [
        "# Bilia V60-bevakning",
        f"_Senast körd: {now} – {len(entries)} matchande bilar (under {PRICE_TO:,} kr) totalt_".replace(",", " "),
        "",
    ]

    def fmt(e: dict, level: str) -> list[str]:
        hitch = " 🔗 DRAGKROK" if e.get("has_tow_hitch") else ""
        out = [f"{level} {e['heading']} – {e['price']} kr – {e.get('branch','?')}{hitch}"]
        mil = e.get("mileage")
        out.append(
            f"{e.get('trim','')} | År: {e.get('year')} | {mil} mil | "
            f"{e.get('transmission','–')} | {e.get('fuel','–')} | {e.get('engine_power_hp','–')} hk"
        )
        if e.get("equipment_tags"):
            out.append(f"Taggar: {', '.join(e['equipment_tags'][:12])}")
        if e.get("dealer_address"):
            out.append(f"Adress: {e['dealer_address']}")
        if e.get("fetch_error"):
            out.append(f"_(kunde inte hämta detaljsida: {e['fetch_error']})_")
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
