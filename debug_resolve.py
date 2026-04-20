import asyncio
from playwright.async_api import async_playwright

URLS = [
    "https://news.google.com/rss/articles/CBMiU0FVX3lxTE9GT0U5dGhFZTdLdkh2N19pbjFlNy1FU0NJTlZISlFNaWxlOW1TOFVLb1NXazFlb3NTXzRMS0ZaZFEtOWpqeWlrOGhfNHRDeFhDN0I0",
    "https://news.google.com/rss/articles/CBMivAFBVV95cUxOY0N0ZzlKYlJnR3JiWVhiUWNBOTdQSGFCczVfcEpzbEN2Mmt5WlNoeFhLRmNEVmdqREFsckZVeUQzZWREYmhEU0NWWm5PVFlRV2g0WW1XcmhhRWZrMXhqZVF4SVBJUmZkNzlnT0RZRWpjS0pka2lDN0V3TXpXY1pZXzNxV2ZjV1JVRzNpVV9QNkU1cHVkZ2tsdVoyQUhOMEZKekpRd1E5SEFXX0dtMnZEdHJUXy1zdjF4QUVJNA",
]

UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"


async def test(browser, label, context_kwargs, url_suffix):
    print("\n" + "#" * 80)
    print("#", label)
    print("#" * 80)
    context = await browser.new_context(**context_kwargs)
    for url in URLS:
        full = url + url_suffix
        print("-" * 60)
        print("OPEN:", full[:120], "...")
        page = await context.new_page()
        bodies = []

        async def on_response(resp):
            if "batchexecute" in resp.url and "Fbv4je" in resp.url:
                try:
                    bodies.append(await resp.text())
                except Exception:
                    pass

        page.on("response", on_response)
        try:
            await page.goto(full, wait_until="domcontentloaded", timeout=20000)
        except Exception as e:
            print("goto error:", e)
        try:
            await page.wait_for_url(lambda u: "news.google.com" not in u, timeout=8000)
        except Exception:
            pass
        print("final:", page.url[:120])
        for b in bodies:
            snippet = b[:250].replace("\n", " ")
            print("Fbv4je:", snippet)
        await page.close()
    await context.close()


async def main():
    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=True)

        await test(browser, "A. Korean locale + Accept-Language",
                   dict(user_agent=UA, locale="ko-KR",
                        extra_http_headers={"Accept-Language": "ko-KR,ko;q=0.9"}),
                   "")

        await test(browser, "B. Explicit ?hl=ko&gl=KR&ceid=KR:ko in URL",
                   dict(user_agent=UA),
                   "?hl=ko&gl=KR&ceid=KR:ko")

        await test(browser, "C. Both combined",
                   dict(user_agent=UA, locale="ko-KR",
                        extra_http_headers={"Accept-Language": "ko-KR,ko;q=0.9"}),
                   "?hl=ko&gl=KR&ceid=KR:ko")

        await browser.close()


asyncio.run(main())
