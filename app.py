import asyncio
import logging
import random
import xml.etree.ElementTree as ET
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Optional
from urllib.parse import quote

log = logging.getLogger("rss-resolver")
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

import httpx
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from playwright.async_api import async_playwright

# 4개의 일관된 프로파일 세트 (UA + platform + locale + timezone + viewport).
PROFILES = [
    {
        "user_agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
        "locale": "ko-KR",
        "timezone_id": "Asia/Seoul",
        "viewport": {"width": 1440, "height": 900},
        "extra_http_headers": {"Accept-Language": "ko-KR,ko;q=0.9,en-US;q=0.8"},
    },
    {
        "user_agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
        "locale": "ko-KR",
        "timezone_id": "Asia/Seoul",
        "viewport": {"width": 1920, "height": 1080},
        "extra_http_headers": {"Accept-Language": "ko-KR,ko;q=0.9"},
    },
    {
        "user_agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.4 Safari/605.1.15",
        "locale": "en-US",
        "timezone_id": "America/Los_Angeles",
        "viewport": {"width": 1680, "height": 1050},
        "extra_http_headers": {"Accept-Language": "en-US,en;q=0.9"},
    },
    {
        "user_agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
        "locale": "en-GB",
        "timezone_id": "Europe/London",
        "viewport": {"width": 1536, "height": 864},
        "extra_http_headers": {"Accept-Language": "en-GB,en;q=0.9"},
    },
]

POOL_SIZE = len(PROFILES)

# RSS 다운로드는 별개로 고정 UA 사용.
FEED_UA = PROFILES[0]["user_agent"]

state: dict = {}


async def _make_pool():
    browser = state["browser"]
    contexts = [await browser.new_context(**p) for p in PROFILES]
    pool: asyncio.Queue = asyncio.Queue()
    for c in contexts:
        pool.put_nowait(c)
    return contexts, pool


async def _close_pool(contexts):
    for c in contexts:
        try:
            await c.close()
        except Exception:
            pass


@asynccontextmanager
async def lifespan(app: FastAPI):
    pw = await async_playwright().start()
    browser = await pw.chromium.launch(headless=True)
    state["pw"] = pw
    state["browser"] = browser
    contexts, pool = await _make_pool()
    state["contexts"] = contexts
    state["pool"] = pool
    state["sem"] = asyncio.Semaphore(POOL_SIZE)
    state["cache"] = {}
    try:
        yield
    finally:
        await _close_pool(state["contexts"])
        await browser.close()
        await pw.stop()


app = FastAPI(lifespan=lifespan)


async def _reset_pool():
    await _close_pool(state.get("contexts", []))
    contexts, pool = await _make_pool()
    state["contexts"] = contexts
    state["pool"] = pool
    state["sem"] = asyncio.Semaphore(POOL_SIZE)
    state["cache"] = {}


@app.get("/api/feed")
async def feed(q: str, hl: str = "ko", gl: str = "KR", ceid: str = "KR:ko"):
    await _reset_pool()
    url = f"https://news.google.com/rss/search?q={q}&hl={hl}&gl={gl}&ceid={ceid}"
    async with httpx.AsyncClient(headers={"User-Agent": FEED_UA}, timeout=15) as client:
        resp = await client.get(url)
        resp.raise_for_status()

    root = ET.fromstring(resp.content)
    items = []
    for item in root.findall("./channel/item"):
        items.append({
            "title": (item.findtext("title") or "").strip(),
            "link": (item.findtext("link") or "").strip(),
            "pubDate": (item.findtext("pubDate") or "").strip(),
            "source": (item.findtext("source") or "").strip(),
        })
    return {"items": items}


async def _resolve_with_context(context, url: str, timeout_ms: int = 10000) -> Optional[str]:
    page = await context.new_page()
    batch_error = asyncio.Event()

    def _on_response(resp):
        if "batchexecute" not in resp.url or "Fbv4je" not in resp.url:
            return
        async def _check():
            try:
                body = await resp.text()
                if "null,null,null,[5]" in body:
                    batch_error.set()
            except Exception:
                pass
        asyncio.ensure_future(_check())

    page.on("response", _on_response)
    try:
        try:
            await page.goto(url, wait_until="domcontentloaded", timeout=timeout_ms)
        except Exception:
            pass

        if batch_error.is_set():
            return None

        wait_redirect = asyncio.ensure_future(
            page.wait_for_url(lambda u: "news.google.com" not in u, timeout=timeout_ms)
        )
        wait_error = asyncio.ensure_future(batch_error.wait())
        try:
            _, pending = await asyncio.wait(
                [wait_redirect, wait_error],
                return_when=asyncio.FIRST_COMPLETED,
            )
        except Exception:
            pending = {wait_redirect, wait_error}

        for t in pending:
            t.cancel()
        for t in (wait_redirect, wait_error):
            if not t.done():
                continue
            try:
                t.result()
            except Exception:
                pass

        if batch_error.is_set():
            return None

        final = page.url
        return final if "news.google.com" not in final else None
    finally:
        try:
            await page.close()
        except Exception:
            pass


