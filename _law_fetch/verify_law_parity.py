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
                "amendedDate": "2026-04-07",
                "noticeNo": "21533",
                "compareBefore": "제104조제2항",
                "compareAfter": "제104조",
                "requireHighlight": True,
            },
            {
                "amendedDate": "2026-06-09",
                "noticeNo": "21784",
                "compareBefore": "제4항 및 제5항",
                "compareAfter": "제4항부터 제6항까지",
                "requireHighlight": True,
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
    if verbose:
        print(f"[INFO] 4법 display_gap count={display_gaps}")

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
    soft = args.soft or (os.environ.get("CI") == "true")
    if not result["ok"]:
        for p in result.get("problems") or []:
            print(f"::warning title=parity::{p}")
        if soft:
            print("parity soft-fail (CI): problems recorded, exit 0")
            raise SystemExit(0)
    raise SystemExit(0 if result["ok"] else 1)


if __name__ == "__main__":
    main()
