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
from collections import Counter
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
        # 21533·21784 → 호 전문 1음영(조각 분리 금지), 최종 문구에 두 변경 모두
        "requireInComposed": ["제104조를", "제4항부터 제6항까지"],
        "forbidInComposed": ["제104조제2항"],
        "forbidDualDateChips": True,
        "forbidSpanHighlight": True,
        "requireHangUnit": [
            {
                "locator": "제1호",
                "mustInclude": "제104조",
                "minLen": 40,
            }
        ],
    },
    {
        "lawId": "labor-standards",
        "articleNo": "제114조",
        "articleId": "labor-standards-statute-114",
        # 21533 + 21784 → 호 전문 1음영
        "requireInComposed": ["제60조제9항", "제95조 및 제100조"],
        "forbidInComposed": ["제103조"],
        "forbidDualDateChips": True,
        "forbidSpanHighlight": True,
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
            # 미시행 삭제는 본문에 현행(제102조…) 유지 — '4. 삭제'로 바꾸지 않음
            "제102조에 따른 근로감독관",
        ],
        "requireOrder": [
            "다음 각 호의 어느 하나에 해당하는 경우에는 1천만원",
            "수급인이 제44조의4제6항",
            "② 다음 각 호의",
            "노동감독관",
            "제102조에 따른 근로감독관",
        ],
        "requirePendingDelete": [
            {
                "locator": "제2항제4호",
                "beforeHas": "제102조에 따른 근로감독관",
                "afterHas": "4. 삭제",
            }
        ],
        "forbidDualDateChips": True,
        "forbidSpanHighlight": True,
    },
    {
        # 퇴직급여법 제43조: 각 호 신설은 1→2→3 순서 (길이순 삽입 회귀 방지)
        "lawId": "retirement",
        "articleNo": "제43조",
        "articleId": "retirement-statute-43",
        "requireInComposed": [
            "1. 제9조제1항을 위반하여 퇴직금을 지급하지 아니한 자",
            "2. 근로자가 퇴직할 때에",
            "3. 제37조제6항을 위반한 자",
        ],
        "requireOrder": [
            "1. 제9조제1항을 위반하여 퇴직금을 지급하지 아니한 자",
            "2. 근로자가 퇴직할 때에",
            "3. 제37조제6항을 위반한 자",
        ],
    },
    {
        # 남녀고용평등법 제19조: 21373 ⑥⑦⑧ 신설+⑥→⑨, 21476 배우자 돌봄
        "lawId": "equal-employment",
        "articleNo": "제19조",
        "articleId": "equal-employment-statute-19",
        "requireInComposed": [
            "모성을 보호하려는 경우, 남성 근로자가",
            "⑥ 사업주는 근로자가 만 8세 이하",
            "⑦ 제6항에 따른 육아휴직",
            "⑧ 사업주는 제6항 단서",
            "⑨ 육아휴직의 신청방법",
        ],
        "requireOrder": [
            "모성을 보호하려는 경우, 남성 근로자가",
            "⑥ 사업주는 근로자가 만 8세 이하",
            "⑦ 제6항에 따른 육아휴직",
            "⑧ 사업주는 제6항 단서",
            "⑨ 육아휴직의 신청방법",
        ],
        "forbidInComposed": ["경우에는는", "는는"],
    },
    {
        # 제19조의4 제1항: 21373+21476 → 항 전문 1음영(조각·이중칩 금지)
        "lawId": "equal-employment",
        "articleNo": "제19조의4",
        "articleId": "equal-employment-statute-19조의4",
        "requireInComposed": [
            "모성을 보호하거나 남성 근로자가 고용노동부령",
            "제19조제6항에 따른 육아휴직을 사용한 횟수",
        ],
        "forbidDualDateChips": True,
        "forbidSpanHighlight": True,
        "requireSingleMarkPerLocator": [
            {"locator": "제1항"},
        ],
        "requireHangUnit": [
            {
                "locator": "제1항",
                "mustStartWith": "①",
                "mustInclude": "모성을 보호하거나",
                "minLen": 80,
            }
        ],
    },
    {
        # 남녀고용평등법 제18조: 동일 개정의 제1항은 항 전문 1음영·칩 1쌍
        "lawId": "equal-employment",
        "articleNo": "제18조",
        "articleId": "equal-employment-statute-18",
        "requireInComposed": [
            "배우자 출산전후휴가",
            "제18조의4에 따른 배우자 유산ㆍ사산휴가",
            "제18조의4제1항 본문",
        ],
        "forbidInComposed": ["제3장에 제18조의4"],
        "forbidDualDateChips": True,
        "forbidSpanHighlight": True,
        "requireSingleMarkPerLocator": [
            {"locator": "제1항", "amendedDate": "2026-03-17"},
            {"locator": "제2항", "amendedDate": "2026-03-17"},
        ],
        "requireHangUnit": [
            {
                "locator": "제1항",
                "mustStartWith": "①",
                "mustInclude": "배우자 출산전후휴가",
                "minLen": 80,
            }
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
                "requirePendingDelete": True,
                "requireLocators": ["제2항제1호", "제2항제4호"],
                "forbidPhraseAfter": "제102조에 따른 노동감독관",
                "requirePhraseBeforeHas": "제102조에 따른 근로감독관",
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
                # 각 호 신설이 청크 절단으로 유실되면 안 됨 (CI parity=6 회귀)
                "requireLocators": ["1호", "2호", "3호"],
                "requirePhraseAfter": "1. 제9조제1항을 위반하여 퇴직금을 지급하지 아니한 자",
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


def _with_jo_prefix(raw: str, old: str, neu: str) -> tuple[str, str]:
    """최소 치환이 '제'를 빼면 음영이 끊기므로 본문에 '제'+old 있으면 복원."""
    if not old or not neu:
        return old, neu
    if old.startswith("제"):
        return old, neu
    prefixed = "제" + old
    if prefixed in (raw or ""):
        return prefixed, "제" + neu
    return old, neu


def _is_clean_span(old: str, neu: str) -> bool:
    if not old or not neu:
        return False
    if len(old) < 4 or len(neu) < 2:
        return False
    if re.match(r"^[\s,·ㆍ]", old) or re.search(r"[\s,·ㆍ]$", old):
        return False
    if re.match(r"^[\s,·ㆍ]", neu) or re.search(r"[\s,·ㆍ]$", neu):
        return False
    return True


def _resolve_independent_span(p: dict, raw: str) -> tuple[str, str] | None:
    summary = p.get("amendmentSummary") or p.get("amendmentTitle") or ""
    sm = re.search(r"「([^」]{2,120})」\s*→\s*「([^」]{2,120})」", summary)
    sub: tuple[str, str] | None = None
    if sm and sm.group(1) in raw and _is_clean_span(sm.group(1), sm.group(2)):
        sub = (sm.group(1), sm.group(2))
    else:
        got = _minimal_substitution(p.get("beforeText") or "", p.get("text") or "")
        if not (got and got[0] and got[0] in raw):
            return None
        old, neu = _with_jo_prefix(raw, got[0], got[1])
        if old not in raw or not _is_clean_span(old, neu):
            return None
        sub = (old, neu)
    old, neu = sub
    if old + "을" in raw:
        neu = neu if re.search(r"[을를]$", neu) else neu + "를"
        old = old + "을"
    elif old + "를" in raw:
        neu = neu if re.search(r"[을를]$", neu) else neu + "를"
        old = old + "를"
    return old, neu


def compose_pending_phrases(body: str, phrases: list[dict]) -> list[dict]:
    """main.js composePendingPhrases 시뮬레이션.

    항·호 단위 1음영만 허용. 서로 다른 개정일이어도 조각(span) 음영으로 쪼개지 않는다.
    """
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
        by_len = sorted(
            sorted_g,
            key=lambda p: len(p.get("beforeText") or ""),
            reverse=True,
        )
        anchor = None
        for p in by_len:
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
            full = by_len[0]
            if full and _strip_hist_tags(full.get("beforeText") or "") != _strip_hist_tags(
                full.get("text") or ""
            ):
                out.append(full)
            else:
                out.append(group[0])
            continue
        by_eff = sorted(
            applied,
            key=lambda p: (
                p.get("effectiveDate") or "",
                p.get("amendedDate") or "",
            ),
        )
        primary = by_eff[-1]  # 최종 합성문 기준 = 가장 늦은 시행
        latest = applied[-1]
        out.append(
            {
                "text": working,
                "beforeText": anchor,
                "pending": True,
                "isNew": False,
                "amendedDate": primary.get("amendedDate"),
                "effectiveDate": primary.get("effectiveDate"),
                "locator": latest.get("locator") or applied[0].get("locator") or "",
            }
        )
    return out


CIRCLE_HANGS = "①②③④⑤⑥⑦⑧⑨⑩⑪⑫⑬⑭⑮"
CIRCLE_TO_N = {ch: i + 1 for i, ch in enumerate(CIRCLE_HANGS)}


def _extract_ho_num(locator: str, text: str = "") -> int | None:
    loc = re.sub(r"\s+", "", locator or "")
    m = re.fullmatch(r"(?:제\d+항)?제?(\d+)(?:의\d+)?호", loc)
    if m:
        return int(m.group(1))
    m = re.match(r"^(\d+)(?:의\d+)?\.", (text or "").lstrip())
    if m:
        return int(m.group(1))
    return None


def _phrase_structure_sort_key(phrase: dict) -> int:
    loc = re.sub(r"\s+", "", phrase.get("locator") or "")
    text = (phrase.get("text") or "").lstrip()
    hang = 0
    hang_m = re.search(r"제(\d+)항", loc)
    if hang_m:
        hang = int(hang_m.group(1))
    elif text and text[0] in CIRCLE_TO_N:
        hang = CIRCLE_TO_N[text[0]]
    ho = _extract_ho_num(loc, text)
    return hang * 100000 + (0 if ho is None else ho)


def _insert_index_for_new_phrase(html: str, phrase: dict) -> int:
    """main.js insertIndexForNewPhrase 와 동일 — 항 블록 안에서 호 번호순 삽입."""
    loc = re.sub(r"\s+", "", phrase.get("locator") or "")
    ho_num = _extract_ho_num(loc, phrase.get("text") or "")
    hang_m = re.search(r"제(\d+)항", loc)

    range_start = 0
    range_end = len(html)
    if hang_m:
        hang_n = int(hang_m.group(1))
        if 1 <= hang_n <= len(CIRCLE_HANGS):
            circle = CIRCLE_HANGS[hang_n - 1]
            at = html.find(circle)
            if at != -1:
                range_start = at
            if hang_n < len(CIRCLE_HANGS):
                next_circle = CIRCLE_HANGS[hang_n]
                end_at = html.find(next_circle, range_start + 1)
                if end_at != -1:
                    range_end = end_at

    if ho_num is not None:
        slice_ = html[range_start:range_end]
        for n in range(ho_num + 1, ho_num + 41):
            m = re.search(rf"(^|\n){n}\.", slice_)
            if m:
                return range_start + m.start() + (
                    len(m.group(1)) if m.group(1) else 0
                )
        if ho_num > 1:
            last = None
            for m in re.finditer(rf"(^|\n){ho_num - 1}\.[^\n]*", slice_):
                last = m
            if last is not None:
                return range_start + last.end()
        if hang_m and range_end < len(html):
            return range_end
        return -1

    if hang_m:
        hang_n = int(hang_m.group(1))
        if 1 <= hang_n <= len(CIRCLE_HANGS):
            # 다음·이후 항 중 본문에 있는 첫 자리 앞 (⑥→⑨ 이동 후 신설 ⑥ 삽입)
            for n in range(hang_n, len(CIRCLE_HANGS)):
                next_circle = CIRCLE_HANGS[n]
                at = html.find(next_circle)
                if at != -1:
                    return at
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
    """음영 적용 후 본문에 보이는 개정 후 텍스트(합성 포함).

    미시행 호 삭제(pendingDelete)는 법제처처럼 현행 문구를 유지한다.
    미시행 신설 호는 항·호 번호 오름차순으로 삽입한다.
    """
    composed = compose_pending_phrases(body, phrases)
    html = body or ""
    # 긴 문구부터 치환 (main.js 와 동일)
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
        pending_del = bool(phrase.get("pendingDelete")) or (
            bool(phrase.get("pending"))
            and bool(re.match(r"\d+(?:의\d+)?\.\s*삭제\b", after))
        )
        if phrase.get("pending") and pending_del and before and before in html:
            # 현행 유지 (삭제 문구로 치환하지 않음)
            continue
        if after in html:
            continue
        if phrase.get("pending") and before and before in html:
            html = html.replace(before, after, 1)
        # isNew 삽입은 아래 오름차순 루프에서 처리
    # 신설: 항·호 번호 오름차순 (길이순이면 2→1→3 섞임)
    news = sorted(
        [
            p
            for p in ordered
            if p.get("pending") and p.get("isNew") and (p.get("text") or "").strip()
        ],
        key=_phrase_structure_sort_key,
    )
    for phrase in news:
        after = phrase.get("text") or ""
        if after and after not in html:
            html = _insert_new_pending_phrase(html, phrase)
    return html


def check_no_dual_date_chips(
    amendments: list[dict], articles: dict, problems: list[str], verbose: bool
) -> None:
    """음영 1개에 공포·시행 칩이 2쌍 붙는 회귀를 전수 차단.

    - main.js 가 다중 칩 루프를 다시 넣지 않았는지
    - 같은 조 합성 결과에 composedFrom 다중 일자가 없는지
    """
    main_js = MAIN_JS.read_text(encoding="utf-8") if MAIN_JS.is_file() else ""
    if "phraseDatePairs" in main_js:
        problems.append("dual_date_chips_regression: phraseDatePairs still in main.js")
    # buildAmendMark 본문에 '공포 ' 템플릿이 2회 이상이면 다중 칩 루프 의심
    mark_fn = re.search(
        r"function buildAmendMark\([\s\S]*?\n  function ",
        main_js,
    )
    if mark_fn:
        body = mark_fn.group(0)
        # 주석 제외 후 칩 템플릿 횟수
        code = re.sub(r"/\*[\s\S]*?\*/|//[^\n]*", "", body)
        chip_hits = len(re.findall(r"공포\s*['\"]?\s*\+|공포\s*", code))
        # '공포 ' + formatDotDate 형태가 2회 이상이면 다중 칩
        if code.count("공포 ") >= 2:
            problems.append(
                "dual_date_chips_regression: buildAmendMark emits multiple 공포 chips"
            )

    # 캐시 전 조: 합성 후 phrase 당 일자 1쌍
    by_art: dict[tuple[str, str], list[dict]] = {}
    for item in amendments:
        if item.get("bodyApplied") is True:
            continue
        law_id = item.get("lawId") or ""
        art_no = item.get("articleNo") or ""
        if not law_id or not art_no:
            continue
        key = (law_id, art_no)
        by_art.setdefault(key, [])
        for h in item.get("highlights") or []:
            for p in h.get("phrases") or []:
                if p.get("skipHighlight") or not (p.get("text") or "").strip():
                    continue
                ph = dict(p)
                ph["pending"] = True
                ph["amendmentSummary"] = (
                    item.get("summary") or item.get("briefSummary") or ""
                )
                by_art[key].append(ph)

    scanned = 0
    for (law_id, art_no), phrases in by_art.items():
        if len(phrases) < 2:
            continue
        body = find_article_body(articles, law_id, "statute", art_no) or find_article_body(
            articles, law_id, "decree", art_no
        )
        composed = compose_pending_phrases(body or "", phrases)
        scanned += 1
        for p in composed:
            cf = p.get("composedFrom")
            if isinstance(cf, list) and len(cf) > 1:
                problems.append(
                    f"dual_date_chips {law_id} {art_no}: "
                    f"locator={p.get('locator')} pairs={len(cf)}"
                )
        # 동일 개정(같은 공포·시행)·같은 locator 가 합성 후에도 2개+ → 조각 음영·칩 중복
        mark_counts: Counter[str] = Counter()
        for p in composed:
            if p.get("isNew") or p.get("skipHighlight"):
                continue
            loc = (p.get("locator") or "").strip()
            if not loc:
                continue
            dk = (
                f"{loc}|{p.get('amendedDate') or ''}|"
                f"{p.get('effectiveDate') or ''}"
            )
            mark_counts[dk] += 1
        for dk, n in mark_counts.items():
            if n > 1:
                problems.append(
                    f"same_amendment_multi_mark {law_id} {art_no}: {dk} x{n}"
                )
    if "spanHighlight: true" in main_js or "spanHighlight:true" in main_js.replace(
        " ", ""
    ):
        problems.append(
            "span_highlight_regression: composePendingGroup still emits spanHighlight"
        )
    if "항·호 단위" not in main_js and "항·호 전문" not in main_js:
        problems.append(
            "unit_highlight_guard_missing: composePendingGroup lacks unit-level comment"
        )
    if verbose:
        print(f"[INFO] dual_date_chip scan groups={scanned}")


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
                    # normalizePhrase 상당: pending 유지 + 요약(독립 치환용)
                    ph = dict(p)
                    if item.get("bodyApplied") is False:
                        ph["pending"] = True
                    text = (ph.get("text") or "").strip()
                    if not ph.get("pendingDelete") and ph.get("pending"):
                        if re.match(r"\d+(?:의\d+)?\.\s*삭제\b", text):
                            ph["pendingDelete"] = True
                    ph["amendmentSummary"] = item.get("summary") or item.get(
                        "briefSummary"
                    ) or ""
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
        # 독립 치환 음영: 각 변경에 올바른 공포·시행 1쌍
        want_spans = probe.get("requireSpanDates") or []
        composed = compose_pending_phrases(body, phrases)
        if want_spans:
            for spec in want_spans:
                token = spec.get("requireAfter") or ""
                want_amd = spec.get("amendedDate") or ""
                want_eff = spec.get("effectiveDate") or ""
                matched = [
                    p
                    for p in composed
                    if token and token in (p.get("text") or "")
                ]
                if not matched:
                    problems.append(f"compose_span_missing {art_no}: {token}")
                    ok = False
                    continue
                hit = next(
                    (
                        p
                        for p in matched
                        if (p.get("amendedDate") or "") == want_amd
                        and (p.get("effectiveDate") or "") == want_eff
                    ),
                    None,
                )
                if not hit:
                    got = [
                        f"{p.get('amendedDate')}/{p.get('effectiveDate')}"
                        for p in matched
                    ]
                    problems.append(
                        f"compose_span_date {art_no}: {token} "
                        f"want {want_amd}/{want_eff} got {got}"
                    )
                    ok = False
        # 음영 1개에 공포·시행 칩이 2쌍 붙지 않도록 (composedFrom 다중 칩 금지)
        if probe.get("forbidDualDateChips"):
            for p in composed:
                cf = p.get("composedFrom")
                if isinstance(cf, list) and len(cf) > 1:
                    problems.append(
                        f"compose_dual_date_chips {art_no}: "
                        f"locator={p.get('locator')} composedFrom={len(cf)}"
                    )
                    ok = False
        # 조각(단어) 음영 금지 — 항·호 단위만
        if probe.get("forbidSpanHighlight"):
            for p in composed:
                if p.get("spanHighlight"):
                    problems.append(
                        f"compose_span_highlight {art_no}: "
                        f"locator={p.get('locator')} (항·호 전문 음영이어야 함)"
                    )
                    ok = False
        # 동일 개정(같은 공포일)이면 locator당 phrase 1개 — 조각 음영·칩 중복 금지
        for spec in probe.get("requireSingleMarkPerLocator") or []:
            loc = spec.get("locator") or ""
            want_amd = spec.get("amendedDate") or ""
            matched = [
                p
                for p in composed
                if loc
                and (p.get("locator") or "") == loc
                and (not want_amd or (p.get("amendedDate") or "") == want_amd)
                and not p.get("isNew")
            ]
            if len(matched) != 1:
                problems.append(
                    f"compose_single_mark {art_no}: locator={loc} "
                    f"amd={want_amd} count={len(matched)} "
                    f"(동일 개정은 항·호 1음영·칩 1쌍이어야 함)"
                )
                ok = False
        # 항 단위 음영: 조각(배우자 출산전후휴가만)이 아니라 ① 전문이어야 함
        for spec in probe.get("requireHangUnit") or []:
            loc = spec.get("locator") or ""
            must_start = spec.get("mustStartWith") or ""
            must_inc = spec.get("mustInclude") or ""
            min_len = int(spec.get("minLen") or 0)
            matched = [
                p
                for p in composed
                if loc and (p.get("locator") or "") == loc and not p.get("isNew")
            ]
            if not matched:
                problems.append(f"compose_hang_unit_missing {art_no}: {loc}")
                ok = False
                continue
            hit = max(matched, key=lambda p: len(p.get("text") or ""))
            text = (hit.get("text") or "").strip()
            if must_start and not text.startswith(must_start):
                problems.append(
                    f"compose_hang_unit_start {art_no}: {loc} "
                    f"want startswith {must_start!r} got {text[:40]!r}"
                )
                ok = False
            if must_inc and must_inc not in text:
                problems.append(
                    f"compose_hang_unit_include {art_no}: {loc} missing {must_inc!r}"
                )
                ok = False
            if min_len and len(text) < min_len:
                problems.append(
                    f"compose_hang_unit_short {art_no}: {loc} "
                    f"len={len(text)} < {min_len} (조각 음영 의심)"
                )
                ok = False
            if hit.get("spanHighlight") and len(text) < min_len:
                problems.append(
                    f"compose_hang_unit_span {art_no}: {loc} "
                    f"spanHighlight on short fragment"
                )
                ok = False
        # 미시행 호 삭제: phrase·본문 현행 유지 검증 (법제처와 동일)
        for spec in probe.get("requirePendingDelete") or []:
            loc = spec.get("locator") or ""
            before_has = spec.get("beforeHas") or ""
            after_has = spec.get("afterHas") or ""
            matched = [
                p
                for p in phrases
                if loc and loc == (p.get("locator") or "")
            ]
            if not matched:
                problems.append(f"compose_pending_delete_missing {art_no}: {loc}")
                ok = False
                continue
            hit = matched[0]
            text = hit.get("text") or ""
            before = hit.get("beforeText") or ""
            if not hit.get("pendingDelete"):
                problems.append(
                    f"compose_pending_delete_flag {art_no}: {loc}"
                )
                ok = False
            if before_has and before_has not in before:
                problems.append(
                    f"compose_pending_delete_before {art_no}: {loc}"
                )
                ok = False
            if after_has and after_has not in text:
                problems.append(
                    f"compose_pending_delete_after {art_no}: {loc}"
                )
                ok = False
            if before_has and before_has not in after:
                problems.append(
                    f"compose_pending_delete_body {art_no}: "
                    f"현행 '{before_has}' 가 합성 본문에 없음"
                )
                ok = False
            # 시행 전 본문에 'N. 삭제'로 치환되면 안 됨
            if after_has and after_has in after and before_has not in after:
                problems.append(
                    f"compose_pending_delete_replaced {art_no}: {loc}"
                )
                ok = False
        if verbose:
            status = "OK" if ok else "FAIL"
            print(f"[{status}] compose {art_no} phrases={len(phrases)}")


def _leading_ho_nums(text: str) -> list[int]:
    """합성 본문에서 줄 시작 호 번호(1. 2. 3.)만 추출."""
    return [int(m.group(1)) for m in re.finditer(r"(?m)^(\d+)(?:의\d+)?\.", text or "")]


def _segments_by_hang(text: str) -> list[str]:
    """항(①②…) 마커 기준으로 조문을 세그먼트로 분리.

    한 조문 안에 항이 여러 개면(예: 제37조 제2항·제3항) 각 항마다 호
    번호가 1부터 다시 시작한다. 이를 나누지 않고 조문 전체를 한 번에
    훑으면 "…8, 9, 1, 2…"처럼 항이 바뀌며 번호가 리셋될 때마다 정상
    조문인데도 순서 위반으로 오탐한다(제37조 제2항→제3항 전환 오탐 방지).
    마커가 없으면 전체를 한 세그먼트로 취급한다.
    """
    marks = "".join(CIRCLE_TO_N.keys())
    parts = re.split(rf"(?m)^(?=[{re.escape(marks)}])", text or "")
    segs = [p for p in parts if p.strip()]
    return segs or [text or ""]


def _leading_hang_nums(text: str) -> list[int]:
    """합성 본문에서 줄 시작 항 원문자(①②…) 번호만 추출."""
    out: list[int] = []
    for m in re.finditer(r"(?m)^([①-⑮])", text or ""):
        n = CIRCLE_TO_N.get(m.group(1))
        if n is not None:
            out.append(n)
    return out


def check_composed_unit_order(
    amendments: list[dict], articles: dict, problems: list[str], verbose: bool
) -> None:
    """미시행 신설 호·항이 2개 이상인 조: 합성 결과가 번호 오름차순인지 전수 검증.

    제43조처럼 길이순 삽입으로 2→1→3 이 되는 회귀를 자동 차단한다.
    """
    # articleId → {lawId, articleNo, phrases}
    by_aid: dict[str, dict] = {}
    for item in amendments:
        if item.get("bodyApplied") is True:
            continue
        if item.get("lawId") not in MAJOR_LAWS:
            continue
        art_no = item.get("articleNo") or ""
        law_id = item.get("lawId") or ""
        for h in item.get("highlights") or []:
            aid = h.get("articleId") or ""
            if not aid:
                continue
            bucket = by_aid.setdefault(
                aid,
                {
                    "lawId": law_id,
                    "articleNo": art_no,
                    "phrases": [],
                },
            )
            if not bucket.get("articleNo") and art_no:
                bucket["articleNo"] = art_no
            for p in h.get("phrases") or []:
                if p.get("skipHighlight"):
                    continue
                if not (p.get("text") or "").strip():
                    continue
                ph = dict(p)
                ph["pending"] = True
                text = (ph.get("text") or "").strip()
                if not ph.get("pendingDelete") and re.match(
                    r"\d+(?:의\d+)?\.\s*삭제\b", text
                ):
                    ph["pendingDelete"] = True
                bucket["phrases"].append(ph)

    checked = 0
    for aid, info in by_aid.items():
        phrases = info["phrases"]
        news = [
            p
            for p in phrases
            if p.get("isNew")
            and p.get("pending")
            and (
                re.match(r"^\d+(?:의\d+)?\.", (p.get("text") or "").lstrip())
                or (
                    (p.get("text") or "").lstrip()
                    and (p.get("text") or "").lstrip()[0] in CIRCLE_TO_N
                )
            )
        ]
        if len(news) < 2:
            continue
        art_no = info.get("articleNo") or aid
        law_id = info.get("lawId") or ""
        body = (
            find_article_body(articles, law_id, "statute", art_no)
            or find_article_body(articles, law_id, "decree", art_no)
            or find_article_body(articles, law_id, "rule", art_no)
            or ""
        )
        # articleId 로 직접 본문 찾기 (번호 매칭 실패 대비)
        if not body:
            for tier in ("statute", "decree", "rule"):
                for a in (articles.get(law_id) or {}).get(tier) or []:
                    if a.get("id") == aid:
                        body = a.get("body") or ""
                        break
        after = simulate_article_highlight_after(body, phrases)
        checked += 1
        for seg in _segments_by_hang(after):
            ho_nums = _leading_ho_nums(seg)
            if len(ho_nums) >= 2 and ho_nums != sorted(ho_nums):
                problems.append(
                    f"ho_order_violation {law_id} {art_no}: got {ho_nums}"
                )
                if verbose:
                    print(f"[FAIL] ho_order {art_no}: {ho_nums}")
        hang_nums = _leading_hang_nums(after)
        if len(hang_nums) >= 2 and hang_nums != sorted(hang_nums):
            problems.append(
                f"hang_order_violation {law_id} {art_no}: got {hang_nums}"
            )
            if verbose:
                print(f"[FAIL] hang_order {art_no}: {hang_nums}")
    if verbose:
        print(f"[INFO] unit_order scan articles_with_multi_new={checked}")


def check_corrupt_and_duplicate_phrases(
    amendments: list[dict], problems: list[str], verbose: bool
) -> None:
    """오염 치환(경우에는는) · 동일 before 중복 phrase 전수 차단."""
    corrupt_n = 0
    dup_n = 0
    for item in amendments:
        if item.get("lawId") not in MAJOR_LAWS:
            continue
        seen: dict[tuple[str, str], int] = {}
        for h in item.get("highlights") or []:
            for p in h.get("phrases") or []:
                if p.get("skipHighlight"):
                    continue
                text = p.get("text") or ""
                before = p.get("beforeText") or ""
                if "는는" in text or "경우에는는" in text:
                    problems.append(f"corrupt_phrase {item.get('id')}: 는는")
                    corrupt_n += 1
                if (
                    before
                    and not before.startswith("해당")
                    and not p.get("isNew")
                ):
                    key = (
                        (p.get("locator") or "").strip(),
                        re.sub(r"\s*<[^>]+>\s*", " ", before).strip(),
                    )
                    seen[key] = seen.get(key, 0) + 1
        for key, n in seen.items():
            if n > 1:
                problems.append(
                    f"duplicate_before_phrase {item.get('id')}: "
                    f"{key[0]} x{n}"
                )
                dup_n += 1
    if verbose:
        print(
            f"[INFO] phrase quality corrupt={corrupt_n} duplicate_before={dup_n}"
        )


def check_reused_article_identity(
    amendments: list[dict], articles: dict, problems: list[str], verbose: bool
) -> None:
    """조번호 재사용 신설이 기존(다른 내용) 조문과 한 카드로 합쳐지지 않는지 검사.

    '해당 조 없음(신설)'을 내세우는 개정 항목의 articleId가, 이미 본문·제목이
    있는(=다른 조문이 그 번호를 쓰고 있는) 기존 조문과 같은 id를 쓰면, 화면에서
    옛 조문 본문 뒤에 새 조문 본문이 이어 붙어 보이는 회귀다(예: 남녀고용평등법
    시행령 제9조의2 "난임치료휴가" 본문에 "배우자 출산전후휴가" 신설문이 합쳐짐).
    """
    n = 0
    for item in amendments:
        if not item.get("articleLevel"):
            continue
        cb = (item.get("compareBefore") or "").strip()
        if not cb.startswith("해당 조 없음"):
            continue
        aid = (item.get("articleIds") or [None])[0]
        if not aid:
            continue
        law_id = item.get("lawId") or ""
        tier = TIER_KEY.get(item.get("tier") or "", "")
        new_title = (item.get("articleTitle") or "").strip()
        for a in (articles.get(law_id) or {}).get(tier) or []:
            if a.get("id") != aid:
                continue
            body = (a.get("body") or "").strip()
            title = (a.get("title") or "").strip()
            if body and title and new_title and title != new_title:
                n += 1
                problems.append(
                    f"merged_reused_article {item.get('id')}: articleId={aid} "
                    f"existing_title={title!r} new_title={new_title!r}"
                )
                if verbose:
                    print(
                        f"[FAIL] merged_reused_article {item.get('id')}: "
                        f"{title!r} vs {new_title!r}"
                    )
    if verbose:
        print(f"[INFO] reused_article_identity scan flagged={n}")


# 조문 청크 분리 실패로 다른 조문(우변)의 치환 문구가 좌변 조문에 잘못
# 들러붙었던 실제 회귀 사례. (articleNo) 조문의 하이라이트 문구에 아래
# 문자열이 나타나면, 그 문구는 원래 이 조문 것이 아니라는 뜻이다.
# 새 회귀를 찾을 때마다 여기에 (lawId, articleNo): [금지 문자열…] 을
# 추가한다.
FORBIDDEN_CROSS_ARTICLE_TEXT: dict[tuple[str, str], list[str]] = {
    # 남녀고용평등법 제18조의3(난임치료휴가)제2항 ← 제39조(과태료) "친족" 치환
    # 오귀속 (2026-05-26 개정, 법률 제21700호).
    ("equal-employment", "제18조의3"): ["법인의 대표자", "친족"],
}


def check_no_cross_article_swap_bleed(
    amendments: list[dict], problems: list[str], verbose: bool
) -> None:
    """다른 조문의 치환 문구가 잘못 들러붙는 회귀를 조문별로 재검증한다.

    개정문의 지시문이 마침표 없이 이어질 때(예: "…불리한 처우를 한 경우
    제39조제2항 중 …") 조문 청크 분리가 실패하면, 그 안의 인용 치환이
    엉뚱한 조문에도 중복 표시된다. `FORBIDDEN_CROSS_ARTICLE_TEXT`에
    등록된 조문·금지 문구 조합을 전수 검사해 재발을 막는다.
    """
    n = 0
    for item in amendments:
        key = (item.get("lawId") or "", item.get("articleNo") or "")
        forbidden = FORBIDDEN_CROSS_ARTICLE_TEXT.get(key)
        if not forbidden:
            continue
        for h in item.get("highlights") or []:
            for p in h.get("phrases") or []:
                haystacks = [
                    p.get("text") or "",
                    p.get("compareAfter") or "",
                    item.get("summary") or "",
                ]
                for token in forbidden:
                    if any(token in hay for hay in haystacks):
                        n += 1
                        problems.append(
                            f"cross_article_swap_bleed {item.get('id')}: "
                            f"contains forbidden token {token!r} (belongs to another article)"
                        )
                        if verbose:
                            print(
                                f"[FAIL] cross_article_swap_bleed {item.get('id')}: "
                                f"{token!r}"
                            )
    if verbose:
        print(f"[INFO] cross_article_swap_bleed scan flagged={n}")


def check_no_noop_replace_phrase(
    amendments: list[dict], problems: list[str], verbose: bool
) -> None:
    """이미 시행된 개정인데 before/after 비교문이 완전히 동일한 회귀를 검사.

    시행일이 지난("현행"에 이미 반영된) 치환은 amendment_articles.py의
    apply_ops_to_article()에서 항상 "new(개정 후 문구)가 이미 현행 본문에
    있는지"를 기준으로 이미 반영 여부를 판단해야 한다. 이 판단이 실패하면
    (예: "제4항"→"제4항ㆍ제6항"처럼 new가 old를 포함하는 확장형 치환) 두 가지
    회귀가 난다:
      1) before==after인 의미 없는 노란 음영 카드가 남거나(제37조제4호,
         2026-02-19 개정 사례),
      2) old가 이미 반영된 본문 뒤쪽에 우연히 다시 나타나는 자리에 잘못
         치환되어 문구가 중복된다(제19조의4제1항 사례).
    이 검사는 (1)을 직접 잡고, compareAfter 안에 동일 구절이 90%+ 겹치는
    형태로 두 번 반복되면 (2)도 함께 잡는다.
    """
    n = 0
    for item in amendments:
        for h in item.get("highlights") or []:
            for p in h.get("phrases") or []:
                cb = (p.get("compareBefore") or "").strip()
                ca = (p.get("compareAfter") or "").strip()
                if not cb or not ca:
                    continue
                if cb == ca:
                    n += 1
                    problems.append(
                        f"noop_replace_phrase {item.get('id')} "
                        f"{h.get('articleId')} {p.get('locator')}: "
                        f"compareBefore == compareAfter (의미 없는 음영)"
                    )
                    if verbose:
                        print(
                            f"[FAIL] noop_replace_phrase {item.get('id')} "
                            f"{h.get('articleId')} {p.get('locator')}"
                        )
                    continue
                # 같은 구절(20자 이상)이 개정 후 문구 안에서 반복되면 치환
                # 위치를 잘못 잡아 중복된 것일 가능성이 높다.
                for seg_len in (40, 30, 20):
                    if len(ca) < seg_len * 2:
                        continue
                    seg = ca[:seg_len]
                    if seg and ca.count(seg) > 1 and seg not in cb:
                        n += 1
                        problems.append(
                            f"duplicated_replace_phrase {item.get('id')} "
                            f"{h.get('articleId')} {p.get('locator')}: "
                            f"repeated segment {seg!r} in compareAfter"
                        )
                        if verbose:
                            print(
                                f"[FAIL] duplicated_replace_phrase "
                                f"{item.get('id')} {h.get('articleId')} "
                                f"{p.get('locator')}"
                            )
                        break
    if verbose:
        print(f"[INFO] noop/duplicated replace scan flagged={n}")


def check_doc_expected_articles(
    amendments: list[dict], problems: list[str], verbose: bool
) -> None:
    """개정문에 명시된 조가 캐시에 빠지지 않았는지(제19조 누락 회귀) 검사."""
    try:
        from amendment_articles import (
            expected_amended_articles_from_doc,
            fetch_doc_map,
        )
    except Exception as exc:  # noqa: BLE001
        if verbose:
            print(f"[WARN] doc coverage skipped: {exc}")
        return

    # noticeNo → law lsId
    ls_by_law = {
        "labor-standards": "001872",
        "retirement": "009883",
        "equal-employment": "000130",
        "fixed-term": "001901",
    }
    # probe notices that must include specific articles
    must = {
        ("000130", "21373"): ["제19조"],
        ("000130", "21476"): ["제19조"],
    }
    doc_cache: dict[str, dict] = {}
    checked = 0
    for (ls_id, notice), arts in must.items():
        if ls_id not in doc_cache:
            try:
                doc_cache[ls_id] = fetch_doc_map(ls_id)
            except Exception as exc:  # noqa: BLE001
                problems.append(f"doc_map_fetch_fail {ls_id}: {exc}")
                continue
        doc = (doc_cache.get(ls_id) or {}).get(notice) or ""
        if not doc:
            problems.append(f"doc_missing {ls_id}/{notice}")
            continue
        expected = expected_amended_articles_from_doc(doc)
        for art in arts:
            if art not in expected:
                # expected 패턴이 약하면 doc 원문 직접 확인
                if not re.search(
                    rf"제\s*{re.escape(art[1:-1])}\s*조", doc.replace("의", "의")
                ) and art not in doc:
                    # 제19조 bare
                    bare = art.replace("제", "").replace("조", "")
                    if f"제{bare}조" not in doc and art not in doc:
                        problems.append(
                            f"doc_expected_pattern_weak {ls_id}/{notice}: {art}"
                        )
            present = any(
                a.get("noticeNo") == notice
                and a.get("articleNo") == art
                and (a.get("highlights") or [])
                for a in amendments
            )
            if not present:
                problems.append(
                    f"doc_article_missing_in_cache {ls_id}/{notice}: {art}"
                )
            checked += 1
    if verbose:
        print(f"[INFO] doc_expected_article checks={checked}")


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

    # 같은 lsId XML 중복 요청 방지 + CI에서는 방금 받은 full-*.txt 를 live 로 재사용
    use_local_full = os.environ.get("LAW_PARITY_USE_LOCAL_FULL", "").strip() in (
        "1",
        "true",
        "TRUE",
    )
    xml_cache: dict[str, str] = {}
    full_cache: dict[str, str] = {}

    def live_article_text(probe: dict) -> str:
        art_no = probe["article"]
        file_name = probe.get("file") or ""
        if use_local_full and file_name:
            path = FETCH / file_name
            if path.is_file():
                if file_name not in full_cache:
                    full_cache[file_name] = path.read_text(encoding="utf-8")
                chunk = article_chunk(full_cache[file_name], art_no)
                if chunk.strip():
                    return chunk
        ls_id = probe["lsId"]
        if ls_id not in xml_cache:
            xml_cache[ls_id] = fetch_xml(ls_id)
        xml = xml_cache[ls_id]
        live_full = xml_to_full_text(xml)
        return article_chunk(live_full, art_no) or extract_live_article(xml, art_no)

    for probe in LIVE_PROBES:
        ls_id = probe["lsId"]
        art_no = probe["article"]
        try:
            live_art = live_article_text(probe)
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
                    if amd.get("requirePendingDelete"):
                        ok_pd = False
                        for p in del_phrases:
                            t = (p.get("text") or "").strip()
                            flagged = bool(p.get("pendingDelete")) or bool(
                                re.match(r"\d+(?:의\d+)?\.\s*삭제\b", t)
                            )
                            if flagged:
                                ok_pd = True
                                break
                        if not ok_pd:
                            problems.append(
                                f"pending_delete_flag_missing {item.get('id')}"
                            )
                            row["ok"] = False
                            row["details"].append("pending_delete_flag_missing")
                    before_need = amd.get("requirePhraseBeforeHas") or ""
                    if before_need:
                        befores = " ".join(
                            (p.get("beforeText") or "") for p in del_phrases
                        )
                        if before_need not in befores:
                            problems.append(
                                f"delete_before_text_missing {item.get('id')}: "
                                f"{before_need[:40]}"
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
    # 신설 호·항 번호 순서 전수 검증 (2→1→3 회귀 차단)
    check_composed_unit_order(amendments, articles, problems, verbose)
    # 오염 치환·동일 before 중복 phrase
    check_corrupt_and_duplicate_phrases(amendments, problems, verbose)
    # 개정문 명시 조 ↔ 캐시 누락 (제19조 등)
    check_doc_expected_articles(amendments, problems, verbose)
    # 조번호 재사용 신설이 기존(다른 내용) 조문과 한 카드로 합쳐지지 않는지
    check_reused_article_identity(amendments, articles, problems, verbose)
    # 청크 분리 실패로 다른 조문 치환이 잘못 들러붙는 회귀(제18조의3 등)
    check_no_cross_article_swap_bleed(amendments, problems, verbose)
    check_no_noop_replace_phrase(amendments, problems, verbose)
    # 공포·시행 칩 2쌍 회귀 전수 차단
    check_no_dual_date_chips(amendments, articles, problems, verbose)

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
    # 법률만이 아니라 시행령·시행규칙도 같은 방식으로 검증한다(누락 시
    # CI가 놓치는 회귀 방지 — 예: 남녀고용평등법 시행령/시행규칙 신설조 누락).
    try:
        from datetime import date as _date

        from amendment_articles import extract_article_changes, fetch_doc_map

        law_names = {
            "labor-standards": "근로기준법",
            "retirement": "근로자퇴직급여 보장법",
            "equal-employment": "남녀고용평등과 일ㆍ가정 양립 지원에 관한 법률",
            "fixed-term": "기간제 및 단시간근로자 보호 등에 관한 법률",
        }
        for law_id, tier_key, ls_id, _filename, _must in FULL_TARGETS:
            law_name = law_names.get(law_id, "")
            tier_kr = {v: k for k, v in TIER_KEY.items()}.get(tier_key, "법률")
            notice_dates: dict[str, tuple[str, str]] = {}
            for a in amendments:
                if a.get("lawId") != law_id or a.get("tier") != tier_kr:
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
                cache_items = [
                    a
                    for a in amendments
                    if a.get("lawId") == law_id
                    and str(a.get("noticeNo") or "") == notice
                    and a.get("articleLevel")
                    and a.get("articleNo")
                ]
                have = {a.get("articleNo") for a in cache_items}
                by_jo: dict[str, dict] = {a.get("articleNo"): a for a in cache_items}
                for ch in parsed:
                    jo = ch.get("articleNo")
                    if not jo:
                        continue
                    # 본문에 적용 불가한 치환만 있는 파싱 결과는 누락으로 보지 않음
                    body = find_article_body(articles, law_id, tier_key, jo)
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
                    if jo not in have:
                        if not applicable:
                            continue
                        problems.append(f"doc_article_missing {law_id} {notice} {jo}")
                        if verbose:
                            print(f"[FAIL] doc_article_missing {law_id} {notice} {jo}")
                        continue
                    # 조는 캐시에 있어도, 신설 조문 본문이 개정문 원문보다
                    # 훨씬 짧게 잘렸는지 대조(파서 종료지점 오탐 회귀 방지).
                    new_ops = [o for o in ops if o.get("kind") == "new_article"]
                    if not new_ops:
                        continue
                    fresh_len = max(len((o.get("text") or "")) for o in new_ops)
                    cached = by_jo.get(jo) or {}
                    cached_len = len((cached.get("compareAfter") or "").strip())
                    if fresh_len >= 60 and cached_len + 20 < fresh_len:
                        problems.append(
                            f"new_article_truncated {law_id} {notice} {jo}: "
                            f"cached={cached_len} fresh={fresh_len}"
                        )
                        if verbose:
                            print(
                                f"[FAIL] new_article_truncated {jo}: "
                                f"cached={cached_len} fresh={fresh_len}"
                            )
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
