import httpx
from pathlib import Path

out_dir = Path("results/debug_bilia")
out_dir.mkdir(parents=True, exist_ok=True)
out_lines = []
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/125.0 Safari/537.36"
)

candidates = [
    "https://www.volvocarretail.se/bilar-i-lager/begagnade/volvo?carType=kombi&facility=kungsangen",
    "https://www.volvocarretail.se/bilar-i-lager/begagnade/volvo?carType=kombi",
    "https://www.volvocarretail.se/bilar-i-lager/begagnade/volvo?facility=kungsangen",
    "https://www.volvocarretail.se/bilar-i-lager/begagnade/volvo?carType=kombi&facility=kungsangen&priceTo=200000",
]

for url in candidates:
    try:
        r = httpx.get(url, headers={"User-Agent": USER_AGENT}, follow_redirects=True, timeout=20)
        count = "?"
        import re
        m = (re.search(r'>(\d+)</span>\s*bilar', r.text)
             or re.search(r'"resultCount":(\d+)', r.text)
             or re.search(r'i lager\D{0,20}(\d+)\s*Bilar i lager', r.text)
             or re.search(r'(\d+)\s*Bilar i lager', r.text))
        if m:
            count = m.group(1)
        kombi_hits = r.text.lower().count("kombi")
        line = f"{r.status_code} | len={len(r.text):>7} | kombi-forekomster={kombi_hits:>3} | resultat-tal-hittat={count} | slutlig-url={r.url} | {url}"
        print(line)
        out_lines.append(line)
    except Exception as e:
        line = f"FEL: {url} -> {e}"
        print(line)
        out_lines.append(line)

(out_dir / "_param_test.txt").write_text("\n".join(out_lines), encoding="utf-8")
