@echo off
chcp 65001 >nul
rem X 미디어 다운로더 실행 (Windows) - 더블클릭하면 GUI가 열립니다.
rem 명령줄 모드: run_windows.bat bookmarks  (옵션은 --help)
setlocal
cd /d "%~dp0"

if exist ".venv\Scripts\python.exe" goto install
echo [설치] 가상환경(.venv)을 만드는 중...
py -3 -m venv .venv 2>nul
if exist ".venv\Scripts\python.exe" goto install
python -m venv .venv
if exist ".venv\Scripts\python.exe" goto install
echo.
echo Python 3.9 이상이 필요합니다. https://www.python.org/downloads/ 에서 설치하세요.
echo 설치할 때 "Add python.exe to PATH" 를 꼭 체크하세요.
pause
exit /b 1

:install
".venv\Scripts\python.exe" -m pip install --disable-pip-version-check -q -r requirements.txt
if errorlevel 1 goto install_failed

if "%~1"=="" goto gui
".venv\Scripts\python.exe" x_media_downloader.py %*
exit /b %errorlevel%

:gui
start "" ".venv\Scripts\pythonw.exe" x_media_downloader.py
exit /b 0

:install_failed
echo.
echo gallery-dl 설치에 실패했습니다. 인터넷 연결을 확인한 뒤 다시 실행하세요.
pause
exit /b 1
