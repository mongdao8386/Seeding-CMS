"""Dang nhap ban thu cong cho mot tai khoan, roi luu phien lai.

    python scripts/login_profile.py <platform> <handle>
    python scripts/login_profile.py threads em_haiyen

Kich ban:
  1. Script mo Camoufox voi dung fingerprint va proxy cua profile do.
  2. BAN dang nhap bang tay trong cua so vua mo - ke ca 2FA va captcha.
  3. Quay lai terminal, an Enter. Script luu cookie jar (da ma hoa) vao profile.

Vi sao lam bang tay: dang nhap la hanh dong rui ro nhat trong ca he thong. Lam mot
lan roi giu phien mai mai an toan hon nhieu so voi tu dong dang nhap lai moi lan
phien chet. Khi phien chet that, hay chay lai script nay chu dung viet code tu login.

Neu tai khoan co 2FA va ban da luu totp_seed vao ket bi mat, script se in san ma
cho ban dan vao.
"""

from __future__ import annotations

import asyncio
import sys

from sqlalchemy import select

from seeding.browser.session import PROBES, open_profile
from seeding.core import profiles as profiles_mod
from seeding.core import vault
from seeding.db import SessionLocal, engine
from seeding.models import Account, Platform, SessionEventKind


async def main(platform_name: str, handle: str) -> int:
    try:
        platform = Platform(platform_name.lower())
    except ValueError:
        print(f"Nen tang khong hop le: {platform_name}")
        print("Chon mot trong:", ", ".join(p.value for p in Platform))
        return 2

    async with SessionLocal() as session:
        account = (
            await session.execute(
                select(Account).where(Account.platform == platform, Account.handle == handle)
            )
        ).scalar_one_or_none()

        if account is None:
            print(f"Khong tim thay tai khoan {handle} tren {platform.value}.")
            return 1

        profile = await profiles_mod.get_for_account(session, account.id)
        if profile is None:
            profile = await profiles_mod.create_profile(session, account)
            print(f"Da tao profile moi cho {handle}.")

        if profile.proxy is None:
            print("CANH BAO: profile nay chua gan proxy. Dang nhap qua IP cua chinh may ban")
            print("          se gan tai khoan voi dia chi that. Chi lam vay khi dang thu.")

        probe = PROBES.get(platform)
        login_url = probe.login_url if probe else "about:blank"

        secrets = account.get_secrets()
        if secrets.get("totp_seed"):
            print(f"Ma 2FA hien tai: {vault.totp_now(secrets['totp_seed'])} (doi moi 30 giay)")

        print(f"\nDang mo trinh duyet cho {handle} ({platform.value})...")
        async with open_profile(profile, headless=False, humanize=True) as (_browser, context):
            page = await context.new_page()
            await page.goto(login_url)

            print("\n" + "=" * 62)
            print("  Dang nhap trong cua so vua mo, ROI quay lai day an Enter.")
            print("  Dung dong cua so trinh duyet - script se tu dong.")
            print("=" * 62)
            await asyncio.to_thread(input, "\nXong roi? An Enter de luu phien: ")

            state = await context.storage_state()

        if not state.get("cookies"):
            print("Khong thay cookie nao. Phien chua duoc luu.")
            await profiles_mod.record_event(
                session, profile, SessionEventKind.HEALTH_FAIL, "dang nhap tay: khong co cookie"
            )
            return 1

        await profiles_mod.save_cookies(session, profile, state)
        await profiles_mod.record_event(session, profile, SessionEventKind.LOGIN, "dang nhap tay")
        print(f"\nDa luu {len(state['cookies'])} cookie (da ma hoa) cho {handle}.")

    await engine.dispose()
    return 0


if __name__ == "__main__":
    if len(sys.argv) != 3:
        print(__doc__)
        raise SystemExit(2)
    raise SystemExit(asyncio.run(main(sys.argv[1], sys.argv[2])))
