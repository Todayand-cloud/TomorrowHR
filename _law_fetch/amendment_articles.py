# -*- coding: utf-8 -*-
"""개정문(lsRvsDocListP)에서 조문 단위 변경·시행일을 추출하고 로컬 조문을 갱신합니다."""

from __future__ import annotations

import json
import re
import time
from datetime import date, timedelta
from pathlib import Path

from http_util import http_get

ROOT = Path(__file__).resolve().parents[1]
ARTICLES_PATH = ROOT / "js" / "law-articles-raw.json"
ARTICLES_JS_PATH = ROOT / "js" / "law-articles.js"
SEED_PATH = ROOT / "js" / "law-articles-seed.json"
UA = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/120.0.0.0 Safari/537.36",
    "Cache-Control": "no-cache",
}

DOC_HEADER_RE = re.compile(
    r"\[시행\s*([0-9.\s]+)\]\s*\[([^\]]+?)\s*제([0-9]+)호,\s*([0-9.\s]+),\s*([^\]]+)\]"
)
PROVISO_NEW_RE = re.compile(
    r"제\s*([0-9]+)\s*조(?:의\s*([0-9]+))?제\s*([0-9]+)\s*항에\s*단서를\s*다음과\s*같이\s*신설한다\.\s*"
    r"(다만,[^.]+그러하지\s*아니하다\.)"
)
QUOTE_SWAP_RE = re.compile(
    r'(?:"([^"]{1,320})"|「([^」]{1,320})」)\s*[을를]\s*'
    r'(?:각각\s*)?'
    r'(?:"([^"]{1,320})"|「([^」]{1,320})」)\s*(?:으로|로)'
)
# 제61조제1항 각 호 외의 부분 중 "A"을 각각 "B"로 한다/하고 (부칙·타법개정 포함)
# ※ 조·항·호와 '중' 사이는 허용 문구만 — 문장 넘어 다음 제N조 중 과 결합 금지
#   (예: …제52조제2항제2호…아니하다. 제108조 중 "근로감독관" → 제52조 오귀속)
_LOCATED_MID = (
    r"(?:\s*(?:각\s*호(?:\s*외의\s*부분)?|제목(?:\s*외의\s*부분)?|"
    r"단서|본문|전단|후단))*"
)
LOCATED_SWAP_RE = re.compile(
    r"제\s*(\d+)\s*조(?:의\s*(\d+))?"
    r"(?:제\s*(\d+)\s*항)?"
    r"(?:제\s*(\d+)\s*호)?"
    + _LOCATED_MID
    + r"\s*중\s*"
    + r'(?:"([^"]{1,320})"|「([^」]{1,320})」)\s*[을를]\s*'
    + r"(?:각각\s*)?"
    + r'(?:"([^"]{1,320})"|「([^」]{1,320})」)\s*(?:으로|로)'
    + r"(?:\s*한다|\s*하고|\s*하며)?"
)
JO_TOKEN_RE = re.compile(r"제\s*([0-9]+)\s*조(?:의\s*([0-9]+))?")
UNIT_HANG_HO_RE = re.compile(
    r"제\s*\d+\s*조(?:의\s*\d+)?제\s*(\d+)\s*항제\s*(\d+)\s*호"
)
UNIT_HO_RE = re.compile(r"제\s*\d+\s*조(?:의\s*\d+)?(?:제\s*\d+\s*항)?제\s*(\d+)\s*호")
UNIT_HANG_RE = re.compile(r"제\s*\d+\s*조(?:의\s*\d+)?제\s*(\d+)\s*항")


def resolve_unit_locator(prefix: str) -> str:
    """개정문 prefix에서 같은 조/같은 항을 포함한 항·호 위치를 해석한다.

    예: 「같은 조 제2항제1호」「같은 항 제2호」「같은 항에」
    인용부("…"·「…」) 안의 조문 번호는 위치 지시가 아니므로 무시한다.
    """
    locs = resolve_unit_locators(prefix)
    return locs[0] if locs else ""


def resolve_unit_locators(prefix: str) -> list[str]:
    """위치 지시가 복수 호(제1호 및 제2호)이면 모든 locator를 반환."""
    # 인용 안 조항호(예: "제44조의4제1항ㆍ제4항")가 같은 항 위치를 오염시키지 않게
    def _blank(m: re.Match[str]) -> str:
        return " " * (m.end() - m.start())

    cleaned = re.sub(r'"[^"]*"', _blank, prefix or "")
    cleaned = re.sub(r"「[^」]*」", _blank, cleaned)
    hang: int | None = None
    ho: int | None = None
    events: list[tuple[int, str, tuple[int, ...]]] = []
    for m in re.finditer(
        r"제\s*\d+\s*조(?:의\s*\d+)?제\s*(\d+)\s*항제\s*(\d+)\s*호", cleaned
    ):
        events.append((m.start(), "hang_ho", (int(m.group(1)), int(m.group(2)))))
    for m in re.finditer(r"같은\s*조\s*제\s*(\d+)\s*항제\s*(\d+)\s*호", cleaned):
        events.append((m.start(), "hang_ho", (int(m.group(1)), int(m.group(2)))))
    # 같은 조 제2항 중 … (호 없음)
    for m in re.finditer(
        r"같은\s*조\s*제\s*(\d+)\s*항(?!\s*제\s*\d+\s*호)", cleaned
    ):
        events.append((m.start(), "hang", (int(m.group(1)),)))
    for m in re.finditer(r"같은\s*항\s*제\s*(\d+)\s*호", cleaned):
        events.append((m.start(), "same_ho", (int(m.group(1)),)))
    for m in re.finditer(
        r"제\s*\d+\s*조(?:의\s*\d+)?제\s*(\d+)\s*항(?!\s*제\s*\d+\s*호)", cleaned
    ):
        events.append((m.start(), "hang", (int(m.group(1)),)))
    for m in re.finditer(r"같은\s*항에", cleaned):
        events.append((m.start(), "same_hang", ()))
    # 제N항 각 호 외의 부분 → 항 본문(호 제외)
    for m in re.finditer(
        r"(?:제\s*\d+\s*조(?:의\s*\d+)?)?제\s*(\d+)\s*항\s*각\s*호\s*외의\s*부분"
        r"|같은\s*조\s*제\s*(\d+)\s*항\s*각\s*호\s*외의\s*부분"
        r"|같은\s*항\s*각\s*호\s*외의\s*부분",
        cleaned,
    ):
        n = m.group(1) or m.group(2)
        if n:
            events.append((m.start(), "hang_lead", (int(n),)))
        else:
            events.append((m.start(), "same_hang_lead", ()))
    # 같은 항 제1호 및 제2호 / 제1호ㆍ제2호
    for m in re.finditer(
        r"(?:같은\s*항\s*)?제\s*(\d+)\s*호(?:\s*(?:및|ㆍ|,)\s*제\s*(\d+)\s*호)+",
        cleaned,
    ):
        hos = [int(x) for x in re.findall(r"제\s*(\d+)\s*호", m.group(0))]
        events.append((m.start(), "multi_ho", tuple(hos)))

    multi_hos: list[int] | None = None
    for _pos, kind, vals in sorted(events, key=lambda x: x[0]):
        if kind == "hang_ho":
            hang, ho = vals[0], vals[1]
            multi_hos = None
        elif kind == "same_ho":
            ho = vals[0]
            multi_hos = None
        elif kind == "hang":
            hang = vals[0]
            ho = None
            multi_hos = None
        elif kind == "same_hang":
            ho = None
            multi_hos = None
        elif kind == "hang_lead":
            hang = vals[0]
            ho = None
            multi_hos = None
        elif kind == "same_hang_lead":
            ho = None
            multi_hos = None
        elif kind == "multi_ho":
            multi_hos = list(vals)
            ho = None
    if multi_hos and hang is not None:
        return [f"제{hang}항제{h}호" for h in multi_hos]
    if hang is not None and ho is not None:
        return [f"제{hang}항제{ho}호"]
    if hang is not None:
        return [f"제{hang}항"]
    if ho is not None:
        return [f"제{ho}호"]
    return []


def _extract_trailing_hos(chunk: str, after_pos: int) -> list[str]:
    """신설 각 호 본문: 개정 지시문 끝(…한다.) 뒤의 1. 2. … 목록.

    단서(다만, …)가 호 목록 앞에 와도 1. 2. 3. 만 수집한다.
    """
    tail = chunk[after_pos:]
    # 지시문과 같은 '신설한다.' 직후부터. 이후 '한다.'로 재절단하지 않음
    # (단서·호 본문에 '…한다.' 가 있으면 호가 잘릴 수 있음)
    first = re.search(r"\d+(?:의\d+)?\.\s*", tail)
    if not first:
        return []
    tail = tail[first.start() :]
    hos: list[str] = []
    for hos_m in re.finditer(
        r"(\d+(?:의\d+)?\.\s*.+?)(?=\s*\d+(?:의\d+)?\.|\s*$)",
        tail,
        flags=re.S,
    ):
        text = re.sub(r"\s+", " ", hos_m.group(1)).strip()
        # 단서·지시 잔여가 호처럼 잡히지 않게: 본문이 너무 짧거나 호 형식만
        if len(text) < 6:
            continue
        if not re.match(r"\d+(?:의\d+)?\.\s+\S", text):
            continue
        hos.append(text)
    return hos


def find_ho_in_hang(
    body: str, hang: int | None, ho: int
) -> tuple[str, int, int] | None:
    """지정 항 블록 안의 N호 한 줄을 찾는다."""
    text = body or ""
    search = text
    base = 0
    if hang:
        mark = N_TO_CIRCLE.get(int(hang))
        if mark:
            m = re.search(rf"(?ms)^({re.escape(mark)}.*?)(?=^[①-⑮]|\Z)", text)
            if not m:
                return None
            search = m.group(1)
            base = m.start()
    for hm in re.finditer(
        rf"(?ms)^({ho}(?:의\d+)?\.\s+.*?)(?=^\d+\.\s|^[①-⑮]|\Z)",
        search,
    ):
        raw = hm.group(1)
        start = base + hm.start()
        end = start + len(raw)
        while end > start and text[end - 1] in "\r\n":
            end -= 1
        return text[start:end].rstrip(), start, end
    return None
NEW_ARTICLE_RE = re.compile(
    r"제\s*([0-9]+)\s*조(?:의\s*([0-9]+))?를\s*다음과\s*같이\s*신설한다\.\s*"
    r"(제\s*\1\s*조(?:의\s*\2)?\(([^)]+)\)\s*)"
    r"(.+?)(?="
    r"제\s*\d+\s*조(?:의\s*\d+)?를\s*다음과\s*같이\s*신설|"
    # 다음 개정 지시문의 시작만 종료 지점으로 인정한다. 이전에는
    # '제N조제M항' 패턴만으로 종료를 판정해, 신설 조문 자체가 다른 조를
    # 인용("① 법 제18조의2제1항에 따라…")하기만 해도 본문이 잘렸다.
    # 실제 지시문은 항상 "…중" 으로 끝나므로 이를 함께 요구한다.
    r"제\s*\d+\s*조(?:의\s*\d+)?(?:제\s*\d+\s*항)?(?:제\s*\d+\s*호)?"
    + _LOCATED_MID
    + r"\s*중\s|"
    r"제\s*\d+\s*장|"
    r"\s부칙\s|"
    r"$)"
)
# 조문 번호 자체를 옮기는 지시("제9조의2를 제9조의3으로 하고"). 이 번호가
# 곧바로 다른 내용으로 신설되면(NEW_ARTICLE_RE), 옛 조문·새 조문을 같은
# articleId로 합쳐서 보여주는 회귀(제9조의2 본문 뒤에 다른 조 신설문이
# 이어 붙는 문제)를 막기 위해 사용한다.
ARTICLE_RENUMBER_RE = re.compile(
    r"제\s*(\d+)\s*조(?:의\s*(\d+))?를\s*제\s*(\d+)\s*조(?:의\s*(\d+))?(?:으로|로)\s*(?:하고|한다|하며)"
)
# 여러 조를 한꺼번에 옮기는 지시("제14조의2 및 제14조의3을 각각 제14조의3 및
# 제14조의4로 하고"). 위 단일형 정규식은 '각각' 나열형은 잡지 못한다.
ARTICLE_RENUMBER_LIST_RE = re.compile(
    r"((?:제\s*\d+\s*조(?:의\s*\d+)?\s*(?:,|및)\s*)+제\s*\d+\s*조(?:의\s*\d+)?)"
    r"\s*(?:을|를)\s*각각\s*"
    r"((?:제\s*\d+\s*조(?:의\s*\d+)?\s*(?:,|및)\s*)+제\s*\d+\s*조(?:의\s*\d+)?)"
    r"\s*(?:으로|로)\s*(?:하고|한다|하며)"
)
CIRCLE = "①②③④⑤⑥⑦⑧⑨⑩⑪⑫⑬⑭⑮"
CIRCLE_TO_N = {c: i + 1 for i, c in enumerate(CIRCLE)}
N_TO_CIRCLE = {i + 1: c for i, c in enumerate(CIRCLE)}

# 조 제목 (빈 제목/제N조() 방지)
ARTICLE_TITLES = {
    ("labor-standards", "제54조"): "휴게",
    ("labor-standards", "제60조"): "연차 유급휴가",
    ("labor-standards", "제61조"): "연차 유급휴가의 사용 촉진",
    ("labor-standards", "제107조"): "벌칙",
    ("labor-standards", "제108조"): "벌칙",
    ("labor-standards", "제109조"): "벌칙",
    ("labor-standards", "제110조"): "벌칙",
    ("labor-standards", "제114조"): "벌칙",
    ("labor-standards", "제116조"): "과태료",
}

# 타법개정 문구가 어느 법령을 고치는지 판별
LAW_ALIASES = {
    "labor-standards": ["근로기준법"],
    "equal-employment": ["남녀고용평등", "일ㆍ가정 양립", "일·가정 양립"],
    "retirement": ["근로자퇴직급여"],
    "fixed-term": ["기간제", "단시간근로자"],
}


