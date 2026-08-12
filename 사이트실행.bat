@echo off
chcp 65001 >nul
cd /d "%~dp0"
echo.
echo [인사 법령 Desk] 서버를 시작합니다.
echo 브라우저가 열리면 「수동 갱신」 버튼만으로 업데이트가 가능합니다.
echo 이 창을 닫으면 사이트가 중지됩니다.
echo.
py -3 "_law_fetch\refresh_server.py"
if errorlevel 1 (
  echo.
  echo Python 실행에 실패했습니다. Python 설치 여부를 확인해 주세요.
  pause
)
