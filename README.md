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
- `asyncio.Semaphore(1)` + 1~2초 지터 — 동시성 제한 및 레이트리밋 회피
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
