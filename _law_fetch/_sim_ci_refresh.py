# -*- coding: utf-8 -*-
"""CI와 동일 조건 시뮬레이션: LAW_FETCH_PROXY 경유 신규수집 + 법제처 대조 재시도.

사용:
  set LAW_FETCH_PROXY=https://wandering-dew-09bd.shkim5.workers.dev
  py -3 _law_fetch/_sim_ci_refresh.py
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

FETCH = Path(__file__).resolve().parent
ROOT = FETCH.parent
PROXY = os.environ.get(
    "LAW_FETCH_PROXY", "https://wandering-dew-09bd.shkim5.workers.dev"
)


def main() -> int:
    env = os.environ.copy()
    env["LAW_FETCH_PROXY"] = PROXY
    env["LAW_HTTP_TIMEOUT"] = env.get("LAW_HTTP_TIMEOUT") or "45"
    env["PYTHONIOENCODING"] = "utf-8"
    env["CI"] = "true"

    print("=== 1) proxy smoke ===")
    from http_util import http_get

    sample = http_get(
        "https://www.law.go.kr/DRF/lawService.do?OC=test&target=law&type=XML&ID=001872"
    )
    assert "근로기준법" in sample, "proxy/law fetch failed"
    print("proxy_ok bytes=", len(sample))

    print("=== 2) refresh_amendments --repair-attempts 2 (신규수집+시뮬레이션) ===")
    r1 = subprocess.run(
        [
            sys.executable,
            str(FETCH / "refresh_amendments.py"),
            "--repair-attempts",
            "2",
        ],
        cwd=str(ROOT),
        env=env,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    print(r1.stdout[-3000:] if r1.stdout else "")
    if r1.stderr:
        print(r1.stderr[-1500:])
    if r1.returncode != 0:
        print("refresh_failed", r1.returncode)
        return r1.returncode

    cache = json.loads((ROOT / "js" / "amendments-cache.json").read_text(encoding="utf-8"))
    count = int(cache.get("count") or len(cache.get("amendments") or []))
    sc = cache.get("selfCheck") or {}
    sim = sc.get("simulation") or {}
    print(
        json.dumps(
            {
                "cache": {
                    "baseDate": cache.get("baseDate"),
                    "count": count,
                    "freshFetch": cache.get("freshFetch"),
                    "selfCheckOk": sc.get("ok"),
                    "simulationPassed": sim.get("passed"),
                    "parityOk": (sc.get("parity") or {}).get("ok"),
                }
            },
            ensure_ascii=False,
            indent=2,
        )
    )

    if count <= 0 or not sc.get("ok") or sim.get("passed") is False:
        print("FINAL FAIL: simulation did not pass")
        return 1

    print("FINAL OK: fresh fetch + simulation passed")
    (FETCH / "_sim_ci_result.json").write_text(
        json.dumps(
            {
                "ok": True,
                "count": count,
                "parityOk": (sc.get("parity") or {}).get("ok"),
                "simulation": sim,
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
