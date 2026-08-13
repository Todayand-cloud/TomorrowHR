# -*- coding: utf-8 -*-
"""
사이트 제공 + 수동 갱신 API 통합 서버.

  py -3 _law_fetch/refresh_server.py
  → http://127.0.0.1:8787/ 에서 홈페이지 접속
  → POST/GET /api/refresh?base=YYYY-MM-DD 로 갱신
"""

from __future__ import annotations

import importlib
import json
import mimetypes
import os
import subprocess
import sys
import traceback
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlparse

sys.path.insert(0, str(Path(__file__).resolve().parent))
import amendment_articles  # noqa: E402
import refresh_amendments  # noqa: E402

ROOT = refresh_amendments.ROOT

HOST = "127.0.0.1"
PORT = 8787


def _reload_fetch_modules() -> None:
    """수동 갱신마다 최신 수집 코드를 다시 로드 (서버 재시작 없이 누락 방지)."""
    importlib.reload(amendment_articles)
    importlib.reload(refresh_amendments)



class Handler(BaseHTTPRequestHandler):
    def _cors(self) -> None:
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")

    def _json(self, code: int, payload: dict) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self._cors()
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_OPTIONS(self) -> None:  # noqa: N802
        self.send_response(204)
        self._cors()
        self.end_headers()

    def do_GET(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        if parsed.path in ("/health", "/api/health"):
            self._json(200, {"ok": True, "service": "hr-law-desk", "port": PORT})
            return
        if parsed.path in ("/refresh", "/api/refresh"):
            self._handle_refresh(parsed)
            return
        self._serve_static(parsed.path)

    def do_POST(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        if parsed.path in ("/refresh", "/api/refresh"):
            self._handle_refresh(parsed)
            return
        self._json(404, {"ok": False, "error": "not found"})

    def _handle_refresh(self, parsed) -> None:
        qs = parse_qs(parsed.query)
        base_text = (qs.get("base") or [None])[0]
        try:
            _reload_fetch_modules()
            # 사이트/로컬 수동 갱신도 Actions와 동일: 신규수집→시뮬레이션→재시도
            cmd = [
                sys.executable,
                str(Path(__file__).resolve().parent / "refresh_amendments.py"),
                "--repair-attempts",
                "3",
            ]
            if base_text:
                cmd.extend(["--base", base_text])
            env = os.environ.copy()
            env["PYTHONIOENCODING"] = "utf-8"
            proc = subprocess.run(
                cmd,
                cwd=str(ROOT),
                env=env,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
            )
            payload = json.loads(
                (ROOT / "js" / "amendments-cache.json").read_text(encoding="utf-8")
            )
            sc = payload.get("selfCheck") or {}
            ok = proc.returncode == 0 and bool(sc.get("ok"))
            self._json(
                200 if ok else 500,
                {
                    "ok": ok,
                    "baseDate": payload.get("baseDate"),
                    "from": payload.get("from"),
                    "to": payload.get("to"),
                    "forwardDays": payload.get("forwardDays", 182),
                    "lookbackDays": payload.get("lookbackDays", 182),
                    "effForwardDays": payload.get("effForwardDays", 182),
                    "effLookbackDays": payload.get("effLookbackDays", 182),
                    "fetchedAt": payload.get("fetchedAt"),
                    "freshFetch": payload.get("freshFetch", True),
                    "count": payload.get("count"),
                    "errors": payload.get("errors"),
                    "audit": payload.get("audit"),
                    "selfCheck": sc,
                    "simulationLog": payload.get("simulationLog"),
                    "noticesRefresh": payload.get("noticesRefresh"),
                    "returncode": proc.returncode,
                    "logTail": (proc.stdout or "")[-2500:],
                    "amendments": payload.get("amendments"),
                },
            )
        except Exception as exc:  # noqa: BLE001
            self._json(
                500,
                {"ok": False, "error": str(exc), "trace": traceback.format_exc(limit=3)},
            )

    def _serve_static(self, raw_path: str) -> None:
        path = unquote(raw_path.split("?", 1)[0])
        if path in ("", "/"):
            path = "/index.html"
        rel = path.lstrip("/").replace("\\", "/")
        if ".." in rel.split("/"):
            self._json(403, {"ok": False, "error": "forbidden"})
            return
        file_path = (ROOT / rel).resolve()
        if not str(file_path).startswith(str(ROOT.resolve())) or not file_path.is_file():
            self.send_response(404)
            self._cors()
            self.end_headers()
            self.wfile.write(b"Not Found")
            return
        ctype = mimetypes.guess_type(str(file_path))[0] or "application/octet-stream"
        data = file_path.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self._cors()
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, fmt: str, *args) -> None:
        print("[%s] %s" % (self.log_date_time_string(), fmt % args))


def main() -> None:
    open_browser = "--no-browser" not in sys.argv
    url = f"http://{HOST}:{PORT}/"
    try:
        server = ThreadingHTTPServer((HOST, PORT), Handler)
    except OSError as exc:
        print(f"포트 {PORT} 사용 중 — 이미 서버가 실행 중일 수 있습니다.")
        print(f"브라우저에서 {url} 를 열어 주세요. ({exc})")
        if open_browser:
            try:
                webbrowser.open(url)
            except Exception:
                pass
        return

    print(f"HR Law Desk server: {url}")
    print("수동 갱신 API: /api/refresh?base=YYYY-MM-DD")
    if open_browser:
        try:
            webbrowser.open(url)
        except Exception:
            pass
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n서버를 종료합니다.")


if __name__ == "__main__":
    main()
