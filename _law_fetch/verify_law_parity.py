# -*- coding: utf-8 -*-
"""법제처(DRF XML) ↔ 로컬 full/조문/개정캐시 자체 피드백 시뮬레이션.

갱신 직후 실행해, 실제 원문과 차이가 없는지 확인합니다.
종료코드: 0=통과, 1=실패
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fetch_full_texts import (  # noqa: E402
    FULL_TARGETS,
    fetch_xml,
    jo_label,
    xml_to_full_text,
    _cdata,
)

ROOT = Path(__file__).resolve().parents[1]
FETCH = Path(__file__).resolve().parent
CACHE_PATH = ROOT / "js" / "amendments-cache.json"
ARTICLES_PATH = ROOT / "js" / "law-articles-raw.json"
MAIN_JS = ROOT / "js" / "main.js"

TIER_KEY = {"법률": "statute", "시행령": "decree", "시행규칙": "rule"}
MAJOR_LAWS = [
    "labor-standards",
    "retirement",
    "equal-employment",
    "fixed-term",
]

# 법제처 현행 본문에 반드시 있어야 하는 앵커 (크롤 누락 회귀 방지)
# 같은 조에 미시행 개정이 여러 건일 때 UI 합성 결과 검증
COMPOSE_PROBES = [
    {
        "lawId": "labor-standards",
        "articleNo": "제110조",
        "articleId": "labor-standards-statute-110",
        # 21533(제104조제2항→제104조) + 21784(제4항및제5항→부터제6항) 합성
        "requireInComposed": ["제104조를", "제4항부터 제6항까지"],
        "forbidInComposed": ["제104조제2항"],
    },
    {
        "lawId": "labor-standards",
        "articleNo": "제114조",
        "articleId": "labor-standards-statute-114",
        # 21533(제103조 삭제, 시행 2026-12-08) + 21784(제60조제9항, 시행 2027-06-10)
        "requireInComposed": ["제60조제9항", "제95조 및 제100조"],
        "forbidInComposed": ["제103조"],
        # 합성 후 대표 일자는 빠른 시행(4월 개정), composedFrom 에 두 일자 모두
        "requireComposedDates": [
            {"amendedDate": "2026-04-07", "effectiveDate": "2026-12-08"},
            {"amendedDate": "2026-06-09", "effectiveDate": "2027-06-10"},
        ],
    },
    {
        "lawId": "labor-standards",
        "articleNo": "제116조",
        "articleId": "labor-standards-statute-116",
        # 제1항제2호(수급인)는 ②·④⑤ 끝이 아니라 ① 블록 안(② 앞)
        "requireInComposed": [
            "수급인이 제44조의4제6항",
            "노동감독관",
            "제44조의4제1항ㆍ제4항ㆍ제5항, 제48조",
            "4. 삭제",
        ],
        "requireOrder": [
            "다음 각 호의 어느 하나에 해당하는 경우에는 1천만원",
            "수급인이 제44조의4제6항",
            "② 다음 각 호의",
            "노동감독관",
            "④ 삭제",
        ],
    },
]

LIVE_PROBES = [
    {
        "lsId": "001872",
        "lawId": "labor-standards",
        "tier": "statute",
        "article": "제110조",
        "must_in_live": ["제104조제2항", "제4항 및 제5항", "다음 각 호의"],
        "file": "full-labor-statute.txt",
        "amendments": [
            {
                # 개정후=제104조 / 개정전=제104조제2항 (방향 고정)
                "amendedDate": "2026-04-07",
                "noticeNo": "21533",
                "effectiveDate": "2026-12-08",
                "compareBefore": "제104조제2항",
                "compareAfter": "제104조",
                "requireHighlight": True,
                "requireBodyApplied": False,
                "requirePhraseAfter": "제104조",
                "requireHighlightPhraseAfter": "제104조를",
                "forbidPhraseAfter": "제104조제2항",
                "requirePhraseBefore": "제104조제2항",
                "requireLocators": ["제1호"],
            },
            {
                "amendedDate": "2026-06-09",
                "noticeNo": "21784",
                "effectiveDate": "2027-06-10",
                "compareBefore": "제4항 및 제5항",
                "compareAfter": "제4항부터 제6항까지",
                "requireHighlight": True,
                "requireBodyApplied": False,
                "requirePhraseAfter": "제4항부터 제6항까지",
                "requireHighlightPhraseAfter": "제4항부터 제6항까지",
                "requireLocators": ["제1호"],
            },
        ],
    },
    {
        # 법률 제21784호: 제54조 단서 신설 — 시행 2026.12.10 전 현행 본문에 단서 없어야 함
        "lsId": "001872",
        "lawId": "labor-standards",
        "tier": "statute",
        "article": "제54조",
        "must_in_live": [
            "근로시간이 4시간인 경우에는 30분 이상",
            "휴게시간은 근로자가 자유롭게 이용할 수 있다",
        ],
        "must_not_in_live": [
            "명시적으로 요청",
            "이용하지 아니할 것을",
            "사용하지 아니할 것을",
        ],
        "must_not_after": "2026-12-10",
        "file": "full-labor-statute.txt",
        "amendments": [
            {
                "amendedDate": "2026-06-09",
                "noticeNo": "21784",
                "effectiveDate": "2026-12-10",
                "compareBefore": "주어야 한다",
                "compareAfter": "명시적으로 요청",
                "requireHighlight": True,
                "requireBodyApplied": False,
                "requirePhraseAfter": "명시적으로 요청",
                "forbidPhraseAfter": "② 휴게시간은 근로자가 자유롭게 이용할 수 있다. <개정",
                "requireLocators": ["제1항"],
            },
        ],
    },
    {
        # 법률 제21784호: 제61조 인용 제60조제7항→제8항 (시행 2027.6.10)
        "lsId": "001872",
        "lawId": "labor-standards",
        "tier": "statute",
        "article": "제61조",
        "must_in_live": ["제60조제7항"],
        "must_not_in_live": ["제60조제8항"],
        "must_not_after": "2027-06-10",
        "file": "full-labor-statute.txt",
        "amendments": [
            {
                "amendedDate": "2026-06-09",
                "noticeNo": "21784",
                "effectiveDate": "2027-06-10",
                "compareBefore": "제60조제7항",
                "compareAfter": "제60조제8항",
                "requireHighlight": True,
                "requireBodyApplied": False,
                "requirePhraseAfter": "제60조제8항",
                "requireLocators": ["제1항", "제1항제1호", "제1항제2호", "제2항"],
            },
        ],
    },
    {
        # 법률 제21533호: 제107조 — 제목외→①, 인용 확대, ②(반의사불벌) 신설
        "lsId": "001872",
        "lawId": "labor-standards",
        "tier": "statute",
        "article": "제107조",
        "must_in_live": [
            "제23조제2항 또는 제40조를 위반한",
        ],
        "must_not_in_live": [
            "피해자의 명시적인 의사와 다르게 공소를",
            "제36조, 제40조, 제43조, 제44조, 제44조의2, 제46조, 제51조의3",
        ],
        "must_not_after": "2026-10-08",
        "file": "full-labor-statute.txt",
        "amendments": [
            {
                "amendedDate": "2026-04-07",
                "noticeNo": "21533",
                "effectiveDate": "2026-10-08",
                "compareBefore": "제23조제2항 또는 제40조",
                "compareAfter": "피해자의 명시적인 의사와 다르게 공소를",
                "requireHighlight": True,
                "requireBodyApplied": False,
                "requirePhraseAfter": "제51조의3",
                "requireHighlightPhraseAfter": "피해자의 명시적인 의사와 다르게 공소를",
                "requireLocators": ["제1항", "제2항"],
            },
        ],
    },
    {
        # 법률 제21533호: 제116조 과태료 — 제1항 각호 신설 + 제2항제1·2호 개정 + 제4호 삭제
        "lsId": "001872",
        "lawId": "labor-standards",
        "tier": "statute",
        "article": "제116조",
        "must_in_live": [
            "직장 내 괴롭힘을 한 경우에는 1천만원 이하의 과태료",
            "근로감독관",
            "제48조",
            "제102조에 따른 근로감독관",
        ],
        "must_not_in_live": [
            "다음 각 호의 어느 하나에 해당하는 경우에는 1천만원",
            "노동감독관",
            "제44조의4제1항ㆍ제4항ㆍ제5항, 제48조",
        ],
        "must_not_after": "2027-01-01",
        "file": "full-labor-statute.txt",
        "amendments": [
            {
                # 부칙: 제1항(기본 6개월) / 제2항제1·4호(8개월) / 제1항제2·제2항제2호(2027.1.1)
                "amendedDate": "2026-04-07",
                "noticeNo": "21533",
                "effectiveDate": "2026-10-08",
                "compareBefore": "직장 내 괴롭힘을 한 경우에는",
                "compareAfter": "다음 각 호의 어느 하나에 해당하는",
                "requireHighlight": True,
                "requireBodyApplied": False,
                "requirePhraseAfter": "다음 각 호의 어느 하나에 해당하는",
                "requireLocators": ["제1항"],
            },
            {
                "amendedDate": "2026-04-07",
                "noticeNo": "21533",
                "effectiveDate": "2026-12-08",
                "compareBefore": "근로감독관",
                "compareAfter": "노동감독관",
                "requireHighlight": True,
                "requireBodyApplied": False,
                "requireHighlightPhraseAfter": "노동감독관",
                "requireDeleteHang": "제2항제4호",
                "requireLocators": ["제2항제1호", "제2항제4호"],
                "forbidPhraseAfter": "제102조에 따른 노동감독관",
            },
            {
                "amendedDate": "2026-04-07",
                "noticeNo": "21533",
                "effectiveDate": "2027-01-01",
                "compareBefore": "제48조",
                "compareAfter": "제44조의4제1항ㆍ제4항ㆍ제5항, 제48조",
                "requireHighlight": True,
                "requireBodyApplied": False,
                "requirePhraseAfter": "수급인이 제44조의4제6항",
                "requireLocators": ["제2항제2호", "제1항제2호"],
            },
        ],
    },
    {
        # 법률 제21533·21784호: 제114조 제1호 (일자·합성)
        "lsId": "001872",
        "lawId": "labor-standards",
        "tier": "statute",
        "article": "제114조",
        "must_in_live": ["제95조, 제100조 및 제103조", "제67조제1항"],
        "must_not_in_live": ["제60조제9항"],
        "must_not_after": "2026-12-08",
        "file": "full-labor-statute.txt",
        "amendments": [
            {
                "amendedDate": "2026-04-07",
                "noticeNo": "21533",
                "effectiveDate": "2026-12-08",
                "compareBefore": "제95조, 제100조 및 제103조",
                "compareAfter": "제95조 및 제100조",
                "requireHighlight": True,
                "requireBodyApplied": False,
                "requireHighlightPhraseAfter": "제95조 및 제100조",
                "forbidPhraseAfter": "제103조",
                "requireLocators": ["제1호"],
            },
            {
                "amendedDate": "2026-06-09",
                "noticeNo": "21784",
                "effectiveDate": "2027-06-10",
                "compareBefore": "제67조제1항",
                "compareAfter": "제60조제9항, 제67조제1항",
                "requireHighlight": True,
                "requireBodyApplied": False,
                "requireHighlightPhraseAfter": "제60조제9항",
                "requireLocators": ["제1호"],
            },
        ],
    },
    {
        # 법률 제21475호: 본문 시행 2026.7.1 / 제43·44조만 2026.9.18
        # 기준일(오늘)이 9.18 이전이면 현행 본문은 짧은 구문이어야 함
        "lsId": "009883",
        "lawId": "retirement",
        "tier": "statute",
        "article": "제43조",
        "must_in_live": ["제37조제6항을 위반한"],
        "must_not_in_live": [
            "다음 각 호의 어느 하나에 해당하는 자는 5년 이하의 징역",
            "피해자의 명시적인 의사에 반하여",
        ],
        "must_not_after": "2026-09-18",  # 이 날짜 이상이면 must_not 검사 생략
        "file": "full-retire-statute.txt",
        "amendments": [
            {
                "amendedDate": "2026-03-17",
                "noticeNo": "21475",
                "effectiveDate": "2026-09-18",
                "compareBefore": "제37조제6항을 위반한",
                "compareAfter": "다음 각 호의 어느 하나에 해당하는",
                "requireHighlight": True,
                "requireBodyApplied": False,
            },
        ],
    },
    {
        # 법률 제21533호: 제109조 ① 인용목록 축소 + ② 삭제 (시행 2026.10.8)
        "lsId": "001872",
        "lawId": "labor-standards",
        "tier": "statute",
        "article": "제109조",
        "must_in_live": [
            "제36조, 제43조, 제44조",
            "피해자의 명시적인 의사와 다르게",
        ],
        "must_not_in_live": ["② 삭제"],
        "must_not_after": "2026-10-08",
        "file": "full-labor-statute.txt",
        "amendments": [
            {
                "amendedDate": "2026-04-07",
                "noticeNo": "21533",
                "effectiveDate": "2026-10-08",
                "compareBefore": "제36조, 제43조",
                "compareAfter": "제65조, 제72조",
                "requireHighlight": True,
                "requireBodyApplied": False,
                "requireDeleteHang": "제2항",
                "requirePhraseAfter": "제65조, 제72조 또는 제76조의3제6항",
            },
        ],
    },
]

# 미시행 신설(현행 XML에 조 없음) — 개정문으로 표시 가능해야 함
PENDING_NEW_PROBES = [
    {
        "lawId": "labor-standards",
        "tier": "statute",
        "article": "제44조의4",
        "amendedDate": "2026-04-07",
        "noticeNo": "21533",
        "must_in_after": ["임금비용", "도급인", "수급인"],
    },
]


def article_chunk(full_text: str, article_no: str) -> str:
    """조 헤더(제N조/제N조(제목))부터 다음 조 헤더 직전까지.

    본문 줄이 '제37조제6항…'처럼 시작해도 조 헤더로 오인하지 않는다.
    """
    pat = re.compile(
        rf"(?ms)^{re.escape(article_no)}(?:\([^)]*\))?.*?"
        rf"(?=^제\d+조(?:의\d+)?(?:\([^)]*\))?$|\Z)"
    )
    m = pat.search(full_text or "")
    return m.group(0) if m else ""


def find_article_body(articles: dict, law_id: str, tier: str, no: str) -> str:
    for a in (articles.get(law_id) or {}).get(tier) or []:
        if a.get("no") == no:
            return a.get("body") or ""
    return ""


def extract_live_article(xml: str, article_no: str) -> str:
    """XML에서 조 번호에 해당하는 본문 조각을 파서와 동일 규칙으로 뽑는다."""
    m = re.match(r"^제(\d+)조(?:의(\d+))?$", article_no or "")
    if not m:
        return ""
    want_num, want_br = m.group(1), m.group(2) or ""
    for block in re.findall(r"<조문단위[^>]*>(.*?)</조문단위>", xml, flags=re.S):
        if _cdata("조문여부", block) != "조문":
            continue
        num = _cdata("조문번호", block)
        branch = _cdata("조문가지번호", block)
        label = jo_label(num, branch)
        if label != article_no and not (
            num == want_num and (branch or "") == want_br
        ):
            continue
        # 단일 조만 있는 가짜 XML로 파서 재사용
        mini = f"<법령><조문><조문단위>{block}</조문단위></조문></법령>"
        text = xml_to_full_text(mini)
        return article_chunk(text, article_no) or text
    return ""


def _strip_hist_tags(text: str) -> str:
    t = re.sub(r"\s*<(?:개정|신설)\s[^>]*>", " ", text or "")
    return re.sub(r"\s+", " ", t).strip()


def _minimal_substitution(before: str, after: str) -> tuple[str, str] | None:
    """main.js minimalSubstitution 과 동일 목적의 최소 치환 추출."""
    b = _strip_hist_tags(before)
    a = _strip_hist_tags(after)
    if not b or not a or b == a:
        return None
    pre = 0
    while pre < len(b) and pre < len(a) and b[pre] == a[pre]:
        pre += 1
    suf = 0
    while (
        suf < len(b) - pre
        and suf < len(a) - pre
        and b[len(b) - 1 - suf] == a[len(a) - 1 - suf]
    ):
        suf += 1
    while pre > 0:
        old = b[pre : len(b) - suf]
        occurrences = b.count(old) if old else 0
        if len(old) >= 8 and occurrences == 1:
            break
        if len(old) >= 24 and occurrences >= 1:
            break
        pre -= 1
    return b[pre : len(b) - suf], a[pre : len(a) - suf]


def _fix_josa_jo_eul(text: str) -> str:
    return re.sub(r"조을(?=\s|위반|위반한|,|\.|$)", "조를", text or "")


def compose_pending_phrases(body: str, phrases: list[dict]) -> list[dict]:
    """main.js composePendingPhrases 시뮬레이션 — 같은 locator 연쇄 합성."""
    pending = [
        p
        for p in phrases
        if p
        and p.get("pending")
        and not p.get("isNew")
        and (p.get("beforeText") or "").strip()
        and (p.get("text") or "").strip()
    ]
    rest = [p for p in phrases if p not in pending]
    if len(pending) <= 1:
        return list(phrases)

    groups: dict[str, list[dict]] = {}
    order: list[str] = []
    for p in pending:
        key = (p.get("locator") or "").strip() or "_"
        if key not in groups:
            groups[key] = []
            order.append(key)
        groups[key].append(p)

    out = list(rest)
    raw = body or ""
    for key in order:
        group = groups[key]
        if len(group) <= 1:
            out.extend(group)
            continue
        sorted_g = sorted(
            group,
            key=lambda p: (
                p.get("effectiveDate") or "",
                p.get("amendedDate") or "",
            ),
        )
        anchor = None
        for p in sorted_g:
            b = p.get("beforeText") or ""
            if b and b in raw:
                anchor = b
                break
            bs = _strip_hist_tags(b)
            if bs and bs in raw:
                anchor = bs
                break
        if not anchor:
            out.extend(group)
            continue
        working = _strip_hist_tags(anchor)
        applied: list[dict] = []
        for p in sorted_g:
            sub = _minimal_substitution(p.get("beforeText") or "", p.get("text") or "")
            if sub and sub[0] and sub[0] in working:
                working = working.replace(sub[0], sub[1], 1)
                working = _fix_josa_jo_eul(working)
                applied.append(p)
                continue
            pb = _strip_hist_tags(p.get("beforeText") or "")
            pa = _strip_hist_tags(p.get("text") or "")
            if pb and pb in working:
                working = working.replace(pb, pa, 1)
                working = _fix_josa_jo_eul(working)
                applied.append(p)
        if len(applied) <= 1:
            out.extend(group)
            continue
        by_eff = sorted(
            applied,
            key=lambda p: (
                p.get("effectiveDate") or "",
                p.get("amendedDate") or "",
            ),
        )
        primary = by_eff[0]
        latest = applied[-1]
        composed = {
            "text": working,
            "beforeText": anchor,
            "pending": True,
            "isNew": False,
            "amendedDate": primary.get("amendedDate"),
            "effectiveDate": primary.get("effectiveDate"),
            "locator": latest.get("locator") or applied[0].get("locator") or "",
            "composedFrom": [
                {
                    "amendedDate": p.get("amendedDate"),
                    "effectiveDate": p.get("effectiveDate"),
                }
                for p in by_eff
            ],
        }
        used = {
            (
                (p.get("text") or "")
                + "|"
                + (p.get("locator") or "")
                + "|"
                + (p.get("amendedDate") or "")
            )
            for p in applied
        }
        leftover = [
            p
            for p in group
            if (
                (p.get("text") or "")
                + "|"
                + (p.get("locator") or "")
                + "|"
                + (p.get("amendedDate") or "")
            )
            not in used
        ]
        out.append(composed)
        out.extend(leftover)
    return out


CIRCLE_HANGS = "①②③④⑤⑥⑦⑧⑨⑩⑪⑫⑬⑭⑮"


def _insert_index_for_new_phrase(html: str, phrase: dict) -> int:
    """main.js insertIndexForNewPhrase 와 동일 — 신설 호를 다음 항 앞에 둠."""
    loc = re.sub(r"\s+", "", phrase.get("locator") or "")
    hang_m = re.search(r"제(\d+)항", loc)
    if hang_m:
        hang_n = int(hang_m.group(1))
        if 1 <= hang_n < len(CIRCLE_HANGS):
            next_circle = CIRCLE_HANGS[hang_n]
            at = html.find(next_circle)
            if at != -1:
                return at
    ho_only = re.fullmatch(r"제(\d+)호", loc)
    if ho_only:
        next_num = str(int(ho_only.group(1)) + 1)
        m = re.search(rf"(^|\n){re.escape(next_num)}\.", html)
        if m:
            return m.start() + (len(m.group(1)) if m.group(1) else 0)
    return -1


def _insert_new_pending_phrase(html: str, phrase: dict) -> str:
    after = phrase.get("text") or ""
    if not after or after in html:
        return html
    at = _insert_index_for_new_phrase(html, phrase)
    if at < 0:
        return (html.rstrip() + "\n" + after) if html.strip() else after
    prefix = html[:at]
    suffix = html[at:]
    if prefix and not prefix.endswith("\n"):
        prefix += "\n"
    if suffix and not suffix.startswith("\n"):
        suffix = "\n" + suffix
    return prefix + after + suffix


def simulate_article_highlight_after(
    body: str, phrases: list[dict]
) -> str:
    """음영 적용 후 본문에 보이는 개정 후 텍스트(합성 포함)."""
    composed = compose_pending_phrases(body, phrases)
    html = body or ""
    # 긴 문구부터 (main.js 와 동일)
    ordered = sorted(
        [p for p in composed if (p.get("text") or "").strip()],
        key=lambda p: len(p.get("text") or ""),
        reverse=True,
    )
    for phrase in ordered:
        after = phrase.get("text") or ""
        before = phrase.get("beforeText") or ""
        if not after:
            continue
        if after in html:
            continue
        if phrase.get("pending") and before and before in html:
            html = html.replace(before, after, 1)
        elif phrase.get("pending") and phrase.get("isNew") and after not in html:
            html = _insert_new_pending_phrase(html, phrase)
    # isNew 가 before 매칭 루프에서 스킵된 경우 한 번 더
    for phrase in ordered:
        if not (phrase.get("pending") and phrase.get("isNew")):
            continue
        after = phrase.get("text") or ""
        if after and after not in html:
            html = _insert_new_pending_phrase(html, phrase)
    return html


def check_compose_probes(
    amendments: list[dict], articles: dict, problems: list[str], verbose: bool
) -> None:
    """같은 조 미시행 개정 합성 결과가 법제처 개정 방향과 맞는지 검증."""
    for probe in COMPOSE_PROBES:
        art_no = probe["articleNo"]
        aid = probe.get("articleId") or ""
        body = find_article_body(
            articles, probe["lawId"], "statute", art_no
        ) or find_article_body(articles, probe["lawId"], "decree", art_no)
        phrases: list[dict] = []
        for item in amendments:
            if item.get("articleNo") != art_no:
                continue
            if item.get("lawId") != probe["lawId"]:
                continue
            if item.get("bodyApplied") is True:
                continue
            for h in item.get("highlights") or []:
                if aid and h.get("articleId") and h.get("articleId") != aid:
                    continue
                for p in h.get("phrases") or []:
                    if p.get("skipHighlight"):
                        continue
                    if not (p.get("text") or "").strip():
                        continue
                    # normalizePhrase 상당: pending 유지
                    ph = dict(p)
                    if item.get("bodyApplied") is False:
                        ph["pending"] = True
                    phrases.append(ph)
        if not phrases:
            problems.append(f"compose_no_phrases {art_no}")
            if verbose:
                print(f"[FAIL] compose {art_no}: no phrases")
            continue
        after = simulate_article_highlight_after(body, phrases)
        ok = True
        for token in probe.get("requireInComposed") or []:
            if token not in after:
                problems.append(f"compose_missing {art_no}: {token}")
                ok = False
        for token in probe.get("forbidInComposed") or []:
            if token in after:
                problems.append(f"compose_forbidden {art_no}: {token}")
                ok = False
        order = probe.get("requireOrder") or []
        if order:
            cursor = -1
            for token in order:
                at = after.find(token)
                if at == -1:
                    problems.append(f"compose_order_missing {art_no}: {token}")
                    ok = False
                    continue
                if at < cursor:
                    problems.append(
                        f"compose_order_violation {art_no}: {token} at {at} < {cursor}"
                    )
                    ok = False
                cursor = at
        # 합성 phrase 의 공포·시행 (제114조 다중 개정)
        want_dates = probe.get("requireComposedDates") or []
        if want_dates:
            composed = compose_pending_phrases(body, phrases)
            target = None
            for p in composed:
                if p.get("composedFrom"):
                    target = p
                    break
            if not target:
                problems.append(f"compose_no_composedFrom {art_no}")
                ok = False
            else:
                got = {
                    (
                        (c.get("amendedDate") if isinstance(c, dict) else c) or "",
                        (c.get("effectiveDate") if isinstance(c, dict) else "") or "",
                    )
                    for c in (target.get("composedFrom") or [])
                }
                # legacy string-only composedFrom → effective 는 phrase 대표값
                if got and all(not g[1] for g in got):
                    got = {
                        (g[0], target.get("effectiveDate") or "") for g in got
                    }
                for d in want_dates:
                    key = (d.get("amendedDate") or "", d.get("effectiveDate") or "")
                    if key not in got:
                        # effective 비어 있으면 amended 만 비교
                        if not any(g[0] == key[0] for g in got):
                            problems.append(
                                f"compose_date_missing {art_no}: {key[0]}/{key[1]}"
                            )
                            ok = False
                # 대표 칩 = 가장 빠른 시행
                if (target.get("amendedDate"), target.get("effectiveDate")) != (
                    want_dates[0].get("amendedDate"),
                    want_dates[0].get("effectiveDate"),
                ):
                    problems.append(
                        f"compose_primary_date {art_no}: "
                        f"{target.get('amendedDate')}/{target.get('effectiveDate')} "
                        f"!= {want_dates[0].get('amendedDate')}/{want_dates[0].get('effectiveDate')}"
                    )
                    ok = False
        if verbose:
            status = "OK" if ok else "FAIL"
            print(f"[{status}] compose {art_no} phrases={len(phrases)}")


def run_simulation(verbose: bool = True) -> dict:
    problems: list[str] = []
    checks: list[dict] = []
    articles = {}
    if ARTICLES_PATH.is_file():
        articles = json.loads(ARTICLES_PATH.read_text(encoding="utf-8"))
    cache = {}
    if CACHE_PATH.is_file():
        cache = json.loads(CACHE_PATH.read_text(encoding="utf-8"))
    amendments = cache.get("amendments") or []

    for probe in LIVE_PROBES:
        ls_id = probe["lsId"]
        art_no = probe["article"]
        try:
            xml = fetch_xml(ls_id)
            live_full = xml_to_full_text(xml)
            live_art = article_chunk(live_full, art_no) or extract_live_article(xml, art_no)
        except Exception as exc:  # noqa: BLE001
            problems.append(f"live_fetch_fail {ls_id}: {exc}")
            continue

        row = {
            "lsId": ls_id,
            "article": art_no,
            "liveChars": len(live_art),
            "ok": True,
            "details": [],
        }

        for token in probe["must_in_live"]:
            if token not in live_art:
                problems.append(f"live_missing {art_no}: {token}")
                row["ok"] = False
                row["details"].append(f"live_missing:{token}")

        # 미시행 조문특례: 기준일 전에는 개정 후 전문이 본문에 있으면 안 됨
        check_not = True
        not_after = probe.get("must_not_after") or ""
        if not_after:
            try:
                from datetime import date as _date

                y, m, d = [int(x) for x in not_after.split("-")]
                if _date.today() >= _date(y, m, d):
                    check_not = False
            except Exception:  # noqa: BLE001
                check_not = True
        if check_not:
            for token in probe.get("must_not_in_live") or []:
                for label, blob in (
                    ("live", live_art),
                    (
                        "local",
                        article_chunk(
                            (FETCH / probe["file"]).read_text(encoding="utf-8")
                            if (FETCH / probe["file"]).is_file()
                            else "",
                            art_no,
                        ),
                    ),
                    ("articles", find_article_body(articles, probe["lawId"], probe["tier"], art_no)),
                ):
                    if token and token in (blob or ""):
                        problems.append(f"premature_body {label} {art_no}: {token[:40]}")
                        row["ok"] = False
                        row["details"].append(f"premature:{label}")

        local_path = FETCH / probe["file"]
        if local_path.is_file():
            local_full = local_path.read_text(encoding="utf-8")
            local_art = article_chunk(local_full, art_no)
            if not local_art.strip():
                problems.append(f"local_full_empty {probe['file']} {art_no}")
                row["ok"] = False
                row["details"].append("local_full_empty")
            else:
                for token in probe["must_in_live"]:
                    if token not in local_art:
                        problems.append(
                            f"local_full_missing {probe['file']} {art_no}: {token}"
                        )
                        row["ok"] = False
                        row["details"].append(f"local_full_missing:{token}")
        else:
            problems.append(f"local_full_absent {probe['file']}")
            row["ok"] = False

        body = find_article_body(articles, probe["lawId"], probe["tier"], art_no)
        if not body.strip():
            problems.append(f"articles_empty_body {probe['lawId']} {art_no}")
            row["ok"] = False
            row["details"].append("articles_empty_body")
        else:
            for token in probe["must_in_live"]:
                if token not in body:
                    problems.append(f"articles_missing {art_no}: {token}")
                    row["ok"] = False
                    row["details"].append(f"articles_missing:{token}")

        for amd in probe.get("amendments") or []:
            hits = [
                a
                for a in amendments
                if a.get("articleNo") == art_no
                and a.get("amendedDate") == amd["amendedDate"]
                and str(a.get("noticeNo") or "") == str(amd["noticeNo"])
                and a.get("lawId") == probe["lawId"]
            ]
            if amd.get("effectiveDate"):
                exact = [
                    a for a in hits if a.get("effectiveDate") == amd["effectiveDate"]
                ]
                if exact:
                    hits = exact
            if not hits:
                problems.append(
                    f"cache_missing_amendment {art_no} {amd['amendedDate']} #{amd['noticeNo']}"
                )
                row["ok"] = False
                row["details"].append(f"cache_missing:{amd['noticeNo']}")
                continue
            item = hits[0]
            if amd.get("effectiveDate") and item.get("effectiveDate") != amd["effectiveDate"]:
                problems.append(
                    f"effective_mismatch {item.get('id')}: "
                    f"{item.get('effectiveDate')} != {amd['effectiveDate']}"
                )
                row["ok"] = False
            if "requireBodyApplied" in amd and item.get("bodyApplied") is not amd["requireBodyApplied"]:
                problems.append(
                    f"bodyApplied_mismatch {item.get('id')}: "
                    f"{item.get('bodyApplied')} != {amd['requireBodyApplied']}"
                )
                row["ok"] = False
            before = (item.get("compareBefore") or "") + "".join(
                (p.get("beforeText") or "")
                for h in (item.get("highlights") or [])
                for p in (h.get("phrases") or [])
            )
            after = (item.get("compareAfter") or "") + "".join(
                (p.get("text") or "")
                for h in (item.get("highlights") or [])
                for p in (h.get("phrases") or [])
            )
            if amd.get("compareBefore") and amd["compareBefore"] not in before:
                problems.append(
                    f"compare_before_mismatch {item.get('id')}: want {amd['compareBefore']}"
                )
                row["ok"] = False
            if amd.get("compareAfter") and amd["compareAfter"] not in after:
                problems.append(
                    f"compare_after_mismatch {item.get('id')}: want {amd['compareAfter']}"
                )
                row["ok"] = False
            if amd.get("requireHighlight"):
                phrases = [
                    p
                    for h in (item.get("highlights") or [])
                    for p in (h.get("phrases") or [])
                    if (p.get("text") or p.get("beforeText"))
                    and not p.get("skipHighlight")
                ]
                if not phrases:
                    problems.append(f"highlight_empty {item.get('id')}")
                    row["ok"] = False
                    row["details"].append(f"highlight_empty:{amd['noticeNo']}")
                else:
                    # pending 일반개정: before가 본문에 있어야 함
                    # pending 신설(isNew): 본문 없이도 phrase.text 로 표시
                    if item.get("bodyApplied") is False and body:
                        ok_phrase = False
                        for p in phrases:
                            b = (p.get("beforeText") or "").strip()
                            t = (p.get("text") or "").strip()
                            if (b and b in body) or (t and t in body) or p.get("isNew"):
                                ok_phrase = True
                                break
                        if not ok_phrase:
                            problems.append(
                                f"highlight_not_in_body {item.get('id')}"
                            )
                            row["ok"] = False
            # 항 삭제 개정이면 노란 음영 phrase에 '삭제'가 있어야 함
            if amd.get("requireDeleteHang"):
                del_loc = amd["requireDeleteHang"]
                del_phrases = [
                    p
                    for h in (item.get("highlights") or [])
                    for p in (h.get("phrases") or [])
                    if not p.get("skipHighlight")
                    and "삭제" in (p.get("text") or "")
                    and (
                        del_loc in (p.get("locator") or "")
                        or del_loc.replace("제", "").replace("항", "")
                        in (p.get("text") or "")
                    )
                ]
                if not del_phrases:
                    # 텍스트에 ② 삭제 형태만 있어도 통과
                    del_phrases = [
                        p
                        for h in (item.get("highlights") or [])
                        for p in (h.get("phrases") or [])
                        if not p.get("skipHighlight")
                        and re.search(r"[①-⑮]\s*삭제", p.get("text") or "")
                    ]
                if not del_phrases:
                    problems.append(
                        f"delete_hang_missing {item.get('id')}: {del_loc}"
                    )
                    row["ok"] = False
                    row["details"].append(f"delete_hang_missing:{del_loc}")
                else:
                    # 삭제 before가 현행 본문 항과 맞는지
                    bp = (del_phrases[0].get("beforeText") or "").strip()
                    if item.get("bodyApplied") is False and body and bp and bp not in body:
                        problems.append(
                            f"delete_before_not_in_body {item.get('id')}"
                        )
                        row["ok"] = False
            if amd.get("requirePhraseAfter"):
                needle = amd["requirePhraseAfter"]
                texts = " ".join(
                    (p.get("text") or "")
                    for h in (item.get("highlights") or [])
                    for p in (h.get("phrases") or [])
                    if not p.get("skipHighlight")
                )
                blob = texts + " " + (item.get("compareAfter") or "")
                if needle not in blob:
                    problems.append(
                        f"phrase_after_missing {item.get('id')}: {needle[:40]}"
                    )
                    row["ok"] = False
            # 노란 음영 phrase에만 있어야 함(compareAfter만 있고 화면 누락 방지)
            if amd.get("requireHighlightPhraseAfter"):
                needle = amd["requireHighlightPhraseAfter"]
                texts = " ".join(
                    (p.get("text") or "")
                    for h in (item.get("highlights") or [])
                    for p in (h.get("phrases") or [])
                    if not p.get("skipHighlight")
                )
                if needle not in texts:
                    problems.append(
                        f"highlight_phrase_after_missing {item.get('id')}: {needle[:40]}"
                    )
                    row["ok"] = False
                    row["details"].append(f"highlight_phrase_missing:{needle[:24]}")
            if amd.get("requireLocators"):
                locs = {
                    (p.get("locator") or "").strip()
                    for h in (item.get("highlights") or [])
                    for p in (h.get("phrases") or [])
                    if not p.get("skipHighlight")
                }
                locs.update(str(x).strip() for x in (item.get("locators") or []) if x)
                for want in amd["requireLocators"]:
                    if not any(want in loc for loc in locs):
                        problems.append(
                            f"locator_missing {item.get('id')}: {want}"
                        )
                        row["ok"] = False
                        row["details"].append(f"locator_missing:{want}")
            if amd.get("forbidPhraseAfter"):
                bad = amd["forbidPhraseAfter"]
                texts = " ".join(
                    (p.get("text") or "")
                    for h in (item.get("highlights") or [])
                    for p in (h.get("phrases") or [])
                    if not p.get("skipHighlight")
                )
                # 개정 후(text/compareAfter)에 금지 토큰이 있으면 전·후 뒤집힘·과다 음영
                if bad in texts or bad in (item.get("compareAfter") or ""):
                    problems.append(
                        f"phrase_after_forbidden {item.get('id')}: {bad}"
                    )
                    row["ok"] = False
            if amd.get("requirePhraseBefore"):
                needle = amd["requirePhraseBefore"]
                befores = (item.get("compareBefore") or "") + " ".join(
                    (p.get("beforeText") or "")
                    for h in (item.get("highlights") or [])
                    for p in (h.get("phrases") or [])
                )
                if needle not in befores:
                    problems.append(
                        f"phrase_before_missing {item.get('id')}: {needle[:40]}"
                    )
                    row["ok"] = False
                    row["details"].append(f"phrase_before_missing:{needle[:24]}")

        checks.append(row)
        if verbose:
            status = "OK" if row["ok"] else "FAIL"
            print(f"[{status}] {art_no} liveChars={row['liveChars']} {row['details']}")

    # --- 미시행 신설 조: 현행 XML에 없어도 개정문으로 표시 가능해야 함 ---
    for probe in PENDING_NEW_PROBES:
        hits = [
            a
            for a in amendments
            if a.get("lawId") == probe["lawId"]
            and a.get("articleNo") == probe["article"]
            and a.get("amendedDate") == probe["amendedDate"]
            and str(a.get("noticeNo") or "") == str(probe["noticeNo"])
        ]
        row = {"article": probe["article"], "ok": True, "details": []}
        if not hits:
            problems.append(f"pending_new_missing {probe['article']}")
            row["ok"] = False
        else:
            item = hits[0]
            after = (item.get("compareAfter") or "").strip()
            phrases = [
                p
                for h in (item.get("highlights") or [])
                for p in (h.get("phrases") or [])
                if not p.get("skipHighlight") and (p.get("text") or "").strip()
            ]
            if not after and not phrases:
                problems.append(f"pending_new_empty_text {item.get('id')}")
                row["ok"] = False
            if not phrases:
                problems.append(f"pending_new_no_highlight {item.get('id')}")
                row["ok"] = False
            blob = after + "".join(p.get("text") or "" for p in phrases)
            for token in probe.get("must_in_after") or []:
                if token not in blob:
                    problems.append(f"pending_new_token {probe['article']}: {token}")
                    row["ok"] = False
        checks.append(row)
        if verbose:
            print(
                f"[{'OK' if row['ok'] else 'FAIL'}] pending-new {probe['article']} {row['details']}"
            )

    # --- 주요 4법×3단: 개정 조문이 화면에 표시될 본문이 있는지 ---
    display_gaps = 0
    for item in amendments:
        if item.get("lawId") not in MAJOR_LAWS:
            continue
        if not item.get("articleLevel"):
            continue
        after = (item.get("compareAfter") or "").strip()
        before = (item.get("compareBefore") or "").strip()
        phrases = [
            p
            for h in (item.get("highlights") or [])
            for p in (h.get("phrases") or [])
            if not p.get("skipHighlight") and (p.get("text") or "").strip()
        ]
        tier = TIER_KEY.get(item.get("tier") or "", "")
        body = find_article_body(
            articles, item.get("lawId") or "", tier, item.get("articleNo") or ""
        )
        is_new_article = before.startswith("해당 조 없음")
        is_new = is_new_article or any(p.get("isNew") for p in phrases)
        displayable = bool(body.strip()) or (
            is_new_article and (bool(after) or bool(phrases))
        )
        # 조 전체 신설인데 표시 텍스트/하이라이트가 없으면 누락
        if is_new_article and after and len(after) >= 20 and not displayable:
            problems.append(f"display_gap {item.get('id')}")
            display_gaps += 1
        if is_new_article and after and len(after) >= 40 and not phrases:
            problems.append(f"new_article_no_highlight {item.get('id')}")
            display_gaps += 1

        # 미시행 개정: 전·후가 동일하면(연혁 태그만 추가) 법제처와 불일치한 파싱
        def _norm_cmp(s: str) -> str:
            s = re.sub(r"\s*<[^>]+>\s*", " ", s or "")
            return re.sub(r"\s+", " ", s).strip()

        if item.get("bodyApplied") is False and before and after:
            if _norm_cmp(before) == _norm_cmp(after) and not before.startswith("해당"):
                problems.append(f"pending_empty_diff {item.get('id')}")
                display_gaps += 1
            summary = item.get("summary") or ""
            # 단서 '신설'인데 개정 후 문구에 단서/명시 요청이 없으면 파싱 누락
            if re.search(r"단서\s*.*신설|신설.*단서", summary) and not (
                "다만," in after or "명시적" in after
            ):
                problems.append(f"pending_proviso_missing {item.get('id')}")
                display_gaps += 1
            # 시행 전인데 로컬 본문에 개정 후 전용 토큰이 있으면 오염
            if body and after and "명시적으로 요청" in after and "명시적으로 요청" in body:
                problems.append(f"pending_body_polluted {item.get('id')}")
                display_gaps += 1
        # 미시행·하이라이트 없음·개정 전 문구가 본문에 없으면 오귀속 유령 카드
        # (이미 시행되어 개정 후만 본문에 남은 경우는 정상)
        if item.get("articleLevel") and not phrases:
            cb = (item.get("compareBefore") or "").strip()
            ca = (item.get("compareAfter") or "").strip()
            if item.get("bodyApplied") is False:
                if cb and not cb.startswith("해당") and body and cb not in body:
                    problems.append(f"ghost_amendment {item.get('id')}")
                    display_gaps += 1
                if not cb and not ca:
                    problems.append(f"ghost_amendment {item.get('id')}")
                    display_gaps += 1
            elif (
                body
                and cb
                and ca
                and not cb.startswith("해당")
                and cb not in body
                and ca not in body
            ):
                problems.append(f"ghost_amendment {item.get('id')}")
                display_gaps += 1
    if verbose:
        print(f"[INFO] 4법 display_gap count={display_gaps}")

    # 같은 조 미시행 개정 합성(제110조: 제104조 + 제4항부터) — UI와 동일 규칙
    check_compose_probes(amendments, articles, problems, verbose)

    # 빈 본문 조문: 개정 캐시에 없고 표시 경로도 없는 경우만 문제로 집계
    empty_n = 0
    orphan_empty = 0
    amended_ids = set()
    for item in amendments:
        for aid in item.get("articleIds") or []:
            amended_ids.add(aid)
    for law_id in MAJOR_LAWS:
        pack = articles.get(law_id) or {}
        for tier in ("statute", "decree", "rule"):
            for a in pack.get(tier) or []:
                if (a.get("body") or "").strip():
                    continue
                empty_n += 1
                if a.get("id") in amended_ids:
                    # 개정 대상인데 본문 공백 → 신설 하이라이트로 보완됐는지 확인
                    related = [
                        it
                        for it in amendments
                        if a.get("id") in (it.get("articleIds") or [])
                    ]
                    ok = any(
                        (it.get("compareAfter") or "").strip()
                        or any(
                            (p.get("text") or "").strip()
                            for h in (it.get("highlights") or [])
                            for p in (h.get("phrases") or [])
                        )
                        for it in related
                    )
                    if not ok:
                        orphan_empty += 1
                        problems.append(
                            f"amended_empty_body {law_id} {a.get('no')}"
                        )
    if orphan_empty:
        if verbose:
            print(f"[FAIL] amended empty bodies without text: {orphan_empty}")

    # --- 개정문 파서가 뽑은 조가 캐시에 있는지 (제61조 누락 등) ---
    try:
        from datetime import date as _date

        from amendment_articles import extract_article_changes, fetch_doc_map

        law_meta = {
            "labor-standards": ("001872", "근로기준법"),
            "retirement": ("009883", "근로자퇴직급여 보장법"),
            "equal-employment": ("000130", "남녀고용평등과 일ㆍ가정 양립 지원에 관한 법률"),
            "fixed-term": ("010356", "기간제 및 단시간근로자 보호 등에 관한 법률"),
        }
        for law_id, (ls_id, law_name) in law_meta.items():
            notice_dates: dict[str, tuple[str, str]] = {}
            for a in amendments:
                if a.get("lawId") != law_id or a.get("tier") != "법률":
                    continue
                n = str(a.get("noticeNo") or "")
                if not n:
                    continue
                notice_dates.setdefault(
                    n, (a.get("amendedDate") or "", a.get("effectiveDate") or "")
                )
            if not notice_dates:
                continue
            try:
                docs = fetch_doc_map(ls_id)
            except Exception as exc:  # noqa: BLE001
                problems.append(f"doc_fetch_fail {ls_id}: {exc}")
                continue
            for notice, (amd_s, eff_s) in notice_dates.items():
                text = (docs or {}).get(notice) or ""
                if len(text) < 40:
                    continue
                try:
                    amd = _date.fromisoformat(amd_s)
                    eff = _date.fromisoformat(eff_s) if eff_s else amd
                except Exception:  # noqa: BLE001
                    continue
                parsed = extract_article_changes(
                    text, amd, eff, law_id=law_id, law_name=law_name
                )
                have = {
                    a.get("articleNo")
                    for a in amendments
                    if a.get("lawId") == law_id
                    and str(a.get("noticeNo") or "") == notice
                    and a.get("articleLevel")
                    and a.get("articleNo")
                }
                for ch in parsed:
                    jo = ch.get("articleNo")
                    if not jo or jo in have:
                        continue
                    # 본문에 적용 불가한 치환만 있는 파싱 결과는 누락으로 보지 않음
                    body = find_article_body(articles, law_id, "statute", jo)
                    ops = ch.get("ops") or []
                    applicable = False
                    for op in ops:
                        k = op.get("kind")
                        if k in (
                            "new_article",
                            "proviso",
                            "insert",
                            "delete_mark",
                            "delete_proviso",
                            "delete_ho",
                            "renumber",
                            "renumber_ho",
                        ):
                            applicable = True
                            break
                        if k == "replace" and (
                            (op.get("old") or "") in body
                            or (op.get("new") or "") in body
                        ):
                            applicable = True
                            break
                    if ch.get("newProviso"):
                        applicable = True
                    if not applicable:
                        continue
                    problems.append(f"doc_article_missing {law_id} {notice} {jo}")
                    if verbose:
                        print(f"[FAIL] doc_article_missing {law_id} {notice} {jo}")
    except Exception as exc:  # noqa: BLE001
        problems.append(f"doc_coverage_error: {exc}")

    # --- 전체 조문개정: 노란 음영(highlights) 미처리 검사 ---
    yellow_missing = 0
    for item in amendments:
        if not item.get("articleLevel"):
            continue
        ca = (item.get("compareAfter") or "").strip()
        cb = (item.get("compareBefore") or "").strip()
        summary = item.get("summary") or ""
        needs = bool(ca or cb or re.search(r"→|삭제|신설", summary))
        if not needs:
            continue
        phrases = [
            p
            for h in (item.get("highlights") or [])
            for p in (h.get("phrases") or [])
            if not p.get("skipHighlight") and (p.get("text") or "").strip()
        ]
        if not phrases:
            yellow_missing += 1
            problems.append(f"missing_yellow_highlight {item.get('id')}")
            if verbose:
                print(f"[FAIL] missing_yellow_highlight {item.get('id')}")
    if verbose and yellow_missing == 0:
        print("[INFO] yellow highlight coverage ok")

    # UI: 안내문 중복 문구가 main.js 에 남아 있지 않은지
    if MAIN_JS.is_file():
        main_src = MAIN_JS.read_text(encoding="utf-8")
        if "article-item__hint" in main_src:
            problems.append("ui_duplicate_hint_still_present")
        if main_src.count("amend-note") > 2:
            # 정의 1 + 문자열 1 정도만 허용
            pass
        if "조문 전문을 표시하고" in main_src and "변경된 호(없으면" in main_src:
            problems.append("ui_two_guide_texts_still_present")
        # 제110조처럼 같은 호에 미시행 개정이 겹칠 때 연쇄 합성 필요
        if "composePendingPhrases" not in main_src:
            problems.append("ui_missing_compose_pending_phrases")
        # 제109조 ①치환+②삭제가 한 덩어리로 합쳐지지 않도록 locator 그룹 합성
        if "composePendingGroup" not in main_src:
            problems.append("ui_missing_compose_pending_group")

    # FULL_TARGETS 파일에 조문 헤더가 있는지 가볍게 확인
    # 기간제 시행규칙 등은 본래 조문이 2개뿐이라 하한을 낮춤
    for _law, tier, _ls, filename, _must in FULL_TARGETS:
        path = FETCH / filename
        if not path.is_file():
            continue
        text = path.read_text(encoding="utf-8")
        jo_n = len(re.findall(r"(?m)^제\d+조", text))
        min_n = 1 if tier == "rule" else 3
        if jo_n < min_n:
            problems.append(f"sparse_full_file:{filename}:{jo_n}")

    result = {
        "ok": len(problems) == 0,
        "problems": problems,
        "checks": checks,
        "emptyBodies": empty_n,
        "orphanEmptyAmended": orphan_empty,
        "displayGaps": display_gaps,
    }
    if verbose:
        print("---")
        print(json.dumps({"ok": result["ok"], "problemCount": len(problems)}, ensure_ascii=False))
        for p in problems[:40]:
            print(" -", p)
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description="법제처 대조 자체검증 시뮬레이션")
    parser.add_argument("--quiet", action="store_true")
    parser.add_argument(
        "--soft",
        action="store_true",
        help="실패해도 exit 0 (CI에서 커밋을 막지 않을 때)",
    )
    args = parser.parse_args()
    result = run_simulation(verbose=not args.quiet)
    (FETCH / "_parity_report.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    soft = args.soft  # CI 자동 soft 금지 — 갱신 파이프라인은 refresh가 재시도·차단
    if not result["ok"]:
        for p in result.get("problems") or []:
            print(f"::warning title=parity::{p}")
        if soft:
            print("parity soft-fail: problems recorded, exit 0")
            raise SystemExit(0)
    raise SystemExit(0 if result["ok"] else 1)


if __name__ == "__main__":
    main()
