import asyncio
import random
import xml.etree.ElementTree as ET
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Optional

import httpx
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from playwright.async_api import async_playwright

UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)

state: dict = {}


@asynccontextmanager
async def lifespan(app: FastAPI):
    pw = await async_playwright().start()
    browser = await pw.chromium.launch(headless=True)
    context = await browser.new_context(user_agent=UA)
    state["pw"] = pw
    state["browser"] = browser
    state["context"] = context
    state["sem"] = asyncio.Semaphore(1)
    state["cache"] = {}
    try:
        yield
    finally:
        await context.close()
        await browser.close()
        await pw.stop()


app = FastAPI(lifespan=lifespan)


async def _reset_context():
    old = state.get("context")
    if old is not None:
        try:
            await old.close()
        except Exception:
            pass
    state["context"] = await state["browser"].new_context(user_agent=UA)
    state["cache"] = {}
    state["sem"] = asyncio.Semaphore(1)


@app.get("/api/feed")
async def feed(q: str, hl: str = "ko", gl: str = "KR", ceid: str = "KR:ko"):
    await _reset_context()
    url = f"https://news.google.com/rss/search?q={q}&hl={hl}&gl={gl}&ceid={ceid}"
    async with httpx.AsyncClient(headers={"User-Agent": UA}, timeout=15) as client:
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


async def _resolve(url: str, timeout_ms: int = 15000) -> Optional[str]:
    context = state["context"]
    page = await context.new_page()
    try:
        try:
            await page.goto(url, wait_until="domcontentloaded", timeout=timeout_ms)
        except Exception:
            pass
        try:
            await page.wait_for_url(
                lambda u: "news.google.com" not in u,
                timeout=timeout_ms,
            )
        except Exception:
            pass
        final = page.url
        return final if "news.google.com" not in final else None
    finally:
        await page.close()


@app.get("/api/resolve")
async def resolve(url: str):
    if not url.startswith("https://news.google.com/"):
        raise HTTPException(400, "not a google news url")
    cache = state["cache"]
    if url in cache:
        return {"url": url, "final_url": cache[url], "cached": True}
    async with state["sem"]:
        if url in cache:
            return {"url": url, "final_url": cache[url], "cached": True}
        await asyncio.sleep(random.uniform(1.0, 2.0))
        final = await _resolve(url)
        if final:
            cache[url] = final
    return {"url": url, "final_url": final, "cached": False}


static_dir = Path(__file__).parent / "static"
app.mount("/static", StaticFiles(directory=static_dir), name="static")


@app.get("/")
async def index():
    return FileResponse(static_dir / "index.html")
