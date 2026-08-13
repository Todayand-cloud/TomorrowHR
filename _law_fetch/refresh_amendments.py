# -*- coding: utf-8 -*-
"""
국가법령정보센터(law.go.kr)에서 주요 인사법령 제·개정 이력을
항상 신규로 수집하고, 로컬 조문 본문의 연혁 태그(<개정|신설 YYYY. M. D.>)와
교차 검증해 js/amendments-cache.json 을 갱신합니다.

규칙:
  - 공포일·시행일은 개정이유 목록의 표기만 사용 (샘플 일자 금지)
  - 하이라이트는 조문 연혁 날짜가 해당 개정의 공포일과 일치할 때만 생성
  - 연혁이 맞지 않으면 articleIds/highlights 를 비우고 요약·일자만 유지
"""

from __future__ import annotations

import argparse
import json
import re
import time
from datetime import date, datetime, timedelta
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(Path(__file__).resolve().parent))
from amendment_articles import (  # noqa: E402
    enrich_revision_with_articles,
    fetch_doc_map,
    load_seed_articles,
    sync_articles_js,
)
from http_util import http_get  # noqa: E402

CACHE_PATH = ROOT / "js" / "amendments-cache.json"
ARTICLES_PATH = ROOT / "js" / "law-articles-raw.json"
# 공포(개정일)·시행: 기준일 ±6개월 (주요 4법 공통)
AMD_FORWARD_DAYS = 182
AMD_LOOKBACK_DAYS = 182
EFF_FORWARD_DAYS = 182
EFF_LOOKBACK_DAYS = 182
# 하위 호환(메타 from/to는 공포 창 기준)
FORWARD_DAYS = AMD_FORWARD_DAYS
LOOKBACK_DAYS = AMD_LOOKBACK_DAYS
UA = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml",
    "Cache-Control": "no-cache",
    "Pragma": "no-cache",
}

LAW_CATALOG = [
    {"lawId": "labor-standards", "lawName": "근로기준법", "tier": "법률", "lsId": "001872"},
    {"lawId": "labor-standards", "lawName": "근로기준법 시행령", "tier": "시행령", "lsId": "003058"},
    {"lawId": "labor-standards", "lawName": "근로기준법 시행규칙", "tier": "시행규칙", "lsId": "006859"},
    {"lawId": "retirement", "lawName": "근로자퇴직급여 보장법", "tier": "법률", "lsId": "009883"},
    {
        "lawId": "retirement",
        "lawName": "근로자퇴직급여 보장법 시행령",
        "tier": "시행령",
        "lsId": "010035",
    },
    {
        "lawId": "retirement",
        "lawName": "근로자퇴직급여 보장법 시행규칙",
        "tier": "시행규칙",
        "lsId": "010043",
    },
    {
        "lawId": "equal-employment",
        "lawName": "남녀고용평등법",
        "tier": "법률",
        "lsId": "000130",
        "fullName": "남녀고용평등과 일ㆍ가정 양립 지원에 관한 법률",
    },
    {
        "lawId": "equal-employment",
        "lawName": "남녀고용평등법 시행령",
        "tier": "시행령",
        "lsId": "003140",
        "fullName": "남녀고용평등과 일ㆍ가정 양립 지원에 관한 법률 시행령",
    },
    {
        "lawId": "equal-employment",
        "lawName": "남녀고용평등법 시행규칙",
        "tier": "시행규칙",
        "lsId": "006909",
        "fullName": "남녀고용평등과 일ㆍ가정 양립 지원에 관한 법률 시행규칙",
    },
    {
        "lawId": "fixed-term",
        "lawName": "기간제법",
        "tier": "법률",
        "lsId": "010356",
        "fullName": "기간제 및 단시간근로자 보호 등에 관한 법률",
    },
    {
        "lawId": "fixed-term",
        "lawName": "기간제법 시행령",
        "tier": "시행령",
        "lsId": "010461",
        "fullName": "기간제 및 단시간근로자 보호 등에 관한 법률 시행령",
    },
    {
        "lawId": "fixed-term",
        "lawName": "기간제법 시행규칙",
        "tier": "시행규칙",
        "lsId": "010473",
        "fullName": "기간제 및 단시간근로자 보호 등에 관한 법률 시행규칙",
    },
]

