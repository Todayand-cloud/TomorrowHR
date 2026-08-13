# -*- coding: utf-8 -*-
"""갱신 후 자율 감사·정정 (사용자 지적 없이 유령/공허 개정 제거·복구).

역할
1) heal: 요약의 「전」→「후」 등으로 빈 compare 복구
2) scrub: 본문에 없는 치환·전후 동일 등 '유령 카드'를 캐시에서 즉시 제거
3) offline_audit: 네트워크 없이 구조 오류 목록
4) heal_cycle 결과는 refresh_amendments 가 parity 재시도와 함께 사용
"""

from __future__ import annotations

import re
from typing import Any

_ARROW_SUMMARY_RE = re.compile(
    r"「\s*([^」]+?)\s*」\s*→\s*「\s*([^」]+?)\s*」"
)


def _norm(s: str) -> str:
    s = re.sub(r"\s*<[^>]+>\s*", " ", s or "")
    return re.sub(r"\s+", " ", s).strip()


def _phrases(item: dict) -> list[dict]:
    return [
        p
        for h in (item.get("highlights") or [])
        for p in (h.get("phrases") or [])
        if not p.get("skipHighlight") and (p.get("text") or "").strip()
    ]


def _article_body(articles: dict, law_id: str, tier: str, no: str) -> str:
    pack = (articles or {}).get(law_id) or {}
    for a in pack.get(tier) or []:
        if a.get("no") == no:
            return a.get("body") or ""
    return ""


def _summary_pair(item: dict) -> tuple[str, str] | None:
    for key in ("summary", "briefSummary"):
        m = _ARROW_SUMMARY_RE.search(item.get(key) or "")
        if m:
            old, new = m.group(1).strip(), m.group(2).strip()
            if old and new and old != new:
                return old, new
    return None


def heal_empty_compares(payload: dict, articles: dict | None = None) -> tuple[dict, list[dict]]:
    """빈 compare를 요약/본문에서 복구. (시행 완료 치환이 phrase를 안 남긴 경우)"""
    articles = articles or {}
    healed: list[dict] = []
    out_items: list[dict] = []
    for item in payload.get("amendments") or []:
        if not item.get("articleLevel"):
            out_items.append(item)
            continue
        cb = (item.get("compareBefore") or "").strip()
        ca = (item.get("compareAfter") or "").strip()
        phrases = _phrases(item)
        if cb or ca or phrases:
            out_items.append(item)
            continue
        pair = _summary_pair(item)
        if not pair:
            out_items.append(item)
            continue
        old, new = pair
        tier = TIER_KEY.get(item.get("tier") or "", "statute")
        body = _article_body(
            articles, item.get("lawId") or "", tier, item.get("articleNo") or ""
        )
        # 본문에 개정 후가 있으면 주변 단위로 확장, 없으면 요약 문구만
        compare_before, compare_after = old, new
        if body and new in body:
            # 짧은 토큰이면 호/항 단위로 넓혀 카드 가독성 확보
            idx = body.find(new)
            if idx >= 0:
                start = max(0, body.rfind("\n", 0, idx) + 1)
                end_m = re.search(r"\n[①-⑮\d]", body[idx + len(new) :])
                end = idx + len(new) + (end_m.start() if end_m else len(body) - idx - len(new))
                after_unit = body[start:end].strip()
                if new in after_unit:
                    before_unit = after_unit.replace(new, old, 1)
                    if before_unit != after_unit:
                        compare_before = _norm(before_unit)
                        compare_after = _norm(after_unit)
        fixed = dict(item)
        fixed["compareBefore"] = compare_before
        fixed["compareAfter"] = compare_after
        out_items.append(fixed)
        healed.append({"id": item.get("id"), "from": "summary_arrow"})
    out = dict(payload)
    out["amendments"] = out_items
    if healed:
        out["_healedCompares"] = healed
        print(f"::notice::self_heal healed {len(healed)} empty compare(s)")
        for h in healed[:20]:
            print(f"  - {h['id']}: {h['from']}")
    return out, healed


