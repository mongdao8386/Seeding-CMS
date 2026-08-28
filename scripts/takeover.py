"""Hang doi can thiep tay: xem, giai, hoac bo.

    python scripts/takeover.py list
    python scripts/takeover.py open <platform> <handle>      mo trinh duyet de giai
    python scripts/takeover.py resolve <platform> <handle> "da giai captcha"
    python scripts/takeover.py abandon <platform> <handle> "acc bi khoa han"

`open` mo Camoufox voi dung fingerprint, proxy va cookie cua tai khoan do, ngay tren
trang no bi ket. Ban giai captcha hoac nhap ma xac minh, roi chay `resolve`.

Ma 2FA duoc in san neu tai khoan da luu totp_seed.

Ghi chu ve noVNC: khi worker chay trong container tren may chu, thao tac nay se dien
ra qua noVNC ngay trong dashboard - worker giu nguyen trinh duyet dang mo va phat man
hinh ra. Tren may ca nhan thi khong can lop do: cua so trinh duyet hien ngay truoc mat.
Co che trang thai la mot, chi khac duong truyen hinh anh.
"""

from __future__ import annotations

import asyncio
import sys

from sqlalchemy import select

from seeding.browser.session import PROBES, open_profile
from seeding.core import profiles as profiles_mod
from seeding.core import takeover, vault
from seeding.db import SessionLocal, engine
from seeding.models import Account, Platform


async def _find(session, platform_name: str, handle: str) -> Account | None:
    try:
        platform = Platform(platform_name.lower())
    except ValueError:
        print(f"Nen tang khong hop le: {platform_name}")
        print("Chon mot trong:", ", ".join(p.value for p in Platform))
        return None

    stmt = select(Account).where(Account.platform == platform, Account.handle == handle)
    account = (await session.execute(stmt)).scalar_one_or_none()
    if account is None:
        print(f"Khong tim thay {handle} tren {platform.value}.")
    return account


async def cmd_list() -> int:
    async with SessionLocal() as session:
        requests = await takeover.list_open(session)
        if not requests:
            print("Hang doi trong.")
            return 0

        print(f"\n{len(requests)} tai khoan dang cho:\n")
        for r in requests:
            age = r.created_at.strftime("%d/%m %H:%M")
            plat, handle = r.account.platform.value, r.account.handle
            print(f"  {plat:<10} {handle:<16} tu {age}")
            print(f"    {r.reason}")
            print(f"    giai bang: python scripts/takeover.py open {plat} {handle}\n")
    return 0


async def cmd_open(platform_name: str, handle: str) -> int:
    async with SessionLocal() as session:
        account = await _find(session, platform_name, handle)
        if account is None:
            return 1

        request = await takeover.open_for_account(session, account.id)
        if request is None:
            print(f"{handle} khong nam trong hang doi cho nguoi.")
            return 1

        profile = await profiles_mod.get_for_account(session, account.id)
        if profile is None:
            print(f"{handle} chua co profile.")
            return 1

        print(f"\nLy do bi ket: {request.reason}")

        secrets = account.get_secrets()
        if secrets.get("totp_seed"):
            print(f"Ma 2FA hien tai: {vault.totp_now(secrets['totp_seed'])} (doi moi 30 giay)")

        probe = PROBES.get(account.platform)
        start_url = probe.feed_url if probe else "about:blank"

        print(f"Dang mo trinh duyet cho {handle}...")
        async with open_profile(profile, headless=False, humanize=True) as (_b, context):
            page = await context.new_page()
            await page.goto(start_url)

            print("\n" + "=" * 62)
            print("  Giai checkpoint trong cua so vua mo, ROI quay lai day an Enter.")
            print("  Cookie moi se duoc luu lai.")
            print("=" * 62)
            await asyncio.to_thread(input, "\nXong roi? An Enter: ")

            state = await context.storage_state()

        if state.get("cookies"):
            await profiles_mod.save_cookies(session, profile, state)
            print(f"Da luu lai {len(state['cookies'])} cookie.")

        print(
            f"\nNeu da giai xong, chot bang:\n  python scripts/takeover.py resolve "
            f'{account.platform.value} {handle} "mo ta ngan"'
        )
    await engine.dispose()
    return 0


async def cmd_resolve(platform_name: str, handle: str, note: str) -> int:
    async with SessionLocal() as session:
        account = await _find(session, platform_name, handle)
        if account is None:
            return 1

        request = await takeover.open_for_account(session, account.id)
        if request is None:
            print(f"{handle} khong nam trong hang doi.")
            return 1

        await takeover.resolve(session, request, by="cli", note=note)
        print(f"Da chot. {handle} tro lai trang thai WARMING.")
        if request.post_job_id:
            print("Job bi ket da duoc hen lai sau 6 tieng, khong chay ngay.")
    await engine.dispose()
    return 0


async def cmd_abandon(platform_name: str, handle: str, note: str) -> int:
    async with SessionLocal() as session:
        account = await _find(session, platform_name, handle)
        if account is None:
            return 1

        request = await takeover.open_for_account(session, account.id)
        if request is None:
            print(f"{handle} khong nam trong hang doi.")
            return 1

        await takeover.abandon(session, request, by="cli", note=note)
        print(f"Da bo {handle}. Trang thai chuyen sang DEAD.")
    await engine.dispose()
    return 0


def main(argv: list[str]) -> int:
    if not argv:
        print(__doc__)
        return 2

    command, rest = argv[0], argv[1:]

    if command == "list":
        return asyncio.run(cmd_list())
    if command == "open" and len(rest) == 2:
        return asyncio.run(cmd_open(*rest))
    if command == "resolve" and len(rest) == 3:
        return asyncio.run(cmd_resolve(*rest))
    if command == "abandon" and len(rest) == 3:
        return asyncio.run(cmd_abandon(*rest))

    print(__doc__)
    return 2


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
