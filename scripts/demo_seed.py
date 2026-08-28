"""Tao du lieu mau de thu pipeline ma khong can goi Reddit that.

    python scripts/demo_seed.py

In ra cac job da lap ke hoach: moi tai khoan mot tieu de khac nhau va mot moc
thoi gian khac nhau. Day la thu can kiem chung o giai doan 01.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime

from sqlalchemy import delete, select

from seeding.core.planner import plan_campaign
from seeding.db import SessionLocal, engine
from seeding.models import (
    Account,
    AccountStatus,
    Campaign,
    CampaignGroup,
    ContentItem,
    Persona,
    Platform,
    PostJob,
    Workspace,
)

HANDLES = ["alpha_reader", "bao_ngo_92", "chi_lan_hn", "dungtran_dev", "emhaiyen"]
WORKSPACE_NAME = "Demo"


async def _reset(s) -> None:
    """Xoa du lieu demo cu de script chay lai duoc bao nhieu lan cung duoc.

    Phai xoa Campaign truoc: post_jobs tro toi variants khong co ON DELETE CASCADE,
    nen neu xoa workspace truoc se dung rang buoc khoa ngoai.
    """
    ws_ids = select(Workspace.id).where(Workspace.name == WORKSPACE_NAME)
    await s.execute(delete(Campaign).where(Campaign.workspace_id.in_(ws_ids)))
    await s.execute(delete(Workspace).where(Workspace.name == WORKSPACE_NAME))
    await s.commit()


async def main() -> None:
    async with SessionLocal() as s:
        await _reset(s)

        ws = Workspace(name=WORKSPACE_NAME)
        s.add(ws)
        await s.flush()

        accounts: list[Account] = []
        for handle in HANDLES:
            persona = Persona(workspace_id=ws.id, name=handle, interests=["tech"])
            s.add(persona)
            await s.flush()
            account = Account(
                persona_id=persona.id,
                platform=Platform.REDDIT,
                handle=handle,
                status=AccountStatus.ACTIVE,
                daily_cap=3,
                warmup_started_at=datetime.now(UTC),
                # Khong dat secrets: demo nay khong goi mang.
            )
            s.add(account)
            accounts.append(account)
        await s.flush()

        content = ContentItem(
            workspace_id=ws.id,
            title_template=(
                "{Vua thu|Moi test|Nghich thu} mot cong cu {lap lich|dang bai} "
                "{kha hay|khong te|dung duoc}"
            ),
            body_template=(
                "{Minh|To} {dung|xai} duoc {vai hom|mot tuan} roi, "
                "{thay on|cung tam on}. {Ai dung chua?|Co ai thu chua?}"
            ),
            approved=True,
        )
        s.add(content)
        await s.flush()

        campaign = Campaign(
            workspace_id=ws.id,
            content_item_id=content.id,
            name="Demo chien dich",
            starts_at=datetime.now(UTC),
            stagger_window_seconds=3600,
        )
        s.add(campaign)
        await s.flush()

        s.add(
            CampaignGroup(
                campaign_id=campaign.id,
                name="Nhom Reddit r/test",
                platform=Platform.REDDIT,
                target={"subreddit": "test"},
                account_ids=[str(a.id) for a in accounts],
            )
        )
        await s.commit()
        campaign_id = campaign.id

    async with SessionLocal() as s:
        jobs = await plan_campaign(s, campaign_id)

        # planner chi gan account_id chu khong gan quan he `account`, nen tra cuu
        # handle tu bang thay vi cham vao job.account (se lazy-load sai ngu canh).
        handles = dict((await s.execute(select(Account.id, Account.handle))).tuples().all())

        print(f"\nDa lap {len(jobs)} job:\n")
        for job in sorted(jobs, key=lambda j: j.scheduled_at):
            when = job.scheduled_at.strftime("%H:%M:%S")
            print(f"  {when}  {handles[job.account_id]:<14}  {job.variant.title}")

        hashes = {job.variant.content_hash for job in jobs}
        print(f"\n{len(hashes)}/{len(jobs)} bien the khac nhau.")
        if len(hashes) < len(jobs):
            print("  -> Canh bao: co bien the trung. Them lua chon vao spintax.")

    # Lap ke hoach lai cho DUNG campaign do: idempotency_key phai chan sach,
    # khong sinh them job nao. Day la thu ngan retry bien thanh dang trung.
    async with SessionLocal() as s:
        again = await plan_campaign(s, campaign_id)
        # Dem trong pham vi campaign nay thoi - DB con job cua cac demo khac.
        total = len(
            (await s.execute(select(PostJob.id).where(PostJob.campaign_id == campaign_id)))
            .scalars()
            .all()
        )
        print(f"\nLap ke hoach lan hai: them {len(again)} job, tong van la {total}.")
        if again or total != len(jobs):
            print("  -> LOI: idempotency khong hoat dong.")

    await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