def _located_swap_belongs(doc_text: str, match_start: int, law_id: str, law_name: str) -> bool:
    """부칙 타법개정으로 다른 법을 고치는 치환은 해당 법에만 귀속."""
    prefix = doc_text[max(0, match_start - 400) : match_start]
    owners = list(
        re.finditer(r"([가-힣ㆍ·\s]{2,60}?)\s*일부를\s*다음과\s*같이\s*개정한다", prefix)
    )
    if not owners:
        return True
    owner = owners[-1].group(1).strip()
    aliases = LAW_ALIASES.get(law_id) or [law_name]
    return any(a and a in owner for a in aliases)


def fetch_html(url: str) -> str:
    sep = "&" if "?" in url else "?"
    return http_get(f"{url}{sep}_ts={int(time.time() * 1000)}", headers=UA)


def html_to_text(html: str) -> str:
    text = re.sub(r"(?is)<script[^>]*>.*?</script>", " ", html)
    text = re.sub(r"(?is)<style[^>]*>.*?</style>", " ", text)
    text = re.sub(r"<[^>]+>", " ", text)
    text = text.replace("&nbsp;", " ").replace("&#39;", "'").replace("&quot;", '"')
    text = text.replace("“", '"').replace("”", '"').replace("＇", "'")
    return re.sub(r"\s+", " ", text).strip()


def parse_ymd_dots(text: str) -> date:
    parts = [int(x) for x in re.findall(r"\d+", text)]
    return date(parts[0], parts[1], parts[2])


def to_iso(d: date) -> str:
    return d.isoformat()


def add_months(d: date, months: int) -> date:
    y = d.year + (d.month - 1 + months) // 12
    m = (d.month - 1 + months) % 12 + 1
    day = min(
        d.day,
        [
            31,
            29 if y % 4 == 0 and (y % 100 != 0 or y % 400 == 0) else 28,
            31,
            30,
            31,
            30,
            31,
            31,
            30,
            31,
            30,
            31,
        ][m - 1],
    )
    return date(y, m, day) + timedelta(days=1)


_DOC_MAP_CACHE: dict[str, dict[str, str]] = {}


def clear_doc_map_cache() -> None:
    _DOC_MAP_CACHE.clear()


def fetch_doc_map(ls_id: str, *, force: bool = False) -> dict[str, str]:
    """noticeNo -> 개정문 plain text (프로세스 내 캐시)."""
    if not force and ls_id in _DOC_MAP_CACHE:
        return _DOC_MAP_CACHE[ls_id]
    url = (
        "https://www.law.go.kr/LSW/lsRvsDocListP.do?"
        f"chrClsCd=010202&lsId={ls_id}&lsRvsGubun=all"
    )
    text = html_to_text(fetch_html(url))
    matches = list(DOC_HEADER_RE.finditer(text))
    out = {}
    for i, m in enumerate(matches):
        notice = m.group(3)
        start = m.start()
        end = matches[i + 1].start() if i + 1 < len(matches) else min(len(text), start + 14000)
        out[notice] = text[start:end]
    _DOC_MAP_CACHE[ls_id] = out
    return out


def jo_label(no: str, of: str | None = None) -> str:
    return f"제{no}조" + (f"의{of}" if of else "")


def hist_tag(amended: date, kind: str = "개정") -> str:
    return f"<{kind} {amended.year}. {amended.month}. {amended.day}.>"


def append_hist_date(unit: str, amended: date, kind: str = "개정") -> str:
    """항·호 단위 끝 연혁 태그에 공포일을 추가(없으면 신설)."""
    text = (unit or "").rstrip()
    d = f"{amended.year}. {amended.month}. {amended.day}."
    m = re.search(r"<(개정|신설)\s*([^>]*)>", text)
    if m:
        inner = (m.group(2) or "").strip().rstrip(",")
        if d in inner:
            return text
        new_inner = f"{inner}, {d}" if inner else d
        return text[: m.start()] + f"<{m.group(1)} {new_inner}>" + text[m.end() :]
    return (text + " " + hist_tag(amended, kind)).strip()


def strip_hist_tags(text: str) -> str:
    return re.sub(r"\s*<(?:개정|신설)\s*[^>]*>\s*", " ", text or "").strip()


def safe_text_replace(text: str, old: str, new: str, count: int = 1) -> str:
    """본문 치환. new 가 old 의 확장형이면 이미 바뀐 자리(경우에는←경우에)를 재치환하지 않음.

    예: old='경우에' new='경우에는' → '경우에는' 안의 '경우에' 는 건드리지 않음
    (그렇지 않으면 '경우에는는' 오타가 생김).
    """
    if not text or not old or old == new:
        return text
    if new.startswith(old) and len(new) > len(old):
        suffix = re.escape(new[len(old) :])
        pat = re.compile(re.escape(old) + rf"(?!{suffix})")
        return pat.sub(new, text, count=count if count > 0 else 0)
    if count == 1:
        return text.replace(old, new, 1)
    if count <= 0:
        return text.replace(old, new)
    out = text
    for _ in range(count):
        if old not in out:
            break
        out = out.replace(old, new, 1)
    return out


def fix_josa_after_jo_replace(text: str, new: str) -> str:
    """제104조제2항→제104조 치환 후 '조을' → '조를' 보정."""
    if not text or not new or not new.endswith("조"):
        return text
    return re.sub(
        rf"({re.escape(new)})을(?=\s|위반|위반한|,|\.|$)",
        r"\1를",
        text,
        count=1,
    )


def parse_special_effective(doc_text: str, amended: date, default_effective: date) -> dict[str, date]:
    """부칙 시행일 특례를 조·항·호 단위로 해석한다.

    키 예: 제114조, 제114조제1호, 제116조제2항제1호, 제116조제1항제2호
    조 단위만 있으면 그 조 전체 기본값. 항·호가 있으면 더 구체적 키가 우선.
    """
    special: dict[str, date] = {}

    def _add_unit_keys(block: str, eff: date) -> None:
        # 제N조부터 제M조까지
        for m in re.finditer(
            r"제\s*(\d+)\s*조(?:의\s*(\d+))?부터\s*제\s*(\d+)\s*조(?:의\s*(\d+))?까지",
            block,
        ):
            a, ao, b, _bo = int(m.group(1)), m.group(2), int(m.group(3)), m.group(4)
            for n in range(a, b + 1):
                special[jo_label(str(n), ao if n == a else None)] = eff
        # 제N조[의K][제H항][제X호[ㆍ제Y호…]]
        for m in re.finditer(
            r"제\s*(\d+)\s*조(?:의\s*(\d+))?"
            r"(?:제\s*(\d+)\s*항)?"
            r"((?:제\s*\d+\s*호)(?:\s*ㆍ\s*제\s*\d+\s*호)*)?",
            block,
        ):
            jo = jo_label(m.group(1), m.group(2) or None)
            hang = m.group(3)
            hos_blob = m.group(4) or ""
            # 장 제목 등 스킵: "제11장의 제목"
            if re.search(rf"제\s*{re.escape(m.group(1))}\s*장", block[max(0, m.start() - 2) : m.end() + 4]):
                continue
            hos = [int(x) for x in re.findall(r"제\s*(\d+)\s*호", hos_blob)]
            if hang and hos:
                for ho in hos:
                    special[f"{jo}제{int(hang)}항제{ho}호"] = eff
            elif hang and not hos:
                special[f"{jo}제{int(hang)}항"] = eff
            elif hos and not hang:
                for ho in hos:
                    special[f"{jo}제{ho}호"] = eff
            else:
                # 조 단위만 (다른 항·호 특례와 충돌 시 구체 키가 우선)
                if jo not in special:
                    special[jo] = eff

    # 제N조의 개정규정은 공포 후 M개월…
    for no, of, months in re.findall(
        r"제\s*([0-9]+)\s*조(?:의\s*([0-9]+))?의\s*개정규정은\s*공포\s*후\s*([0-9]+)\s*개월이\s*경과한\s*날부터\s*시행",
        doc_text,
    ):
        special[jo_label(no, of or None)] = add_months(amended, int(months))

    # 다만, … 의 개정규정은 공포 후 N개월…
    for block, months in re.findall(
        r"다만,\s*([^.]{10,800}?)"
        r"(?:까지(?:의)?|의)\s*개정규정은\s*공포\s*후\s*([0-9]+)\s*개월이\s*경과한\s*날부터\s*시행",
        doc_text,
    ):
        _add_unit_keys(block, add_months(amended, int(months)))

    # …하고, … 의 개정규정은 YYYY년 M월 D일부터 시행
    for block, y, m, d in re.findall(
        r"(?:하고|그리고)\s*,?\s*([^.]{8,500}?)"
        r"(?:까지(?:의)?|의)\s*개정규정은\s*([0-9]{4})\s*년\s*([0-9]{1,2})\s*월\s*([0-9]{1,2})\s*일부터\s*시행",
        doc_text,
    ):
        _add_unit_keys(block, date(int(y), int(m), int(d)))

    return special


def law_default_effective(doc_text: str, amended: date, fallback: date) -> date:
    """부칙 '이 법은 공포 후 N개월' 기본 시행일."""
    m = re.search(
        r"이\s*법은\s*공포\s*후\s*(\d+)\s*개월이\s*경과한\s*날부터\s*시행",
        doc_text or "",
    )
    if m:
        return add_months(amended, int(m.group(1)))
    m2 = re.search(
        r"이\s*법은\s*공포\s*후\s*(\d+)\s*년이\s*경과한\s*날부터\s*시행",
        doc_text or "",
    )
    if m2:
        return add_months(amended, int(m2.group(1)) * 12)
    return fallback


def resolve_unit_effective(
    jo: str,
    unit_loc: str,
    special: dict[str, date],
    default_eff: date,
) -> date:
    """항·호 특례 > 조 특례 > 법률 기본 시행일."""
    loc = (unit_loc or "").replace(" ", "")
    candidates: list[str] = []
    if loc:
        if loc.startswith("제") and "조" in loc:
            candidates.append(loc)
        else:
            candidates.append(f"{jo}{loc}")
            candidates.append(loc)
        # 제2항제1호 → 제2항 도 후보
        hm = re.match(r"(제\d+항)(제\d+호)?$", loc)
        if hm and jo:
            candidates.append(f"{jo}{hm.group(1)}")
    candidates.append(jo)
    for key in candidates:
        if key and key in special:
            return special[key]
    return default_eff


_STMT_START_RE = re.compile(
    r"(?:^|(?<=\.\s)|(?<=다\.\s)|(?<=자\s)|(?<=다\s)|(?<=고\s)|(?<=며\s))"
    r"제\s*([0-9]+)\s*조(?:의\s*([0-9]+))?"
    r"(?="
    # 제19조제6항을 제9항으로 — 항·호 접미사 뒤 조사/중/신설 지시
    r"(?:제\s*\d+\s*항)?(?:제\s*\d+\s*호)?"
    r"(?:"
    r"(?:\s*(?:각\s*호(?:\s*외의\s*부분)?|제목(?:\s*외의\s*부분)?|단서|본문|전단|후단))?\s*중\s"
    r"|의\s*제목"
    r"|\s*제목"
    r"|\s*중\s"
    r"|[을를]\s"
    r"|\s*[을를]\s"
    r"|\s*에\s"
    r"|\s*부터\s"
    r"|\s*각\s*호"
    r"|를\s*다음과"
    r"|\("
    r")"
    r")"
)


def expected_amended_articles_from_doc(doc_text: str) -> list[str]:
    """개정문에서 '이 법이 고치는 조' 목록 (누락 검증용)."""
    main = re.split(r"\s부칙\s", doc_text or "", maxsplit=1)[0]
    found: list[str] = []
    seen: set[str] = set()
    patterns = [
        # 제N조…중 "…"을 "…"로 (인용 속 제52조제2항제2호 오탐 방지)
        re.compile(
            r"제\s*(\d+)\s*조(?:의\s*(\d+))?"
            r"(?:제\s*\d+\s*항)?(?:제\s*\d+\s*호)?"
            r"(?:\s*(?:각\s*호(?:\s*외의\s*부분)?|제목(?:\s*외의\s*부분)?|단서|본문))?"
            r"\s*중\s*[\"「]"
        ),
        # 단서 신설
        re.compile(
            r"제\s*(\d+)\s*조(?:의\s*(\d+))?제\s*\d+\s*항에\s*단서를\s*다음과\s*같이\s*신설"
        ),
        # 조 신설
        re.compile(r"제\s*(\d+)\s*조(?:의\s*(\d+))?를\s*다음과\s*같이\s*신설"),
        # 제N조제M항…를 다음과 같이
        re.compile(
            r"제\s*(\d+)\s*조(?:의\s*(\d+))?제\s*\d+\s*항(?:제\s*\d+\s*호)?"
            r"를\s*다음과"
        ),
        # 제N조제M항을 제K항으로 (항 이동 후 신설)
        re.compile(
            r"제\s*(\d+)\s*조(?:의\s*(\d+))?제\s*\d+\s*항을\s*제\s*\d+\s*항으로"
        ),
        # 같은 조에 제N항부터 … 신설 — 직전 조 지시와 함께 쓰이므로
        # 제N조제M항을 … 패턴으로 이미 잡히면 충분
    ]
    for pat in patterns:
        for m in pat.finditer(main):
            jo = jo_label(m.group(1), m.group(2) if m.lastindex and m.lastindex >= 2 else None)
            if jo and jo not in seen:
                seen.add(jo)
                found.append(jo)
    return found


def _is_cite_token(text: str) -> bool:
    s = re.sub(r"\s+", "", text or "")
    return bool(
        re.fullmatch(
            r"제\d+조(?:의\d+)?(?:제\d+항)?(?:제\d+호)?(?:단서|본문)?",
            s,
        )
    )


def _is_ho_list_embedded_jo(text: str, pos: int) -> bool:
    """호 목록 본문 속 '1. 제9조제1항을 위반…' 은 조문 지시가 아님.

    `_STMT_START_RE` 가 `1. ` 뒤 `(?<=\\.\\s)` 로 제N조를 잡아
    제43조 각 호 신설 청크가 잘리는 회귀를 막는다.
    """
    prev = text[max(0, pos - 12) : pos]
    return bool(re.search(r"\d+(?:의\d+)?\.\s*$", prev))


