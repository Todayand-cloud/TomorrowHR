# -*- coding: utf-8 -*-
"""시드 조문 JSON 생성 — 전문 캐시(full-*.txt)로 제목·본문 보강. 본문 삭제 없음."""
from __future__ import annotations

from hydrate_articles import build_seed_from_full

if __name__ == "__main__":
    seed = build_seed_from_full()
    for lid, pack in seed.items():
        if not isinstance(pack, dict):
            continue
        for tier in ("statute", "decree", "rule"):
            arts = pack.get(tier) or []
            empty = [a["no"] for a in arts if not (a.get("title") or "").strip()]
            print(lid, tier, "n=", len(arts), "emptyTitle=", empty[:10])
