# -*- coding: utf-8 -*-
import re
import urllib.parse
import urllib.request

UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/120.0.0.0 Safari/537.36"}


def get(url: str) -> str:
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=40) as r:
        return r.read().decode("utf-8", "replace")


NAMES = [
    "근로기준법",
    "근로기준법 시행령",
    "근로기준법 시행규칙",
    "근로자퇴직급여 보장법",
    "근로자퇴직급여 보장법 시행령",
    "근로자퇴직급여 보장법 시행규칙",
    "남녀고용평등과 일ㆍ가정 양립 지원에 관한 법률",
    "남녀고용평등과 일ㆍ가정 양립 지원에 관한 법률 시행령",
    "남녀고용평등과 일ㆍ가정 양립 지원에 관한 법률 시행규칙",
    "기간제 및 단시간근로자 보호 등에 관한 법률",
    "기간제 및 단시간근로자 보호 등에 관한 법률 시행령",
    "기간제 및 단시간근로자 보호 등에 관한 법률 시행규칙",
]

for name in NAMES:
    url = "https://www.law.go.kr/LSW/lsInfoP.do?" + urllib.parse.urlencode({"lsNm": name})
    try:
        html = get(url)
    except Exception as e:
        print(name, "FAIL", e)
        continue
    ls_id = re.search(r"lsId=([0-9A-Za-z]+)", html)
    lsi = re.search(r"lsiSeq=(\d+)", html)
    # also try from meta / links
    ids = set(re.findall(r"lsId=([0-9]{5,6})", html))
    print(name, "| lsId=", ls_id.group(1) if ls_id else "-", "| lsiSeq=", lsi.group(1) if lsi else "-", "| ids=", sorted(ids)[:5])
