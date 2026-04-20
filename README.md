# Google News RSS Resolver

Playwright로 Google News RSS의 `news.google.com/rss/articles/CBM...` 링크를 실제 기사 URL로 변환하는 웹 UI.

## 스택

백엔드:

- Python 3 (venv)
- FastAPI — HTTP API 프레임워크
- Uvicorn — ASGI 서버
- httpx — 비동기 HTTP 클라이언트 (RSS 피드 다운로드)
- `xml.etree.ElementTree` — RSS XML 파싱 (표준 라이브러리)
- Playwright (Chromium, headless) — Google News 링크를 실제 기사 URL로 해석
- **컨텍스트 풀(4개)** — 서로 다른 UA/locale/timezone/viewport/Accept-Language 세트
- `asyncio.Semaphore(4)` + 0.6~1.2초 지터 — 동시성 제한 및 레이트리밋 회피
- 프로세스 메모리 `dict` 캐시 — 피드 갱신 시 초기화

프론트엔드:

- 바닐라 HTML/CSS/JavaScript (프레임워크 없음)
- `fetch` + `AbortController` — 해석 요청/중단

## 설치

가상환경(venv) 생성 및 활성화:

```bash
python3 -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate
```

의존성 설치:

```bash
pip install --upgrade pip
pip install -r requirements.txt
playwright install chromium
```

## 실행

```bash
uvicorn app:app --reload
```

가상환경을 활성화하지 않고 바로 실행하려면:

```bash
.venv/bin/uvicorn app:app --reload
```

브라우저에서 http://localhost:8000 접속.

## 구성

- `GET /api/feed?q=검색어` — Google News RSS를 파싱해 항목 목록 반환
- `GET /api/resolve?url=...` — Playwright(Chromium headless)로 URL을 따라가 실제 기사 주소 반환
- `static/index.html` — 검색 → 목록 표시 → 항목별/일괄 해석 UI

## 컨텍스트 풀 구조

탐지 회피와 병렬 처리를 위해 **4개의 독립된 Playwright 브라우저 컨텍스트**를 풀로 유지합니다. 각 컨텍스트는 서로 다른 "사용자 프로파일"을 가지며, 모든 요소가 **일관된 세트**로 구성되어 있어 지문 불일치로 의심받지 않습니다.

| # | User-Agent | locale | timezone | viewport |
|---|---|---|---|---|
| 1 | Mac / Chrome 124 | ko-KR | Asia/Seoul | 1440×900 |
| 2 | Windows / Chrome 124 | ko-KR | Asia/Seoul | 1920×1080 |
| 3 | Mac / Safari 17.4 | en-US | America/Los_Angeles | 1680×1050 |
| 4 | Linux / Chrome 124 | en-GB | Europe/London | 1536×864 |

동작 방식:

- 요청이 들어오면 `asyncio.Queue`로 구현된 풀에서 컨텍스트 하나를 꺼내고, 해석 후 반납합니다.
- `Semaphore(4)`로 전체 동시 요청을 4개로 제한. 각 컨텍스트가 동시에 최대 1개의 페이지만 다룹니다.
- 컨텍스트 획득 전 0.6~1.2초의 지터를 넣어 같은 컨텍스트로 연속 요청이 몰리지 않게 합니다.
- "피드 가져오기"를 누르면 풀 전체를 재생성해 이전 세션의 쿠키·캐시를 모두 초기화합니다.

이 구조는 단일 컨텍스트·순차 처리 구조 대비 쿠키/세션의 누적 시그널을 4개로 분산시키고, 처리 속도도 이론상 약 4배로 향상됩니다.

### 벤치마크

위 구성으로 한 번 측정 시, 캐시 미스 상태에서 **100개 항목 해석에 약 1분 37초**가 걸렸습니다. 네트워크 상태 및 Google의 응답 지연에 따라 달라집니다.
