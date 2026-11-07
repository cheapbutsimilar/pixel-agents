# X(트위터) 미디어 다운로더

**내 북마크** 또는 **특정 계정의 모든 게시물**에 있는 사진·동영상을 한 번에 내려받는 간단한 앱입니다.

- 사진은 원본 해상도, 동영상은 가장 높은 화질로 저장합니다. (GIF는 X에서 mp4로 제공되므로 mp4로 저장)
- 이미 받은 파일은 건너뛰므로 여러 번 실행해도 새로 생긴 것만 추가로 받습니다.
- GUI(창)와 명령줄 둘 다 지원합니다.

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
   - `새 게시물만 받기` — 이미 받은 파일이 연속 20개 나오면 멈춥니다. 한 번 전체를 받은 뒤 정기적으로 새 북마크만 받을 때 빠릅니다.
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

## 5. 명령줄로 쓰기 (선택)

```bash
# Windows는 run_windows.bat, macOS/Linux는 bash run_mac_linux.sh 뒤에 옵션을 붙입니다
bash run_mac_linux.sh bookmarks --auth-token 값 --ct0 값 --save   # 북마크 + 로그인 정보 저장
bash run_mac_linux.sh bookmarks --update                           # 저장된 로그인으로 새 북마크만
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
run_mac_linux.sh        macOS/Linux 실행기
```

테스트: `python -m unittest discover -s tests -v`

gallery-dl(GPL-2.0)은 이 폴더에 포함되지 않으며, 실행 시 pip로 별도 설치되는 외부 프로그램으로 호출합니다.