def _split_jo_chunks(doc_text: str) -> list[tuple[str, str]]:
    """개정 본문을 조문 지시 단위로 자른다(인용·본문 속 조문번호 제외)."""
    main = re.split(r"\s부칙\s", doc_text, maxsplit=1)[0]
    starts = [
        m
        for m in _STMT_START_RE.finditer(main)
        if not _is_ho_list_embedded_jo(main, m.start())
    ]
    chunks: list[tuple[str, str]] = []
    for i, m in enumerate(starts):
        jo = jo_label(m.group(1), m.group(2))
        start = m.start()
        end = starts[i + 1].start() if i + 1 < len(starts) else len(main)
        chunk = main[start:end].strip()
        if len(chunk) >= 8:
            chunks.append((jo, chunk))
    return chunks


def _extract_new_paragraphs(chunk: str) -> list[str]:
    """'신설한다.' 뒤에 오는 ①~⑮ 항 본문을 수집."""
    paras = []
    for m in re.finditer(r"신설한다\.\s*", chunk):
        rest = chunk[m.end() :]
        stop = None
        for sm in _STMT_START_RE.finditer(rest):
            if _is_ho_list_embedded_jo(rest, sm.start()):
                continue
            stop = sm
            break
        # 제N장에 제M조를 신설 — 항 본문에 다음 조 지시가 붙지 않게
        stop2 = re.search(r"제\s*\d+\s*장에\s*제\s*\d+\s*조", rest)
        end = len(rest)
        if stop:
            end = min(end, stop.start())
        if stop2:
            end = min(end, stop2.start())
        block = rest[: min(end, 1200)]
        for pm in re.finditer(r"([①-⑮].+?)(?=[①-⑮]|$)", block, flags=re.S):
            text = re.sub(r"\s+", " ", pm.group(1)).strip()
            if len(text) < 8:
                continue
            if text.endswith("한다"):
                text += "."
            elif not text.endswith(("다.", "다", ".", "요.")):
                text = text.rstrip(" ,·") + "."
            paras.append(text)
    return paras


def extract_article_changes(
    doc_text: str,
    amended: date,
    default_effective: date,
    law_id: str = "",
    law_name: str = "",
) -> list[dict]:
    """개정문에서 조문별 변경·치환·신설 항을 뽑는다."""
    law_default = law_default_effective(doc_text, amended, default_effective)
    special_eff = parse_special_effective(doc_text, amended, law_default)
    changes: dict[str, dict] = {}

    def ensure(jo: str) -> dict:
        if jo not in changes:
            changes[jo] = {
                "articleNo": jo,
                "effectiveDate": special_eff.get(jo, law_default),
                "summaryParts": [],
                "ops": [],
                "newProviso": "",
                "hang": "",
                "patchBody": False,
                "articleTitle": "",
            }
        elif jo in special_eff:
            # 조 단위 특례만 있을 때 갱신 (항·호 특례는 op에 개별 부여)
            changes[jo]["effectiveDate"] = special_eff[jo]
        return changes[jo]

    def stamp_op(jo: str, op: dict) -> dict:
        unit = (op.get("unitLocator") or op.get("locator") or "").strip()
        # locator가 조문번호만이면 단위 없음
        if unit == jo:
            unit = ""
        op["effectiveDate"] = resolve_unit_effective(jo, unit, special_eff, law_default)
        return op

    # 조 번호 자체가 다른 번호로 옮겨가는 지시("제9조의2를 제9조의3으로 하고").
    # 이 번호가 바로 뒤에서 새 내용으로 신설되면, 옛 조문과 새 조문이 서로
    # 다른 내용인데도 같은 번호를 잠깐 같이 쓰게 된다.
    renumbered_away: set[str] = set()
    for m in ARTICLE_RENUMBER_RE.finditer(doc_text):
        from_jo = jo_label(m.group(1), m.group(2))
        to_jo = jo_label(m.group(3), m.group(4))
        if from_jo and to_jo and from_jo != to_jo:
            renumbered_away.add(from_jo)
    for m in ARTICLE_RENUMBER_LIST_RE.finditer(doc_text):
        from_tokens = JO_TOKEN_RE.findall(m.group(1))
        to_tokens = JO_TOKEN_RE.findall(m.group(2))
        if from_tokens and len(from_tokens) == len(to_tokens):
            for (fn, fo), (tn, to_) in zip(from_tokens, to_tokens):
                from_jo = jo_label(fn, fo or None)
                to_jo = jo_label(tn, to_ or None)
                if from_jo and to_jo and from_jo != to_jo:
                    renumbered_away.add(from_jo)

    # 0) 조문 전체 신설 (제목+본문)
    for no, of, _header, title, body in NEW_ARTICLE_RE.findall(doc_text):
        jo = jo_label(no, of or None)
        body = re.sub(r"\s+", " ", body).strip()
        # 항 번호 앞에서 줄바꿈
        body = re.sub(r"\s*([①-⑮])\s*", r"\n\1 ", body).strip()
        body = re.sub(r"\s*(\d+(?:의\d+)?\.)\s*", r"\n\1 ", body).strip()
        entry = ensure(jo)
        entry["articleTitle"] = title.strip()
        # 같은 번호를 옛 조문이 막 비워주고 새 조문이 들어오는 경우 표시
        # (같은 번호라도 서로 다른 내용 — 화면에서 한 조문으로 합치면 안 됨)
        if jo in renumbered_away:
            entry["numberReused"] = True
        entry["ops"].append(
            {
                "kind": "new_article",
                "title": title.strip(),
                "text": body,
                "locator": jo,
                "isNew": True,
            }
        )
        entry["summaryParts"].append(f"{jo}({title.strip()}) 신설")
        entry["patchBody"] = True

    # 0.5) 위치 지정 치환 (부칙·타법개정 포함, 전문 스캔)
    for m in LOCATED_SWAP_RE.finditer(doc_text):
        if law_id and not _located_swap_belongs(doc_text, m.start(), law_id, law_name):
            continue
        no, of, hang, ho, q1, q2, q3, q4 = m.groups()
        jo = jo_label(no, of or None)
        old = (q1 or q2 or "").strip()
        new = (q3 or q4 or "").strip()
        if not old or not new or old == new:
            continue
        unit_loc = ""
        if hang and ho:
            unit_loc = f"제{int(hang)}항제{int(ho)}호"
        elif hang:
            unit_loc = f"제{int(hang)}항"
        elif ho:
            unit_loc = f"제{int(ho)}호"
        entry = ensure(jo)
        dup = any(
            op.get("kind") == "replace"
            and op.get("old") == old
            and op.get("new") == new
            and (op.get("unitLocator") or "") == (unit_loc or "")
            for op in entry["ops"]
        )
        if dup:
            continue
        entry["ops"].append(
            {
                "kind": "replace",
                "old": old,
                "new": new,
                "locator": unit_loc or jo,
                "unitLocator": unit_loc,
                "isNew": False,
            }
        )
        entry["summaryParts"].append(f"「{old[:40]}」→「{new[:40]}」")

    # 1) 단서 신설 (휴게 등)
    for no, of, hang, proviso in PROVISO_NEW_RE.findall(doc_text):
        jo = jo_label(no, of or None)
        proviso = proviso.strip()
        if ("휴게시간" in proviso or "명시적으로 요청" in proviso) and jo != "제54조":
            continue
        entry = ensure(jo)
        entry["newProviso"] = proviso
        entry["hang"] = hang
        entry["patchBody"] = True
        entry["ops"].append(
            {
                "kind": "proviso",
                "text": proviso,
                "locator": f"제{hang}항",
                "isNew": True,
            }
        )
        if jo == "제54조":
            entry["summaryParts"].append(
                "근로시간이 4시간인 경우 근로자가 휴게시간을 이용하지 않겠다고 "
                f"명시적으로 요청하면 휴게를 부여하지 않을 수 있도록 제{hang}항에 단서를 신설함"
            )
        else:
            entry["summaryParts"].append(f"{jo} 제{hang}항에 단서 신설")

    # 2) 조문 청크별 치환·신설·삭제
    for jo, chunk in _split_jo_chunks(doc_text):
        # 부칙·타법 개정 문구는 스킵
        if "다른 법률의 개정" in chunk[:40]:
            continue
        entry = ensure(jo)

        for qm in QUOTE_SWAP_RE.finditer(chunk):
            g1, g2, g3, g4 = qm.groups()
            old = (g1 or g2 or "").strip()
            new = (g3 or g4 or "").strip()
            if not old or not new or old == new:
                continue
            prefix = chunk[: qm.start()]
            # 장 제목 변경은 조문 본문 치환이 아님
            if re.search(r"제\s*\d+\s*장의\s*제목", prefix[-40:]):
                continue
            if re.search(r"제목\s*[\"「]", prefix[-20:]):
                continue
            # 같은 조/같은 항 포함 (제116조: 같은 조 제2항제1호, 같은 항 제2호)
            # 제61조: 같은 항 제1호 및 제2호 → 복수 locator
            unit_locs = resolve_unit_locators(prefix)
            if not unit_locs:
                unit_loc = ""
                for hm in UNIT_HANG_HO_RE.finditer(prefix):
                    unit_loc = f"제{hm.group(1)}항제{hm.group(2)}호"
                if not unit_loc:
                    for hm in UNIT_HO_RE.finditer(prefix):
                        unit_loc = f"제{hm.group(1)}호"
                if not unit_loc:
                    for am in UNIT_HANG_RE.finditer(prefix):
                        unit_loc = f"제{am.group(1)}항"
                unit_locs = [unit_loc] if unit_loc else [""]
            for unit_loc in unit_locs:
                # 동일 치환이라도 단위(항·호)가 다르면 각각 유지
                if any(
                    op.get("kind") == "replace"
                    and op.get("old") == old
                    and op.get("new") == new
                    and (op.get("unitLocator") or "") == (unit_loc or "")
                    for op in entry["ops"]
                ):
                    continue
                entry["ops"].append(
                    {
                        "kind": "replace",
                        "old": old,
                        "new": new,
                        "locator": unit_loc or jo,
                        "unitLocator": unit_loc,
                        "isNew": False,
                    }
                )
                entry["summaryParts"].append(f"「{old[:40]}」→「{new[:40]}」")

        # 「제목 외의 부분을 제1항으로 하고」— 현행 단락 본문을 ①로 승격
        if re.search(r"제목\s*외의\s*부분을\s*제\s*1\s*항으로", chunk):
            entry["ops"].append(
                {
                    "kind": "promote_to_hang1",
                    "locator": jo,
                }
            )
            entry["summaryParts"].append("제목 외의 부분→제1항")

        for para in _extract_new_paragraphs(chunk):
            entry["ops"].append(
                {
                    "kind": "insert",
                    "text": para,
                    "locator": hang_locator_from_text(para, jo),
                    "isNew": True,
                }
            )
            entry["summaryParts"].append(f"{para[:60]}… 신설" if len(para) > 60 else f"{para} 신설")

        # 조 단위 단서 신설: 「같은 조에 단서를 다음과 같이 신설」
        if re.search(r"단서를\s*다음과\s*같이\s*신설", chunk) and not entry.get("newProviso"):
            pm = re.search(
                r"(다만,[^\n]+?(?:없다|아니하다)\.)",
                chunk,
            )
            if pm:
                proviso = re.sub(r"\s+", " ", pm.group(1)).strip()
                entry["newProviso"] = proviso
                entry["ops"].append(
                    {
                        "kind": "proviso",
                        "text": proviso,
                        "locator": jo,
                        "isNew": True,
                    }
                )
                entry["summaryParts"].append(f"{jo} 단서 신설")

        # 각 호 신설: 「같은 항에 각 호를 다음과 같이 신설하며/한다」
        hm = re.search(
            r"(?:같은\s*항에|제\s*(\d+)\s*항에|같은\s*조에)\s*"
            r"각\s*호를\s*다음과\s*같이\s*신설(?:한다\.|하며|하고)",
            chunk,
        )
        if not hm:
            hm = re.search(
                r"각\s*호를\s*다음과\s*같이\s*신설(?:한다\.|하며|하고)",
                chunk,
            )
        if hm:
            hang_loc = resolve_unit_locator(chunk[: hm.start() + 1])
            hang_n = None
            if hm.lastindex and hm.group(1):
                hang_n = int(hm.group(1))
            else:
                m_hang = re.search(r"제\s*(\d+)\s*항", hang_loc or "")
                if m_hang:
                    hang_n = int(m_hang.group(1))
            for text in _extract_trailing_hos(chunk, hm.end()):
                if any(
                    op.get("kind") == "insert" and op.get("text") == text
                    for op in entry["ops"]
                ):
                    continue
                ho_n = text.split(".", 1)[0]
                loc = (
                    f"제{hang_n}항제{ho_n}호"
                    if hang_n is not None
                    else f"{ho_n}호"
                )
                entry["ops"].append(
                    {
                        "kind": "insert",
                        "text": text,
                        "locator": loc,
                        "hang": hang_n,
                        "isNew": True,
                    }
                )
                entry["summaryParts"].append(
                    f"{text[:50]}… 신설" if len(text) > 50 else f"{text} 신설"
                )

        # 각 호 외 부분 단서 삭제
        if re.search(r"각\s*호\s*외의\s*부분\s*단서를\s*삭제", chunk):
            entry["ops"].append(
                {
                    "kind": "delete_proviso",
                    "text": "단서 삭제",
                    "locator": jo,
                    "isNew": False,
                }
            )
            entry["summaryParts"].append(f"{jo} 단서 삭제")

        # 호 삭제: 제1호 및 제2호를 각각 삭제
        del_ho = re.search(
            r"제\s*(\d+)\s*호\s*및\s*제\s*(\d+)\s*호를\s*각각\s*삭제",
            chunk,
        )
        if del_ho:
            hang_loc = resolve_unit_locator(chunk[: del_ho.start()])
            hang_n = None
            m_hang = re.search(r"제\s*(\d+)\s*항", hang_loc or "")
            if m_hang:
                hang_n = int(m_hang.group(1))
            entry["ops"].append(
                {
                    "kind": "delete_ho",
                    "fromHo": int(del_ho.group(1)),
                    "toHo": int(del_ho.group(2)),
                    "hang": hang_n,
                    "locator": (
                        f"제{hang_n}항"
                        if hang_n is not None
                        else jo
                    ),
                    "isNew": False,
                }
            )
            entry["summaryParts"].append(
                f"제{del_ho.group(1)}호·제{del_ho.group(2)}호 삭제"
            )

        # 단일 호 삭제: 같은 항 제4호를 삭제한다
        for del_one in re.finditer(
            r"(?:같은\s*항\s*)?제\s*(\d+)\s*호를\s*삭제한다",
            chunk,
        ):
            # 「제1호 및 제2호를 각각 삭제」와 중복 방지
            if re.search(
                r"제\s*\d+\s*호\s*및\s*제\s*\d+\s*호를\s*각각\s*삭제",
                chunk[max(0, del_one.start() - 30) : del_one.end()],
            ):
                continue
            n = int(del_one.group(1))
            hang_loc = resolve_unit_locator(chunk[: del_one.start()])
            hang_n = None
            m_hang = re.search(r"제\s*(\d+)\s*항", hang_loc or "")
            if m_hang:
                hang_n = int(m_hang.group(1))
            if any(
                op.get("kind") == "delete_ho"
                and int(op.get("fromHo") or 0) <= n <= int(op.get("toHo") or 0)
                and op.get("hang") == hang_n
                for op in entry["ops"]
            ):
                continue
            loc = f"제{hang_n}항제{n}호" if hang_n is not None else f"제{n}호"
            entry["ops"].append(
                {
                    "kind": "delete_ho",
                    "fromHo": n,
                    "toHo": n,
                    "hang": hang_n,
                    "locator": loc,
                    "isNew": False,
                }
            )
            entry["summaryParts"].append(f"{loc} 삭제")

        # 호 번호 이동: 제3호 및 제4호를 각각 제1호 및 제2호로
        renum_ho = re.search(
            r"제\s*(\d+)\s*호\s*및\s*제\s*(\d+)\s*호를\s*각각\s*"
            r"제\s*(\d+)\s*호\s*및\s*제\s*(\d+)\s*호로",
            chunk,
        )
        if renum_ho:
            entry["ops"].append(
                {
                    "kind": "renumber_ho",
                    "fromStart": int(renum_ho.group(1)),
                    "fromEnd": int(renum_ho.group(2)),
                    "toStart": int(renum_ho.group(3)),
                    "toEnd": int(renum_ho.group(4)),
                    "locator": jo,
                }
            )
            entry["summaryParts"].append(
                f"제{renum_ho.group(1)}·{renum_ho.group(2)}호→"
                f"제{renum_ho.group(3)}·{renum_ho.group(4)}호"
            )

        del_hang = re.search(r"제\s*(\d+)\s*항을\s*삭제한다", chunk)
        if del_hang or "제2항을 삭제한다" in chunk:
            hang_n = int(del_hang.group(1)) if del_hang else 2
            mark = N_TO_CIRCLE.get(hang_n, "②")
            entry["ops"].append(
                {
                    "kind": "delete_mark",
                    "hang": hang_n,
                    "text": f"{mark} 삭제",
                    "locator": f"제{hang_n}항",
                    "isNew": False,
                }
            )
            entry["summaryParts"].append(f"제{hang_n}항 삭제")

        # 항 번호 이동 지시 (제60조: 5~7항 → 6~8항)
        renum = re.search(
            r"제\s*(\d+)\s*항부터\s*제\s*(\d+)\s*항까지를\s*각각\s*제\s*(\d+)\s*항부터\s*제\s*(\d+)\s*항까지로",
            chunk,
        )
        if renum:
            entry["ops"].append(
                {
                    "kind": "renumber",
                    "fromStart": int(renum.group(1)),
                    "fromEnd": int(renum.group(2)),
                    "toStart": int(renum.group(3)),
                    "toEnd": int(renum.group(4)),
                }
            )
            entry["summaryParts"].append(
                f"제{renum.group(1)}~{renum.group(2)}항→"
                f"제{renum.group(3)}~{renum.group(4)}항"
            )

        # 단일 항 이동: 제6항을 제9항으로 하고 (제19조 방학 육아휴직 신설 전형)
        renum_one = re.search(
            r"제\s*(\d+)\s*항을\s*제\s*(\d+)\s*항으로",
            chunk,
        )
        if renum_one:
            fs, ts = int(renum_one.group(1)), int(renum_one.group(2))
            if fs != ts and not any(
                op.get("kind") == "renumber"
                and op.get("fromStart") == fs
                and op.get("toStart") == ts
                for op in entry["ops"]
            ):
                entry["ops"].append(
                    {
                        "kind": "renumber",
                        "fromStart": fs,
                        "fromEnd": fs,
                        "toStart": ts,
                        "toEnd": ts,
                    }
                )
                entry["summaryParts"].append(f"제{fs}항→제{ts}항")

    # 요약이 전혀 없는 빈 엔트리 제거, ops만 있어도 유지
    results = []
    for jo, data in changes.items():
        for op in data["ops"]:
            stamp_op(jo, op)
        if data["ops"]:
            data["effectiveDate"] = min(
                op.get("effectiveDate") or data["effectiveDate"] for op in data["ops"]
            )
        if not data["ops"] and not data["summaryParts"]:
            continue
        if not data["summaryParts"] and data["ops"]:
            data["summaryParts"].append(f"{jo} 관련 규정이 개정됨")
        results.append(
            {
                "articleNo": jo,
                "articleTitle": data.get("articleTitle") or "",
                "effectiveDate": data["effectiveDate"],
                "summary": " ".join(dict.fromkeys(data["summaryParts"]))[:280],
                "newProviso": data.get("newProviso") or "",
                "hang": data.get("hang") or "",
                "patchBody": bool(data.get("patchBody") or data.get("ops")),
                "ops": data.get("ops") or [],
                "numberReused": bool(data.get("numberReused")),
            }
        )
    return results


