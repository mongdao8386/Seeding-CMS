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
from seeding.core import cookies as cookies_mod
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
        closed_early = False
        async with open_profile(profile, headless=False, humanize=True) as (_browser, context):
            page = await context.new_page()
            await page.goto(login_url)
            print(f"Da mo: {page.url}")

            print("\n" + "=" * 62)
            print("  Dang nhap trong cua so vua mo, ROI quay lai day an Enter.")
            print("  DUNG DONG cua so trinh duyet - phien chi lay duoc khi no con mo.")
            print("=" * 62)
            await asyncio.to_thread(input, "\nXong roi? An Enter de luu phien: ")

            # Lay phien trong khoi try: dong cua so truoc khi an Enter la loi hay gap
            # nhat, va khi do storage_state() nem loi "Target closed" - mot cau khong
            # noi gi ve viec phai lam lai the nao.
            try:
                state = await context.storage_state()
            except Exception as exc:
                closed_early = True
                state = {"cookies": []}
                print(f"\nKhong doc duoc phien: {type(exc).__name__}")

        if not state.get("cookies"):
            print("\nKhong thay cookie nao. Phien CHUA duoc luu.")
            print("\nHai ly do hay gap:")
            if closed_early:
                print("  * Cua so trinh duyet da dong truoc khi ban an Enter. Phien chi lay")
                print("    duoc khi cua so con mo - de nguyen no, quay lai day, roi an Enter.")
            else:
                print("  * Trang chua tai duoc (proxy chet, hoac mang chan). Mot trang TikTok")
                print("    tai xong luon dat it nhat vai cookie, ke ca khi chua dang nhap -")
                print("    khong co cookie NAO nghia la trinh duyet chua den duoc trang do.")
                print("  * Cua so da bi dong truoc khi an Enter.")
            if profile.proxy is not None:
                print(f"\n  Kiem tra proxy dang gan: {profile.proxy.label}")
                print("  Vao man hinh Accounts > Proxies roi bam 'test' o dong do.")
            await profiles_mod.record_event(
                session, profile, SessionEventKind.HEALTH_FAIL, "dang nhap tay: khong co cookie"
            )
            return 1

        # Co cookie chua chac la da dang nhap: trang nao cung dat cookie thiet bi ngay
        # tu lan tai dau tien. Luu mot phien chua dang nhap con te hon la khong luu -
        # he thong se tuong tai khoan san sang va giao viec cho no.
        names = {c["name"] for c in state["cookies"]}
        expected = cookies_mod.SESSION_COOKIES.get(platform, ())
        missing = [n for n in expected if n not in names]
        if missing:
            print(f"\nCo {len(names)} cookie, nhung THIEU cookie phien: {', '.join(missing)}")
            print("Nghia la trinh duyet da vao duoc trang, nhung ban chua dang nhap xong.")
            print("Phien CHUA duoc luu - dang nhap lai roi chay lai script nay.")
            await profiles_mod.record_event(
                session,
                profile,
                SessionEventKind.HEALTH_FAIL,
                f"dang nhap tay: thieu cookie phien {missing}",
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
