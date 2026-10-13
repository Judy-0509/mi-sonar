"""Regenerate assets/badges/*.svg from shields.io (run: python assets/make_badges.py)."""
import pathlib, urllib.request
from urllib.parse import quote

B = [  # (file, label, message, color, logo)
    ("python", "python", "3.10+", "3776AB", "python"),
    ("postgres", "postgres", "read-only", "336791", "postgresql"),
    ("minio", "storage", "minio", "C72C48", "minio"),
    ("agent", "agent", "claude code · opencode", "D97757", ""),
    ("tests", "tests", "48 passing", "4C1", ""),
    ("want-trending", "WANT", "GitHub Trending #1", "ff69b4", ""),
    ("want-best-repo", "WANT", "Best Repo of 2026", "gold", ""),
    ("want-stars", "WANT", "10k stars (현재 1)", "yellow", ""),
    ("want-tool-of-year", "WANT", "올해의 사내 툴", "8A2BE2", ""),
    ("want-usage", "WANT", "사내 사용률 1위", "2ea44f", ""),
    ("want-ax", "WANT", "AX 대상", "ff8c00", ""),
]
enc = lambda s: quote(s.replace("-", "--").replace("_", "__"), safe="")
out = pathlib.Path(__file__).parent / "badges"
out.mkdir(exist_ok=True)
for f, l, m, c, logo in B:
    url = f"https://img.shields.io/badge/{enc(l)}-{enc(m)}-{c}" + (f"?logo={logo}&logoColor=white" if logo else "")
    with urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})) as r:
        (out / f"{f}.svg").write_bytes(r.read())
        print(r.status, url)
