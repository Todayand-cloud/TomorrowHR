# -*- coding: utf-8 -*-
"""법제처 Open API(DRF)로 4법×3단 전문을 받아 full-*.txt 를 덮어씁니다.

임의 창작 없이 API XML만 사용합니다.

중요: target=law 는 미시행 조문특례 본문까지 미리 넣는 경우가 있어,
기준일(오늘) 이하의 시행일 법령(target=eflaw)을 우선 사용합니다.
예) 근로자퇴직급여 보장법 제43조·제44조는 공포(2026.3.17) 후 6개월(2026.9.18) 시행.
"""

from __future__ import annotations

import re
import time
import urllib.parse
from datetime import date
from pathlib import Path

from http_util import http_get

FETCH = Path(__file__).resolve().parent
UA = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/120.0.0.0 Safari/537.36",
    "Cache-Control": "no-cache",
}

# (lawId, tier, lsId, outfile, must_contain)
FULL_TARGETS = [
    ("labor-standards", "statute", "001872", "full-labor-statute.txt", ["근로기준법", "이 법"]),
    ("labor-standards", "decree", "003058", "full-labor-decree.txt", ["근로기준법 시행령", "이 영"]),
    ("labor-standards", "rule", "006859", "full-labor-rule.txt", ["근로기준법 시행규칙", "이 규칙"]),
    ("retirement", "statute", "009883", "full-retire-statute.txt", ["근로자퇴직급여", "이 법"]),
    ("retirement", "decree", "010035", "full-retire-decree.txt", ["근로자퇴직급여", "시행령"]),
    ("retirement", "rule", "010043", "full-retire-rule.txt", ["근로자퇴직급여", "시행규칙"]),
    ("equal-employment", "statute", "000130", "full-equal-statute.txt", ["남녀고용평등", "이 법"]),
    ("equal-employment", "decree", "003140", "full-equal-decree.txt", ["남녀고용평등", "시행령"]),
    ("equal-employment", "rule", "006909", "full-equal-rule.txt", ["남녀고용평등", "시행규칙"]),
    ("fixed-term", "statute", "010356", "full-fixed-statute.txt", ["기간제", "이 법"]),
    ("fixed-term", "decree", "010461", "full-fixed-decree.txt", ["기간제", "시행령"]),
    ("fixed-term", "rule", "010473", "full-fixed-rule.txt", ["기간제", "시행규칙"]),
]


def _http_get(url: str) -> str:
    return http_get(url, headers=UA)


def _plain_tag(tag: str, block: str) -> str:
    m = re.search(rf"<{tag}[^>]*><!\[CDATA\[(.*?)\]\]></{tag}>", block, flags=re.S)
    if m:
        return m.group(1).strip()
    m = re.search(rf"<{tag}[^>]*>(.*?)</{tag}>", block, flags=re.S)
    if not m:
        return ""
    return re.sub(r"<[^>]+>", "", m.group(1)).strip()


def resolve_eflaw_ref(ls_id: str, as_of: date | None = None) -> dict | None:
    """기준일 이하 시행일 중 최신 eflaw (MST, efYd) 를 고른다."""
    as_of = as_of or date.today()
    as_of_n = int(as_of.strftime("%Y%m%d"))
    lid = str(ls_id).strip()
    candidates: list[dict] = []
    for lid_try in (lid, str(int(lid)) if lid.isdigit() else lid):
        url = (
            "https://www.law.go.kr/DRF/lawSearch.do?"
            + urllib.parse.urlencode(
                {
                    "OC": "test",
                    "target": "eflaw",
                    "type": "XML",
                    "LID": lid_try,
                    "display": "100",
                    "sort": "efdes",
                }
            )
        )
        try:
            xml = _http_get(url)
        except Exception:  # noqa: BLE001
            continue
        for block in re.findall(r"<law[^>]*>(.*?)</law>", xml, flags=re.S):
            law_id = _plain_tag("법령ID", block)
            if law_id and law_id.lstrip("0") != lid.lstrip("0"):
                continue
            mst = _plain_tag("법령일련번호", block)
            ef = re.sub(r"\D", "", _plain_tag("시행일자", block))
            if not mst or len(ef) < 8:
                continue
            ef_n = int(ef[:8])
            if ef_n > as_of_n:
                continue
            candidates.append(
                {
                    "mst": mst,
                    "efYd": ef[:8],
                    "ancYd": re.sub(r"\D", "", _plain_tag("공포일자", block))[:8],
                    "noticeNo": _plain_tag("공포번호", block),
                    "status": _plain_tag("현행연혁코드", block),
                }
            )
        if candidates:
            break
    if not candidates:
        return None
    candidates.sort(key=lambda r: (r["efYd"], r["mst"]), reverse=True)
    return candidates[0]


