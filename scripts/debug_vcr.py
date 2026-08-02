import httpx
from pathlib import Path

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/125.0 Safari/537.36"
)
out_dir = Path("results/debug_vcr")
out_dir.mkdir(parents=True, exist_ok=True)

urls = {
    "v60_model_page": "https://www.volvocarretail.se/bilar-i-lager/begagnade/volvo/v60",
    "v60_page2": "https://www.volvocarretail.se/bilar-i-lager/begagnade/volvo/v60?page=2",
}
summary = []
for name, url in urls.items():
    r = httpx.get(url, headers={"User-Agent": USER_AGENT}, follow_redirects=True, timeout=30)
    (out_dir / f"{name}.html").write_text(r.text, encoding="utf-8")
    import re
    title_m = re.search(r"<title>([^<]*)</title>", r.text)
    summary.append(f"{name}: status={r.status_code} len={len(r.text)} title={title_m.group(1) if title_m else '?'}")

(out_dir / "_summary.txt").write_text("\n".join(summary), encoding="utf-8")
print("\n".join(summary))
