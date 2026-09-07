"""Mo mot profile ra man hinh de nguoi van hanh tu nhin va tu thao tac.

    python scripts/open_profile.py <profile_id> [url]

Khac `takeover.py open` o mot cho: cai kia gan voi hang doi checkpoint va cho nguoi
go Enter vao console. Cai nay khong can console - dashboard goi no chay nen, va no
tu ket thuc khi ban DONG CUA SO. Nho vay bam mot nut trong CMS la co cua so hien ra.

Cookie duoc luu lai dinh ky va luu lan cuoi khi dong. Neu ban dang nhap lai, giai
captcha, hay doi gi do bang tay trong cua so do, he thong giu duoc ket qua.
"""

from __future__ import annotations

import asyncio
import sys
import uuid

from seeding.browser.session import PROBES, open_profile
from seeding.core import profiles as profiles_mod
from seeding.core import readiness
from seeding.db import SessionLocal, engine
from seeding.models import Account, Profile

# Luu cookie moi tung nay giay. Trinh duyet mo lau ma sap nguon hay treo may thi van
# con lai phan lon tien do.
SAVE_EVERY = 20
# Tran cung: mot cua so bi quen khong duoc giu trinh duyet song mai. ~400MB moi phien.
MAX_MINUTES = 120


async def main(profile_id: str, url: str | None) -> int:
    async with SessionLocal() as session:
        profile = await session.get(Profile, uuid.UUID(profile_id))
        if profile is None:
            print(f"Khong co profile {profile_id}")
            return 1

        account = await session.get(Account, profile.account_id)
        if account is None:
            print("Profile nay khong gan voi tai khoan nao")
            return 1

        # Cung lop chan nhu job dang bai. Mo tay khong phai la ngoai le: mot profile
        # khong co proxy thi mo ra la duyet bang IP nha ban, va TikTok ghi lai dieu do
        # y het nhu khi worker lam. Bat buoc phai co proxy.
        verdict = readiness.check(account, profile)
        if not verdict.ready and profile.proxy_id is None:
            print(f"Khong mo duoc: {verdict.reason}")
            return 2

        probe = PROBES.get(account.platform)
        start = url or (probe.feed_url if probe else "about:blank")

        print(f"Dang mo {account.handle} ({account.platform.value}) tai {start}")
        print("Dong cua so lai la xong. Cookie se duoc luu lai.")

        last_state = None
        async with open_profile(profile, headless=False, humanize=True) as (_b, context):
            page = await context.new_page()
            try:
                await page.goto(start, wait_until="domcontentloaded", timeout=180_000)
            except Exception as exc:
                # Trang khong tai duoc thi cua so van cu mo - nguoi dung con go tay
                # dia chi khac duoc. Bao loi roi thoat la lam hong dung muc dich.
                print(f"Trang dau khong tai duoc ({type(exc).__name__}), cua so van mo.")

            for _ in range(MAX_MINUTES * 60 // SAVE_EVERY):
                try:
                    last_state = await context.storage_state()
                except Exception:
                    # Nem loi = nguoi dung da dong trinh duyet. Do la duong ket thuc
                    # binh thuong cua ham nay, khong phai loi.
                    print("Cua so da dong.")
                    break
                await asyncio.sleep(SAVE_EVERY)
            else:
                print(f"Da mo qua {MAX_MINUTES} phut - tu dong dong lai.")

        if last_state and last_state.get("cookies"):
            await profiles_mod.save_cookies(session, profile, last_state)
            print(f"Da luu {len(last_state['cookies'])} cookie.")

    await engine.dispose()
    return 0


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print(__doc__)
        raise SystemExit(1)
    raise SystemExit(asyncio.run(main(sys.argv[1], sys.argv[2] if len(sys.argv) > 2 else None)))