def heal_empty_highlights(
    payload: dict, articles: dict | None = None
) -> tuple[dict, list[dict]]:
    """compare는 있는데 highlights 가 비어 노란 음영이 안 나오는 항목을 복구."""
    articles = articles or {}
    healed: list[dict] = []
    out_items: list[dict] = []
    for item in payload.get("amendments") or []:
        if not item.get("articleLevel"):
            out_items.append(item)
            continue
        phrases = _phrases(item)
        cb = (item.get("compareBefore") or "").strip()
        ca = (item.get("compareAfter") or "").strip()
        if phrases or not ca:
            out_items.append(item)
            continue

        tier = TIER_KEY.get(item.get("tier") or "", "statute")
        body = _article_body(
            articles, item.get("lawId") or "", tier, item.get("articleNo") or ""
        )
        pending = item.get("bodyApplied") is False
        text = ca
        before = cb
        locator = (item.get("articleNo") or "").strip()

        # 본문에 있는 더 긴 단위로 확장(시행 완료 음영 매칭)
        if body and ca:
            # compareAfter 전문이 본문에 있으면 그대로
            if ca in body:
                text = ca
            else:
                # 요약 화살표 new 토큰으로 단위 찾기
                pair = _summary_pair(item)
                needle = pair[1] if pair else ca[:24]
                if needle and needle in body:
                    idx = body.find(needle)
                    start = max(0, body.rfind("\n", 0, idx) + 1)
                    end_m = re.search(r"\n[①-⑮\d]", body[idx + len(needle) :])
                    end = (
                        idx
                        + len(needle)
                        + (end_m.start() if end_m else len(body) - idx - len(needle))
                    )
                    unit = body[start:end].strip()
                    if unit:
                        text = unit
                        if pair and pair[0] and pair[0] in unit.replace(pair[1], pair[0], 1):
                            before = unit.replace(pair[1], pair[0], 1)
                        elif cb:
                            before = cb
            # locator: 호/항
            t0 = text.lstrip()
            if t0 and t0[0] in "①②③④⑤⑥⑦⑧⑨⑩⑪⑫⑬⑭⑮":
                locator = f"제{'①②③④⑤⑥⑦⑧⑨⑩⑪⑫⑬⑭⑮'.index(t0[0]) + 1}항"
            else:
                hm = re.match(r"^(\d+(?:의\d+)?)\.", t0)
                if hm:
                    locator = hm.group(1) + "호"

        # pending 인데 before가 본문에 없으면 복구해도 화면 치환 실패 → 감사로 남김
        if pending and before and body and before not in body and not before.startswith("해당"):
            out_items.append(item)
            continue

        aid = ""
        if item.get("articleIds"):
            aid = item["articleIds"][0]
        phrase = {
            "text": text,
            "beforeText": before or ("해당 문구 없음(신설)" if not before else before),
            "pending": pending,
            "isNew": (not before) or before.startswith("해당"),
            "locator": locator,
            "amendedDate": item.get("amendedDate"),
            "effectiveDate": item.get("effectiveDate"),
            "historyKind": "개정",
            "historyDates": [item.get("amendedDate")] if item.get("amendedDate") else [],
            "beforeNote": "",
            "compareBefore": cb,
            "compareAfter": ca,
        }
        fixed = dict(item)
        fixed["highlights"] = [{"articleId": aid, "phrases": [phrase]}] if aid else [
            {"articleId": "", "phrases": [phrase]}
        ]
        out_items.append(fixed)
        healed.append({"id": item.get("id"), "from": "compare_to_highlight", "locator": locator})

    out = dict(payload)
    out["amendments"] = out_items
    if healed:
        out["_healedHighlights"] = healed
        print(f"::notice::self_heal healed {len(healed)} empty highlight(s)")
        for h in healed[:20]:
            print(f"  - {h['id']}: {h['from']} ({h.get('locator')})")
    return out, healed


