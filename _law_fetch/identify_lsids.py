# -*- coding: utf-8 -*-
import json
import re
import urllib.request
from pathlib import Path

UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/120.0.0.0 Safari/537.36"}
OUT = Path(__file__).with_name("lsid-identify.json")

CANDIDATES = [
    "001872",
    "003058",
    "006288",
    "000130",
    "009883",
    "010356",
    "004949",
    "009884",
    "010357",
    "010358",
    "000131",
    "008280",
]


def get(url: str) -> str:
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=40) as r:
        return r.read().decode("utf-8", "replace")


rows = []
for ls in CANDIDATES:
    url = f"https://www.law.go.kr/LSW/lsRvsRsnListP.do?chrClsCd=010102&lsId={ls}"
    html = get(url)
    revs = re.findall(
        r"\[시행\s*([0-9.\s]+)\]\s*\[([^\]]+?)\s*제([0-9]+)호,\s*([0-9.\s]+),\s*([^\]]+)\]",
        html,
    )
    # grab nearby Korean title-ish strings
    titles = re.findall(r"<strong>([^<]{2,80})</strong>", html)
    h2 = re.findall(r"<h2[^>]*>([^<]+)</h2>", html)
    rows.append(
        {
            "lsId": ls,
            "titles": (h2 + titles)[:8],
            "revCount": len(revs),
            "latest": [
                {
                    "ef": a.strip(),
                    "kind": b.strip(),
                    "no": c.strip(),
                    "anc": d.strip(),
                    "type": e.strip(),
                }
                for a, b, c, d, e in revs[:3]
            ],
        }
    )

OUT.write_text(json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8")
print("wrote", OUT)