REV_RE = re.compile(
    r"\[시행\s*([0-9.\s]+)\]\s*\[([^\]]+?)\s*제([0-9]+)호,\s*([0-9.\s]+),\s*([^\]]+)\]"
)
REASON_RE = re.compile(
    r"◇\s*개정이유\s*및\s*주요내용\s*([^◇【]{20,800})",
    re.DOTALL,
)
HISTORY_RE = re.compile(r"<(신설|개정)\s*([^>]+)>")
ARTICLE_MENTION_RE = re.compile(r"제\s*([0-9]+)\s*조(?:의\s*([0-9]+))?")
TIER_KEY = {"법률": "statute", "시행령": "decree", "시행규칙": "rule"}


def parse_ymd_dots(text: str) -> date:
    parts = [int(x) for x in re.findall(r"\d+", text)]
    return date(parts[0], parts[1], parts[2])


def to_iso(d: date) -> str:
    return d.isoformat()


def normalize_history_dates(blob: str) -> list[date]:
    dates = []
    for y, m, d in re.findall(r"(\d{4})\.\s*(\d{1,2})\.\s*(\d{1,2})", blob):
        dates.append(date(int(y), int(m), int(d)))
    return dates


def fetch_html(url: str) -> str:
    # cache-buster + no-cache headers → 수동 갱신 시 항상 신규 수집
    # Actions에서는 LAW_FETCH_PROXY(Cloudflare) 경유
    sep = "&" if "?" in url else "?"
    bust = f"{url}{sep}_ts={int(time.time() * 1000)}"
    return http_get(bust, headers=UA)


def fetch_revisions(ls_id: str) -> list[dict]:
    url = (
        "https://www.law.go.kr/LSW/lsRvsRsnListP.do?"
        f"chrClsCd=010102&lsId={ls_id}&lsRvsGubun=all"
    )
    html = fetch_html(url)
    reasons = REASON_RE.findall(html)
    reason_idx = 0
    items = []
    for ef, kind, no, anc, rtype in REV_RE.findall(html):
        summary_full = ""
        if reason_idx < len(reasons):
            summary_full = reasons[reason_idx]
            summary_full = re.sub(r"<[^>]+>", " ", summary_full)
            summary_full = re.sub(r"\s+", " ", summary_full).strip()
            reason_idx += 1
        summary = summary_full
        if len(summary) > 220:
            summary = summary[:217] + "…"
        items.append(
            {
                "effectiveDate": parse_ymd_dots(ef),
                "amendedDate": parse_ymd_dots(anc),
                "noticeNo": no,
                "instrument": kind.strip(),
                "revisionType": rtype.strip(),
                "summary": summary,
                "summaryFull": summary_full,
            }
        )
    return items


def in_window(rev: dict, base: date, end: date, start: date) -> bool:
    """공포·시행 모두 ±6개월. 둘 중 하나라도 해당하면 포함."""
    amd_start = base - timedelta(days=AMD_LOOKBACK_DAYS)
    amd_end = base + timedelta(days=AMD_FORWARD_DAYS)
    eff_start = base - timedelta(days=EFF_LOOKBACK_DAYS)
    eff_end = base + timedelta(days=EFF_FORWARD_DAYS)
    amd_in = amd_start <= rev["amendedDate"] <= amd_end
    eff_in = eff_start <= rev["effectiveDate"] <= eff_end
    return amd_in or eff_in


def status_for(effective: date, base: date) -> str:
    return "시행예정" if effective > base else "시행중"


def load_articles() -> dict:
    """수동 갱신: 법제처 전문을 다시 받은 뒤 시드·본문을 현행 기준으로 만든다."""
    try:
        from fetch_full_texts import refresh_all_full_texts

        report = refresh_all_full_texts()
        if not report.get("ok"):
            # 일부 실패해도 기존 전문으로 진행하되 오류는 상위에서 볼 수 있게 보관
            load_articles.last_full_report = report  # type: ignore[attr-defined]
        else:
            load_articles.last_full_report = report  # type: ignore[attr-defined]
    except Exception as exc:  # noqa: BLE001
        load_articles.last_full_report = {"ok": False, "errors": [str(exc)]}  # type: ignore[attr-defined]
    return load_seed_articles()