def looks_like_stub_body(body: str) -> bool:
    text = (body or "").strip()
    if not text:
        return True
    if len(text) < 80:
        return True
    lines = [ln.strip() for ln in text.split("\n") if ln.strip()]
    return all(
        len(ln) < 140 and (("<개정" in ln) or ("<신설" in ln) or ("삭제" in ln))
        for ln in lines
    )


def find_article(articles_db: dict, law_id: str, tier_key: str, article_no: str) -> dict | None:
    pack = articles_db.get(law_id) or {}
    for art in pack.get(tier_key) or []:
        if re.sub(r"\s+", "", art.get("no") or "") == re.sub(r"\s+", "", article_no):
            return art
    return None


def ensure_article(
    articles_db: dict,
    law_id: str,
    tier_key: str,
    article_no: str,
    title: str = "",
) -> dict:
    art = find_article(articles_db, law_id, tier_key, article_no)
    resolved_title = (title or ARTICLE_TITLES.get((law_id, article_no), "")).strip()
    if art:
        if not (art.get("title") or "").strip() and resolved_title:
            art["title"] = resolved_title
        return art
    pack = articles_db.setdefault(law_id, {"statute": [], "decree": [], "rule": [], "meta": {}})
    lst = pack.setdefault(tier_key, [])
    num = re.sub(r"[^0-9의]", "", article_no)
    art = {
        "id": f"{law_id}-{tier_key}-{num}",
        "no": article_no,
        "title": resolved_title,
        "body": "",
    }
    lst.append(art)
    return art


def find_containing_unit(body: str, needle: str) -> tuple[str, int, int] | None:
    """needle을 포함하는 최소 단위(호→항→줄)를 반환."""
    if not needle or needle not in body:
        return None

    def _clip(m: re.Match[str]) -> tuple[str, int, int]:
        raw = m.group(0)
        start, end = m.start(), m.end()
        # 정규식이 잡은 끝 개행은 본문 줄바꿈 유지용으로 end에서 제외
        while end > start and body[end - 1] in "\r\n":
            end -= 1
        unit = body[start:end].rstrip()
        return unit, start, end

    # 1) 원자 단위(항 본문 / 각 호) 우선 — 항 전체+호를 한 덩어리로 잡지 않음
    for loc, unit, start, end in iter_atomic_units(body):
        if needle in unit:
            return unit, start, end

    for m in re.finditer(r"(?ms)^(\d+)\.\s+.*?(?=^\d+\.\s|^[①-⑮]|\Z)", body):
        if needle in m.group(0):
            return _clip(m)
    for m in re.finditer(r"(?ms)^([①-⑮]).*?(?=^[①-⑮]|\Z)", body):
        if needle in m.group(0):
            return _clip(m)
    idx = body.find(needle)
    if idx < 0:
        return None
    line_start = body.rfind("\n", 0, idx) + 1
    line_end = body.find("\n", idx)
    if line_end < 0:
        line_end = len(body)
    unit = body[line_start:line_end].rstrip()
    return unit, line_start, line_end


def iter_atomic_units(body: str) -> list[tuple[str, str, int, int]]:
    """조문을 항 본문(각 호 외)과 각 호로 쪼갠다.

    제61조처럼 ①·①의 1·2호·②만 개정되고 ②의 1·2호는 그대로인 경우,
    음영을 바뀐 단위에만 걸기 위함.
    반환: (locator, text, start, end)
    """
    text = (body or "").replace("\r\n", "\n")
    if not text.strip():
        return []
    out: list[tuple[str, str, int, int]] = []
    for hm in re.finditer(r"(?ms)^([①-⑮])(.*?)(?=^[①-⑮]|\Z)", text):
        mark = hm.group(1)
        hang_n = CIRCLE_TO_N.get(mark)
        if hang_n is None:
            continue
        block = hm.group(0)
        block_start = hm.start()
        # 항 본문: 첫 줄(및 호 시작 전 연속 줄) / 호: ^N.
        parts: list[tuple[str, int, int]] = []  # kind lead|ho, rel_start, rel_end
        rel = 0
        lines = block.split("\n")
        idxs: list[tuple[int, str]] = []
        cursor = 0
        for ln in lines:
            idxs.append((cursor, ln))
            cursor += len(ln) + 1
        lead_upto = len(idxs)
        for i, (_off, ln) in enumerate(idxs):
            if i > 0 and re.match(r"^\d+(?:의\d+)?\.\s*", ln):
                lead_upto = i
                break
        if lead_upto > 0:
            lead_start = idxs[0][0]
            last_off, last_ln = idxs[lead_upto - 1]
            lead_end = last_off + len(last_ln)
            lead = block[lead_start:lead_end].rstrip()
            if lead:
                out.append(
                    (
                        f"제{hang_n}항",
                        lead,
                        block_start + lead_start,
                        block_start + lead_start + len(lead),
                    )
                )
        i = lead_upto
        while i < len(idxs):
            off, ln = idxs[i]
            if not re.match(r"^\d+(?:의\d+)?\.\s*", ln):
                i += 1
                continue
            ho = ln.split(".", 1)[0]
            j = i + 1
            end_off = off + len(ln)
            while j < len(idxs) and not re.match(r"^\d+(?:의\d+)?\.\s*", idxs[j][1]):
                end_off = idxs[j][0] + len(idxs[j][1])
                j += 1
            unit = block[off:end_off].rstrip()
            out.append(
                (
                    f"제{hang_n}항제{ho}호",
                    unit,
                    block_start + off,
                    block_start + off + len(unit),
                )
            )
            i = j
    if out:
        return out

    # 항 기호(①…) 없는 조문(제110조·제114조 등): 머리말 + 1. 2. 호 단위
    # (통째로 잡으면 미개정 호까지 노란 음영·전후 합성이 깨짐)
    idxs: list[tuple[int, str]] = []
    cursor = 0
    for ln in text.split("\n"):
        idxs.append((cursor, ln))
        cursor += len(ln) + 1
    lead_upto = len(idxs)
    for i, (_off, ln) in enumerate(idxs):
        if re.match(r"^\d+(?:의\d+)?\.\s*", ln):
            lead_upto = i
            break
    if 0 < lead_upto < len(idxs):
        lead_start = idxs[0][0]
        last_off, last_ln = idxs[lead_upto - 1]
        lead_end = last_off + len(last_ln)
        lead = text[lead_start:lead_end].rstrip()
        if lead:
            out.append(("", lead, lead_start, lead_start + len(lead)))
        i = lead_upto
        while i < len(idxs):
            off, ln = idxs[i]
            if not re.match(r"^\d+(?:의\d+)?\.\s*", ln):
                i += 1
                continue
            ho = ln.split(".", 1)[0]
            j = i + 1
            end_off = off + len(ln)
            while j < len(idxs) and not re.match(
                r"^\d+(?:의\d+)?\.\s*", idxs[j][1]
            ):
                end_off = idxs[j][0] + len(idxs[j][1])
                j += 1
            unit = text[off:end_off].rstrip()
            out.append((f"제{ho}호", unit, off, off + len(unit)))
            i = j
    if not out and text.strip():
        stripped = text.strip()
        start = text.find(stripped)
        out.append(("", stripped, start, start + len(stripped)))
    return out


def atomic_units_containing(body: str, needle: str) -> list[tuple[str, str]]:
    """needle이 들어 있는 원자 단위만 (locator, text)."""
    if not needle:
        return []
    return [(loc, unit) for loc, unit, _s, _e in iter_atomic_units(body) if needle in unit]


# 휴게 단서 문구 변형(법제처 개정문·조문특례 표기가 조금씩 다름)
_REST_PROVISO_RE = re.compile(
    r"\s*다만,\s*근로시간이\s*4시간인\s*경우로서\s*근로자가\s*"
    r"(?:휴게시간을\s*이용하지|이를\s*사용하지)\s*아니할\s*것을\s*"
    r"명시적으로\s*요청(?:한\s*때에는|하는\s*경우에는)\s*그러하지\s*아니하다\.\s*"
)


def _strip_rest_proviso(text: str) -> str:
    t = re.sub(r"\s*<개정[^>]*>\s*", " ", text)
    t = _REST_PROVISO_RE.sub(" ", t)
    t = re.sub(r"\s+", " ", t).strip().rstrip(".")
    return (t + ".") if t else ""


