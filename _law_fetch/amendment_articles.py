# -*- coding: utf-8 -*-
"""개정문(lsRvsDocListP)에서 조문 단위 변경·시행일을 추출하고 로컬 조문을 갱신합니다."""

from __future__ import annotations

import json
import re
import time
import urllib.request
from datetime import date, timedelta
from pathlib import Path

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
    r'(?:"([^"]{1,320})"|「([^」]{1,320})」)\s*(?:으로|로)'
)
# 제60조제6항제3호 중 "A"을 "B"로 한다 (부칙·타법개정 포함)
LOCATED_SWAP_RE = re.compile(
    r"제\s*(\d+)\s*조(?:의\s*(\d+))?"
    r"(?:제\s*(\d+)\s*항)?(?:제\s*(\d+)\s*호)?\s*중\s*"
    r'(?:"([^"]{1,320})"|「([^」]{1,320})」)\s*[을를]\s*'
    r'(?:"([^"]{1,320})"|「([^」]{1,320})」)\s*(?:으로|로)\s*한다'
)
JO_TOKEN_RE = re.compile(r"제\s*([0-9]+)\s*조(?:의\s*([0-9]+))?")
UNIT_HANG_HO_RE = re.compile(
    r"제\s*\d+\s*조(?:의\s*\d+)?제\s*(\d+)\s*항제\s*(\d+)\s*호"
)
UNIT_HO_RE = re.compile(r"제\s*\d+\s*조(?:의\s*\d+)?(?:제\s*\d+\s*항)?제\s*(\d+)\s*호")
UNIT_HANG_RE = re.compile(r"제\s*\d+\s*조(?:의\s*\d+)?제\s*(\d+)\s*항")
NEW_ARTICLE_RE = re.compile(
    r"제\s*([0-9]+)\s*조(?:의\s*([0-9]+))?를\s*다음과\s*같이\s*신설한다\.\s*"
    r"(제\s*\1\s*조(?:의\s*\2)?\(([^)]+)\)\s*)"
    r"(.+?)(?="
    r"제\s*\d+\s*조(?:의\s*\d+)?를\s*다음과\s*같이\s*신설|"
    r"제\s*\d+\s*조(?:의\s*\d+)?제\s*\d+\s*(?:항|호)|"
    r"제\s*\d+\s*조(?:의\s*\d+)?\s*중\s|"
    r"제\s*\d+\s*장|"
    r"\s부칙\s|"
    r"$)"
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
    req = urllib.request.Request(f"{url}{sep}_ts={int(time.time() * 1000)}", headers=UA)
    with urllib.request.urlopen(req, timeout=60) as res:
        return res.read().decode("utf-8", "replace")


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


def fetch_doc_map(ls_id: str) -> dict[str, str]:
    """noticeNo -> 개정문 plain text"""
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
    return out


def jo_label(no: str, of: str | None = None) -> str:
    return f"제{no}조" + (f"의{of}" if of else "")


def hist_tag(amended: date, kind: str = "개정") -> str:
    return f"<{kind} {amended.year}. {amended.month}. {amended.day}.>"


def parse_special_effective(doc_text: str, amended: date, default_effective: date) -> dict[str, date]:
    """부칙 시행일 특례를 조문별로 해석한다."""
    special: dict[str, date] = {}

    # 제N조의 개정규정은 공포 후 M개월…
    for no, of, months in re.findall(
        r"제\s*([0-9]+)\s*조(?:의\s*([0-9]+))?의\s*개정규정은\s*공포\s*후\s*([0-9]+)\s*개월이\s*경과한\s*날부터\s*시행",
        doc_text,
    ):
        special[jo_label(no, of or None)] = add_months(amended, int(months))

    # 다만, 제13조 … 제114조제1호 … 까지의 개정규정은 공포 후 8개월…
    for block, months in re.findall(
        r"다만,\s*([^.]{10,500}?)"
        r"(?:까지(?:의)?|의)\s*개정규정은\s*공포\s*후\s*([0-9]+)\s*개월이\s*경과한\s*날부터\s*시행",
        doc_text,
    ):
        eff = add_months(amended, int(months))
        for no, of in JO_TOKEN_RE.findall(block):
            special[jo_label(no, of or None)] = eff

    # …하고, 제44조의4 … 의 개정규정은 2027년 1월 1일부터 시행
    # (같은 문장 앞부분의 8개월 특례 조문을 덮어쓰지 않도록 '하고/그리고' 뒤만 대상)
    for block, y, m, d in re.findall(
        r"(?:하고|그리고)\s*,?\s*([^.]{8,300}?)"
        r"(?:까지(?:의)?|의)\s*개정규정은\s*([0-9]{4})\s*년\s*([0-9]{1,2})\s*월\s*([0-9]{1,2})\s*일부터\s*시행",
        doc_text,
    ):
        eff = date(int(y), int(m), int(d))
        for no, of in JO_TOKEN_RE.findall(block):
            special[jo_label(no, of or None)] = eff

    return special


_STMT_START_RE = re.compile(
    r"(?:^|(?<=\.\s)|(?<=다\.\s)|(?<=자\s)|(?<=다\s))"
    r"제\s*([0-9]+)\s*조(?:의\s*([0-9]+))?"
    r"(?="
    # 제60조제6항제3호 중 … / 제43조 중 … (인용 제37조제6항 단독은 제외)
    r"(?:제\s*\d+\s*항)?(?:제\s*\d+\s*호)?\s*중\s"
    r"|\s*제목"
    r"|\s*중\s"
    r"|\s*[을를]\s"
    r"|\s*에\s"
    r"|\s*부터\s"
    r"|\s*각\s*호"
    r"|를\s*다음과"
    r"|\("
    r")"
)


def _split_jo_chunks(doc_text: str) -> list[tuple[str, str]]:
    """개정 본문을 조문 지시 단위로 자른다(인용·본문 속 조문번호 제외)."""
    main = re.split(r"\s부칙\s", doc_text, maxsplit=1)[0]
    starts = list(_STMT_START_RE.finditer(main))
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
        stop = _STMT_START_RE.search(rest)
        block = rest[: stop.start()] if stop else rest[:1200]
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
    special_eff = parse_special_effective(doc_text, amended, default_effective)
    changes: dict[str, dict] = {}

    def ensure(jo: str) -> dict:
        if jo not in changes:
            changes[jo] = {
                "articleNo": jo,
                "effectiveDate": special_eff.get(jo, default_effective),
                "summaryParts": [],
                "ops": [],
                "newProviso": "",
                "hang": "",
                "patchBody": False,
                "articleTitle": "",
            }
        elif jo in special_eff:
            changes[jo]["effectiveDate"] = special_eff[jo]
        return changes[jo]

    # 0) 조문 전체 신설 (제목+본문)
    for no, of, _header, title, body in NEW_ARTICLE_RE.findall(doc_text):
        jo = jo_label(no, of or None)
        body = re.sub(r"\s+", " ", body).strip()
        # 항 번호 앞에서 줄바꿈
        body = re.sub(r"\s*([①-⑮])\s*", r"\n\1 ", body).strip()
        body = re.sub(r"\s*(\d+(?:의\d+)?\.)\s*", r"\n\1 ", body).strip()
        entry = ensure(jo)
        entry["articleTitle"] = title.strip()
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
            op.get("kind") == "replace" and op.get("old") == old and op.get("new") == new
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
            unit_loc = ""
            for hm in UNIT_HANG_HO_RE.finditer(prefix):
                unit_loc = f"제{hm.group(1)}항제{hm.group(2)}호"
            if not unit_loc:
                for hm in UNIT_HO_RE.finditer(prefix):
                    unit_loc = f"제{hm.group(1)}호"
            if not unit_loc:
                for am in UNIT_HANG_RE.finditer(prefix):
                    unit_loc = f"제{am.group(1)}항"
            # 0.5에서 이미 넣은 동일 치환은 스킵
            if any(
                op.get("kind") == "replace" and op.get("old") == old and op.get("new") == new
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

        for para in _extract_new_paragraphs(chunk):
            entry["ops"].append(
                {
                    "kind": "insert",
                    "text": para,
                    "locator": f"{jo} {para[0]}항" if para and para[0] in CIRCLE_TO_N else jo,
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

        # 조 단위 각 호 신설: 「같은 조에 각 호를 다음과 같이 신설한다」
        hm = re.search(r"각\s*호를\s*다음과\s*같이\s*신설한다\.", chunk)
        if hm:
            rest = chunk[hm.end() :]
            stop = _STMT_START_RE.search(rest)
            block = rest[: stop.start()] if stop else rest
            for hos in re.findall(
                r"(\d+(?:의\d+)?\.\s*.+?)(?=\s*\d+(?:의\d+)?\.|\s*$)",
                block,
                flags=re.S,
            ):
                text = re.sub(r"\s+", " ", hos).strip()
                if len(text) < 4:
                    continue
                if any(
                    op.get("kind") == "insert" and op.get("text") == text
                    for op in entry["ops"]
                ):
                    continue
                entry["ops"].append(
                    {
                        "kind": "insert",
                        "text": text,
                        "locator": f"{jo} 제{text.split('.', 1)[0]}호",
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
            entry["ops"].append(
                {
                    "kind": "delete_ho",
                    "fromHo": int(del_ho.group(1)),
                    "toHo": int(del_ho.group(2)),
                    "locator": jo,
                    "isNew": False,
                }
            )
            entry["summaryParts"].append(
                f"제{del_ho.group(1)}호·제{del_ho.group(2)}호 삭제"
            )

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

        if re.search(r"제\s*\d+\s*항을\s*삭제한다", chunk) or "제2항을 삭제한다" in chunk:
            entry["ops"].append(
                {
                    "kind": "delete_mark",
                    "text": "② 삭제",
                    "locator": "제2항",
                    "isNew": False,
                }
            )
            entry["summaryParts"].append("제2항 삭제")

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

    # 요약이 전혀 없는 빈 엔트리 제거, ops만 있어도 유지
    results = []
    for jo, data in changes.items():
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

    for m in re.finditer(r"(?ms)^(\d+)\.\s+.*?(?=^\d+\.\s|\Z)", body):
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


def _strip_rest_proviso(text: str) -> str:
    t = re.sub(r"\s*<개정[^>]*>\s*", " ", text)
    t = re.sub(
        r"\s*다만,\s*근로시간이\s*4시간인\s*경우로서\s*근로자가\s*휴게시간을\s*"
        r"이용하지\s*아니할\s*것을\s*명시적으로\s*요청한\s*때에는\s*그러하지\s*아니하다\.\s*",
        " ",
        t,
    )
    t = re.sub(r"\s+", " ", t).strip().rstrip(".")
    return (t + ".") if t else ""


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
        return fallback or t.split(".", 1)[0] + "호"
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
    structural = any(
        op.get("kind") in ("proviso", "insert", "delete_proviso", "delete_ho", "renumber_ho")
        for op in ops
    )

    replace_hits: list[tuple[str, str, str]] = []  # before_unit, after_unit, loc

    for op in ops:
        kind = op.get("kind")
        if kind in ("renumber", "renumber_ho", "delete_ho", "delete_proviso"):
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
            unit_info = find_containing_unit(body, old)
            if unit_info:
                before_unit, _, _ = unit_info
                before_clean = re.sub(r"\s*<개정[^>]*>\s*", " ", before_unit).strip()
                after_unit = before_unit.replace(old, new, 1)
                after_clean = re.sub(r"\s*<개정[^>]*>\s*", " ", after_unit).rstrip()
                loc = op.get("unitLocator") or hang_locator_from_text(
                    before_unit, op.get("locator") or art.get("no") or ""
                )
                replace_hits.append((before_unit, after_unit, loc))
                if not structural:
                    phrases.append(
                        {
                            "text": after_clean,  # 개정된 내용
                            "beforeText": before_clean,  # 개정 전
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
            para = (op.get("text") or "").strip()
            if hist_new not in para and hist_rev not in para:
                para = para.rstrip() + " " + hist_new
            loc = hang_locator_from_text(para, op.get("locator") or art.get("no") or "")
            phrases.append(
                {
                    "text": para,
                    "beforeText": "해당 항·호 없음(신설)",
                    "isNew": True,
                    "historyKind": "신설",
                    "historyDates": [amd],
                    "locator": loc,
                    "amendedDate": amd,
                    "effectiveDate": eff,
                    "beforeNote": "",
                    "pending": True,
                    "skipHighlight": True,
                    "compareBefore": "해당 항·호 없음(신설)",
                    "compareAfter": re.sub(r"\s*<[^>]+>\s*", "", para).strip(),
                }
            )
        elif kind == "delete_mark":
            phrases.append(
                {
                    "text": "② 삭제",
                    "beforeText": "② (삭제 전 항)",
                    "isNew": False,
                    "historyKind": "개정",
                    "historyDates": [amd],
                    "locator": "제2항",
                    "amendedDate": amd,
                    "effectiveDate": eff,
                    "beforeNote": "",
                    "pending": True,
                    "skipHighlight": True,
                    "compareBefore": "② (삭제 전 항)",
                    "compareAfter": "② 삭제",
                }
            )

    # 구조 개정(단서·각호 신설 등): 현행 본문은 유지하고,
    # 치환 단위에 단서를 붙인 개정 후 문구를 음영 + 전문 compareAfter
    if structural and body.strip():
        before_full = body.strip()
        after_full = body
        for op in ops:
            if op.get("kind") == "replace":
                old, new = op.get("old") or "", op.get("new") or ""
                if old and old in after_full:
                    after_full = after_full.replace(old, new, 1)
        proviso = next(
            (op.get("text") or "" for op in ops if op.get("kind") == "proviso"),
            "",
        )
        if proviso and proviso not in after_full:
            if re.search(r"처한다\.\s*<", after_full):
                after_full = re.sub(
                    r"(처한다\.)(\s*<)",
                    r"\1 " + proviso + r"\2",
                    after_full,
                    count=1,
                )
            else:
                after_full = re.sub(
                    r"(처한다\.)",
                    r"\1 " + proviso,
                    after_full,
                    count=1,
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

        if re.search(r"<개정\s*[^>]*>", after_full):
            if f"{amended.year}. {amended.month}. {amended.day}." not in after_full:
                after_full = re.sub(
                    r"<개정\s*([^>]+)>",
                    rf"<개정 \1, {amended.year}. {amended.month}. {amended.day}.>",
                    after_full,
                    count=1,
                )
        else:
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
                if re.search(r"처한다\.\s*<", after_show):
                    after_show = re.sub(
                        r"(처한다\.)(\s*<)",
                        r"\1 " + proviso + r"\2",
                        after_show,
                        count=1,
                    )
                else:
                    after_show = re.sub(
                        r"(처한다\.)",
                        r"\1 " + proviso,
                        after_show,
                        count=1,
                    )
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
                    "compareBefore": compare_before,
                    "compareAfter": compare_after,
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
            phrases.append(
                {
                    "text": f"제{op.get('fromHo')}호·제{op.get('toHo')}호 삭제",
                    "beforeText": f"제{op.get('fromHo')}호·제{op.get('toHo')}호",
                    "isNew": False,
                    "historyKind": "개정",
                    "historyDates": [amd],
                    "locator": op.get("locator") or art.get("no"),
                    "amendedDate": amd,
                    "effectiveDate": eff,
                    "beforeNote": "",
                    "pending": True,
                    "skipHighlight": True,
                    "compareBefore": f"제{op.get('fromHo')}호·제{op.get('toHo')}호",
                    "compareAfter": f"제{op.get('fromHo')}호·제{op.get('toHo')}호 삭제",
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

    return phrases


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
            # 이미 eflaw 현행 본문에 반영된 치환은 재적용하지 않음
            if old not in body and new and new in body:
                continue
            unit_info = find_containing_unit(body, old)
            if unit_info:
                before_unit, start, end = unit_info
                after_unit = before_unit.replace(old, new, 1)
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
            unit_info = find_containing_unit(body, "②") if "②" in body else None
            if unit_info:
                before_unit, start, end = unit_info
                after_marked = f"② 삭제 {hist_rev}"
                body = body[:start] + after_marked + body[end:]
                phrases.append(
                    {
                        "text": after_marked,
                        "beforeText": before_unit,
                        "isNew": False,
                        "historyKind": "개정",
                        "historyDates": [amd],
                        "locator": "제2항",
                        "amendedDate": amd,
                        "effectiveDate": eff,
                        "beforeNote": "",
                    }
                )
            else:
                after_marked = f"② 삭제 {hist_rev}"
                body = (body + "\n" + after_marked).strip() if body else after_marked
                phrases.append(
                    {
                        "text": after_marked,
                        "beforeText": "② (삭제 전 항)",
                        "isNew": False,
                        "historyKind": "개정",
                        "historyDates": [amd],
                        "locator": "제2항",
                        "amendedDate": amd,
                        "effectiveDate": eff,
                        "beforeNote": "",
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
        apply_body = ch["effectiveDate"] <= base
        if apply_body and (ch.get("articleTitle") or "").strip():
            art["title"] = ch["articleTitle"].strip()
        elif not (art.get("title") or "").strip() and (ch.get("articleTitle") or "").strip():
            art["title"] = ch["articleTitle"].strip()
        article_id = art["id"]
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
            # 본문은 항상 전문 현행 유지(재적용 오염 방지)
            if full_index is not None:
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
            p0 = phrases[0]
            compare_before = p0.get("compareBefore") or p0.get("beforeText") or ""
            compare_after = p0.get("compareAfter") or re.sub(
                r"\s*<[^>]+>\s*", "", p0.get("text") or ""
            ).strip()
            # pending: compareBefore/After 필드 우선
            if p0.get("pending") and p0.get("compareBefore"):
                compare_before = p0["compareBefore"]
                compare_after = p0.get("compareAfter") or compare_after
        elif ch.get("newProviso"):
            compare_before = "해당 단서 없음(신설)"
            compare_after = ch["newProviso"]

        highlights = (
            [{"articleId": article_id, "phrases": highlight_phrases}]
            if highlight_phrases
            else []
        )
        locators = []
        for ph in phrases:
            if ph.get("locator") and ph["locator"] not in locators:
                locators.append(ph["locator"])
        if not locators:
            locators = [ch["articleNo"] + (f" 제{ch['hang']}항" if ch.get("hang") else "")]

        child = dict(item)
        child.update(
            {
                "id": f"{item['id']}-{ch['articleNo']}",
                "parentId": item["id"],
                "title": display_title,
                "articleNo": ch["articleNo"],
                "articleTitle": title_name,
                "effectiveDate": to_iso(ch["effectiveDate"]),
                "summary": ch["summary"],
                "briefSummary": ch["summary"][:90] + ("…" if len(ch["summary"]) > 90 else ""),
                "status": "시행예정" if ch["effectiveDate"] > date.today() else item.get("status"),
                "mentionedArticles": [ch["articleNo"]],
                "locators": locators,
                "articleIds": [article_id],
                "highlights": highlights,
                "articleLevel": True,
                "compareBefore": compare_before,
                "compareAfter": compare_after,
                "bodyApplied": apply_body,
            }
        )
        expanded.append(child)
    return expanded