def article_units(body: str) -> list[str]:
    """항·호 단위로 잘라 하이라이트 후보를 만든다."""
    text = (body or "").replace("\r\n", "\n").strip()
    if not text:
        return []
    parts = re.split(r"(?=\n[①-⑮]|^\n?[①-⑮]|\n\d+\.\s)", "\n" + text)
    units = []
    for part in parts:
        chunk = part.strip()
        if chunk:
            units.append(chunk)
    return units or [text]


def normalize_jo_label(label: str) -> str:
    label = re.sub(r"\s+", "", label or "")
    return label.replace("제", "제")


def match_highlights(
    law_id: str,
    tier: str,
    amended: date,
    articles_db: dict,
    mentions: list[str] | None = None,
) -> tuple[list[str], list[dict], list[str]]:
    """연혁 일치 하이라이트 + 언급 조문 ID. 반환: articleIds, highlights, locators."""
    pack = articles_db.get(law_id) or {}
    key = TIER_KEY.get(tier)
    if not key:
        return [], [], []
    mention_set = {normalize_jo_label(m) for m in (mentions or [])}
    article_ids: list[str] = []
    highlights: list[dict] = []
    locators: list[str] = []

    for art in pack.get(key) or []:
        aid = art.get("id")
        no = normalize_jo_label(art.get("no") or "")
        body = art.get("body") or ""
        phrases = []
        for unit in article_units(body):
            for kind, blob in HISTORY_RE.findall(unit):
                dates = normalize_history_dates(blob)
                if amended not in dates:
                    continue
                loc = unit_locator(unit, art.get("no") or "")
                phrases.append(
                    {
                        "text": unit,
                        "isNew": kind == "신설",
                        "historyKind": kind,
                        "historyDates": [to_iso(d) for d in dates],
                        "locator": loc,
                        "beforeText": "",
                        "beforeNote": (
                            "신설된 내용으로, 개정 전 해당 문구는 없습니다."
                            if kind == "신설"
                            else "개정 전 전문은 법제처 조문 연혁·비교보기에서 확인하세요."
                        ),
                    }
                )
                if loc and loc not in locators:
                    locators.append(loc)
        mentioned = no in mention_set
        if phrases:
            article_ids.append(aid)
            highlights.append({"articleId": aid, "phrases": phrases})
        elif mentioned:
            # 연혁 태그는 아직 없더라도, 개정이유에 명시된 조문은 상세에서 전문 표시
            if aid not in article_ids:
                article_ids.append(aid)
            if no and no not in locators:
                locators.append(no)
    return article_ids, highlights, locators


def mentioned_article_nos(summary: str) -> list[str]:
    found = []
    for m in ARTICLE_MENTION_RE.finditer(summary or ""):
        no = m.group(1)
        of = m.group(2)
        label = f"제{no}조" + (f"의{of}" if of else "")
        if label not in found:
            found.append(label)
    return found


def unit_locator(unit: str, article_no: str) -> str:
    """제N조 + 항/호 위치 표기."""
    parts = [article_no] if article_no else []
    hang = re.match(r"^([①-⑮])", unit.strip())
    if hang:
        parts.append(f"{hang.group(1)}항")
    else:
        ho = re.match(r"^(\d+)\.\s*", unit.strip())
        if ho:
            parts.append(f"제{ho.group(1)}호")
    return " ".join(parts)


def brief_summary(text: str, limit: int = 90) -> str:
    s = re.sub(r"\s+", " ", (text or "")).strip()
    if len(s) <= limit:
        return s
    cut = s[: limit - 1]
    # 문장 중간에서 끊기 않게 마지막 조사/구두점 근처에서 자름
    for sep in ("다. ", "고, ", "며, ", "고 ", "·"):
        i = cut.rfind(sep)
        if i >= 40:
            return cut[: i + len(sep)].strip() + "…"
    return cut.rstrip(" ,·") + "…"


