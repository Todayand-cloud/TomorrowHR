@echo off
cd /d "%~dp0.."
powershell -NoProfile -WindowStyle Hidden -Command ^
  "try { $r = Invoke-WebRequest -Uri 'http://127.0.0.1:8787/health' -UseBasicParsing -TimeoutSec 2; if ($r.StatusCode -eq 200) { exit 0 } } catch {} ; Start-Process -WindowStyle Hidden -FilePath 'py' -ArgumentList '-3','_law_fetch\refresh_server.py','--no-browser' -WorkingDirectory '%cd%'"