def is_ghost_amendment(item: dict, body: str) -> str | None:
    """유령/공허 개정이면 사유 문자열, 아니면 None."""
    if not item.get("articleLevel"):
        return None
    phrases = _phrases(item)
    if phrases:
        return None
    cb = (item.get("compareBefore") or "").strip()
    ca = (item.get("compareAfter") or "").strip()
    pending = item.get("bodyApplied") is False

    # 요약에 전·후가 있으면 빈 compare는 '미복구'로 감사만 (즉시 삭제하지 않음)
    if not cb and not ca:
        if _summary_pair(item):
            return "empty_compare_recoverable"
        # 시행 완료·요약도 없는 완전 공허만 제거
        if not (item.get("summary") or "").strip():
            return "empty_compare"
        # 요약만 있고 화살표도 없으면 유지(구조 개정 등) — 삭제하지 않음
        return None

    if pending:
        # 개정 전 문구가 본문에 없음 → 오귀속(제52조←제108조 유형)
        if cb and not cb.startswith("해당") and body and cb not in body:
            return "before_not_in_body"
        # 전·후 동일(연혁만 다른 경우 포함)
        if cb and ca and _norm(cb) == _norm(ca) and not cb.startswith("해당"):
            return "empty_diff"
        # 요약은 있는데 표시 문구/하이라이트 전무
        if (item.get("summary") or "").strip() and not ca and not phrases:
            return "summary_without_display"
    else:
        # 시행 완료인데 전·후 모두 본문에 없으면 오귀속
        if (
            cb
            and ca
            and body
            and not cb.startswith("해당")
            and cb not in body
            and ca not in body
        ):
            return "applied_orphan"

    return None


# scrub 대상: 복구 가능한 empty_compare 는 제외
_SCRUB_REASONS = {
    "empty_compare",
    "before_not_in_body",
    "empty_diff",
    "summary_without_display",
    "applied_orphan",
}


TIER_KEY = {"법률": "statute", "시행령": "decree", "시행규칙": "rule"}


def scrub_ghost_amendments(
    payload: dict, articles: dict | None = None
) -> tuple[dict, list[dict]]:
    """유령 개정 항목을 제거하고 (새 payload, 제거 로그) 반환."""
    articles = articles or {}
    kept: list[dict] = []
    removed: list[dict] = []
    for item in payload.get("amendments") or []:
        tier = TIER_KEY.get(item.get("tier") or "", "statute")
        body = _article_body(
            articles, item.get("lawId") or "", tier, item.get("articleNo") or ""
        )
        reason = is_ghost_amendment(item, body)
        if reason in _SCRUB_REASONS:
            removed.append({"id": item.get("id"), "reason": reason})
            continue
        kept.append(item)
    out = dict(payload)
    out["amendments"] = kept
    out["count"] = len(kept)
    if removed:
        out["_scrubbedGhosts"] = removed
        print(f"::notice::self_heal scrubbed {len(removed)} ghost amendment(s)")
        for r in removed[:20]:
            print(f"  - {r['id']}: {r['reason']}")
    return out, removed


