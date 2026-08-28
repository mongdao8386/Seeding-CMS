"""Kiem chung hoat dong nen va hang doi can thiep tay tren DB that.

    python scripts/demo_takeover.py

Khong mo trinh duyet, khong dung toi mang xa hoi nao. Chay qua dung nhung bat bien
cua giai doan 03:
  - hoat dong nen nhieu gap nhieu lan job dang bai, rai deu trong khung gio thuc
  - lap lich lai trong cung mot ngay khong nhan doi lich
  - gap checkpoint thi tai khoan VA job cung dung lai, va nho duoc job nao bi ket
  - giai xong thi job duoc hen lai chu khong chay ngay
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime

from sqlalchemy import delete, select

from seeding.core import activity as activity_mod
from seeding.core import profiles as profiles_mod
from seeding.core import takeover
from seeding.core.planner import plan_campaign
from seeding.db import SessionLocal, engine
from seeding.models import (
    Account,
    AccountStatus,
    ActivityJob,
    Campaign,
    CampaignGroup,
    ContentItem,
    JobStatus,
    Persona,
    Platform,
    PostJob,
    SessionEvent,
    Workspace,
)

WORKSPACE_NAME = "Demo takeover"
HANDLE = "em_haiyen_p3"


def ok(label: str, passed: bool, note: str = "") -> bool:
    print(f"  [{'OK ' if passed else 'LOI'}] {label}{f' - {note}' if note else ''}")
    return passed


async def main() -> int:
    results: list[bool] = []

    async with SessionLocal() as s:
        ws_ids = select(Workspace.id).where(Workspace.name == WORKSPACE_NAME)
        await s.execute(delete(Campaign).where(Campaign.workspace_id.in_(ws_ids)))
        await s.execute(delete(Workspace).where(Workspace.name == WORKSPACE_NAME))
        await s.commit()

        ws = Workspace(name=WORKSPACE_NAME)
        s.add(ws)
        await s.flush()

        persona = Persona(workspace_id=ws.id, name=HANDLE)
        s.add(persona)
        await s.flush()

        account = Account(
            persona_id=persona.id,
            platform=Platform.THREADS,
            handle=HANDLE,
            status=AccountStatus.WARMING,
            daily_cap=3,
            warmup_started_at=datetime.now(UTC),
        )
        s.add(account)
        await s.flush()
        profile = await profiles_mod.create_profile(s, account)

        print("\n1. Lap lich hoat dong nen\n")
        jobs = await activity_mod.plan_for_account(s, account)
        print(f"  {len(jobs)} lan hoat dong cho tran {account.daily_cap} bai/ngay")
        results.append(
            ok(
                "nhieu gap it nhat 5 lan so bai dang",
                len(jobs) >= account.daily_cap * 5,
                f"{len(jobs)} vs {account.daily_cap}",
            )
        )

        kinds = {}
        for j in jobs:
            kinds[j.kind.value] = kinds.get(j.kind.value, 0) + 1
        print("  phan bo:", ", ".join(f"{k}={v}" for k, v in sorted(kinds.items())))
        results.append(ok("co nhieu hon mot loai hoat dong", len(kinds) > 1))

        hours = sorted({j.scheduled_at.hour for j in jobs})
        print(f"  trai tu {hours[0]}h den {hours[-1]}h")
        results.append(ok("khong co lan nao vao ban dem", hours[0] >= 7 and hours[-1] <= 23))

        again = await activity_mod.plan_for_account(s, account)
        results.append(
            ok("lap lai trong ngay khong nhan doi lich", again == [], f"{len(again)} moi")
        )

        print("\n2. Mot bai dang bi ket vi checkpoint\n")
        content = ContentItem(
            workspace_id=ws.id,
            title_template="{Chao|Hi} moi nguoi",
            body_template="Thu nghiem",
            approved=True,
        )
        s.add(content)
        await s.flush()

        campaign = Campaign(
            workspace_id=ws.id,
            content_item_id=content.id,
            name="Demo p3",
            starts_at=datetime.now(UTC),
            stagger_window_seconds=60,
        )
        s.add(campaign)
        await s.flush()
        s.add(
            CampaignGroup(
                campaign_id=campaign.id,
                name="nhom thu",
                platform=Platform.THREADS,
                target={},
                account_ids=[str(account.id)],
            )
        )
        await s.commit()

        post_jobs = await plan_campaign(s, campaign.id)
        job = post_jobs[0]

        # Gia lap dung nhung gi worker lam khi adapter tra ve needs_human.
        job.status = JobStatus.NEEDS_HUMAN
        job.last_error = "verify: trang co chu 'confirm your identity'"
        await s.commit()

        request = await takeover.open_request(s, account, job.last_error, post_job_id=job.id)
        await s.refresh(account)

        results.append(
            ok("tai khoan chuyen NEEDS_HUMAN", account.status == AccountStatus.NEEDS_HUMAN)
        )
        results.append(ok("nho duoc job nao bi ket", request.post_job_id == job.id))
        await s.refresh(profile)
        results.append(ok("phien bi danh dau la chet", not profile.session_alive))

        duplicate = await takeover.open_request(s, account, "van con captcha")
        results.append(ok("bao lai khong tao them yeu cau", duplicate.id == request.id))
        results.append(ok("ly do duoc cap nhat", duplicate.reason == "van con captcha"))

        # Dem rieng tai khoan nay: DB con yeu cau cua cac demo khac.
        mine = [r for r in await takeover.list_open(s) if r.account_id == account.id]
        results.append(ok("tai khoan nay co dung mot yeu cau", len(mine) == 1))

        print("\n3. Nguoi giai xong\n")
        before = job.scheduled_at
        await takeover.resolve(s, request, by="demo", note="da nhap ma xac minh")
        await s.refresh(account)
        await s.refresh(job)

        results.append(
            ok(
                "tai khoan ve WARMING chu khong phai ACTIVE",
                account.status == AccountStatus.WARMING,
            )
        )
        results.append(ok("job duoc dat lai lich", job.status == JobStatus.SCHEDULED))
        results.append(
            ok(
                "job khong chay ngay ma nghi mot luc",
                job.scheduled_at > before,
                f"lui {(job.scheduled_at - datetime.now(UTC)).total_seconds() / 3600:.1f} tieng",
            )
        )
        results.append(
            ok(
                "tai khoan nay ra khoi hang doi",
                await takeover.open_for_account(s, account.id) is None,
            )
        )

        events = (
            (
                await s.execute(
                    select(SessionEvent)
                    .where(SessionEvent.profile_id == profile.id)
                    .order_by(SessionEvent.created_at)
                )
            )
            .scalars()
            .all()
        )
        print("\n  Nhat ky phien:")
        for e in events:
            print(f"    {e.kind.value:<14} {(e.detail or '')[:60]}")
        results.append(ok("co ghi ca luc ket va luc giai", len(events) >= 3))

        print("\n4. Tai khoan khong cuu duoc\n")
        second = await takeover.open_request(s, account, "suspended")
        await takeover.abandon(s, second, by="demo", note="bi khoa han")
        await s.refresh(account)
        results.append(ok("tai khoan chuyen DEAD", account.status == AccountStatus.DEAD))

        # plan_all cham vao moi tai khoan trong DB, ke ca cua demo khac - nen dem
        # rieng tai khoan nay thay vi dem tong.
        before_count = await activity_mod.count_for_day(s, account.id, datetime.now(UTC).date())
        await activity_mod.plan_all(s)
        after_count = await activity_mod.count_for_day(s, account.id, datetime.now(UTC).date())
        # Lich cu van nam do, nhung hang doi phai bo qua chung: tai khoan chet ma van
        # cuon feed thi vua vo ich vua lam ban nhat ky.
        still_due = await activity_mod.due_activity(s, now=datetime(2099, 1, 1, tzinfo=UTC))
        results.append(
            ok(
                "tai khoan chet bi loai khoi hang doi hoat dong",
                all(j.account_id != account.id for j in still_due),
            )
        )
        remaining = (
            (
                await s.execute(
                    select(ActivityJob).where(
                        ActivityJob.account_id == account.id,
                        ActivityJob.status == JobStatus.SCHEDULED,
                    )
                )
            )
            .scalars()
            .all()
        )
        results.append(
            ok(
                "tai khoan chet khong duoc lap lich moi",
                after_count == before_count,
                f"{len(remaining)} lich cu van con",
            )
        )

        stuck = (
            (await s.execute(select(PostJob).where(PostJob.campaign_id == campaign.id)))
            .unique()
            .scalars()
            .all()
        )
        results.append(ok("khong sinh them job dang bai nao", len(stuck) == 1))

        print("\n5. Bat bien toan he thong\n")
        # Moi tai khoan NEEDS_HUMAN phai co mot yeu cau dang mo. Thieu no thi tai khoan
        # vo hinh voi nguoi van hanh: nam do mai ma khong ai biet de cuu.
        stuck = (
            (await s.execute(select(Account).where(Account.status == AccountStatus.NEEDS_HUMAN)))
            .scalars()
            .all()
        )
        orphans = [a.handle for a in stuck if await takeover.open_for_account(s, a.id) is None]
        results.append(
            ok(
                "khong tai khoan nao ket ma khong nam trong hang doi",
                not orphans,
                f"vo hinh: {', '.join(orphans)}" if orphans else f"{len(stuck)} dang cho",
            )
        )

    await engine.dispose()

    passed = sum(results)
    print(f"\n{'=' * 58}\n  {passed}/{len(results)} kiem tra dat\n{'=' * 58}\n")
    return 0 if passed == len(results) else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
