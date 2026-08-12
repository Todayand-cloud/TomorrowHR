# -*- coding: utf-8 -*-
"""full-*.txt(법령 전문 크롤 캐시)에서 조 제목·본문을 추출해 시드/조문 DB를 채웁니다.
임의 창작 없이 파일에 있는 문구만 사용합니다.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FETCH = Path(__file__).resolve().parent
ARTICLES_PATH = ROOT / "js" / "law-articles-raw.json"
SEED_PATH = ROOT / "js" / "law-articles-seed.json"

FULL_MAP = {
    ("labor-standards", "statute"): FETCH / "full-labor-statute.txt",
    ("labor-standards", "decree"): FETCH / "full-labor-decree.txt",
    ("labor-standards", "rule"): FETCH / "full-labor-rule.txt",
    ("retirement", "statute"): FETCH / "full-retire-statute.txt",
    ("retirement", "decree"): FETCH / "full-retire-decree.txt",
    ("retirement", "rule"): FETCH / "full-retire-rule.txt",
    ("equal-employment", "statute"): FETCH / "full-equal-statute.txt",
    ("equal-employment", "decree"): FETCH / "full-equal-decree.txt",
    ("equal-employment", "rule"): FETCH / "full-equal-rule.txt",
    ("fixed-term", "statute"): FETCH / "full-fixed-statute.txt",
    ("fixed-term", "decree"): FETCH / "full-fixed-decree.txt",
    ("fixed-term", "rule"): FETCH / "full-fixed-rule.txt",
}

# 제목 괄호가 있는 조문 헤더만 인정.
# (본문이 "제31조제3항…"처럼 다른 조를 인용할 때 새 헤더로 오인하던 문제 방지)
HEADER_RE = re.compile(
    r"(?:^|\n)(제\d+조(?:의\d+)?)(?:\(([^)\n]{1,80})\)|(?=\s*삭제\b))",
)
NOISE_LINE_RE = re.compile(
    r"^(판례\s*\d+\+?|별표·서식|고용노동부|일부개정|타법개정)$"
)


def article_sort_key(no: str) -> tuple[int, int]:
    m = re.search(r"제\s*(\d+)\s*조(?:의\s*(\d+))?", no or "")
    if not m:
        return (99999, 0)
    return (int(m.group(1)), int(m.group(2) or 0))


def make_id(law_id: str, tier: str, no: str) -> str:
    num = re.sub(r"^제", "", no or "")
    num = re.sub(r"조$", "", num)
    return f"{law_id}-{tier}-{num}"


def clean_body(text: str) -> str:
    lines = []
    for raw in (text or "").split("\n"):
        line = re.sub(r"[ \t]+", " ", raw).strip()
        if not line:
            continue
        if NOISE_LINE_RE.match(line):
            continue
        if re.match(r"^제\s*\d+호$", line):
            continue
        lines.append(line)
    return "\n".join(lines).strip()


def main_article_region(text: str) -> str:
    """목차의 '부칙' 오탐을 피하고 본칙 조문 구간만 반환."""
    # 본문 시작: 실제 제1조(…) 헤더(목차보다 뒤에 오는 본문)
    starts = [m.start() for m in re.finditer(r"(?:^|\n)제1조\([^)\n]{1,40}\)", text)]
    start = 0
    for s in starts:
        window = text[s : s + 400]
        if "판례" in window or "①" in window or "이 법" in window or "이 영" in window or "이 규칙" in window:
            start = s
            break
    else:
        if starts:
            start = starts[-1]
    region = text[start:]
    # 진짜 부칙: "부칙 <법률|대통령령|…"
    bu = re.search(r"\n부칙\s*<", region)
    if bu:
        return region[: bu.start()]
    # 차선: 별표 직전
    bye = re.search(r"\n별표", region)
    if bye:
        return region[: bye.start()]
    return region


def parse_full_text(text: str) -> dict[str, dict]:
    """본문 영역에서 제N조(제목) → {title, body} 맵."""
    body = main_article_region(text)

    hits = []
    for m in HEADER_RE.finditer(body):
        no = m.group(1)
        title = (m.group(2) or "").strip()
        start = m.start() + (1 if m.group(0).startswith("\n") else 0)
        hits.append({"no": no, "title": title, "index": start, "header_end": m.end()})

    by_no: dict[str, dict] = {}
    for i, hit in enumerate(hits):
        end = hits[i + 1]["index"] if i + 1 < len(hits) else len(body)
        chunk = body[hit["header_end"] : end]
        cleaned = clean_body(chunk)
        prev = by_no.get(hit["no"])
        cand = {
            "title": hit["title"],
            "body": cleaned,
            "score": len(cleaned) + (50 if hit["title"] else 0),
        }
        if not prev or cand["score"] > prev["score"]:
            by_no[hit["no"]] = cand

    out = {}
    for no, data in by_no.items():
        if not data["body"] and not data["title"]:
            continue
        out[no] = {"title": data["title"], "body": data["body"]}
    return out


def load_full_index() -> dict[tuple[str, str], dict[str, dict]]:
    index: dict[tuple[str, str], dict[str, dict]] = {}
    for key, path in FULL_MAP.items():
        if not path.is_file():
            continue
        text = path.read_text(encoding="utf-8")
        index[key] = parse_full_text(text)
    return index


def looks_stub(body: str) -> bool:
    lines = [ln.strip() for ln in (body or "").split("\n") if ln.strip()]
    if not lines:
        return True
    if len(body) < 80:
        return True
    return all(
        len(ln) < 140 and (("<개정" in ln) or ("<신설" in ln) or ("삭제" in ln))
        for ln in lines
    )


def hydrate_articles_db(articles_db: dict, full_index: dict | None = None) -> dict:
    """기존 조문 목록을 유지한 채 제목·본문을 전문 캐시로 채웁니다(내용 삭제 없음)."""
    full_index = full_index or load_full_index()
    for law_id, pack in list(articles_db.items()):
        if not isinstance(pack, dict):
            continue
        for tier in ("statute", "decree", "rule"):
            fmap = full_index.get((law_id, tier)) or {}
            lst = pack.get(tier) or []
            for art in lst:
                no = art.get("no") or ""
                src = fmap.get(no)
                if not src:
                    continue
                if src.get("title"):
                    art["title"] = src["title"]
                new = (src.get("body") or "").strip()
                if new:
                    art["body"] = new
            pack[tier] = sorted(lst, key=lambda a: article_sort_key(a.get("no") or ""))
    return articles_db


def fill_article_from_full(
    art: dict,
    law_id: str,
    tier_key: str,
    full_index: dict | None = None,
) -> dict:
    """전문 캐시가 있으면 제목·본문을 법제처(전문) 기준으로 덮어쓴다."""
    full_index = full_index or load_full_index()
    src = (full_index.get((law_id, tier_key)) or {}).get(art.get("no") or "")
    if not src:
        return art
    if src.get("title"):
        art["title"] = src["title"]
    new = (src.get("body") or "").strip()
    if new:
        art["body"] = new
    return art


def build_seed_from_full() -> dict:
    """전문 캐시를 기준으로 시드를 새로 만든다(수동 갱신 시 현행 법령 복원)."""
    raw = {}
    if ARTICLES_PATH.is_file():
        raw = json.loads(ARTICLES_PATH.read_text(encoding="utf-8"))
    full_index = load_full_index()

    law_ids = set(raw.keys())
    for lid, _tier in full_index.keys():
        law_ids.add(lid)

    seed: dict = {}
    for law_id in sorted(law_ids):
        if law_id in raw and not isinstance(raw[law_id], dict):
            seed[law_id] = raw[law_id]
            continue
        out = {
            "statute": [],
            "decree": [],
            "rule": [],
            "meta": (raw.get(law_id) or {}).get("meta") or {},
        }
        for tier in ("statute", "decree", "rule"):
            fmap = full_index.get((law_id, tier)) or {}
            seen = set()
            for no, src in fmap.items():
                body = (src.get("body") or "").strip()
                title = (src.get("title") or "").strip()
                if not body and not title:
                    continue
                # 목차성 빈 본문 스킵
                if len(body) < 8 and not title:
                    continue
                out[tier].append(
                    {
                        "id": make_id(law_id, tier, no),
                        "no": no,
                        "title": title,
                        "body": body,
                    }
                )
                seen.add(no)
            # 전문 캐시가 있으면 그 조문만 사용(오염된 raw stub 혼입 방지)
            if fmap:
                out[tier].sort(key=lambda a: article_sort_key(a.get("no") or ""))
                continue
            # 전문이 없을 때만 raw 목록 유지
            for art in (raw.get(law_id) or {}).get(tier) or []:
                no = art.get("no") or ""
                if not no or no in seen:
                    continue
                out[tier].append(
                    {
                        "id": art.get("id") or make_id(law_id, tier, no),
                        "no": no,
                        "title": (art.get("title") or "").strip(),
                        "body": (art.get("body") or "").strip(),
                    }
                )
                seen.add(no)
            out[tier].sort(key=lambda a: article_sort_key(a.get("no") or ""))
        seed[law_id] = out

    SEED_PATH.write_text(json.dumps(seed, ensure_ascii=False, indent=2), encoding="utf-8")
    return seed


if __name__ == "__main__":
    seed = build_seed_from_full()
    for lid, pack in seed.items():
        if not isinstance(pack, dict):
            continue
        for tier in ("statute", "decree", "rule"):
            empty = [a["no"] for a in pack.get(tier) or [] if not (a.get("title") or "").strip()]
            print(lid, tier, "count", len(pack.get(tier) or []), "emptyTitle", empty[:12])