def extract_compare_pair(summary: str, highlights: list | None = None) -> tuple[str, str]:
    """개정 전/후 문안을 하이라이트 또는 개정이유 문장에서 뽑는다."""
    # 1) 조문 하이라이트에 개정 전이 명시된 경우 최우선
    for h in highlights or []:
        for ph in h.get("phrases") or []:
            before = (ph.get("beforeText") or "").strip()
            after = (ph.get("text") or "").strip()
            if before and after:
                return before, after

    text = re.sub(r"\s+", " ", (summary or "")).strip()
    if text:
        # 2) 종전에는 A … 앞으로는 B …
        m = re.search(
            r"종전에는\s*(.+?)\s*"
            r"(?:하던\s*것을|하도록\s*하던\s*것을|로\s*하던\s*것을|이었으나|였으나)\s*"
            r"앞으로는\s*(.+?)(?:\s*함으로써|\s*하려는|\s*하도록|\s*하도록\s*함|\.|$)",
            text,
        )
        if m:
            return m.group(1).strip(" ,·"), m.group(2).strip(" ,·")

        # 3) ‘A’를 ‘B’로 (명칭 변경)
        m = re.search(
            r"[‘'']([^‘'']{2,80})[’'']\s*를\s*[‘'']([^‘'']{2,80})[’'']\s*로",
            text,
        )
        if m:
            return m.group(1).strip(), m.group(2).strip()

        # 4) ‘A’에서 ‘B’로/으로
        m = re.search(
            r"[‘'']([^‘'']{2,120})[’'']\s*에서\s*[‘'']([^‘'']{2,120})[’'']\s*(?:으로|로)",
            text,
        )
        if m:
            return m.group(1).strip(), m.group(2).strip()

        # 5) 2일에서 4일로 / 30명 이하 기업에서 100명 미만 기업으로
        m = re.search(
            r"([0-9]+일|[0-9]+명\s*(?:이하|미만|이상|초과)?(?:\s*기업)?)\s*에서\s*"
            r"([0-9]+일|[0-9]+명\s*(?:이하|미만|이상|초과)?(?:\s*기업)?)\s*(?:으로|로)",
            text,
        )
        if m:
            return m.group(1).strip(), m.group(2).strip()

        # 6) 현행 A에서 B로 상향/확대… (짧은 구간만)
        m = re.search(
            r"현행\s*([0-9][^.]{0,60}?|[‘'][^‘']{2,80}[’'])\s*에서\s*"
            r"([0-9][^.]{0,60}?|[‘'][^‘']{2,80}[’'])\s*(?:으로|로)\s*(?:상향|강화|확대|조정|변경)",
            text,
        )
        if m:
            return m.group(1).strip(" ,·"), m.group(2).strip(" ,·")

    # 7) 신설만 있는 하이라이트
    for h in highlights or []:
        for ph in h.get("phrases") or []:
            after = (ph.get("text") or "").strip()
            if after and (ph.get("isNew") or "신설" in after):
                return "해당 문구 없음(신설)", after

    return "", ""


def attach_compare_fields(item: dict) -> dict:
    before, after = extract_compare_pair(item.get("summary") or "", item.get("highlights"))
    # 조문 펼침 단계에서 이미 채운 전·후는 유지
    if not (item.get("compareBefore") or "").strip():
        item["compareBefore"] = before
    if not (item.get("compareAfter") or "").strip():
        item["compareAfter"] = after
    return item


