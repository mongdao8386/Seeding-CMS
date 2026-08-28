"""Kiem chung profile store tren DB that, khong dung toi mang xa hoi nao.

    python scripts/demo_profiles.py

Chay qua dung nhung bat bien cua giai doan 02:
  - moi tai khoan mot fingerprint rieng, va chi tao duoc mot lan
  - bi mat va cookie khong bao gio nam duoi dang ro trong DB
  - khong doi duoc proxy cua profile da gan, tru khi force va ghi ly do
  - hai lan health check that bai lien tiep thi tai khoan chuyen sang cho nguoi xu ly
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime

from sqlalchemy import delete, select

from seeding.core import fingerprint as fpm
from seeding.core import profiles as profiles_mod
from seeding.core import takeover
from seeding.db import SessionLocal, engine
from seeding.models import (
    Account,
    AccountStatus,
    Persona,
    Platform,
    Profile,
    Proxy,
    SessionEvent,
    Workspace,
)

WORKSPACE_NAME = "Demo profile"
HANDLES = ["em_haiyen", "bao_ngo_92", "chi_lan_hn"]


def ok(label: str, passed: bool, note: str = "") -> bool:
    print(f"  [{'OK ' if passed else 'LOI'}] {label}{f' - {note}' if note else ''}")
    return passed


async def main() -> int:
    results: list[bool] = []

    async with SessionLocal() as s:
        # Don du lieu demo cu de chay lai duoc nhieu lan.
        ws_ids = select(Workspace.id).where(Workspace.name == WORKSPACE_NAME)
        await s.execute(delete(Workspace).where(Workspace.id.in_(ws_ids)))
        await s.execute(delete(Proxy).where(Proxy.label.like("demo-%")))
        await s.commit()

        ws = Workspace(name=WORKSPACE_NAME)
        s.add(ws)
        await s.flush()

        print("\n1. Tao profile cho tung tai khoan\n")
        profiles: list[Profile] = []
        for i, handle in enumerate(HANDLES):
            persona = Persona(workspace_id=ws.id, name=handle)
            s.add(persona)
            await s.flush()

            account = Account(
                persona_id=persona.id,
                platform=Platform.THREADS,
                handle=handle,
                status=AccountStatus.WARMING,
                warmup_started_at=datetime.now(UTC),
            )
            account.set_secrets({"password": f"mat-khau-{i}", "totp_seed": "JBSWY3DPEHPK3PXP"})
            s.add(account)
            await s.flush()

            proxy = Proxy(label=f"demo-{handle}", host=f"10.0.0.{10 + i}", port=8080)
            proxy.set_password("bi-mat-proxy")
            s.add(proxy)
            await s.flush()

            profile = await profiles_mod.create_profile(s, account, proxy=proxy)
            profiles.append(profile)
            print(f"  {handle:<12} {fpm.summary(profile.fingerprint)}")

        seeds = {p.fingerprint["canvas:seed"] for p in profiles}
        results.append(
            ok(
                "moi profile mot canvas seed rieng",
                len(seeds) == len(profiles),
                f"{len(seeds)} seed",
            )
        )
        results.append(
            ok(
                "fingerprint deu mo duoc trinh duyet",
                all(fpm.is_launchable(p.fingerprint) for p in profiles),
            )
        )

        print("\n2. Bi mat khong nam duoi dang ro trong DB\n")
        account = await s.get(Account, profiles[0].account_id)
        raw = account.secrets_enc or ""
        results.append(ok("mat khau da ma hoa", "mat-khau-0" not in raw))
        results.append(ok("doc lai van dung", account.get_secrets()["password"] == "mat-khau-0"))

        proxy0 = profiles[0].proxy
        results.append(
            ok("mat khau proxy da ma hoa", "bi-mat-proxy" not in (proxy0.password_enc or ""))
        )

        print("\n3. Bat bien: mot tai khoan mot profile\n")
        try:
            await profiles_mod.create_profile(s, account)
            results.append(ok("tao profile lan hai bi chan", False, "khong bi chan"))
        except profiles_mod.ProfileError:
            results.append(ok("tao profile lan hai bi chan", True))

        print("\n4. Bat bien: khong xoay proxy\n")
        other_proxy = Proxy(label="demo-khac", host="10.0.0.99", port=8080)
        s.add(other_proxy)
        await s.flush()
        try:
            await profiles_mod.bind_proxy(s, profiles[0], other_proxy)
            results.append(ok("doi proxy bi chan", False, "khong bi chan"))
        except profiles_mod.ProfileError:
            results.append(ok("doi proxy bi chan", True))

        await profiles_mod.bind_proxy(
            s, profiles[0], other_proxy, force=True, reason="demo: proxy cu chet"
        )
        results.append(ok("force doi duoc va co ghi ly do", profiles[0].proxy_id == other_proxy.id))

        print("\n5. Vong doi phien\n")
        p = profiles[1]
        await profiles_mod.save_cookies(
            s, p, {"cookies": [{"name": "sessionid", "value": "xyz"}], "origins": []}
        )
        results.append(ok("cookie da ma hoa", "xyz" not in (p.cookies_enc or "")))
        results.append(ok("doc lai duoc", p.get_cookies()["cookies"][0]["value"] == "xyz"))
        results.append(ok("phien duoc danh dau con song", p.session_alive))

        due = await profiles_mod.due_for_health_check(s, interval_hours=12)
        results.append(
            ok("chi profile da dang nhap moi vao hang doi kiem tra", [x.id for x in due] == [p.id])
        )

        print("\n6. That bai lien tiep thi chuyen cho nguoi xu ly\n")
        crossed1 = await profiles_mod.mark_health(
            s, p, False, detail="demo: bi day ve trang login", threshold=2
        )
        acc = await s.get(Account, p.account_id)
        await s.refresh(acc)
        results.append(ok("that bai lan 1 chua bao dong", acc.status != AccountStatus.NEEDS_HUMAN))
        results.append(ok("lan 1 chua bao nguoi goi mo hang doi", crossed1 is False))

        crossed2 = await profiles_mod.mark_health(
            s, p, False, detail="demo: van bi day ve login", threshold=2
        )
        # Neu cho nay tra ve False thi tai khoan se nam o NEEDS_HUMAN ma khong bao gio
        # hien ra trong hang doi - nguoi van hanh khong biet de cuu.
        results.append(ok("lan 2 bao nguoi goi phai mo hang doi", crossed2 is True))

        # Va nguoi goi PHAI lam theo. Day la dung nhung gi worker lam trong health_sweep.
        if crossed2:
            await takeover.open_request(s, acc, "demo: phien chet sau 2 lan kiem")
        results.append(
            ok(
                "tai khoan hien ra trong hang doi cho nguoi",
                await takeover.open_for_account(s, acc.id) is not None,
            )
        )
        await s.refresh(acc)
        results.append(
            ok("that bai lan 2 chuyen NEEDS_HUMAN", acc.status == AccountStatus.NEEDS_HUMAN)
        )

        due_after = await profiles_mod.due_for_health_check(s, interval_hours=0)
        results.append(
            ok(
                "tai khoan cho nguoi xu ly bi loai khoi hang doi",
                p.id not in [x.id for x in due_after],
            )
        )

        events = (
            (
                await s.execute(
                    select(SessionEvent)
                    .where(SessionEvent.profile_id == p.id)
                    .order_by(SessionEvent.created_at)
                )
            )
            .scalars()
            .all()
        )
        print("\n  Nhat ky phien cua", HANDLES[1] + ":")
        for e in events:
            print(f"    {e.kind.value:<14} {e.detail or ''}")
        results.append(ok("nhat ky ghi day du", len(events) >= 4, f"{len(events)} su kien"))

    await engine.dispose()

    passed = sum(results)
    print(f"\n{'=' * 58}\n  {passed}/{len(results)} kiem tra dat\n{'=' * 58}\n")
    return 0 if passed == len(results) else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
