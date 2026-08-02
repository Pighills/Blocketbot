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
    "https://www.bilia.se/bilar/sok-bil/bro/kombi/",
    "https://www.bilia.se/bilar/sok-bil/kombi/bro/",
    "https://www.bilia.se/bilar/sok-bil/bro/?biltyp=kombi",
]

for url in candidates:
    try:
        r = httpx.get(url, headers={"User-Agent": USER_AGENT}, follow_redirects=True, timeout=20)
        count = "?"
        if "bilar</span>" in r.text or " bilar" in r.text:
            import re
            m = re.search(r'>(\d+)</span>\s*bilar', r.text) or re.search(r'"resultCount":(\d+)', r.text)
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

# Spara fullstandig HTML for de tva som redan bekraftats fungera separat, for innehallskoll
for name, url in [("bro_only", "https://www.bilia.se/bilar/sok-bil/bro/"),
                   ("kombi_only", "https://www.bilia.se/bilar/sok-bil/kombi/")]:
    r = httpx.get(url, headers={"User-Agent": USER_AGENT}, follow_redirects=True, timeout=20)
    (out_dir / f"{name}_raw.html").write_text(r.text, encoding="utf-8")
