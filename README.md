# Google News RSS Resolver

Playwright로 Google News RSS의 `news.google.com/rss/articles/CBM...` 링크를 실제 기사 URL로 변환하는 웹 UI.

## 설치

```bash
pip install -r requirements.txt
playwright install chromium
```

## 실행

```bash
uvicorn app:app --reload
```

브라우저에서 http://localhost:8000 접속.

## 구성

- `GET /api/feed?q=검색어` — Google News RSS를 파싱해 항목 목록 반환
- `GET /api/resolve?url=...` — Playwright(Chromium headless)로 URL을 따라가 실제 기사 주소 반환
- `static/index.html` — 검색 → 목록 표시 → 항목별/일괄 해석 UI