def build_amendments(base: date) -> dict:
    end = base + timedelta(days=FORWARD_DAYS)
    start = base - timedelta(days=LOOKBACK_DAYS)
    articles_db = load_articles()
    collected = []
    errors = []
    audit = {
        "matchedHighlights": 0,
        "unmatchedRevisions": 0,
        "rejectedDemoRule": "highlight only when article history date == promulgation date",
    }

    doc_cache: dict[str, dict[str, str]] = {}

    for meta in LAW_CATALOG:
        try:
            revs = fetch_revisions(meta["lsId"])
            time.sleep(0.15)
        except Exception as exc:  # noqa: BLE001
            errors.append({"lsId": meta["lsId"], "lawName": meta["lawName"], "error": str(exc)})
            continue

        tier_key = TIER_KEY.get(meta["tier"], "statute")
        # 법률·시행령·시행규칙 모두 개정문을 수집해 조문 단위로 펼침
        if meta["lsId"] not in doc_cache:
            try:
                doc_cache[meta["lsId"]] = fetch_doc_map(meta["lsId"])
                time.sleep(0.2)
            except Exception as exc:  # noqa: BLE001
                errors.append(
                    {"lsId": meta["lsId"], "lawName": meta["lawName"], "error": f"doc:{exc}"}
                )
                doc_cache[meta["lsId"]] = {}

        # 오래된 개정부터 적용해야 시드→연속 치환이 올바름
        window_revs = [rev for rev in revs if in_window(rev, base, end, start)]
        window_revs.sort(key=lambda r: (r["amendedDate"], int(r.get("noticeNo") or 0)))

        for rev in window_revs:
            display_name = meta.get("fullName") or meta["lawName"]
            title = (
                f"{meta['lawName']} {rev['revisionType']} "
                f"({rev['instrument']} 제{rev['noticeNo']}호)"
            )
            summary = rev["summary"] or (
                f"{display_name} {rev['revisionType']} "
                f"(공포 {to_iso(rev['amendedDate'])}, 시행 {to_iso(rev['effectiveDate'])})"
            )
            mentions = mentioned_article_nos(rev.get("summaryFull") or rev.get("summary") or "")
            article_ids, highlights, locators = match_highlights(
                meta["lawId"],
                meta["tier"],
                rev["amendedDate"],
                articles_db,
                mentions,
            )

            item = {
                "id": f"live-{meta['lsId']}-{to_iso(rev['amendedDate'])}-{rev['noticeNo']}",
                "lawId": meta["lawId"],
                "lawName": meta["lawName"],
                "fullName": display_name,
                "tier": meta["tier"],
                "title": title,
                "amendedDate": to_iso(rev["amendedDate"]),
                "effectiveDate": to_iso(rev["effectiveDate"]),
                "summary": summary,
                "briefSummary": brief_summary(summary),
                "status": status_for(rev["effectiveDate"], base),
                "revisionType": rev["revisionType"],
                "noticeNo": rev["noticeNo"],
                "instrument": rev["instrument"],
                "source": "law.go.kr",
                "sourceUrl": (
                    "https://www.law.go.kr/LSW/lsRvsRsnListP.do?"
                    f"chrClsCd=010102&lsId={meta['lsId']}"
                ),
                "mentionedArticles": mentions,
                "locators": locators,
                "articleIds": article_ids,
                "highlights": highlights,
                "verified": True,
            }

            doc_text = (doc_cache.get(meta["lsId"]) or {}).get(rev["noticeNo"], "")
            if doc_text:
                expanded = enrich_revision_with_articles(
                    item, doc_text, articles_db, tier_key, base_date=base
                )
                for child in expanded:
                    child["status"] = status_for(date.fromisoformat(child["effectiveDate"]), base)
                    attach_compare_fields(child)
                    if child.get("highlights"):
                        audit["matchedHighlights"] += 1
                    else:
                        audit["unmatchedRevisions"] += 1
                    collected.append(child)
            else:
                attach_compare_fields(item)
                if highlights:
                    audit["matchedHighlights"] += 1
                else:
                    audit["unmatchedRevisions"] += 1
                collected.append(item)

    # 시행일 기준 전문(eflaw)이 현행 본문의 단일 출처.
    # enrich 중 apply_ops가 이미 반영된 치환을 재적용해 오염시키는 것을 막는다.
    try:
        from hydrate_articles import fill_article_from_full, load_full_index

        full_index = load_full_index()
        for law_id, pack in articles_db.items():
            if not isinstance(pack, dict):
                continue
            for tier in ("statute", "decree", "rule"):
                for art in pack.get(tier) or []:
                    if isinstance(art, dict):
                        fill_article_from_full(art, law_id, tier, full_index)
    except Exception as exc:  # noqa: BLE001
        errors.append({"stage": "restore_bodies_from_full", "error": str(exc)})

    # 수동 갱신마다 조문·캐시를 시드 적용 결과로 전면 교체
    sync_articles_js(articles_db)

    collected.sort(
        key=lambda x: (x["amendedDate"], x["effectiveDate"], x.get("articleNo") or ""),
        reverse=True,
    )

    notices_report = None
    try:
        from refresh_notices import fetch_notices, save_cache as save_notices, sync_resource_data_js

        notices_payload = fetch_notices(base)
        save_notices(notices_payload)
        sync_resource_data_js(notices_payload)
        notices_report = {
            "ok": not notices_payload.get("errors"),
            "count": notices_payload.get("count"),
            "latest": (
                notices_payload["notices"][0]["date"]
                if notices_payload.get("notices")
                else None
            ),
            "errors": notices_payload.get("errors") or [],
        }
    except Exception as exc:  # noqa: BLE001
        notices_report = {"ok": False, "error": str(exc)}

    return {
        "baseDate": to_iso(base),
        "from": to_iso(start),
        "to": to_iso(end),
        "forwardDays": AMD_FORWARD_DAYS,
        "lookbackDays": AMD_LOOKBACK_DAYS,
        "amdForwardDays": AMD_FORWARD_DAYS,
        "amdLookbackDays": AMD_LOOKBACK_DAYS,
        "effForwardDays": EFF_FORWARD_DAYS,
        "effLookbackDays": EFF_LOOKBACK_DAYS,
        "effWindowLabel": "±6개월",
        "amdWindowLabel": "±6개월",
        "fetchedAt": datetime.now().isoformat(timespec="seconds"),
        "freshFetch": True,
        "count": len(collected),
        "errors": errors,
        "audit": audit,
        "fullTexts": getattr(load_articles, "last_full_report", None),
        "noticesRefresh": notices_report,
        "amendments": collected,
    }


