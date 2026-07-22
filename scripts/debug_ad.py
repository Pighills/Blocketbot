"""
Engångs-diagnostik: hämtar riktiga annonssidor direkt (utan bibliotekets
parser) och sparar rå-HTML + eventuell inbäddad JSON, så vi kan se varför
'beskrivning' inte extraheras, eller vad en borttagen/såld annons faktiskt
returnerar. Körs manuellt, inte del av det schemalagda workflowet.
"""
import json
import re
import sys
from pathlib import Path

import httpx

AD_IDS = sys.argv[1:] if len(sys.argv) > 1 else ["24301114"]

out_dir = Path("results/debug")
out_dir.mkdir(parents=True, exist_ok=True)

summary = []

for AD_ID in AD_IDS:
    URL = f"https://www.blocket.se/mobility/item/{AD_ID}"
    resp = httpx.get(
        URL,
        headers={
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                "(KHTML, like Gecko) Chrome/125.0 Safari/537.36"
            )
        },
        follow_redirects=True,
        timeout=30,
    )

    html = resp.text
    (out_dir / f"{AD_ID}_raw.html").write_text(html, encoding="utf-8")

    report = [
        f"ad_id: {AD_ID}",
        f"status_code: {resp.status_code}",
        f"final url: {resp.url}",
        f"content length: {len(html)} tecken",
        "",
    ]
    summary.append(
        f"{AD_ID}: status={resp.status_code} final_url={resp.url} len={len(html)}"
    )

    for needle in ["hittades inte", "inte längre tillgänglig", "har tagits bort",
                   "annons finns inte", "not found", "borttagen", "avpublicerad"]:
        if needle.lower() in html.lower():
            report.append(f"HITTADE SIGNAL: '{needle}' finns i sidan")
            summary.append(f"  -> mojlig 'borttagen'-signal: '{needle}'")

    script_patterns = [
        r'<script[^>]*id="__staticRouterHydrationData"[^>]*>(.*?)</script>',
        r'<script[^>]*id="__NEXT_DATA__"[^>]*>(.*?)</script>',
    ]
    for pat in script_patterns:
        m = re.search(pat, html, re.DOTALL)
        report.append(f"pattern hittad: {pat[:50]}... -> {'JA' if m else 'nej'}")
        if m:
            blob = m.group(1)
            (out_dir / f"{AD_ID}_hydration.json").write_text(blob[:200000], encoding="utf-8")

    for m in re.finditer(r"beskrivning", html, re.IGNORECASE):
        idx = m.start()
        snippet = html[max(0, idx - 150):idx + 300].replace("\n", " ")
        report.append(f"\n'beskrivning' hittad vid index {idx}:\n{snippet}")
        break  # bara forsta traffen racker for diagnostik

    (out_dir / f"{AD_ID}_report.txt").write_text("\n".join(report), encoding="utf-8")

(out_dir / "_summary.txt").write_text("\n".join(summary), encoding="utf-8")
print("\n".join(summary))

