# -*- coding: utf-8 -*-
"""HTTP GET — 로컬은 직접, GitHub Actions는 Cloudflare Worker 프록시 경유.

원인: Actions 러너 IP에서 law.go.kr / moel.go.kr 가 자주 timed out 됨.
해결: LAW_FETCH_PROXY 가 있으면 Worker가 대신 받아 본문을 돌려준다.
"""

from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request

DEFAULT_UA = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/120.0.0.0 Safari/537.36",
    "Cache-Control": "no-cache",
    "Pragma": "no-cache",
}

HTTP_TIMEOUT_S = int(os.environ.get("LAW_HTTP_TIMEOUT", "45"))


def _proxy_base() -> str:
    return (os.environ.get("LAW_FETCH_PROXY") or "").strip().rstrip("/")


def http_get(url: str, headers: dict | None = None, timeout: int | None = None) -> str:
    """URL 본문을 문자열로 반환. 실패 시 예외."""
    timeout = HTTP_TIMEOUT_S if timeout is None else timeout
    headers = {**DEFAULT_UA, **(headers or {})}
    proxy = _proxy_base()
    if proxy:
        return _via_proxy(proxy, url, headers, timeout)
    return _direct(url, headers, timeout)


def _direct(url: str, headers: dict, timeout: int) -> str:
    req = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(req, timeout=timeout) as res:
        return res.read().decode("utf-8", "replace")


def _via_proxy(proxy: str, url: str, headers: dict, timeout: int) -> str:
    """Worker POST {action:fetch,url} → {ok,body}."""
    payload = json.dumps(
        {"action": "fetch", "url": url, "headers": headers},
        ensure_ascii=False,
    ).encode("utf-8")
    req_headers = {
        "Content-Type": "application/json; charset=utf-8",
        "User-Agent": "TomorrowHR-Actions-fetch",
    }
    secret = (os.environ.get("LAW_FETCH_PROXY_SECRET") or "").strip()
    if secret:
        req_headers["X-Proxy-Secret"] = secret

    last_exc: Exception | None = None
    for attempt in range(2):
        try:
            req = urllib.request.Request(
                proxy, data=payload, headers=req_headers, method="POST"
            )
            with urllib.request.urlopen(req, timeout=timeout + 15) as res:
                raw = res.read().decode("utf-8", "replace")
            data = json.loads(raw)
            # 구버전 Worker는 action=fetch 를 모르고 dispatch 만 함 → 재배포 필요
            if data.get("dispatched") and "body" not in data:
                raise RuntimeError(
                    "Cloudflare Worker에 fetch 액션이 없습니다. "
                    "_law_fetch/cloudflare-refresh-worker.js 를 재배포하세요."
                )
            if not data.get("ok"):
                raise RuntimeError(data.get("error") or "proxy fetch failed")
            body = data.get("body")
            if body is None:
                raise RuntimeError("proxy returned empty body")
            return str(body)
        except Exception as exc:  # noqa: BLE001
            last_exc = exc
            if attempt == 0:
                time.sleep(1.5)
    assert last_exc is not None
    raise last_exc