def save_cache(payload: dict) -> Path:
    """기존 캐시를 지우고 신규 수집 결과로 덮어쓴다."""
    CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
    if CACHE_PATH.is_file():
        CACHE_PATH.unlink()
    CACHE_PATH.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return CACHE_PATH


def parse_base(text: str | None) -> date:
    if not text:
        return date.today()
    return datetime.strptime(text, "%Y-%m-%d").date()


def audit_payload(payload: dict) -> list[str]:
    """자체 검증: 하이라이트 연혁일과 공포일 불일치, 개정>시행 등."""
    problems = []
    warnings = []
    for item in payload.get("amendments") or []:
        amd = item.get("amendedDate")
        eff = item.get("effectiveDate")
        if not amd or not eff:
            problems.append(f"{item.get('id')}: missing dates")
            continue
        if item.get("articleLevel") and not (item.get("articleTitle") or "").strip():
            warnings.append(f"{item.get('id')}: empty articleTitle ({item.get('articleNo')})")
        for h in item.get("highlights") or []:
            for phrase in h.get("phrases") or []:
                hist = phrase.get("historyDates") or []
                if amd not in hist:
                    problems.append(
                        f"{item.get('id')} / {h.get('articleId')}: history {hist} != amended {amd}"
                    )
        if date.fromisoformat(amd) > date.fromisoformat(eff):
            problems.append(
                f"{item.get('id')}: amendedDate {amd} > effectiveDate {eff} (검토 필요)"
            )
    payload["_auditWarnings"] = warnings
    return problems


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base", help="기준일 YYYY-MM-DD (기본: 오늘)")
    parser.add_argument(
        "--skip-parity",
        action="store_true",
        help="법제처 대조 시뮬레이션 생략",
    )
    args = parser.parse_args()
    base = parse_base(args.base)
    payload = build_amendments(base)
    problems = audit_payload(payload)
    warnings = payload.pop("_auditWarnings", [])
    payload["selfCheck"] = {
        "ok": len(problems) == 0,
        "problems": problems,
        "warnings": warnings,
    }
    path = save_cache(payload)
    notices_report = payload.get("noticesRefresh")

    parity = None
    if not args.skip_parity:
        try:
            from verify_law_parity import run_simulation

            parity = run_simulation(verbose=False)
            payload["selfCheck"]["parity"] = {
                "ok": parity.get("ok"),
                "problemCount": len(parity.get("problems") or []),
                "problems": (parity.get("problems") or [])[:30],
            }
            if not parity.get("ok"):
                payload["selfCheck"]["ok"] = False
                payload["selfCheck"]["problems"] = (
                    list(payload["selfCheck"].get("problems") or [])
                    + [f"parity:{p}" for p in (parity.get("problems") or [])[:20]]
                )
            # parity 결과 반영해 캐시 재저장
            save_cache(payload)
        except Exception as exc:  # noqa: BLE001
            payload["selfCheck"]["parity"] = {"ok": False, "error": str(exc)}
            save_cache(payload)

    print(
        json.dumps(
            {
                "ok": True,
                "baseDate": payload["baseDate"],
                "from": payload["from"],
                "to": payload["to"],
                "count": payload["count"],
                "errors": payload["errors"],
                "audit": payload.get("audit"),
                "selfCheck": payload["selfCheck"],
                "noticesRefresh": notices_report,
                "cache": str(path),
            },
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    main()
