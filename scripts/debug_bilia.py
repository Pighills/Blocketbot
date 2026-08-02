"""
Engångs-diagnostik: hämtar Bilias sok-sida och en detaljsida rått, sparar
HTML och drar ut ledtrådar om hur kort/etiketter faktiskt är uppbyggda i
DOM:en - eftersom Claudes web_fetch-markdown-konvertering tappar
klassnamn/struktur som en riktig parser behöver.
"""
import re
from pathlib import Path

import httpx

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/125.0 Safari/537.36"
)

out_dir = Path("results/debug_bilia")
out_dir.mkdir(parents=True, exist_ok=True)

urls = {
    "search_v60": "https://www.bilia.se/bilar/sok-bil/volvo/v60/",
    "detail_sample": "https://www.bilia.se/bilar/sok-bil/volvo/v90/goj371/",
}

summary = []
for name, url in urls.items():
    resp = httpx.get(url, headers={"User-Agent": USER_AGENT}, follow_redirects=True, timeout=30)
    html = resp.text
    (out_dir / f"{name}_raw.html").write_text(html, encoding="utf-8")
    summary.append(f"{name}: status={resp.status_code} len={len(html)}")

    # Leta efter data-testid / data-cy attribut - vanligt i moderna React-appar
    testids = sorted(set(re.findall(r'data-testid="([^"]+)"', html)))[:60]
    summary.append(f"  data-testid attribut ({len(testids)}): {testids}")

    # Leta efter inbäddad JSON (Next.js/Remix-monster)
    for pat_name, pat in [
        ("__NEXT_DATA__", r'<script[^>]*id="__NEXT_DATA__"[^>]*>(.*?)</script>'),
        ("staticRouterHydrationData", r'<script[^>]*id="__staticRouterHydrationData"[^>]*>(.*?)</script>'),
        ("application/json script", r'<script[^>]*type="application/json"[^>]*id="([^"]*)"[^>]*>'),
    ]:
        m = re.search(pat, html, re.DOTALL)
        summary.append(f"  {pat_name}: {'JA' if m else 'nej'}")

    # Antal ganger "Kontantpris" forekommer (grovt matt pa hur manga kort som laddats)
    summary.append(f"  'Kontantpris' forekomster: {html.count('Kontantpris')}")
    summary.append(f"  'Dragkrok' forekomster: {html.lower().count('dragkrok')}")

(out_dir / "_summary.txt").write_text("\n".join(summary), encoding="utf-8")
print("\n".join(summary))
