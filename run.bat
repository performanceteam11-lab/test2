@echo off
chcp 65001 > nul
echo =============================================
echo  네이버 쇼핑 모니터링 실행
echo =============================================
echo.

cd /d "%~dp0"

echo [1/2] 모니터링 실행 중...
python monitor.py

echo.
echo [2/2] 대시보드 열기...
start dashboard.html

echo.
echo 완료! 브라우저에서 대시보드를 확인하세요.
pause
