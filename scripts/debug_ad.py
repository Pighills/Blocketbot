"""
Engångs-diagnostik: hämtar EN riktig annonssida direkt (utan bibliotekets
parser) och sparar rå-HTML + eventuell inbäddad JSON, så vi kan se varför
'beskrivning' inte extraheras. Körs manuellt, inte del av det schemalagda
workflowet.
"""
import json
import re
import sys
from pathlib import Path

import httpx

AD_ID = sys.argv[1] if len(sys.argv) > 1 else "24301114"
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

out_dir = Path("results/debug")
out_dir.mkdir(parents=True, exist_ok=True)

html = resp.text
(out_dir / f"{AD_ID}_raw.html").write_text(html, encoding="utf-8")

report = [f"status_code: {resp.status_code}", f"content length: {len(html)} tecken", ""]

# Leta efter inbäddade JSON-datablock (vanligt i React/Remix-appar)
script_patterns = [
    r'<script[^>]*id="__staticRouterHydrationData"[^>]*>(.*?)</script>',
    r'<script[^>]*id="__NEXT_DATA__"[^>]*>(.*?)</script>',
    r"window\.__staticRouterHydrationData\s*=\s*(\{.*?\});",
]
for pat in script_patterns:
    m = re.search(pat, html, re.DOTALL)
    report.append(f"pattern hittad: {pat[:50]}... -> {'JA' if m else 'nej'}")
    if m:
        blob = m.group(1)
        (out_dir / f"{AD_ID}_hydration.json").write_text(blob[:200000], encoding="utf-8")
        report.append(f"  sparad, längd: {len(blob)} tecken")
        # sök efter "description" i blobben
        if '"description"' in blob.lower():
            idx = blob.lower().find('"description"')
            report.append(f"  '\"description\"' hittad vid index {idx}, kontext:")
            report.append("  " + blob[max(0, idx - 50):idx + 300])

# Leta även i plain HTML efter ordet "beskrivning" (case-insensitive), oavsett var
for m in re.finditer(r"beskrivning", html, re.IGNORECASE):
    idx = m.start()
    snippet = html[max(0, idx - 150):idx + 300].replace("\n", " ")
    report.append(f"\n'beskrivning' hittad i rå-HTML vid index {idx}:\n{snippet}")

(out_dir / f"{AD_ID}_report.txt").write_text("\n".join(report), encoding="utf-8")
print("\n".join(report[:20]))