def offline_audit(payload: dict, articles: dict | None = None) -> list[str]:
    """네트워크 없이 캐시 구조 감사."""
    articles = articles or {}
    problems: list[str] = []
    for item in payload.get("amendments") or []:
        if not item.get("articleLevel"):
            continue
        tier = TIER_KEY.get(item.get("tier") or "", "statute")
        body = _article_body(
            articles, item.get("lawId") or "", tier, item.get("articleNo") or ""
        )
        reason = is_ghost_amendment(item, body)
        if reason:
            problems.append(f"ghost:{reason}:{item.get('id')}")
        phrases = _phrases(item)
        cb = (item.get("compareBefore") or "").strip()
        ca = (item.get("compareAfter") or "").strip()
        if item.get("bodyApplied") is False and phrases:
            # 노란 표시(text)와 호버(before)가 사실상 동일
            for p in phrases:
                t = _norm(p.get("text") or "")
                b = _norm(p.get("beforeText") or p.get("compareBefore") or "")
                if t and b and t == b and not b.startswith("해당"):
                    problems.append(f"highlight_noop:{item.get('id')}")
                    break
        summary = item.get("summary") or ""
        if re.search(r"단서\s*.*신설|신설.*단서", summary) and "명시적" not in ca and "다만," not in ca:
            problems.append(f"proviso_missing_in_after:{item.get('id')}")
        # 요약에 항 삭제가 있으면 하이라이트에 '삭제' phrase 필수 (제109조② 유형)
        if re.search(r"제\s*\d+\s*항\s*삭제", summary):
            all_ph = [
                p
                for h in (item.get("highlights") or [])
                for p in (h.get("phrases") or [])
                if not p.get("skipHighlight")
            ]
            if not any(re.search(r"삭제", p.get("text") or "") for p in all_ph):
                problems.append(f"hang_delete_undisplayed:{item.get('id')}")
            elif item.get("bodyApplied") is False and body:
                # 삭제 before가 플레이스홀더면 본문 치환 불가
                for p in all_ph:
                    if "삭제" not in (p.get("text") or ""):
                        continue
                    b = (p.get("beforeText") or "").strip()
                    if b and "삭제 전" in b:
                        problems.append(f"hang_delete_placeholder:{item.get('id')}")
                    elif b and b not in body:
                        problems.append(f"hang_delete_before_miss:{item.get('id')}")
        # pending 치환: before에 연혁이 없고 본문 항에는 연혁이 있으면 잔여 태그 위험
        if item.get("bodyApplied") is False and body:
            for p in phrases:
                b = (p.get("beforeText") or "").strip()
                t = (p.get("text") or "").strip()
                if not b or not t or "삭제" in t:
                    continue
                if "<개정" in b or "<신설" in b:
                    continue
                # 본문에서 before 직후 연혁이 남아 표시가 깨지는지
                idx = body.find(b)
                if idx >= 0:
                    rest = body[idx + len(b) : idx + len(b) + 80]
                    if re.match(r"\s*<(?:개정|신설)\s", rest):
                        problems.append(f"hist_tail_orphan_risk:{item.get('id')}")
                        break
        amd = item.get("amendedDate") or ""
        eff = item.get("effectiveDate") or ""
        if amd and eff and amd > eff:
            problems.append(f"date_order:{item.get('id')}")
        if not (item.get("articleNo") or "").strip():
            problems.append(f"no_articleNo:{item.get('id')}")
        # 노란 음영 미처리: compare/요약은 있는데 highlights 없음
        needs_yellow = bool(
            ca
            or cb
            or _summary_pair(item)
            or re.search(r"삭제|신설|→", item.get("summary") or "")
        )
        if needs_yellow and not phrases:
            problems.append(f"missing_yellow_highlight:{item.get('id')}")
        elif phrases and item.get("bodyApplied") is False and body:
            ok_match = False
            for p in phrases:
                t = (p.get("text") or "").strip()
                b = (p.get("beforeText") or "").strip()
                if (b and b in body) or (t and t in body) or p.get("isNew"):
                    ok_match = True
                    break
            if not ok_match:
                problems.append(f"yellow_unmatched:{item.get('id')}")
        elif phrases and item.get("bodyApplied") is not False and body:
            if not any((p.get("text") or "").strip() in body for p in phrases):
                ok_tok = any(
                    len((p.get("text") or "").strip()) >= 8
                    and (p.get("text") or "").strip()[:20] in body
                    for p in phrases
                )
                if not ok_tok:
                    problems.append(f"yellow_after_not_in_body:{item.get('id')}")
        # 빈 compare이면서 요약 화살표도 없으면 문제
        if not cb and not ca and not phrases and not _summary_pair(item):
            if not (item.get("summary") or "").strip():
                problems.append(f"blank_card:{item.get('id')}")
    return problems



def load_articles_db() -> dict:
    from pathlib import Path
    import json

    path = Path(__file__).resolve().parents[1] / "js" / "law-articles-raw.json"
    if path.is_file():
        return json.loads(path.read_text(encoding="utf-8"))
    return {}


def self_heal_payload(payload: dict, articles: dict | None = None) -> tuple[dict, dict]:
    """heal → scrub → audit 한 사이클. 보고서 dict 함께 반환."""
    articles = articles or load_articles_db()
    payload, healed = heal_empty_compares(payload, articles)
    payload, healed_hl = heal_empty_highlights(payload, articles)
    payload, scrubbed = scrub_ghost_amendments(payload, articles)
    problems = offline_audit(payload, articles)
    report = {
        "healed": list(healed) + list(healed_hl),
        "healedCompares": healed,
        "healedHighlights": healed_hl,
        "scrubbed": scrubbed,
        "problems": problems,
    }
    return payload, report
