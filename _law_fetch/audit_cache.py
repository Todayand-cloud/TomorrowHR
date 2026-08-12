# -*- coding: utf-8 -*-
import json
from pathlib import Path

p = json.loads((Path(__file__).resolve().parents[1] / "js" / "amendments-cache.json").read_text(encoding="utf-8"))
print("count", p["count"], "from", p["from"], "to", p["to"])
print("selfCheck", p.get("selfCheck"))
print("audit", p.get("audit"))
for a in p["amendments"]:
    hl = len(a.get("highlights") or [])
    mark = "*" if hl else " "
    print(
        f"{mark} {a['amendedDate']}~{a['effectiveDate']} | {a['tier']} | {a['lawName']} | "
        f"제{a['noticeNo']}호 | hl={hl} | articles={a.get('articleIds')}"
    )
    for h in a.get("highlights") or []:
        for ph in h["phrases"][:3]:
            t = ph["text"].replace("\n", " ")[:100]
            print("   ", ph.get("historyKind"), ph.get("historyDates"), t)

print("has_fake_2026-07-10", any(a["amendedDate"] == "2026-07-10" for a in p["amendments"]))
for a in p["amendments"]:
    for h in a.get("highlights") or []:
        if "statute-61" in (h.get("articleId") or ""):
            print("FALSE_61_LINK", a["id"], a["amendedDate"])

# cross-check retirement 2026-03-17
for a in p["amendments"]:
    if a["lawId"] == "retirement" and a["amendedDate"] == "2026-03-17":
        print("retirement_2026-03-17", "hl", len(a.get("highlights") or []), a.get("articleIds"), a["effectiveDate"])

# labor 2024-10-22
for a in p["amendments"]:
    if a["amendedDate"] == "2024-10-22":
        print("laborish_2024-10-22", a["lawName"], a["effectiveDate"], a.get("articleIds"))