def attach_proviso_to_body(
    body: str, proviso: str, hang: int | str = 1
) -> str:
    """본문 지정 항(기본 ①)에 단서를 붙인다.

    예전 로직은 '처한다.' 뒤에만 붙여 제54조(주어야 한다.) 등에서
    단서가 빠지고 연혁 태그만 붙는 오류가 있었다.
    """
    proviso = (proviso or "").strip()
    if not proviso:
        return body or ""
    if proviso in (body or ""):
        return body
    try:
        hang_n = int(str(hang).strip() or "1")
    except ValueError:
        hang_n = 1
    mark = N_TO_CIRCLE.get(hang_n, "①")
    text = body or ""

    m = re.search(rf"(?ms)^({re.escape(mark)}.*?)(?=^[①-⑮]|\Z)", text)
    if m:
        block = m.group(1).rstrip()
        if proviso in block:
            return text
        if re.search(r"\.\s*<", block):
            new_block = re.sub(
                r"(\.)(\s*<)", r"\1 " + proviso + r"\2", block, count=1
            )
        elif "." in block:
            new_block = re.sub(r"(\.)", r"\1 " + proviso, block, count=1)
        else:
            new_block = block + " " + proviso
        tail = text[m.end() :]
        head = text[: m.start()]
        joiner = "\n" if tail and not new_block.endswith("\n") else ""
        return head + new_block + joiner + tail

    # 벌칙형(처한다.) 또는 첫 문장 끝
    if re.search(r"처한다\.\s*<", text):
        return re.sub(
            r"(처한다\.)(\s*<)", r"\1 " + proviso + r"\2", text, count=1
        )
    if "처한다." in text:
        return text.replace("처한다.", "처한다. " + proviso, 1)
    if "." in text:
        return re.sub(r"(\.)", r"\1 " + proviso, text, count=1)
    return (text.rstrip() + " " + proviso).strip()


def apply_proviso_to_article(art: dict, proviso: str, amended: date) -> tuple[str, dict]:
    body = art.get("body") or ""
    lines = body.split("\n") if body else [""]
    first = lines[0] if lines else ""
    before = _strip_rest_proviso(first) if first else "해당 문구 없음(신설)"
    hist = hist_tag(amended, "개정")
    if first and "명시적으로 요청" not in first:
        new_first = before.rstrip(".") + ". " + proviso.strip() + " " + hist
    elif first:
        new_first = _strip_rest_proviso(first).rstrip(".") + ". " + proviso.strip() + " " + hist
        before = _strip_rest_proviso(re.sub(r"다만,.+$", "", first))
    else:
        new_first = "① " + proviso.strip() + " " + hist
        before = "해당 항 없음(신설)"
    lines[0] = new_first
    new_body = "\n".join([x for x in lines if x is not None])
    # 항 단위 전체 하이라이트
    phrase = {
        "text": new_first,
        "beforeText": before if before.startswith("①") or "해당" in before else (
            first.split("다만")[0].strip() if first else before
        ),
        "isNew": True,
        "historyKind": "개정",
        "historyDates": [to_iso(amended)],
        "locator": f"{art.get('no')} ①항",
        "beforeNote": "",
    }
    return new_body, phrase


def insert_hang_at_position(body: str, para: str) -> str:
    """항(①~⑮) 신설 문구를 번호 순서상 올바른 위치에 삽입한다."""
    para = para.strip()
    if not para:
        return body
    mark = para[0] if para[0] in CIRCLE_TO_N else ""
    if not mark:
        return (body.rstrip() + "\n" + para).strip() if body.strip() else para

    # 같은 항이 있으면 해당 블록만 교체
    if re.search(rf"(?m)^{re.escape(mark)}", body or ""):
        return re.sub(
            rf"(?ms)^{re.escape(mark)}.*?(?=^[①-⑮]|\Z)",
            para + "\n",
            body,
            count=1,
        ).strip()

    n = CIRCLE_TO_N[mark]
    # 번호가 더 큰 항 앞에 삽입 (④ 다음·⑥ 앞 → ⑤)
    for m in re.finditer(r"(?m)^([①-⑮])", body or ""):
        hn = CIRCLE_TO_N.get(m.group(1), 0)
        if hn > n:
            head = body[: m.start()].rstrip()
            tail = body[m.start() :].lstrip()
            return (head + "\n" + para + "\n" + tail).strip()
    return ((body or "").rstrip() + "\n" + para).strip()


def normalize_hang_order(body: str) -> str:
    """①~⑮ 항 블록을 번호순으로 정렬(호는 해당 항 안에 유지)."""
    text = (body or "").replace("\r\n", "\n")
    if not text.strip():
        return text
    first = re.search(r"(?m)^[①-⑮]", text)
    if not first:
        return text.strip()
    preamble = text[: first.start()].rstrip()
    blocks: dict[int, str] = {}
    for m in re.finditer(r"(?ms)^([①-⑮]).*?(?=^[①-⑮]|\Z)", text):
        n = CIRCLE_TO_N.get(m.group(1))
        if n is None:
            continue
        blocks[n] = m.group(0).rstrip()
    ordered = [blocks[k] for k in sorted(blocks.keys())]
    if preamble:
        return (preamble + "\n" + "\n".join(ordered)).strip()
    return "\n".join(ordered).strip()


def hang_locator_from_text(text: str, fallback: str = "") -> str:
    t = (text or "").lstrip()
    if t and t[0] in CIRCLE_TO_N:
        base = f"제{CIRCLE_TO_N[t[0]]}항"
        # fallback에 호가 있으면 항+호 유지
        if "호" in (fallback or ""):
            return fallback
        return base
    if re.match(r"^\d+(?:의\d+)?\.", t):
        ho_label = t.split(".", 1)[0]
        hm = re.search(r"제\s*(\d+)\s*항", fallback or "")
        if hm:
            return f"제{hm.group(1)}항제{ho_label}호"
        # 호 단위는 번호 표기를 우선 (제2조 안의 14. → 14호)
        return ho_label + "호"
    return fallback


