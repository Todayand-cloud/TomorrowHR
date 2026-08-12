# -*- coding: utf-8 -*-
import re
import urllib.request

UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/120.0.0.0 Safari/537.36"}
CANDIDATES = [
    "001872",
    "003058",
    "005901",
    "006288",
    "000130",
    "000131",
    "009883",
    "009884",
    "010356",
    "010357",
    "003059",
    "010358",
    "008280",
    "004949",
]


def get(url: str) -> str:
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=40) as r:
        return r.read().decode("utf-8", "replace")


for ls in CANDIDATES:
    url = f"https://www.law.go.kr/LSW/lsRvsRsnListP.do?chrClsCd=010102&lsId={ls}"
    try:
        html = get(url)
    except Exception as e:
        print(ls, "FAIL", e)
        continue
    m = re.search(r"\[시행\s*[0-9.\s]+\]\s*\[[^\]]+\]", html)
    names = re.findall(
        r">(근로기준법(?:\s*시행령|\s*시행규칙)?|근로자퇴직급여 보장법(?:\s*시행령|\s*시행규칙)?|남녀고용평등과 일ㆍ가정 양립 지원에 관한 법률(?:\s*시행령|\s*시행규칙)?|기간제 및 단시간근로자 보호 등에 관한 법률(?:\s*시행령|\s*시행규칙)?)<",
        html,
    )
    print(ls, "ok" if m else "empty", "names=", sorted(set(names))[:3], "first=", (m.group(0)[:90] if m else "-"))