def fetch_eflaw_xml(mst: str, ef_yd: str) -> str:
    url = (
        "https://www.law.go.kr/DRF/lawService.do?"
        + urllib.parse.urlencode(
            {
                "OC": "test",
                "target": "eflaw",
                "type": "XML",
                "MST": mst,
                "efYd": ef_yd,
            }
        )
    )
    return _http_get(url)


def fetch_law_xml(ls_id: str) -> str:
    """현행 통합본(미시행 조문특례 본문이 포함될 수 있음)."""
    url = (
        "https://www.law.go.kr/DRF/lawService.do?"
        + urllib.parse.urlencode(
            {"OC": "test", "target": "law", "type": "XML", "ID": ls_id}
        )
    )
    return _http_get(url)


def fetch_xml(ls_id: str, as_of: date | None = None) -> str:
    """기준일 시점의 법제처 본문(eflaw 우선, 실패 시 law)."""
    ref = resolve_eflaw_ref(ls_id, as_of=as_of)
    if ref:
        return fetch_eflaw_xml(ref["mst"], ref["efYd"])
    return fetch_law_xml(ls_id)


def _cdata(tag: str, block: str) -> str:
    m = re.search(rf"<{tag}[^>]*><!\[CDATA\[(.*?)\]\]></{tag}>", block, flags=re.S)
    if m:
        return m.group(1).strip()
    m = re.search(rf"<{tag}[^>]*>(.*?)</{tag}>", block, flags=re.S)
    return (m.group(1).strip() if m else "")


def normalize_hist(text: str) -> str:
    """<개정 2010.7.12> → <개정 2010. 7. 12.>"""

    def _fix(m: re.Match[str]) -> str:
        kind = m.group(1)
        blob = m.group(2)
        parts = []
        for y, mo, d in re.findall(r"(\d{4})\.\s*(\d{1,2})\.\s*(\d{1,2})\.?", blob):
            parts.append(f"{int(y)}. {int(mo)}. {int(d)}.")
        if not parts:
            return m.group(0)
        return f"<{kind} {', '.join(parts)}>"

    return re.sub(r"<(신설|개정)\s*([^>]+)>", _fix, text)


def jo_label(num: str, branch: str = "") -> str:
    num = (num or "").strip()
    branch = (branch or "").strip()
    m = re.match(r"^(\d+)(?:의(\d+))?$", num)
    if m:
        base = f"제{m.group(1)}조"
        br = m.group(2) or branch
        return base + (f"의{br}" if br else "")
    if not num:
        return ""
    if branch:
        return f"제{num}조의{branch}"
    return f"제{num}조"


def xml_to_full_text(xml: str) -> str:
    name = _cdata("법령명_한글", xml) or ""
    eff = _cdata("시행일자", xml)
    amd = _cdata("공포일자", xml)
    notice = _cdata("공포번호", xml)
    kind = _cdata("법종구분", xml) or _cdata("제개정구분", xml)

    def ymd(s: str) -> str:
        s = re.sub(r"\D", "", s or "")
        if len(s) >= 8:
            return f"{s[0:4]}. {int(s[4:6])}. {int(s[6:8])}."
        return s

    header = [
        name,
        f"[시행 {ymd(eff)}] [{kind} 제{notice}호, {ymd(amd)}]",
        "",
    ]
    lines: list[str] = list(header)

    for block in re.findall(r"<조문단위[^>]*>(.*?)</조문단위>", xml, flags=re.S):
        yn = _cdata("조문여부", block)
        if yn != "조문":
            cont = _cdata("조문내용", block)
            if cont and ("장" in cont or "절" in cont):
                lines.append(cont.strip())
                lines.append("")
            continue
        num = _cdata("조문번호", block)
        branch = _cdata("조문가지번호", block)
        title = _cdata("조문제목", block)
        label = jo_label(num, branch)
        if not label:
            continue
        head = f"{label}({title})" if title else label
        lines.append(head)

        # 법제처 XML: 벌칙 조문 등은 <항내용> 없이 <호>만 있는 경우가 많음.
        # 예전 파서는 항내용이 있을 때만 호를 넣어 제110조 등이 빈 본문이 되었음.
        cont = normalize_hist(_cdata("조문내용", block))
        cont = re.sub(rf"^{re.escape(label)}(?:\([^)]*\))?\s*", "", cont).strip()
        if title:
            cont = re.sub(rf"^\({re.escape(title)}\)\s*", "", cont).strip()
        hangs = re.findall(r"<항>(.*?)</항>", block, flags=re.S)
        hang_parts: list[str] = []
        for h in hangs:
            body = normalize_hist(_cdata("항내용", h))
            if body:
                hang_parts.append(body)
            for ho in re.findall(r"<호>(.*?)</호>", h, flags=re.S):
                hb = normalize_hist(_cdata("호내용", ho))
                if hb:
                    hang_parts.append(hb)
            # 목·세목
            for mok in re.findall(r"<목>(.*?)</목>", h, flags=re.S):
                mb = normalize_hist(_cdata("목내용", mok))
                if mb:
                    hang_parts.append(mb)

        if hang_parts:
            joined = "\n".join(hang_parts)
            # 조문내용 preamble(「다음 각 호의…」)은 호와 별도 → 앞에 붙임
            if cont and cont not in joined:
                lines.append(cont)
            lines.extend(hang_parts)
        elif cont:
            lines.append(cont)
        lines.append("")

    return "\n".join(lines).strip() + "\n"