def _pending_phrases_only(
    art: dict,
    ops: list[dict],
    amended: date,
    effective: date,
) -> list[dict]:
    """시행 전 개정: 본문 미변경. 표기(text)=개정 후, beforeText=개정 전."""
    body = art.get("body") or ""
    phrases: list[dict] = []
    amd = to_iso(amended)
    eff = to_iso(effective)
    hist_rev = hist_tag(amended, "개정")
    hist_new = hist_tag(amended, "신설")
    has_renumber = any(op.get("kind") == "renumber" for op in ops)
    # proviso/renumber_ho 만 전문 병합 구조개정.
    # insert·delete_ho 는 단위 음영을 유지(제116조 같은 조 제2항제1호 등).
    structural = any(
        op.get("kind") in ("proviso", "delete_proviso", "renumber_ho")
        for op in ops
    )
    folded_inserts: set[int] = set()

    def _hang_n_from_loc(loc: str) -> int | None:
        m = re.search(r"제\s*(\d+)\s*항", loc or "")
        if m:
            return int(m.group(1))
        for ch, n in CIRCLE_TO_N.items():
            if ch in (loc or ""):
                return n
        return None

    has_promote = any(op.get("kind") == "promote_to_hang1" for op in ops)

    def _maybe_promote_hang1(before_unit: str, after_unit: str, loc: str) -> tuple[str, str]:
        """제목 외 → 제1항: 개정 후 표기에만 ①을 붙이고 locator를 제1항으로."""
        if not has_promote:
            return after_unit, loc
        if before_unit.lstrip()[:1] in CIRCLE_TO_N:
            return after_unit, loc
        au = after_unit.lstrip()
        if not au.startswith("①"):
            au = "① " + au
        return au, "제1항"

    def _fold_inserts_into(
        after_unit: str, hang_n: int | None, target_eff: date | None = None
    ) -> str:
        if hang_n is None:
            return after_unit
        parts = [after_unit.rstrip()]
        for i, op in enumerate(ops):
            if op.get("kind") != "insert" or i in folded_inserts:
                continue
            if _hang_n_from_loc(str(op.get("locator") or "")) != hang_n:
                continue
            # 시행일이 다른 호 신설은 합치지 않음 (제116조 제1항제2호 vs 제1호)
            op_eff = op.get("effectiveDate")
            if (
                target_eff is not None
                and isinstance(op_eff, date)
                and op_eff != target_eff
            ):
                continue
            raw = re.sub(r"\s*<신설[^>]*>\s*", "", (op.get("text") or "")).strip()
            if not raw:
                continue
            if hist_new not in raw and hist_rev not in raw:
                raw = raw.rstrip() + " " + hist_new
            parts.append(raw)
            folded_inserts.add(i)
        return "\n".join(parts)

    def _eff_for(op: dict | None = None) -> str:
        if op and op.get("effectiveDate"):
            d = op["effectiveDate"]
            return to_iso(d) if isinstance(d, date) else str(d)[:10]
        return eff

    replace_hits: list[tuple[str, str, str]] = []  # before_unit, after_unit, loc

    for op_i, op in enumerate(ops):
        kind = op.get("kind")
        if kind in ("renumber_ho", "delete_ho", "delete_proviso", "promote_to_hang1"):
            continue
        if kind == "renumber":
            fs = int(op.get("fromStart") or 0)
            fe = int(op.get("fromEnd") or fs)
            ts = int(op.get("toStart") or 0)
            if not fs or not ts:
                continue
            for src in range(fe, fs - 1, -1):
                dst = ts + (src - fs)
                sc, dc = N_TO_CIRCLE.get(src), N_TO_CIRCLE.get(dst)
                if not sc or not dc or sc not in body:
                    continue
                unit_info = find_containing_unit(body, sc)
                before_unit = unit_info[0] if unit_info else sc
                after_unit = re.sub(
                    rf"^{re.escape(sc)}", dc, before_unit, count=1
                )
                if after_unit == before_unit:
                    continue
                after_unit = append_hist_date(after_unit, amended)
                phrases.append(
                    {
                        "text": after_unit,
                        "beforeText": before_unit,
                        "isNew": False,
                        "historyKind": "개정",
                        "historyDates": [amd],
                        "locator": f"제{src}항→제{dst}항",
                        "amendedDate": amd,
                        "effectiveDate": _eff_for(op),
                        "beforeNote": f"시행 후 제{dst}항으로 이동",
                        "pending": True,
                        "compareBefore": strip_hist_tags(before_unit),
                        "compareAfter": strip_hist_tags(after_unit),
                    }
                )
            continue
        if kind == "proviso":
            phrases.append(
                {
                    "text": op.get("text") or "",
                    "beforeText": "해당 단서 없음(신설)",
                    "isNew": True,
                    "historyKind": "개정",
                    "historyDates": [amd],
                    "locator": op.get("locator") or f"{art.get('no')} ①항",
                    "amendedDate": amd,
                    "effectiveDate": eff,
                    "beforeNote": "",
                    "pending": True,
                    "compareBefore": "해당 단서 없음(신설)",
                    "compareAfter": op.get("text") or "",
                    "skipHighlight": structural,
                }
            )
        elif kind == "new_article":
            title = (op.get("title") or "").strip()
            if title and not (art.get("title") or "").strip():
                art["title"] = title
            para = (op.get("text") or "").strip()
            phrases.append(
                {
                    "text": para,
                    "beforeText": "해당 조 없음(신설)",
                    "isNew": True,
                    "historyKind": "신설",
                    "historyDates": [amd],
                    "locator": op.get("locator") or art.get("no"),
                    "amendedDate": amd,
                    "effectiveDate": eff,
                    "beforeNote": "",
                    "pending": True,
                    "compareBefore": "해당 조 없음(신설)",
                    "compareAfter": para,
                }
            )
        elif kind == "replace":
            # 항 번호 이동과 함께 온 치환은 현행 구조와 어긋나 음영 제외(비교 카드만)
            if has_renumber:
                old, new = op.get("old") or "", op.get("new") or ""
                phrases.append(
                    {
                        "text": new,
                        "beforeText": old,
                        "isNew": False,
                        "historyKind": "개정",
                        "historyDates": [amd],
                        "locator": op.get("unitLocator") or op.get("locator") or art.get("no"),
                        "amendedDate": amd,
                        "effectiveDate": eff,
                        "beforeNote": "",
                        "pending": True,
                        "skipHighlight": True,
                        "compareBefore": old,
                        "compareAfter": new,
                    }
                )
                continue
            old, new = op.get("old") or "", op.get("new") or ""
            if not old or not new or old == new:
                continue

            # 조문 전문 음영 금지. old가 들어 있는 항 본문·호만 노란색.
            # (제61조: ①·①1·2호·②만, 미변경 ②1·2호는 제외)
            # unitLocator가 있으면 그 단위만 (제116조 근로감독관이 1호·4호에 동시 존재)
            # 제N항(각 호 외)은 항 본문만 — 자식 호로 확산하지 않음
            atomic_hits = atomic_units_containing(body, old)
            want_loc = (op.get("unitLocator") or "").strip()
            if want_loc:
                filtered = [
                    (loc, unit)
                    for loc, unit in atomic_hits
                    if loc == want_loc
                ]
                if filtered:
                    atomic_hits = filtered
                else:
                    atomic_hits = []
            if atomic_hits:
                for loc, before_unit in atomic_hits:
                    before_clean = strip_hist_tags(before_unit)
                    after_raw = fix_josa_after_jo_replace(
                        safe_text_replace(before_unit, old, new), new
                    )
                    after_unit = append_hist_date(after_raw, amended)
                    after_unit, loc = _maybe_promote_hang1(before_unit, after_unit, loc)
                    after_clean = strip_hist_tags(after_unit)
                    if before_clean == after_clean:
                        continue
                    hang_n = _hang_n_from_loc(loc)
                    if (
                        hang_n is not None
                        and "호" not in (loc or "")
                        and after_unit.lstrip()[:1] in CIRCLE_TO_N
                    ):
                        after_unit = _fold_inserts_into(
                            after_unit,
                            hang_n,
                            op.get("effectiveDate")
                            if isinstance(op.get("effectiveDate"), date)
                            else None,
                        )
                        after_clean = strip_hist_tags(after_unit)
                    replace_hits.append((before_unit, after_unit, loc))
                    if not structural:
                        phrases.append(
                            {
                                "text": after_unit,
                                "beforeText": before_unit,
                                "isNew": False,
                                "historyKind": "개정",
                                "historyDates": [amd],
                                "locator": loc or art.get("no") or "",
                                "amendedDate": amd,
                                "effectiveDate": eff,
                                "beforeNote": "",
                                "pending": True,
                                "compareBefore": before_clean,
                                "compareAfter": after_clean,
                            }
                        )
                continue

            unit_info = find_containing_unit(body, old)
            if unit_info:
                before_unit, _, _ = unit_info
                before_clean = strip_hist_tags(before_unit)
                after_raw = fix_josa_after_jo_replace(
                    safe_text_replace(before_unit, old, new, count=1), new
                )
                after_unit = append_hist_date(after_raw, amended)
                loc = op.get("unitLocator") or hang_locator_from_text(
                    before_unit, op.get("locator") or art.get("no") or ""
                )
                after_unit, loc = _maybe_promote_hang1(before_unit, after_unit, loc)
                # 항 본문(①…) 치환이면 같은 항 각 호 신설을 음영 블록에 합침
                hang_n = _hang_n_from_loc(loc)
                if (
                    hang_n is not None
                    and "호" not in (loc or "")
                    and after_unit.lstrip()[:1] in CIRCLE_TO_N
                ):
                    after_unit = _fold_inserts_into(
                        after_unit,
                        hang_n,
                        op.get("effectiveDate")
                        if isinstance(op.get("effectiveDate"), date)
                        else None,
                    )
                after_clean = strip_hist_tags(after_unit)
                replace_hits.append((before_unit, after_unit, loc))
                if not structural:
                    phrases.append(
                        {
                            "text": after_unit,  # 개정 후(+연혁) — 화면 노란 음영
                            "beforeText": before_unit,  # 본문 매칭용(연혁 포함, 잔여 태그 방지)
                            "isNew": False,
                            "historyKind": "개정",
                            "historyDates": [amd],
                            "locator": loc,
                            "amendedDate": amd,
                            "effectiveDate": eff,
                            "beforeNote": "",
                            "pending": True,
                            "compareBefore": before_clean,
                            "compareAfter": after_clean,
                        }
                    )
            else:
                phrases.append(
                    {
                        "text": new,
                        "beforeText": old,
                        "isNew": False,
                        "historyKind": "개정",
                        "historyDates": [amd],
                        "locator": op.get("unitLocator") or op.get("locator") or art.get("no"),
                        "amendedDate": amd,
                        "effectiveDate": eff,
                        "beforeNote": "",
                        "pending": True,
                        "compareBefore": old,
                        "compareAfter": new,
                        "skipHighlight": structural,
                    }
                )
        elif kind == "insert":
            if op_i in folded_inserts:
                continue
            para = (op.get("text") or "").strip()
            if hist_new not in para and hist_rev not in para:
                para = para.rstrip() + " " + hist_new
            loc = hang_locator_from_text(para, op.get("locator") or art.get("no") or "")
            # ①②… 항 신설·1. 2. 호 신설은 화면 음영. 그 외만 비교 카드용으로 제외
            lead = para.lstrip()
            unit_insert = bool(
                lead
                and (
                    lead[0] in CIRCLE_TO_N
                    or re.match(r"^\d+(?:의\d+)?\.\s*", lead)
                )
            )
            phrases.append(
                {
                    "text": para,
                    "beforeText": "해당 항·호 없음(신설)",
                    "isNew": True,
                    "historyKind": "신설",
                    "historyDates": [amd],
                    "locator": loc or op.get("locator") or art.get("no") or "",
                    "amendedDate": amd,
                    "effectiveDate": eff,
                    "beforeNote": "",
                    "pending": True,
                    "skipHighlight": not unit_insert,
                    "compareBefore": "해당 항·호 없음(신설)",
                    "compareAfter": re.sub(r"\s*<[^>]+>\s*", "", para).strip(),
                }
            )
        elif kind == "delete_mark":
            hang_n = int(op.get("hang") or 2)
            mark = N_TO_CIRCLE.get(hang_n, "②")
            loc = op.get("locator") or f"제{hang_n}항"
            unit_info = find_containing_unit(body, mark) if mark in body else None
            before_unit = unit_info[0] if unit_info else f"{mark} (삭제 전 항)"
            after_text = f"{mark} 삭제 {hist_rev}".strip()
            phrases.append(
                {
                    "text": after_text,
                    "beforeText": before_unit,
                    "isNew": False,
                    "historyKind": "개정",
                    "historyDates": [amd],
                    "locator": loc,
                    "amendedDate": amd,
                    "effectiveDate": eff,
                    "beforeNote": "",
                    "pending": True,
                    "compareBefore": strip_hist_tags(before_unit)
                    or f"{mark} (삭제 전 항)",
                    "compareAfter": f"{mark} 삭제",
                }
            )

    # 구조 개정(단서·각호 신설 등): 현행 본문은 유지하고,
    # 실제로 바뀐 항·호만 음영(단서 신설이면 해당 항만 — 제54조 ② 오음영 방지)
    if structural and body.strip():
        before_full = body.strip()
        after_full = body
        for op in ops:
            if op.get("kind") == "replace":
                old, new = op.get("old") or "", op.get("new") or ""
                if old and old in after_full:
                    # 인용 토큰은 조 안 복수 출현을 모두 치환
                    after_full = (
                        safe_text_replace(after_full, old, new, count=0)
                        if _is_cite_token(old)
                        else safe_text_replace(after_full, old, new, count=1)
                    )
        proviso_op = next((op for op in ops if op.get("kind") == "proviso"), None)
        proviso = (proviso_op or {}).get("text") or ""
        hang_for_proviso = 1
        if proviso_op:
            hm = re.search(r"제\s*(\d+)\s*항", str(proviso_op.get("locator") or ""))
            if hm:
                hang_for_proviso = int(hm.group(1))
        if proviso and proviso not in after_full:
            after_full = attach_proviso_to_body(
                after_full, proviso, hang=hang_for_proviso
            )
        inserts = [
            re.sub(r"\s*<신설[^>]*>\s*", "", (op.get("text") or "")).strip()
            for op in ops
            if op.get("kind") == "insert"
        ]
        inserts = [t for t in inserts if t]
        if inserts and not re.search(r"(?m)^\d+\.", after_full):
            after_full = after_full.rstrip() + "\n" + "\n".join(inserts)

        # 단서·호 삭제/이동(제44조 등)
        if any(op.get("kind") == "delete_proviso" for op in ops):
            after_full = re.sub(
                r"\s*다만,.+?(?:없다|아니하다)\.",
                "",
                after_full,
                count=1,
            )
        del_ho = next((op for op in ops if op.get("kind") == "delete_ho"), None)
        renum_ho = next((op for op in ops if op.get("kind") == "renumber_ho"), None)
        if del_ho or renum_ho:
            lines = after_full.split("\n")
            head = []
            hos: dict[int, str] = {}
            for ln in lines:
                hm = re.match(r"^(\d+)(?:의\d+)?\.\s*", ln)
                if hm:
                    hos[int(hm.group(1))] = ln
                else:
                    head.append(ln)
            if del_ho:
                for n in range(int(del_ho["fromHo"]), int(del_ho["toHo"]) + 1):
                    hos.pop(n, None)
            if renum_ho:
                fs, fe = int(renum_ho["fromStart"]), int(renum_ho["fromEnd"])
                ts = int(renum_ho["toStart"])
                moved = []
                for n in range(fs, fe + 1):
                    if n in hos:
                        moved.append(hos.pop(n))
                for i, raw in enumerate(moved):
                    new_n = ts + i
                    moved[i] = re.sub(r"^\d+(?:의\d+)?\.", f"{new_n}.", raw, count=1)
                    hos[new_n] = moved[i]
            after_full = "\n".join(
                [ln for ln in head if ln.strip()]
                + [hos[k] for k in sorted(hos.keys())]
            ).strip()

        # 연혁 태그는 변경된 항에만 붙인다(조 말미 ②에 <개정>이 붙는 오류 방지)
        mark_p = N_TO_CIRCLE.get(hang_for_proviso, "①")
        hang_before = ""
        hang_after = ""
        m_before = re.search(
            rf"(?ms)^({re.escape(mark_p)}.*?)(?=^[①-⑮]|\Z)", before_full
        )
        m_after = re.search(
            rf"(?ms)^({re.escape(mark_p)}.*?)(?=^[①-⑮]|\Z)", after_full
        )
        if m_before:
            hang_before = m_before.group(1).rstrip()
        if m_after:
            hang_after = append_hist_date(m_after.group(1).rstrip(), amended)
            after_full = (
                after_full[: m_after.start()]
                + hang_after
                + after_full[m_after.end() :]
            ).strip()
        elif re.search(r"<개정\s*[^>]*>", after_full):
            if f"{amended.year}. {amended.month}. {amended.day}." not in after_full:
                after_full = re.sub(
                    r"<개정\s*([^>]+)>",
                    rf"<개정 \1, {amended.year}. {amended.month}. {amended.day}.>",
                    after_full,
                    count=1,
                )
        else:
            # 항을 못 찾으면 최후 수단으로만 전문 말미에 연혁
            after_full = after_full.rstrip() + " " + hist_rev
        after_full = after_full.strip()
        compare_after = re.sub(r"\s*<[^>]+>\s*", " ", after_full)
        compare_after = re.sub(r"[ \t]+\n", "\n", compare_after).strip()
        compare_before = re.sub(r"\s*<개정[^>]*>\s*", " ", before_full).strip()

        if replace_hits:
            before_unit, after_unit, loc = replace_hits[0]
            # 단서가 있으면 치환 단위(한 줄) 개정 후에 포함 → 음영 범위 확대
            after_show = after_unit
            if proviso and proviso not in after_show:
                after_show = attach_proviso_to_body(
                    after_show, proviso, hang=hang_for_proviso
                )
                after_show = append_hist_date(after_show, amended)
            phrases.insert(
                0,
                {
                    "text": after_show,
                    "beforeText": before_unit,  # 본문 매칭용(연혁 태그 유지)
                    "isNew": False,
                    "historyKind": "개정",
                    "historyDates": [amd],
                    "locator": loc or (art.get("no") or ""),
                    "amendedDate": amd,
                    "effectiveDate": eff,
                    "beforeNote": "",
                    "pending": True,
                    "compareBefore": strip_hist_tags(before_unit),
                    "compareAfter": strip_hist_tags(after_show),
                },
            )
        elif proviso and hang_before and hang_after:
            # 단서만 신설: 해당 항(①)만 노란색 — 미변경 ②는 제외
            phrases.insert(
                0,
                {
                    "text": hang_after,
                    "beforeText": hang_before,
                    "isNew": False,
                    "historyKind": "개정",
                    "historyDates": [amd],
                    "locator": f"제{hang_for_proviso}항",
                    "amendedDate": amd,
                    "effectiveDate": eff,
                    "beforeNote": "",
                    "pending": True,
                    "compareBefore": strip_hist_tags(hang_before),
                    "compareAfter": strip_hist_tags(hang_after),
                },
            )
        elif after_full != before_full:
            phrases.insert(
                0,
                {
                    "text": after_full,
                    "beforeText": before_full,
                    "isNew": False,
                    "historyKind": "개정",
                    "historyDates": [amd],
                    "locator": art.get("no") or "",
                    "amendedDate": amd,
                    "effectiveDate": eff,
                    "beforeNote": "",
                    "pending": True,
                    "compareBefore": compare_before,
                    "compareAfter": compare_after,
                },
            )
    elif structural and not body.strip() and replace_hits:
        # 본문 비어 있으면 치환 단위만이라도
        b, a, loc = replace_hits[0]
        phrases.insert(
            0,
            {
                "text": a,
                "beforeText": b,
                "isNew": False,
                "historyKind": "개정",
                "historyDates": [amd],
                "locator": loc,
                "amendedDate": amd,
                "effectiveDate": eff,
                "beforeNote": "",
                "pending": True,
                "compareBefore": b,
                "compareAfter": a,
            },
        )

    # 삭제·이동만 있는 구조개정(제44조 등): 비교 카드
    for op in ops:
        kind = op.get("kind")
        if kind == "delete_proviso":
            phrases.append(
                {
                    "text": "단서 삭제",
                    "beforeText": "단서 있음(삭제 예정)",
                    "isNew": False,
                    "historyKind": "개정",
                    "historyDates": [amd],
                    "locator": op.get("locator") or art.get("no"),
                    "amendedDate": amd,
                    "effectiveDate": eff,
                    "beforeNote": "",
                    "pending": True,
                    "skipHighlight": True,
                    "compareBefore": "단서 있음(삭제 예정)",
                    "compareAfter": "단서 삭제",
                }
            )
        elif kind == "delete_ho":
            from_ho = int(op.get("fromHo") or 0)
            to_ho = int(op.get("toHo") or from_ho)
            hang_n = op.get("hang")
            if hang_n is None:
                hang_n = _hang_n_from_loc(str(op.get("locator") or ""))
            if from_ho and from_ho == to_ho:
                found = find_ho_in_hang(body, hang_n, from_ho)
                before_unit = found[0] if found else f"{from_ho}."
                loc = (
                    op.get("locator")
                    or (
                        f"제{hang_n}항제{from_ho}호"
                        if hang_n is not None
                        else f"제{from_ho}호"
                    )
                )
                after_text = f"{from_ho}. 삭제 {hist_rev}".strip()
                phrases.append(
                    {
                        # 시행 전: 법제처 본문과 같이 현행 호 문구를 유지하고
                        # UI 는 pendingDelete 로 '삭제예정' 칩·호버(시행 후 삭제) 표시
                        "text": after_text,
                        "beforeText": before_unit,
                        "isNew": False,
                        "pendingDelete": True,
                        "historyKind": "개정",
                        "historyDates": [amd],
                        "locator": loc,
                        "amendedDate": amd,
                        "effectiveDate": eff,
                        "beforeNote": "시행일 이후 이 호는 삭제됩니다.",
                        "pending": True,
                        "compareBefore": strip_hist_tags(before_unit),
                        "compareAfter": f"{from_ho}. 삭제",
                    }
                )
            else:
                phrases.append(
                    {
                        "text": f"제{from_ho}호·제{to_ho}호 삭제",
                        "beforeText": f"제{from_ho}호·제{to_ho}호",
                        "isNew": False,
                        "historyKind": "개정",
                        "historyDates": [amd],
                        "locator": op.get("locator") or art.get("no"),
                        "amendedDate": amd,
                        "effectiveDate": eff,
                        "beforeNote": "",
                        "pending": True,
                        "skipHighlight": True,
                        "compareBefore": f"제{from_ho}호·제{to_ho}호",
                        "compareAfter": f"제{from_ho}호·제{to_ho}호 삭제",
                    }
                )
        elif kind == "renumber_ho":
            phrases.append(
                {
                    "text": (
                        f"제{op.get('fromStart')}·{op.get('fromEnd')}호→"
                        f"제{op.get('toStart')}·{op.get('toEnd')}호"
                    ),
                    "beforeText": f"제{op.get('fromStart')}호·제{op.get('fromEnd')}호",
                    "isNew": False,
                    "historyKind": "개정",
                    "historyDates": [amd],
                    "locator": op.get("locator") or art.get("no"),
                    "amendedDate": amd,
                    "effectiveDate": eff,
                    "beforeNote": "",
                    "pending": True,
                    "skipHighlight": True,
                    "compareBefore": f"제{op.get('fromStart')}호·제{op.get('fromEnd')}호",
                    "compareAfter": (
                        f"제{op.get('toStart')}호·제{op.get('toEnd')}호"
                    ),
                }
            )

    # 항·호별 부칙 시행일을 phrase에 반영
    for ph in phrases:
        loc = (ph.get("locator") or "").strip().replace(" ", "")
        if not loc:
            continue
        best = None
        best_score = -1
        for op in ops:
            if not op.get("effectiveDate"):
                continue
            ol = (
                (op.get("unitLocator") or op.get("locator") or "")
                .strip()
                .replace(" ", "")
            )
            if not ol:
                continue
            score = -1
            if ol == loc:
                score = 3
            elif loc.endswith(ol) or ol.endswith(loc):
                score = 2
            elif ol in loc or loc in ol:
                score = 1
            if score > best_score:
                best_score = score
                best = op.get("effectiveDate")
        if best is not None and best_score >= 2:
            ph["effectiveDate"] = (
                to_iso(best) if isinstance(best, date) else str(best)[:10]
            )

    # 같은 항·같은 개정 전 본문에 replace 가 여러 개면 하나로 병합
    # (제19조 「보호하거나」+「경우에」 → 이중 칩·경우에는는 방지)
    phrases = _merge_same_unit_replace_phrases(phrases, amended)
    return phrases


