#!/usr/bin/env bash
# X 미디어 다운로더 — 안드로이드(Termux) 설치/업데이트
#
# Termux 앱에서 아래 한 줄을 붙여넣어 실행합니다. 다시 실행하면 앱과 엔진을 최신으로 업데이트합니다.
# (yes | pkg upgrade 를 먼저 해야 한다: 갓 설치한 Termux에서 curl만 올리면 openssl과 버전이 어긋나 curl이 깨진다)
#   yes | pkg upgrade && pkg install -y curl && curl -fsSLo setup.sh https://raw.githubusercontent.com/cheapbutsimilar/pixel-agents/claude/twitter-media-crawler-j2oynh/twitter-media-crawler/setup_android.sh && bash setup.sh
set -euo pipefail

BASE_URL="${XMD_BASE_URL:-https://raw.githubusercontent.com/cheapbutsimilar/pixel-agents/claude/twitter-media-crawler-j2oynh/twitter-media-crawler}"
APP_DIR="${XMD_APP_DIR:-$HOME/x-media-downloader}"
SHORTCUT_DIR="$HOME/.shortcuts"
DOWNLOAD_DIR="/storage/emulated/0/Download"
TERMUX_BASH="${PREFIX:-/data/data/com.termux/files/usr}/bin/bash"

step() { printf '\n== %s\n' "$*"; }

if [[ "${PREFIX:-}" != *com.termux* && -z "${XMD_ALLOW_NON_TERMUX:-}" ]]; then
  echo "이 스크립트는 안드로이드 Termux 앱 전용입니다. PC에서는 run_windows.bat / run_mac_linux.sh 를 쓰세요." >&2
  exit 1
fi

step "1/4 파이썬 설치"
if ! command -v python3 >/dev/null 2>&1; then
  pkg install -y python
fi
python3 --version

step "2/4 저장소 권한 — 팝업이 뜨면 '허용'을 누르세요"
if [ ! -w "$DOWNLOAD_DIR" ] && command -v termux-setup-storage >/dev/null 2>&1; then
  termux-setup-storage || true
  for _ in $(seq 1 60); do
    [ -w "$DOWNLOAD_DIR" ] && break
    sleep 1
  done
fi
if [ -w "$DOWNLOAD_DIR" ]; then
  echo "OK — 받은 파일은 '내 파일 > 다운로드 > x-media' 에 저장됩니다."
else
  echo "아직 권한이 없습니다. 나중에 Termux에서 termux-setup-storage 를 실행하고 '허용'을 누르세요."
fi

step "3/4 앱 내려받기 + 다운로드 엔진(gallery-dl) 설치"
mkdir -p "$APP_DIR"
for f in x_media_downloader.py requirements.txt run_mac_linux.sh README.md; do
  curl -fsSL "$BASE_URL/$f" -o "$APP_DIR/$f.tmp"
  mv "$APP_DIR/$f.tmp" "$APP_DIR/$f"
done
chmod +x "$APP_DIR/run_mac_linux.sh"
[ -x "$APP_DIR/.venv/bin/python" ] || python3 -m venv "$APP_DIR/.venv"
"$APP_DIR/.venv/bin/python" -m pip install --disable-pip-version-check -q --upgrade -r "$APP_DIR/requirements.txt"
echo "엔진: gallery-dl $("$APP_DIR/.venv/bin/python" -m gallery_dl --version)"

step "4/4 홈 화면 버튼 만들기 (Termux:Widget 앱용)"
mkdir -p "$SHORTCUT_DIR"
chmod 700 "$SHORTCUT_DIR"
cat > "$SHORTCUT_DIR/X 다운로더" <<SCRIPT
#!$TERMUX_BASH
exec bash "$APP_DIR/run_mac_linux.sh"
SCRIPT
cat > "$SHORTCUT_DIR/X 북마크 새로고침" <<SCRIPT
#!$TERMUX_BASH
bash "$APP_DIR/run_mac_linux.sh" bookmarks
echo
read -r -p "끝났습니다. Enter를 누르면 닫힙니다."
SCRIPT
chmod +x "$SHORTCUT_DIR/X 다운로더" "$SHORTCUT_DIR/X 북마크 새로고침"

cat <<DONE

설치 완료!
  - 지금 실행:        bash ~/x-media-downloader/run_mac_linux.sh
  - 홈 화면 버튼:     Termux:Widget 앱 설치 → 홈 화면 빈 곳 길게 누르기 → 위젯 → Termux:Widget
                      ('X 다운로더' = 메뉴, 'X 북마크 새로고침' = 저장된 로그인으로 새 북마크만 받기)
                      ※ Termux:Widget 앱 아이콘을 누르면 영어 설명 화면만 나옵니다. 위젯으로 추가해서 쓰세요.
  - 받은 파일:        내 파일 > 다운로드 > x-media (갤러리 앱에도 표시)
  - 업데이트:         bash setup.sh 를 다시 실행
DONE
