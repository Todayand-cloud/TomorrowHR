# -*- coding: utf-8 -*-
"""4법×3단 개정 캐시·조문 감사 (법제처 기준 정합성)."""
from __future__ import annotations

import json
import re
import sys
from collections import defaultdict
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from amendment_articles import fetch_doc_map, extract_article_changes, html_to_text  # noqa: E402
from refresh_amendments import LAW_CATALOG, fetch_revisions  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
BASE = date(2026, 8, 11)
TIER_KEY = {"법률": "statute", "시행령": "decree", "시행규칙": "rule"}


def main() -> None:
    cache = json.loads((ROOT / "js" / "amendments-cache.json").read_text(encoding="utf-8"))
    arts = json.loads((ROOT / "js" / "law-articles-raw.json").read_text(encoding="utf-8"))
    issues: list[str] = []

    def find_art(law_id: str, tier: str, no: str):
        for a in (arts.get(law_id) or {}).get(tier) or []:
            if a.get("no") == no:
                return a
        return None

    print("=== 1) 하이라이트 전·후 규칙 ===")
    for item in cache.get("amendments") or []:
        for h in item.get("highlights") or []:
            for p in h.get("phrases") or []:
                text = (p.get("text") or "").strip()
                before = (p.get("beforeText") or "").strip()
                if not text:
                    issues.append(f"empty_text {item['id']}")
                # 표기=개정후, 박스=개정전: pending인데 본문에 text만 있고 before가 본문에 있으면
                # before가 개정후처럼 보이면 이상
                note = p.get("beforeNote") or ""
                if "개정 후" in note:
                    issues.append(f"inverted_note {item['id']} {note}")

    print("=== 2) bodyApplied vs 시행일 ===")
    for item in cache.get("amendments") or []:
        if not item.get("articleLevel"):
            continue
        eff = item.get("effectiveDate")
        if not eff:
            continue
        eff_d = date.fromisoformat(eff)
        expect = eff_d <= BASE
        ba = item.get("bodyApplied")
        if ba is None:
            issues.append(f"bodyApplied_None {item['id']} eff={eff}")
        elif ba != expect:
            issues.append(f"bodyApplied_mismatch {item['id']} ba={ba} expect={expect}")

    print("=== 3) applied 하이라이트가 본문에 존재하는지 ===")
    for item in cache.get("amendments") or []:
        if item.get("bodyApplied") is not True:
            continue
        tier = TIER_KEY.get(item.get("tier") or "", "")
        art = find_art(item.get("lawId") or "", tier, item.get("articleNo") or "")
        body = (art or {}).get("body") or ""
        for h in item.get("highlights") or []:
            for p in h.get("phrases") or []:
                text = (p.get("text") or "").strip()
                if text and text not in body and text[:48] not in body:
                    issues.append(
                        f"applied_missing {item['id']} loc={p.get('locator')} :: {text[:60]}"
                    )

    print("=== 4) pending 하이라이트: before가 본문에 있어야 함 ===")
    for item in cache.get("amendments") or []:
        if item.get("bodyApplied") is not False:
            continue
        tier = TIER_KEY.get(item.get("tier") or "", "")
        art = find_art(item.get("lawId") or "", tier, item.get("articleNo") or "")
        body = (art or {}).get("body") or ""
        for h in item.get("highlights") or []:
            for p in h.get("phrases") or []:
                if p.get("skipHighlight"):
                    continue
                before = (p.get("beforeText") or "").strip()
                text = (p.get("text") or "").strip()
                if text in body:
                    continue  # 이미 반영된 경우
                if before and before not in body and before[:40] not in body:
                    issues.append(
                        f"pending_before_missing {item['id']} loc={p.get('locator')} :: {before[:60]}"
                    )

    print("=== 5) 타법 오귀속(타법 조가 다른 법에 stub) ===")
    # 근로기준법 조가 equal에 있으면 이상
    for lid, foreign_prefix in [
        ("equal-employment", "제60조"),
    ]:
        nos = {a.get("no") for a in (arts.get(lid) or {}).get("statute") or []}
        # 남녀고용평등법에 제60조가 실제로 있는지 법제처상 없음
        if "제60조" in nos:
            issues.append(f"foreign_stub {lid} has 제60조")

    print("=== 6) 법제처 개정 이력 윈도우 vs 캐시 ===")
    amd_from, amd_to = BASE - timedelta(days=182), BASE + timedelta(days=182)
    eff_from, eff_to = BASE - timedelta(days=182), BASE + timedelta(days=182)
    cache_keys = {
        (i.get("lsId") or (i.get("id") or "").split("-")[1], i.get("noticeNo") or "")
        for i in cache.get("amendments") or []
    }
    # id format live-{lsId}-{date}-{notice}
    cache_notices = defaultdict(set)
    for i in cache.get("amendments") or []:
        parts = (i.get("id") or "").split("-")
        if len(parts) >= 4:
            cache_notices[parts[1]].add(parts[3] if parts[2][0].isdigit() else parts[-2])
    # better parse
    cache_by_ls: dict[str, set[str]] = defaultdict(set)
    for i in cache.get("amendments") or []:
        m = re.match(r"live-(\d+)-(\d{4}-\d{2}-\d{2})-(\d+)", i.get("id") or "")
        if m:
            cache_by_ls[m.group(1)].add(m.group(3))

    for meta in LAW_CATALOG:
        revs = fetch_revisions(meta["lsId"])
        win = [
            r
            for r in revs
            if (amd_from <= r["amendedDate"] <= amd_to)
            or (eff_from <= r["effectiveDate"] <= eff_to)
        ]
        notices = {r["noticeNo"] for r in win}
        cached = cache_by_ls.get(meta["lsId"], set())
        missing = notices - cached
        extra = cached - notices
        print(
            f"  {meta['lsId']} {meta['lawName']}: window={len(win)} cached_notices={len(cached)} "
            f"missing={sorted(missing)} extra={sorted(extra)}"
        )
        if missing:
            issues.append(f"missing_notices {meta['lsId']} {sorted(missing)}")

    print("=== 7) 샘플 추출: labor 21373 / retire applied / equal pending ===")
    docs_labor = fetch_doc_map("001872")
    chs = extract_article_changes(
        docs_labor.get("21373", ""),
        date(2026, 2, 19),
        date(2026, 8, 20),
        law_id="labor-standards",
        law_name="근로기준법",
    )
    print("  labor 21373 changes:", [(c["articleNo"], c["ops"][0].get("unitLocator")) for c in chs])

    docs_eq = fetch_doc_map("000130")
    chs_eq = extract_article_changes(
        docs_eq.get("21373", ""),
        date(2026, 2, 19),
        date(2026, 8, 20),
        law_id="equal-employment",
        law_name="남녀고용평등법",
    )
    bad60 = [c for c in chs_eq if c["articleNo"] == "제60조"]
    print("  equal 21373 has 제60조?", bool(bad60), "total", len(chs_eq))
    if bad60:
        issues.append("equal_still_extracts_labor_art60")

    # 근로기준법 제60조 본문 현행 구조
    a60 = find_art("labor-standards", "statute", "제60조")
    body = (a60 or {}).get("body") or ""
    marks = [ln[0] for ln in body.split("\n") if ln and ln[0] in "①②③④⑤⑥⑦⑧⑨"]
    print("  art60 hang order:", marks)
    if marks != ["①", "②", "③", "④", "⑤", "⑥", "⑦"]:
        # ③ may be 삭제
        if "⑤" in marks and marks.index("⑤") < marks.index("⑥") if "⑥" in marks else True:
            pass
        if "⑨" in marks:
            issues.append(f"art60_has_future_hang {marks}")
    if "제19조제1항" not in body:
        # 시행 전이면 제1항이 있어야 함
        if "제19조에 따른" in body and "제19조제1항" not in body:
            issues.append("art60_item3_already_future_text")

    print("\n=== ISSUES ({}) ===".format(len(issues)))
    for x in issues:
        print(" -", x)

    # 요약 표
    print("\n=== HIGHLIGHT SUMMARY ===")
    by = defaultdict(lambda: {"n": 0, "hl": 0, "applied": 0, "pending": 0})
    for item in cache.get("amendments") or []:
        key = f"{item.get('lawId')}/{item.get('tier')}"
        by[key]["n"] += 1
        if item.get("highlights"):
            by[key]["hl"] += 1
        if item.get("bodyApplied") is True:
            by[key]["applied"] += 1
        if item.get("bodyApplied") is False:
            by[key]["pending"] += 1
    for k in sorted(by):
        print(k, by[k])


if __name__ == "__main__":
    main()
