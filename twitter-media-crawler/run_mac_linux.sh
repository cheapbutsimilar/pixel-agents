#!/usr/bin/env bash
# X 미디어 다운로더 실행 (macOS / Linux / 안드로이드 Termux)
#   bash run_mac_linux.sh              → GUI (휴대폰·서버에서는 글자 메뉴)
#   bash run_mac_linux.sh bookmarks    → 명령줄 모드 (옵션은 --help)
set -euo pipefail
cd "$(dirname "$0")"

if [ ! -x .venv/bin/python ]; then
  echo "[설치] 가상환경(.venv)을 만드는 중..."
  "${PYTHON:-python3}" -m venv .venv
fi
.venv/bin/python -m pip install --disable-pip-version-check -q -r requirements.txt
exec .venv/bin/python x_media_downloader.py "$@"