import re

def _tokenize(s: str) -> set:
    return set(re.findall(r'[\w]+', s.lower()))


def _similarity(a: str, b: str) -> tuple[float, str]:
    sa = _tokenize(a)
    sb = _tokenize(b)
    if not sa or not sb:
        return 0.0, "none"
    intersection = len(sa & sb)
    jaccard = intersection / len(sa | sb)
    containment = intersection / len(sa)
    if containment > jaccard:
        return containment, "containment"
    return jaccard, "jaccard"


async def _fetch_rss_items(query: str, hl: str = "ko", gl: str = "KR", ceid: str = "KR:ko"):
    encoded_q = quote(query, safe="")
    url = f"https://news.google.com/rss/search?q={encoded_q}&hl={hl}&gl={gl}&ceid={ceid}"
    log.info("[fallback] RSS search: %s", url[:200])
    async with httpx.AsyncClient(headers={"User-Agent": FEED_UA}, timeout=15) as client:
        resp = await client.get(url)
        resp.raise_for_status()
    root = ET.fromstring(resp.content)
    items = []
    for item in root.findall("./channel/item"):
        items.append({
            "title": (item.findtext("title") or "").strip(),
            "link": (item.findtext("link") or "").strip(),
        })
    log.info("[fallback] candidates found: %d", len(items))
    return items


SIMILARITY_THRESHOLD = 0.5


def _has_korean(s: str) -> bool:
    return any('\uac00' <= c <= '\ud7a3' for c in s)


async def _fallback_by_title(title: str) -> Optional[str]:
    words = title.split()
    query = " ".join(words[:8]) if len(words) > 8 else title
    if _has_korean(title):
        hl, gl, ceid = "ko", "KR", "KR:ko"
    else:
        hl, gl, ceid = "en", "US", "US:en"
    log.info("[fallback] title='%s' query='%s' locale=%s", title, query, hl)
    try:
        candidates = await _fetch_rss_items(query, hl=hl, gl=gl, ceid=ceid)
    except Exception as e:
        log.error("[fallback] RSS fetch failed: %s", e)
        return None, 0.0, "none"
    if not candidates:
        log.info("[fallback] no candidates")
        return None, 0.0, "none"

    best_score = 0.0
    best_method = "none"
    best_link = None
    for c in candidates:
        score, method = _similarity(title, c["title"])
        if score > best_score:
            best_score = score
            best_method = method
            best_link = c["link"]
        if score > 0.1:
            log.info("[fallback]   score=%.3f (%s) '%s'", score, method, c["title"][:60])

    log.info("[fallback] best=%.3f (%s) threshold=%.1f link=%s",
             best_score, best_method, SIMILARITY_THRESHOLD, (best_link or "")[:80])

    if best_score < SIMILARITY_THRESHOLD or not best_link:
        return None, best_score, best_method
    return best_link, best_score, best_method


async def _resolve_one(url: str) -> Optional[str]:
    pool: asyncio.Queue = state["pool"]
    context = await pool.get()
    try:
        return await _resolve_with_context(context, url)
    finally:
        pool.put_nowait(context)


@app.get("/api/resolve")
async def resolve(url: str, title: str = ""):
    if not url.startswith("https://news.google.com/"):
        raise HTTPException(400, "not a google news url")
    cache = state["cache"]
    if url in cache:
        return {"url": url, "final_url": cache[url], "cached": True}

    async with state["sem"]:
        if url in cache:
            return {"url": url, "final_url": cache[url], "cached": True}

        await asyncio.sleep(random.uniform(0.6, 1.2))
        final = await _resolve_one(url)

        if final:
            cache[url] = final
            return {"url": url, "final_url": final, "cached": False}

        if not title:
            return {"url": url, "final_url": None, "cached": False}

        alt_link, score, method = await _fallback_by_title(title)
        if not alt_link or alt_link == url:
            return {"url": url, "final_url": None, "cached": False,
                    "fallback_attempted": True,
                    "similarity": round(score, 3), "method": method}

        await asyncio.sleep(random.uniform(0.6, 1.2))
        final = await _resolve_one(alt_link)
        if final:
            cache[url] = final

    return {"url": url, "final_url": final, "cached": False,
            "fallback": True, "similarity": round(score, 3), "method": method}


static_dir = Path(__file__).parent / "static"
app.mount("/static", StaticFiles(directory=static_dir), name="static")


@app.get("/")
async def index():
    return FileResponse(static_dir / "index.html")
