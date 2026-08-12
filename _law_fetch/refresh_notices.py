# -*- coding: utf-8 -*-
"""고용노동부 입법·행정예고를 기준일 기준으로 수집해 js/notices-cache.json 에 저장.

출처: https://www.moel.go.kr/info/lawinfo/lawmaking/list.do
"""

from __future__ import annotations

import argparse
import html as html_lib
import json
import re
import time
import urllib.parse
import urllib.request
from datetime import date, datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CACHE_PATH = ROOT / "js" / "notices-cache.json"
RESOURCE_JS = ROOT / "js" / "resource-data.js"

LIST_URL = "https://www.moel.go.kr/info/lawinfo/lawmaking/list.do"
VIEW_URL = "https://www.moel.go.kr/info/lawinfo/lawmaking/view.do"
UA = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml",
    "Cache-Control": "no-cache",
}

# 기준일로부터 과거 몇 일까지 수집할지
LOOKBACK_DAYS = 90
# 페이지당 약 10건 · 최대 페이지
MAX_PAGES = 8
MAX_ITEMS = 24


def parse_base(text: str | None) -> date:
    if not text:
        return date.today()
    return datetime.strptime(text, "%Y-%m-%d").date()


def fetch_list_page(page_index: int) -> str:
    url = LIST_URL + "?" + urllib.parse.urlencode({"pageIndex": str(page_index)})
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=12) as res:
        return res.read().decode("utf-8", "replace")


def _cell_text(raw: str) -> str:
    text = re.sub(r"<[^>]+>", " ", raw or "")
    text = html_lib.unescape(text)
    return re.sub(r"\s+", " ", text).strip()


def parse_list_html(page_html: str) -> list[dict]:
    rows: list[dict] = []
    blocks = re.findall(
        r"<tr[^>]*>\s*<td[^>]*>\s*(\d+)\s*</td>(.*?)</tr>",
        page_html,
        flags=re.S | re.I,
    )
    for _num, body in blocks:
        seq_m = re.search(r"bbs_seq=(\d+)", body)
        if not seq_m:
            continue
        seq = seq_m.group(1)
        cells = re.findall(r"<td[^>]*>(.*?)</td>", body, flags=re.S | re.I)
        texts = [_cell_text(c) for c in cells]
        # 제목·부서·등록일·첨부·조회
        title_raw = texts[0] if texts else ""
        dept = texts[1] if len(texts) > 1 else ""
        date_raw = texts[2] if len(texts) > 2 else ""
        views_raw = texts[4] if len(texts) > 4 else (texts[-1] if texts else "0")

        type_m = re.match(r"^\[(입법|행정)\]\s*(.*)$", title_raw)
        if type_m:
            ntype, title = type_m.group(1), type_m.group(2).strip()
        else:
            ntype, title = "예고", title_raw
        # 「제목」 형태·짝 안 맞는 따옴표 정리
        title = re.sub(r"^[「\"']+|[」\"']+$", "", title).strip()
        title = title.replace("」 ", " ").replace("「", "").replace("」", "")
        title = re.sub(r"\s+", " ", title).strip()

        date_m = re.search(r"(20\d{2})[.\-/](\d{1,2})[.\-/](\d{1,2})", date_raw)
        if not date_m:
            continue
        y, mo, d = int(date_m.group(1)), int(date_m.group(2)), int(date_m.group(3))
        iso = f"{y:04d}-{mo:02d}-{d:02d}"
        views = int(re.sub(r"[^\d]", "", views_raw) or "0")

        rows.append(
            {
                "id": f"nt-{seq}",
                "type": ntype,
                "title": title,
                "dept": dept,
                "date": iso,
                "views": views,
                "summary": f"{ntype}예고 · {dept}" if dept else f"{ntype}예고",
                "url": f"{VIEW_URL}?bbs_seq={seq}",
                "bbsSeq": seq,
            }
        )
    return rows


def fetch_notices(base: date, lookback_days: int = LOOKBACK_DAYS) -> dict:
    start = base - timedelta(days=lookback_days)
    collected: list[dict] = []
    seen: set[str] = set()
    errors: list[str] = []
    stop = False

    for page in range(1, MAX_PAGES + 1):
        try:
            html = fetch_list_page(page)
            rows = parse_list_html(html)
        except Exception as exc:  # noqa: BLE001
            errors.append(f"page{page}:{exc}")
            break
        if not rows:
            break
        for row in rows:
            if row["id"] in seen:
                continue
            seen.add(row["id"])
            try:
                d = date.fromisoformat(row["date"])
            except ValueError:
                continue
            if d > base:
                continue
            if d < start:
                stop = True
                break
            collected.append(row)
            if len(collected) >= MAX_ITEMS:
                stop = True
                break
        if stop:
            break
        time.sleep(0.2)

    collected.sort(key=lambda x: (x["date"], x.get("bbsSeq") or ""), reverse=True)
    return {
        "baseDate": base.isoformat(),
        "from": start.isoformat(),
        "to": base.isoformat(),
        "lookbackDays": lookback_days,
        "fetchedAt": datetime.now().isoformat(timespec="seconds"),
        "sourcePortal": LIST_URL,
        "note": "고용노동부 「입법·행정예고」 게시판을 기준일 기준으로 자동 수집한 결과입니다.",
        "count": len(collected),
        "errors": errors,
        "notices": collected,
    }


def save_cache(payload: dict) -> Path:
    CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
    CACHE_PATH.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return CACHE_PATH


def sync_resource_data_js(payload: dict) -> None:
    """resource-data.js 의 noticesMeta/notices 를 캐시 결과로 덮어쓴다."""
    if not RESOURCE_JS.is_file():
        return
    src = RESOURCE_JS.read_text(encoding="utf-8")
    meta = {
        "sourcePortal": payload.get("sourcePortal") or LIST_URL,
        "note": payload.get("note")
        or "고용노동부 「입법·행정예고」 중 최근 공고입니다.",
        "fetchedAt": payload.get("fetchedAt"),
        "baseDate": payload.get("baseDate"),
    }
    notices = payload.get("notices") or []
    meta_js = json.dumps(meta, ensure_ascii=False, indent=2)
    notices_js = json.dumps(notices, ensure_ascii=False, indent=2)
    # window.LAW_DATA.xxx = ...; 블록 교체
    src2, n1 = re.subn(
        r"window\.LAW_DATA\.noticesMeta\s*=\s*\{.*?\};",
        "window.LAW_DATA.noticesMeta = " + meta_js + ";",
        src,
        count=1,
        flags=re.S,
    )
    src3, n2 = re.subn(
        r"window\.LAW_DATA\.notices\s*=\s*\[.*?\];",
        "window.LAW_DATA.notices = " + notices_js + ";",
        src2,
        count=1,
        flags=re.S,
    )
    if n1 and n2:
        RESOURCE_JS.write_text(src3, encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base", help="기준일 YYYY-MM-DD (기본: 오늘)")
    parser.add_argument("--lookback", type=int, default=LOOKBACK_DAYS)
    args = parser.parse_args()
    base = parse_base(args.base)
    payload = fetch_notices(base, lookback_days=args.lookback)
    path = save_cache(payload)
    sync_resource_data_js(payload)
    print(
        json.dumps(
            {
                "ok": not payload.get("errors"),
                "baseDate": payload["baseDate"],
                "count": payload["count"],
                "latest": (payload["notices"][0]["date"] if payload["notices"] else None),
                "errors": payload["errors"],
                "cache": str(path),
            },
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    main()