def _minimal_substitution_expanded(before: str, after: str) -> tuple[str, str] | None:
    """before/after 에서 old→new 추출. 공통접미로 old 가 비는 경우(출산휴가↔출산전후휴가) 좌측 확장."""
    b = strip_hist_tags(before)
    a = strip_hist_tags(after)
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
        old = b[pre : len(b) - suf if suf else len(b)]
        occ = b.count(old) if old else 0
        if old and len(old) >= 2 and occ == 1:
            break
        if old and len(old) >= 8 and occ >= 1:
            break
        pre -= 1
    old = b[pre : len(b) - suf if suf else len(b)]
    neu = a[pre : len(a) - suf if suf else len(a)]
    if not old or not neu or old == neu:
        return None
    return old, neu


def _merge_same_unit_replace_phrases(
    phrases: list[dict], amended: date
) -> list[dict]:
    """동일 locator+beforeText 의 미시행 replace 문구를 순차 치환 1개로 합친다."""
    buckets: dict[tuple[str, str], list[dict]] = {}
    rest: list[dict] = []
    for p in phrases:
        if (
            p.get("isNew")
            or p.get("pendingDelete")
            or p.get("skipHighlight")
            or not p.get("beforeText")
            or (p.get("beforeText") or "").startswith("해당")
        ):
            rest.append(p)
            continue
        key = (
            (p.get("locator") or "").strip(),
            strip_hist_tags(p.get("beforeText") or ""),
        )
        buckets.setdefault(key, []).append(p)

    out = list(rest)
    for (_loc, _before_key), group in buckets.items():
        if len(group) == 1:
            out.append(group[0])
            continue
        base = group[0].get("beforeText") or ""
        after = base
        for p in group:
            sub = _minimal_substitution_expanded(
                p.get("beforeText") or "", p.get("text") or ""
            )
            if not sub:
                continue
            old, neu = sub
            after = safe_text_replace(after, old, neu, count=1)
            after = fix_josa_after_jo_replace(after, neu)
        after = append_hist_date(after, amended)
        if "는는" in after:
            clean = [
                p
                for p in group
                if "는는" not in (p.get("text") or "")
            ]
            out.append(
                max(
                    clean or group,
                    key=lambda p: len(p.get("text") or ""),
                )
            )
            continue
        if strip_hist_tags(after) == strip_hist_tags(base):
            # 병합 실패 시 변경량이 가장 큰 후보
            out.append(
                max(
                    group,
                    key=lambda p: abs(
                        len(p.get("text") or "") - len(p.get("beforeText") or "")
                    ),
                )
            )
            continue
        rep = dict(group[0])
        rep["text"] = after
        rep["compareAfter"] = strip_hist_tags(after)
        rep["compareBefore"] = strip_hist_tags(base)
        out.append(rep)
    return out


def apply_ops_to_article(
    art: dict,
    ops: list[dict],
    amended: date,
    effective: date,
    apply_body: bool = True,
) -> list[dict]:
    """조문 본문에 치환·신설·삭제를 반영. 하이라이트는 호/항 단위 전체.

    apply_body=False(시행일 미도래): 법제처 현행 본문은 유지하고 전·후 비교 phrase만 생성.
    """
    if not apply_body:
        return _pending_phrases_only(art, ops, amended, effective)

    body = art.get("body") or ""
    phrases: list[dict] = []
    amd = to_iso(amended)
    eff = to_iso(effective)
    hist_rev = hist_tag(amended, "개정")
    hist_new = hist_tag(amended, "신설")

    # 제목 외 → 제1항: 시행 반영 시 본문 선두에 ① 부여
    if any(op.get("kind") == "promote_to_hang1" for op in ops):
        if body.strip() and body.lstrip()[:1] not in CIRCLE_TO_N:
            body = "① " + body.lstrip()

    for op in ops:
        if op.get("kind") != "renumber":
            continue
        for src in range(op["fromEnd"], op["fromStart"] - 1, -1):
            dst = op["toStart"] + (src - op["fromStart"])
            sc, dc = N_TO_CIRCLE.get(src), N_TO_CIRCLE.get(dst)
            if sc and dc:
                body = re.sub(rf"(?m)^{re.escape(sc)}", dc, body)

    for op in ops:
        kind = op.get("kind")
        if kind == "renumber":
            continue
        if kind == "proviso":
            body, phrase = apply_proviso_to_article(art, op["text"], amended)
            art["body"] = body
            phrase["amendedDate"] = amd
            phrase["effectiveDate"] = eff
            phrases.append(phrase)
            body = art["body"]
            continue
        if kind == "new_article":
            title = (op.get("title") or "").strip()
            if title:
                art["title"] = title
            para = (op.get("text") or "").strip()
            if hist_new not in para:
                para = para.rstrip() + " " + hist_new
            body = para
            phrases.append(
                {
                    "text": para,
                    "beforeText": "해당 조 없음(신설)",
                    "isNew": True,
                    "historyKind": "신설",
                    "historyDates": [amd],
                    "locator": op.get("locator") or art.get("no"),
                    "amendedDate": amd,
                    "effectiveDate": eff,
                    "beforeNote": "",
                }
            )
            continue
        if kind == "replace":
            old, new = op["old"], op["new"]
            # 이미 eflaw 현행 본문에 반영된 치환은 재적용하지 않음.
            # 다만 전·후 비교 카드는 남겨 빈 카드/유령 스크럽을 막는다.
            if old not in body and new and new in body:
                # 이미 시행·본문 반영됨 → 재치환 없이 개정 후(현행) 음영 + 호버=개정 전
                unit_info = find_containing_unit(body, new)
                loc = op.get("unitLocator") or op.get("locator") or art.get("no")
                if unit_info:
                    after_unit, _, _ = unit_info
                    before_unit = after_unit.replace(new, old, 1)
                    loc = hang_locator_from_text(after_unit, loc or "")
                    after_clean = strip_hist_tags(after_unit)
                    before_clean = strip_hist_tags(before_unit)
                    # 본문 매칭용 text는 실제 단위(연혁 포함 가능)
                    phrases.append(
                        {
                            "text": after_unit.strip(),
                            "beforeText": before_clean,
                            "isNew": False,
                            "historyKind": "개정",
                            "historyDates": [amd],
                            "locator": loc,
                            "amendedDate": amd,
                            "effectiveDate": eff,
                            "beforeNote": "",
                            "pending": False,
                            "compareBefore": before_clean,
                            "compareAfter": after_clean,
                        }
                    )
                else:
                    phrases.append(
                        {
                            "text": new,
                            "beforeText": old,
                            "isNew": False,
                            "historyKind": "개정",
                            "historyDates": [amd],
                            "locator": loc,
                            "amendedDate": amd,
                            "effectiveDate": eff,
                            "beforeNote": "",
                            "pending": False,
                            "compareBefore": old,
                            "compareAfter": new,
                        }
                    )
                continue
            # 인용 번호 일괄 변경: 본문은 전체 치환하되, 음영은 바뀐 항·호만
            if _is_cite_token(old) and body.count(old) > 1:
                atomic_hits = atomic_units_containing(body, old)
                for loc, before_unit in atomic_hits:
                    after_unit = append_hist_date(
                        fix_josa_after_jo_replace(
                            safe_text_replace(before_unit, old, new), new
                        ),
                        amended,
                    )
                    phrases.append(
                        {
                            "text": after_unit,
                            "beforeText": before_unit,
                            "isNew": False,
                            "historyKind": "개정",
                            "historyDates": [amd],
                            "locator": loc or art.get("no") or "",
                            "amendedDate": amd,
                            "effectiveDate": eff,
                            "beforeNote": "",
                            "compareBefore": strip_hist_tags(before_unit),
                            "compareAfter": strip_hist_tags(after_unit),
                        }
                    )
                body = append_hist_date(safe_text_replace(body, old, new), amended)
                continue
            unit_info = find_containing_unit(body, old)
            if unit_info:
                before_unit, start, end = unit_info
                after_unit = safe_text_replace(before_unit, old, new, count=1)
                after_clean = re.sub(r"\s*<개정[^>]*>\s*", " ", after_unit).rstrip()
                after_marked = after_clean + " " + hist_rev
                body = body[:start] + after_marked + body[end:]
                loc = hang_locator_from_text(
                    after_marked,
                    op.get("unitLocator") or op.get("locator") or art.get("no") or "",
                )
                phrases.append(
                    {
                        "text": after_marked,
                        "beforeText": re.sub(r"\s*<개정[^>]*>\s*", " ", before_unit).strip(),
                        "isNew": False,
                        "historyKind": "개정",
                        "historyDates": [amd],
                        "locator": loc,
                        "amendedDate": amd,
                        "effectiveDate": eff,
                        "beforeNote": "",
                    }
                )
            else:
                unit_info = find_containing_unit(body, new)
                loc = op.get("unitLocator") or op.get("locator") or art.get("no")
                if unit_info:
                    after_unit, _, _ = unit_info
                    before_unit = after_unit.replace(new, old, 1)
                    loc = hang_locator_from_text(after_unit, loc or "")
                    phrases.append(
                        {
                            "text": after_unit.strip(),
                            "beforeText": re.sub(r"\s*<개정[^>]*>\s*", " ", before_unit).strip(),
                            "isNew": False,
                            "historyKind": "개정",
                            "historyDates": [amd],
                            "locator": loc,
                            "amendedDate": amd,
                            "effectiveDate": eff,
                            "beforeNote": "",
                        }
                    )
                else:
                    phrases.append(
                        {
                            "text": new,
                            "beforeText": old,
                            "isNew": False,
                            "historyKind": "개정",
                            "historyDates": [amd],
                            "locator": loc,
                            "amendedDate": amd,
                            "effectiveDate": eff,
                            "beforeNote": "",
                        }
                    )
            continue
        if kind == "insert":
            para = op["text"].strip()
            if hist_new not in para and hist_rev not in para:
                para = para.rstrip() + " " + hist_new
            core = re.sub(r"\s*<[^>]+>\s*", "", para).strip()
            body_plain = re.sub(r"\s*<[^>]+>\s*", "", body)
            already = bool(core and core[:24] in body_plain)
            mark = para[0] if para and para[0] in CIRCLE_TO_N else ""
            ho = re.match(r"^(\d+(?:의\d+)?)\.\s*", para)
            if not already:
                if mark:
                    body = insert_hang_at_position(body, para)
                elif ho and body.strip():
                    body = (body.rstrip() + "\n" + para).strip()
                elif not body.strip():
                    body = para
            # 하이라이트는 신설 항/호 자체만 (인접 항과 묶지 않음)
            highlight_text = para
            if mark and body:
                unit = find_containing_unit(body, core[:48] if core else para[:48])
                if unit and unit[0].lstrip()[:1] == mark:
                    highlight_text = unit[0]
            loc = hang_locator_from_text(
                highlight_text, op.get("locator") or art.get("no") or ""
            )
            phrases.append(
                {
                    "text": highlight_text,
                    "beforeText": "해당 항·호 없음(신설)",
                    "isNew": True,
                    "historyKind": "신설",
                    "historyDates": [amd],
                    "locator": loc,
                    "amendedDate": amd,
                    "effectiveDate": eff,
                    "beforeNote": "",
                }
            )
            continue
        if kind == "delete_mark":
            hang_n = int(op.get("hang") or 2)
            mark = N_TO_CIRCLE.get(hang_n, "②")
            loc = op.get("locator") or f"제{hang_n}항"
            unit_info = find_containing_unit(body, mark) if mark in body else None
            if unit_info:
                before_unit, start, end = unit_info
                after_marked = f"{mark} 삭제 {hist_rev}"
                body = body[:start] + after_marked + body[end:]
                phrases.append(
                    {
                        "text": after_marked,
                        "beforeText": before_unit,
                        "isNew": False,
                        "historyKind": "개정",
                        "historyDates": [amd],
                        "locator": loc,
                        "amendedDate": amd,
                        "effectiveDate": eff,
                        "beforeNote": "",
                        "compareBefore": strip_hist_tags(before_unit),
                        "compareAfter": f"{mark} 삭제",
                    }
                )
            else:
                after_marked = f"{mark} 삭제 {hist_rev}"
                body = (body + "\n" + after_marked).strip() if body else after_marked
                phrases.append(
                    {
                        "text": after_marked,
                        "beforeText": f"{mark} (삭제 전 항)",
                        "isNew": False,
                        "historyKind": "개정",
                        "historyDates": [amd],
                        "locator": loc,
                        "amendedDate": amd,
                        "effectiveDate": eff,
                        "beforeNote": "",
                        "compareBefore": f"{mark} (삭제 전 항)",
                        "compareAfter": f"{mark} 삭제",
                    }
                )

    body = normalize_hang_order(body)
    art["body"] = body.strip()
    for ph in phrases:
        if ph["text"] not in art["body"]:
            bare = re.sub(r"\s*<[^>]+>\s*", "", ph["text"]).strip()
            for line in art["body"].split("\n"):
                if bare[:24] and bare[:24] in line:
                    ph["text"] = line.strip()
                    break
            # 항 단위 재매칭
            if ph["text"] not in art["body"] and bare:
                unit = find_containing_unit(art["body"], bare[:40])
                if unit:
                    ph["text"] = unit[0]
                    ph["locator"] = hang_locator_from_text(unit[0], ph.get("locator") or "")
    return phrases


