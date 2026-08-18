import asyncio
from playwright.async_api import async_playwright

async def main():
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page()
        print("Going to localhost:8000...")
        await page.goto("http://localhost:8000")
        print("Waiting for #app...")
        await page.wait_for_selector("#app", timeout=10000)
        await asyncio.sleep(2)

        print("Calling playGreeting...")
        await page.evaluate("if(window.mentor3DScene) window.mentor3DScene.playGreeting()")

        # 360 turn + jump take some time. Wave starts at greetingTime > 1.7.
        # Peak wave is around 1.7 + (1.05 * 0.5) = 2.225.
        await asyncio.sleep(2.2)

        print("Taking peak wave screenshot...")
        await page.screenshot(path="wave_peak.png")

        await asyncio.sleep(1.5)
        print("Taking post wave screenshot...")
        await page.screenshot(path="wave_end.png")

        await browser.close()
        print("Done!")

if __name__ == "__main__":
    asyncio.run(main())
