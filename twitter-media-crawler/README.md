# X(트위터) 미디어 다운로더

**내 북마크** 또는 **특정 계정의 모든 게시물**에 있는 사진·동영상을 한 번에 내려받는 간단한 앱입니다.

- 사진은 원본 해상도, 동영상은 가장 높은 화질로 저장합니다. (GIF는 X에서 mp4로 제공되므로 mp4로 저장)
- **한 번 받은 건 다시 받지 않습니다.** 받은 파일을 다른 폴더로 옮기거나 지워도, 작성자가 아이디를 바꿔도 마찬가지입니다.
- 처음 한 번 전체를 받고 나면, 그다음부터는 새로 북마크했거나 새로 올라온 것만 빠르게 확인해서 받습니다.
- PC(Windows/맥/리눅스)는 창(GUI)으로, **안드로이드 폰(갤럭시 등)은 Termux 앱에서 메뉴 방식**으로 씁니다.

실제 수집은 오픈소스 [gallery-dl](https://github.com/mikf/gallery-dl)이 맡습니다. X는 내부 API를 자주 바꾸는데,
그럴 때 이 앱을 고칠 필요 없이 앱의 **엔진 업데이트** 버튼만 누르면 됩니다.

## 1. 준비

- **Python 3.9 이상**
  - Windows: <https://www.python.org/downloads/> 에서 설치합니다. 설치 첫 화면에서 **"Add python.exe to PATH"를 꼭 체크**하세요.
  - macOS: python.org 설치본을 권장합니다. (Homebrew Python이라면 `brew install python-tk`도 필요)
  - Linux: `sudo apt install python3 python3-venv python3-tk`
- 처음 실행할 때 필요한 패키지(gallery-dl)가 이 폴더의 `.venv` 안에 자동으로 설치됩니다.

## 2. 실행

| OS            | 방법                                                   |
| ------------- | ------------------------------------------------------ |
| Windows       | `run_windows.bat` 더블클릭                             |
| macOS / Linux | 터미널에서 이 폴더로 이동 후 `bash run_mac_linux.sh`   |
| 안드로이드    | 아래 [안드로이드 폰](#안드로이드-폰-갤럭시-등) 참고     |

### 안드로이드 폰 (갤럭시 등)

휴대폰에서는 무료 앱 **Termux**(안드로이드용 리눅스 터미널) 안에서 실행합니다. 화면은 번호를 고르는 메뉴 방식입니다.

1. **Termux 설치** — [F-Droid](https://f-droid.org/packages/com.termux/) 또는 [GitHub](https://github.com/termux/termux-app/releases)에서 받습니다. (Play 스토어 버전은 권장하지 않습니다)
   - 홈 화면 버튼을 쓰려면 **[Termux:Widget](https://f-droid.org/packages/com.termux.widget/)**도 **Termux와 같은 곳**에서 설치하세요. 설치처가 다르면 서로 연결되지 않습니다.
2. Termux를 열고 아래 한 줄을 붙여넣은 뒤 Enter를 누릅니다. (화면을 길게 누르면 Paste 메뉴가 나옵니다)
   ```
   apt update && yes | apt full-upgrade && apt install -y curl && curl -fsSLo setup.sh https://raw.githubusercontent.com/cheapbutsimilar/pixel-agents/claude/twitter-media-crawler-j2oynh/twitter-media-crawler/setup_android.sh && bash setup.sh
   ```
   중간에 **저장소 접근 권한** 팝업이 뜨면 **허용**을 누르세요.
   (앞부분은 Termux를 최신으로 맞추는 단계로, 몇 분 걸립니다. 빼면 `CANNOT LINK EXECUTABLE "curl"` 오류가 날 수 있습니다)
3. **실행** — 홈 화면 빈 곳 길게 누르기 › **위젯** › **Termux:Widget** 추가 → 위젯 안에 버튼 두 개가 생깁니다.
   (Termux:Widget 앱 아이콘을 누르면 영어 설명 화면만 나오는데 정상입니다. 앱이 아니라 위젯으로 씁니다)
   - **X 다운로더**: 메뉴 (1 북마크 / 2 특정 계정 / 3 로그인 / 4 옵션 / 5 엔진 업데이트). 처음 받을 때 `auth_token`, `ct0`를 물어봅니다.
   - **X 북마크 새로고침**: 저장된 로그인으로 새 북마크만 바로 받습니다.
   - 버튼을 누르면 `Termux requires "Display over other apps" permission` 메시지가 뜰 수 있습니다.
     **Termux 아이콘 길게 누르기 › ⓘ 앱 정보 › 다른 앱 위에 표시 › 허용**으로 켜면 됩니다. (한 번만)
   - 위젯 없이 Termux에서 `bash ~/x-media-downloader/run_mac_linux.sh` 로 실행해도 됩니다.
4. **받은 파일** — **내 파일 › 다운로드 › x-media** 에 저장되고, 갤러리 앱에도 표시됩니다.
5. **업데이트** — Termux에서 `bash setup.sh` 를 다시 실행하면 앱과 엔진이 최신으로 바뀝니다.

- 받는 중에 화면이 꺼져도 계속 받습니다. (Termux 알림에 wake lock이 표시됨) 단, 최근 앱 목록에서 Termux를 지우면 멈춥니다.
- 갤럭시에서 오래 받다가 멈춘다면: **설정 › 애플리케이션 › Termux › 배터리 › 제한 없음**으로 바꾸세요.
- 휴대폰 브라우저에는 F12(개발자 도구)가 없어서 쿠키를 보기 어렵습니다. PC에서 [3번](#3-로그인-쿠키-준비-필수) 방법으로 복사해 휴대폰에 붙여넣는 것이 가장 확실합니다.
  (메신저로 옮겼다면 붙여넣은 뒤 그 메시지는 지우세요) 휴대폰만 있다면 안드로이드용 Firefox에 Cookie-Editor 같은 쿠키 보기 부가기능을 설치하는 방법도 있습니다.

## 3. 로그인 쿠키 준비 (필수)

X는 로그인하지 않으면 게시물 목록을 보여주지 않기 때문에, PC 브라우저에 로그인된 **쿠키 값 2개**가 필요합니다.
비밀번호를 입력하는 방식이 아니라서 2단계 인증 계정도 그대로 쓸 수 있습니다.

1. PC 브라우저(크롬/엣지/파이어폭스)에서 <https://x.com> 에 로그인합니다.
2. **F12**를 눌러 개발자 도구를 엽니다.
3. 쿠키 목록을 엽니다.
   - 크롬/엣지: 위쪽 탭 **Application(애플리케이션)** → 왼쪽 **Storage › Cookies › https://x.com**
   - 파이어폭스: 위쪽 탭 **Storage(저장소)** → 왼쪽 **Cookies › https://x.com**
4. Name이 **`auth_token`** 인 줄의 Value, **`ct0`** 인 줄의 Value를 각각 복사해 앱에 붙여넣습니다.

> 쿠키를 직접 복사하는 대신 앱에서 **"브라우저에서 가져오기"**를 고를 수도 있습니다.
> 파이어폭스는 잘 되지만, 크롬/엣지는 최신 보안 정책 때문에 실패하는 경우가 많아 직접 입력을 권장합니다.
> 브라우저 확장 프로그램으로 내보낸 `cookies.txt`(Netscape 형식) 파일도 쓸 수 있습니다.

## 4. 사용법 (GUI)

1. **어디서 받을까요?** — `내 북마크` 또는 `특정 계정의 모든 게시물`을 고릅니다.
   계정은 `@nasa`, `nasa`, `https://x.com/nasa` 어떤 형태로 넣어도 됩니다.
2. **로그인 쿠키** — 위에서 복사한 `auth_token`, `ct0`를 붙여넣습니다.
   "로그인 정보 저장"을 켜 두면 다음부터는 입력하지 않아도 됩니다.
3. **옵션**
   - `사진 + 동영상` / `사진만` / `동영상만(GIF 포함)`
   - `리트윗한 게시물의 미디어도 받기` — 계정 모드에서만. 기본은 그 계정이 직접 올린 게시물만 받습니다.
   - `빠른 새로고침` (기본 켜짐) — 아래 [다시 받기(새로고침)](#다시-받기새로고침)를 참고하세요.
   - `저장 폴더` — 기본값은 다운로드 폴더 안의 `x-media` (예: `C:\Users\이름\Downloads\x-media`)
4. **다운로드 시작**을 누르면 아래 로그 창에 받은 파일이 하나씩 표시됩니다. 언제든 **중지**할 수 있고, 다시 시작하면 이어서 받습니다.

### 저장 구조

```
x-media/
├── bookmarks/                                   ← 내 북마크
│   ├── 20241026_alice_1850000000000000001_1.jpg
│   ├── 20241026_alice_1850000000000000001_2.jpg
│   └── 20241026_bob_1850000000000000002_1.mp4
└── nasa/                                        ← @nasa 계정
    └── 20241122_nasa_1860000000000000001_1.jpg
```

파일 이름은 `게시일_작성자아이디_게시물ID_순번.확장자` 입니다.
원본 게시물은 `https://x.com/작성자아이디/status/게시물ID` 로 찾아갈 수 있습니다.
저장 폴더 안의 `.download-history/` 폴더는 받은 기록이니 지우지 마세요. (아래 참고)

### 다시 받기(새로고침)

북마크를 새로 추가했거나 계정에 새 게시물이 올라왔다면, **같은 저장 폴더로 다운로드 시작을 다시 누르기만 하면 됩니다.**

- **중복 방지**: 받은 파일은 `.download-history/대상.sqlite3`에 **게시물 ID 기준**으로 기록됩니다.
  그래서 받은 파일을 다른 폴더로 옮기거나 지워도, 작성자가 아이디를 바꿔 파일 이름이 달라져도 다시 받지 않습니다.
  기록이 생기기 전에 받아 둔 파일이 폴더에 있으면 그 파일도 이미 받은 것으로 보고 기록에 추가합니다.
- **빠른 새로고침**: 북마크는 북마크한 순서, 계정은 게시 순서로 최신 것이 맨 앞에 옵니다.
  그래서 이미 받은 것이 연속으로 20개 나오면 그 뒤는 전부 받은 것으로 보고 멈춥니다. 수천 개를 처음부터 다시 훑지 않습니다.
- **처음 받기가 중간에 끊긴 경우**: 빠른 새로고침은 **전체 받기를 끝까지 한 번 마친 뒤에만** 켜집니다.
  첫 받기가 오류나 중지로 끊겼다면, 다음 실행은 자동으로 처음부터 끝까지 확인해서 빠진 것을 마저 받습니다.
- **범위를 넓힌 경우**: `사진만`으로 받다가 `사진 + 동영상`으로 바꾸거나, 리트윗 포함을 켜면
  예전 게시물의 동영상·리트윗은 받은 적이 없으므로 그 한 번은 자동으로 전체 확인을 합니다.
- 기록은 대상(북마크 / 계정)마다 따로입니다. 같은 게시물이 북마크와 계정 폴더 양쪽에 해당하면 각 폴더에 하나씩 저장됩니다.
- 일부러 **다시 받고 싶다면** `.download-history/` 안의 해당 대상 파일(`bookmarks.*` 또는 `계정아이디.*`)을 지우세요.
  그래도 폴더에 같은 이름의 파일이 있으면 그 파일은 건너뜁니다.
- 북마크를 해제하거나 게시물이 삭제돼도 이미 받은 파일은 지우지 않습니다.

## 5. 명령줄로 쓰기 (선택)

```bash
# Windows는 run_windows.bat, macOS/Linux는 bash run_mac_linux.sh 뒤에 옵션을 붙입니다
bash run_mac_linux.sh bookmarks --auth-token 값 --ct0 값 --save   # 북마크 + 로그인 정보 저장
bash run_mac_linux.sh bookmarks                                    # 저장된 로그인으로 새로고침 (새로 생긴 것만)
bash run_mac_linux.sh bookmarks --full                             # 처음부터 끝까지 다시 확인 (받은 건 그래도 건너뜀)
bash run_mac_linux.sh @nasa --only videos -o ~/Videos/x            # 특정 계정의 동영상만
bash run_mac_linux.sh @nasa --retweets                             # 리트윗한 게시물 포함
bash run_mac_linux.sh @nasa --browser firefox                      # 파이어폭스 로그인 쿠키 사용
bash run_mac_linux.sh --upgrade-engine                             # gallery-dl 업데이트
bash run_mac_linux.sh --help                                       # 전체 옵션
```

`auth_token`/`ct0`는 환경변수 `X_AUTH_TOKEN`, `X_CT0`로도 줄 수 있습니다. (명령어 기록에 남기기 싫을 때)

## 6. 문제 해결

| 증상 | 해결 |
| --- | --- |
| `로그인 쿠키가 만료됐거나 잘못됐습니다` (종료 코드 16) | 브라우저에서 x.com에 다시 로그인한 뒤 `auth_token`, `ct0`를 새로 복사하세요. X에서 로그아웃하면 기존 쿠키는 무효가 됩니다. |
| `X에서 데이터를 받지 못했습니다` (종료 코드 4) | 인터넷 연결과 계정 아이디를 확인하세요. 잘 되다가 갑자기 안 되면 X가 내부 API를 바꾼 것이니 **엔진 업데이트**를 누르세요. |
| 로그에 `Waiting until 12:34:56 (rate limit)` | X 요청 한도에 걸린 것입니다. 정상 동작이며, 시간이 되면 자동으로 이어서 받습니다. 그대로 두세요. |
| `... blocked your account` / `Tweets are protected` | 나를 차단했거나, 팔로우하지 않은 비공개 계정입니다. |
| "브라우저에서 가져오기" 실패 | 크롬/엣지에서 흔합니다. 쿠키를 직접 입력하세요. |
| GUI가 안 열림 (Linux) | `sudo apt install python3-tk` |

## 7. 주의

- **`auth_token`은 비밀번호와 같습니다.** 이 값만 있으면 누구든 내 계정으로 접속할 수 있으니 절대 공유하지 마세요.
  저장을 선택하면 `~/.x-media-downloader/settings.json`(본인만 읽기 가능)에 보관되며, 지우려면 이 파일을 삭제하거나
  "로그인 정보 저장"을 끄고 한 번 실행하세요.
- 자동 수집은 X 이용약관에서 제한될 수 있고, 아주 많이 받으면 계정이 일시적으로 제한될 수 있습니다. 본인 책임 하에 사용하세요.
- 받은 사진·동영상의 저작권은 원작자에게 있습니다. 개인 보관 용도로만 사용하세요.

## 개발자용

```
x_media_downloader.py   앱 전체 (설정 생성 → gallery-dl 실행 → 결과 표시, GUI/CLI)
tests/                  단위 테스트 (네트워크 불필요)
requirements.txt        gallery-dl
run_windows.bat         Windows 실행기 (.venv 생성 + 설치 + 실행)
run_mac_linux.sh        macOS/Linux/안드로이드(Termux) 실행기
setup_android.sh        안드로이드 Termux 설치·업데이트 (앱 내려받기, 엔진 설치, 홈 화면 버튼)
```

테스트: `python -m unittest discover -s tests -v`

gallery-dl(GPL-2.0)은 이 폴더에 포함되지 않으며, 실행 시 pip로 별도 설치되는 외부 프로그램으로 호출합니다.