def sync_articles_js(articles_db: dict) -> None:
    try:
        from hydrate_articles import article_sort_key

        for pack in articles_db.values():
            if not isinstance(pack, dict):
                continue
            for tier in ("statute", "decree", "rule"):
                if tier in pack and isinstance(pack[tier], list):
                    pack[tier].sort(key=lambda a: article_sort_key(a.get("no") or ""))
    except Exception:
        pass
    ARTICLES_PATH.write_text(json.dumps(articles_db, ensure_ascii=False, indent=2), encoding="utf-8")
    js = "window.LAW_ARTICLES = " + json.dumps(articles_db, ensure_ascii=False, indent=2) + ";\n"
    ARTICLES_JS_PATH.write_text(js, encoding="utf-8")


def load_seed_articles() -> dict:
    """수동 갱신마다 시드 조문에서 시작해 중복·오염을 막는다."""
    try:
        from hydrate_articles import build_seed_from_full, hydrate_articles_db

        # 전문 캐시로 시드를 매번 재생성(제목·본문 보강, 삭제 없음)
        seed = build_seed_from_full()
        return hydrate_articles_db(json.loads(json.dumps(seed, ensure_ascii=False)))
    except Exception:
        if SEED_PATH.is_file():
            return json.loads(SEED_PATH.read_text(encoding="utf-8"))
        if ARTICLES_PATH.is_file():
            return json.loads(ARTICLES_PATH.read_text(encoding="utf-8"))
        return {}


def enrich_revision_with_articles(
    item: dict,
    doc_text: str,
    articles_db: dict,
    tier_key: str,
    base_date: date | None = None,
) -> list[dict]:
    """하나의 공포 이력을 조문 단위 목록으로 펼친다."""
    try:
        from hydrate_articles import fill_article_from_full, load_full_index

        full_index = load_full_index()
    except Exception:
        full_index = None

    amended = date.fromisoformat(item["amendedDate"])
    default_eff = date.fromisoformat(item["effectiveDate"])
    base = base_date or date.today()
    changes = extract_article_changes(
        doc_text,
        amended,
        default_eff,
        law_id=item.get("lawId") or "",
        law_name=item.get("lawName") or "",
    )
    if not changes:
        return [item]

    expanded = []
    for ch in changes:
        apply_body = ch["effectiveDate"] <= base
        is_new_article_change_early = any(
            op.get("kind") == "new_article" for op in (ch.get("ops") or [])
        )
        # 번호 재사용 + 아직 미시행: 같은 번호의 옛(다른 내용) 조문과
        # articleId를 공유하면 화면에서 두 조문이 한 카드로 합쳐 보인다
        # (예: 제9조의2 옛 "난임치료휴가" 본문 뒤에 신설 "배우자 출산전후휴가"
        # 본문이 이어 붙는 회귀). 시행일이 지나면 전문(eflaw)이 번호를
        # 실제로 분리해 주므로 그 전까지만 별도 id를 쓴다.
        pending_detached = bool(
            is_new_article_change_early and ch.get("numberReused") and not apply_body
        )
        if pending_detached:
            num = re.sub(r"[^0-9의]", "", ch["articleNo"])
            art = {
                "id": f"{item['lawId']}-{tier_key}-{num}-신설예정",
                "no": ch["articleNo"],
                "title": (ch.get("articleTitle") or "").strip(),
                "body": "",
            }
        else:
            art = ensure_article(
                articles_db,
                item["lawId"],
                tier_key,
                ch["articleNo"],
                ARTICLE_TITLES.get((item["lawId"], ch["articleNo"]), ""),
            )
            # 매번 전문(eflaw) 현행 본문으로 리셋 후 비교·음영만 계산
            if full_index is not None:
                fill_article_from_full(art, item["lawId"], tier_key, full_index)
        # 시행된 신설 조만 제목 덮어쓰기 (미시행 신설 제목으로 현행을 바꾸지 않음)
        if apply_body and (ch.get("articleTitle") or "").strip():
            art["title"] = ch["articleTitle"].strip()
        elif not (art.get("title") or "").strip() and (ch.get("articleTitle") or "").strip():
            art["title"] = ch["articleTitle"].strip()
        article_id = art["id"]
        # 신설 조 개정 카드는 새 조문 제목을 표시한다. 조번호 재사용·이동
        # (예: 종전 제9조의2 → 제9조의3, 새 제9조의2 신설)이 있으면 art["title"]은
        # 아직 옛 내용을 가리키므로, 카드 제목에는 개정문이 밝힌 새 제목을 쓴다.
        is_new_article_change = any(
            op.get("kind") == "new_article" for op in (ch.get("ops") or [])
        )
        if is_new_article_change and (ch.get("articleTitle") or "").strip():
            title_name = ch["articleTitle"].strip()
        else:
            title_name = (art.get("title") or "").strip()
        display_title = (
            f"{item['lawName']} {ch['articleNo']}"
            + (f"({title_name})" if title_name else "")
            + " 개정"
        )

        phrases: list[dict] = []
        compare_before = ""
        compare_after = ""
        ops = ch.get("ops") or []

        if ops:
            phrases = apply_ops_to_article(
                art, ops, amended, ch["effectiveDate"], apply_body=apply_body
            )
            # 본문은 항상 전문 현행 유지(재적용 오염 방지). 다만 번호 재사용으로
            # 분리해 둔 미시행 신설 조는 전문에 아직 옛 내용만 있으므로 리셋하지
            # 않는다(그러면 옛 조문 본문이 다시 섞여 들어온다).
            if full_index is not None and not pending_detached:
                fill_article_from_full(art, item["lawId"], tier_key, full_index)
        elif ch.get("newProviso") and ch.get("patchBody") and apply_body:
            new_body, phrase = apply_proviso_to_article(art, ch["newProviso"], amended)
            art["body"] = new_body
            phrase["amendedDate"] = item["amendedDate"]
            phrase["effectiveDate"] = to_iso(ch["effectiveDate"])
            phrases = [phrase]
            if full_index is not None:
                fill_article_from_full(art, item["lawId"], tier_key, full_index)
        elif ch.get("newProviso") and not apply_body:
            phrases = [
                {
                    "text": ch["newProviso"],
                    "beforeText": "해당 단서 없음(신설)",
                    "isNew": True,
                    "historyKind": "개정",
                    "historyDates": [item["amendedDate"]],
                    "locator": f"{ch['articleNo']} ①항",
                    "amendedDate": item["amendedDate"],
                    "effectiveDate": to_iso(ch["effectiveDate"]),
                    "beforeNote": "",
                    "pending": True,
                    "compareBefore": "해당 단서 없음(신설)",
                    "compareAfter": ch["newProviso"],
                }
            ]

        # phrase 중복 제거
        uniq = []
        seen = set()
        for ph in phrases:
            key = (
                (ph.get("text") or "").strip(),
                (ph.get("locator") or "").strip(),
                (ph.get("amendedDate") or ""),
            )
            if key in seen or not key[0]:
                continue
            seen.add(key)
            uniq.append(ph)
        phrases = uniq

        # 본문에 있는 개정 후 문구, 또는 시행 전(본문은 개정 전·표기는 개정 후)인 경우
        body_now = art.get("body") or ""

        def _can_highlight(ph: dict) -> bool:
            if ph.get("skipHighlight"):
                return False
            text = (ph.get("text") or "").strip()
            before = (ph.get("beforeText") or "").strip()
            if text and text in body_now:
                return True
            # 시행 전: 본문에 개정 전이 있으면 화면에서 개정 후로 바꿔 음영
            if ph.get("pending") and before and before in body_now and text:
                return True
            # 항 삭제: before가 연혁 포함 전체 항이면 매칭, 아니면 항 기호만으로도 허용
            if (
                ph.get("pending")
                and text
                and "삭제" in text
                and before
                and (before in body_now or (before[:1] in CIRCLE_TO_N and before[:1] in body_now))
            ):
                return True
            # 미시행 신설 조: 현행 법제처 본문에 조 자체가 없음 → 개정문 전문을 음영으로 채택
            if (
                ph.get("pending")
                and ph.get("isNew")
                and text
                and (
                    not body_now.strip()
                    or before.startswith("해당 조 없음")
                    or before.startswith("해당 항·호 없음")
                    or before.startswith("해당 단서 없음")
                )
            ):
                return True
            return False

        highlight_phrases = [ph for ph in phrases if _can_highlight(ph)]

        if phrases:
            cbs: list[str] = []
            cas: list[str] = []
            for ph in phrases:
                b = (ph.get("compareBefore") or "").strip()
                if not b:
                    b = strip_hist_tags(ph.get("beforeText") or "")
                a = (ph.get("compareAfter") or "").strip()
                if not a:
                    a = strip_hist_tags(ph.get("text") or "")
                if b and b not in cbs:
                    cbs.append(b)
                if a and a not in cas:
                    cas.append(a)
            compare_before = "\n".join(cbs)
            compare_after = "\n".join(cas)
        elif ch.get("newProviso"):
            compare_before = "해당 단서 없음(신설)"
            compare_after = ch["newProviso"]

        # 미시행인데 본문에 없는 치환만 있으면 유령 카드 제외
        # (제52조←제108조 오귀속). 이미 시행되어 개정 후만 본문에 있는 경우는 유지.
        body_check = art.get("body") or ""
        ops_hit = False
        for op in ops:
            kind = op.get("kind")
            if kind in (
                "new_article",
                "proviso",
                "insert",
                "delete_mark",
                "delete_proviso",
                "delete_ho",
                "renumber",
                "renumber_ho",
                "promote_to_hang1",
            ):
                ops_hit = True
                break
            if kind == "replace":
                old, new = op.get("old") or "", op.get("new") or ""
                if old in body_check or (new and new in body_check):
                    ops_hit = True
                    break
        if ch.get("newProviso"):
            ops_hit = True
        if (not apply_body) and (not ops_hit) and (not highlight_phrases):
            continue

        # 부칙 항·호별 시행일이 다르면 카드·칩을 시행일별로 분리
        groups: dict[str, list[dict]] = {}
        for ph in phrases:
            ek = (ph.get("effectiveDate") or to_iso(ch["effectiveDate"]))[:10]
            groups.setdefault(ek, []).append(ph)
        if not groups:
            groups[to_iso(ch["effectiveDate"])] = []

        for eff_iso, group_phrases in sorted(groups.items()):
            group_highlight = [ph for ph in group_phrases if _can_highlight(ph)]
            if (not apply_body) and (not ops_hit) and (not group_highlight) and group_phrases:
                # skipHighlight 만 있는 그룹은 비교용으로라도 유지
                pass
            if (not apply_body) and (not group_highlight) and not any(
                not p.get("skipHighlight") for p in group_phrases
            ):
                if not group_phrases:
                    continue

            cbs: list[str] = []
            cas: list[str] = []
            for ph in group_phrases:
                b = (ph.get("compareBefore") or "").strip()
                if not b:
                    b = strip_hist_tags(ph.get("beforeText") or "")
                a = (ph.get("compareAfter") or "").strip()
                if not a:
                    a = strip_hist_tags(ph.get("text") or "")
                if b and b not in cbs:
                    cbs.append(b)
                if a and a not in cas:
                    cas.append(a)

            locators = []
            for ph in group_phrases:
                if ph.get("locator") and ph["locator"] not in locators:
                    locators.append(ph["locator"])
            if not locators:
                locators = [
                    ch["articleNo"]
                    + (f" 제{ch['hang']}항" if ch.get("hang") else "")
                ]

            try:
                eff_d = date.fromisoformat(eff_iso)
            except ValueError:
                eff_d = ch["effectiveDate"]

            # 이 시행일 그룹에 속한 op만으로 요약 축약
            group_summary_parts = []
            for op in ops:
                od = op.get("effectiveDate")
                oi = to_iso(od) if isinstance(od, date) else str(od or "")[:10]
                if oi and oi != eff_iso:
                    continue
                kind = op.get("kind")
                if kind == "replace":
                    group_summary_parts.append(
                        f"「{(op.get('old') or '')[:24]}」→「{(op.get('new') or '')[:24]}」"
                    )
                elif kind == "insert":
                    t = (op.get("text") or "")[:40]
                    group_summary_parts.append(f"{t}… 신설" if len(op.get("text") or "") > 40 else f"{t} 신설")
                elif kind == "delete_ho":
                    group_summary_parts.append(f"{op.get('locator') or ''} 삭제")
            summary = " ".join(group_summary_parts) if group_summary_parts else ch["summary"]

            id_suffix = f"-{eff_iso}" if len(groups) > 1 else ""
            child = dict(item)
            child.update(
                {
                    "id": f"{item['id']}-{ch['articleNo']}{id_suffix}",
                    "parentId": item["id"],
                    "title": display_title,
                    "articleNo": ch["articleNo"],
                    "articleTitle": title_name,
                    "effectiveDate": eff_iso,
                    "summary": summary,
                    "briefSummary": summary[:90] + ("…" if len(summary) > 90 else ""),
                    "status": "시행예정" if eff_d > date.today() else item.get("status"),
                    "mentionedArticles": [ch["articleNo"]],
                    "locators": locators,
                    "articleIds": [article_id],
                    "highlights": (
                        [{"articleId": article_id, "phrases": group_highlight}]
                        if group_highlight
                        else []
                    ),
                    "articleLevel": True,
                    "compareBefore": "\n".join(cbs),
                    "compareAfter": "\n".join(cas),
                    "bodyApplied": eff_d <= base,
                }
            )
            expanded.append(child)
    return expanded