def validate_text(text: str, must_contain: list[str], tier: str) -> list[str]:
    problems = []
    if not (text or "").strip():
        return ["empty"]
    head = text[:2500]
    for token in must_contain:
        if token not in text:
            problems.append(f"missing:{token}")
    if tier == "rule":
        if "시행규칙" not in head and "이 규칙" not in text[:8000]:
            problems.append("not_rule_text")
        if "이 법은" in head and "이 규칙" not in text[:8000]:
            problems.append("statute_text_in_rule_file")
    if tier == "decree":
        if "시행령" not in head and "이 영" not in text[:8000]:
            problems.append("not_decree_text")
    if tier == "statute":
        if "이 영은" in head[:500] and "이 법은" not in text[:8000]:
            problems.append("decree_text_in_statute_file")
    return problems


def refresh_all_full_texts(
    sleep_s: float | None = None, as_of: date | None = None, workers: int | None = None
) -> dict:
    """4법×3단 전문을 병렬 수집. CI(LAW_FETCH_FAST)에서는 sleep 없이 동시 요청."""
    import os
    from concurrent.futures import ThreadPoolExecutor, as_completed

    as_of = as_of or date.today()
    fast = os.environ.get("LAW_FETCH_FAST", "").strip() in ("1", "true", "TRUE") or (
        os.environ.get("CI", "").strip() == "true"
    )
    if sleep_s is None:
        sleep_s = 0.0 if fast else 0.25
    if workers is None:
        workers = 4 if fast else 1

    report: dict = {"ok": True, "asOf": as_of.isoformat(), "files": [], "errors": []}

    def _one(target: tuple) -> dict:
        law_id, tier, ls_id, filename, must = target
        path = FETCH / filename
        ref = resolve_eflaw_ref(ls_id, as_of=as_of)
        xml = (
            fetch_eflaw_xml(ref["mst"], ref["efYd"]) if ref else fetch_law_xml(ls_id)
        )
        text = xml_to_full_text(xml)
        problems = validate_text(text, must, tier)
        if problems:
            raise RuntimeError(f"validation failed: {problems}")
        jo_n = len(re.findall(r"(?m)^제\d+조", text))
        if jo_n < 1:
            raise RuntimeError("no articles parsed")
        path.write_text(text, encoding="utf-8")
        if sleep_s > 0:
            time.sleep(sleep_s)
        return {
            "lawId": law_id,
            "tier": tier,
            "lsId": ls_id,
            "file": filename,
            "bytes": len(text.encode("utf-8")),
            "articles": jo_n,
            "eflaw": ref,
        }

    if workers <= 1:
        for target in FULL_TARGETS:
            try:
                report["files"].append(_one(target))
            except Exception as exc:  # noqa: BLE001
                report["ok"] = False
                law_id, tier, ls_id, filename, _must = target
                report["errors"].append(
                    {
                        "lawId": law_id,
                        "tier": tier,
                        "lsId": ls_id,
                        "file": filename,
                        "error": str(exc),
                    }
                )
        return report

    with ThreadPoolExecutor(max_workers=workers) as pool:
        futs = {pool.submit(_one, t): t for t in FULL_TARGETS}
        for fut in as_completed(futs):
            target = futs[fut]
            try:
                report["files"].append(fut.result())
            except Exception as exc:  # noqa: BLE001
                report["ok"] = False
                law_id, tier, ls_id, filename, _must = target
                report["errors"].append(
                    {
                        "lawId": law_id,
                        "tier": tier,
                        "lsId": ls_id,
                        "file": filename,
                        "error": str(exc),
                    }
                )
    return report


if __name__ == "__main__":
    import json

    print(json.dumps(refresh_all_full_texts(), ensure_ascii=False, indent=2))
