"""Do xem tung proxy co TAI DUOC web TikTok khong - tieu chi chon proxy cho viec bam
(tha tim / follow / binh luan) bang trinh duyet.

    .venv\\Scripts\\python.exe scripts\\check_proxy_tiktok.py            # moi proxy trong DB
    .venv\\Scripts\\python.exe scripts\\check_proxy_tiktok.py P03 HA1    # chi vai proxy

Moi proxy: mo trang video TikTok trong Camoufox (an, KHONG cookie, khong tai khoan), di chuot
va cuon nhe moi 20 giay, do bao lau thi thanh hanh dong (nut tim/binh luan) hien ra. Qua
LIMIT giay ma chua co thi proxy do khong dung duoc cho viec bam.

Do that 08/09/2026: khong proxy 45s; P03 ~100-170s va luc duoc luc khong; HA1 khong bao gio.
"""

from __future__ import annotations

import asyncio
import sys
import time

from sqlalchemy import select

sys.path.insert(0, "src")
sys.stdout.reconfigure(encoding="utf-8")

from camoufox.async_api import AsyncCamoufox  # noqa: E402

from seeding.db import SessionLocal  # noqa: E402
from seeding.domain.models import Proxy  # noqa: E402

URL = "https://www.tiktok.com/@tiktok/video/7106594312292453675"
LIMIT = 240
JS = r"""() => ({
  e2e: document.querySelectorAll('[data-e2e]').length,
  bar: !!document.querySelector(
    '[class*="DivActionBarContainer"] button, '
    + '[class*="SectionActionBarContainer"] button, [data-e2e*="like-icon"]'),
  video: !!document.querySelector('video'),
  err: /Không thể mở trang|Something went wrong|Access Denied/i.test(document.body.innerText || '')
})"""


async def measure(proxy: Proxy) -> str:
    opts = {
        "headless": True,
        "humanize": False,
        "proxy": proxy.as_playwright_proxy(),
        "geoip": True,
    }
    t0 = time.monotonic()
    try:
        async with AsyncCamoufox(**opts) as browser:
            ctx = await browser.new_context()
            page = await ctx.new_page()
            try:
                await page.goto(URL, wait_until="domcontentloaded", timeout=LIMIT * 1000)
            except Exception as exc:
                return (
                    f"KHONG tai duoc trang: {type(exc).__name__} sau {time.monotonic() - t0:.0f}s"
                )
            dom = time.monotonic() - t0
            while time.monotonic() - t0 < LIMIT:
                await asyncio.sleep(20)
                try:
                    await page.mouse.move(640, 400)
                    await page.mouse.wheel(0, 120)
                    await page.mouse.wheel(0, -120)
                except Exception:
                    pass
                info = await page.evaluate(JS)
                if info["err"]:
                    return f"TikTok bao loi trang sau {time.monotonic() - t0:.0f}s"
                if info["bar"]:
                    return (
                        f"OK - thanh hanh dong sau {time.monotonic() - t0:.0f}s (khung {dom:.0f}s)"
                    )
            return (
                f"KHONG hien thanh hanh dong trong {LIMIT}s "
                f"(khung {dom:.0f}s, e2e={info['e2e']}, video={info['video']})"
            )
    except Exception as exc:
        return f"loi mo trinh duyet: {type(exc).__name__}: {str(exc)[:80]}"


async def main() -> None:
    wanted = set(sys.argv[1:])
    async with SessionLocal() as s:
        proxies = list((await s.execute(select(Proxy).order_by(Proxy.label))).scalars())
    for p in proxies:
        if wanted and p.label not in wanted:
            continue
        print(f"{p.label:6} {p.host:32} ", end="", flush=True)
        print(await measure(p), flush=True)


if __name__ == "__main__":
    asyncio.run(main())
