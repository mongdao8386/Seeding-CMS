"""Chiu tai: gom job cung acc vao mot trinh duyet, kiem phien clone thua hon, don lich su."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

from seeding.db import SessionLocal
from seeding.domain import fingerprint as fpm
from seeding.domain import profiles as profiles_mod
from seeding.domain.defaults import ensure_defaults
from seeding.domain.models import (
    Account,
    AccountRole,
    AccountStatus,
    ActivityJob,
    ActivityKind,
    JobStatus,
    Platform,
    Profile,
    SessionEvent,
    SessionEventKind,
)
from seeding.worker import tasks


async def _account(s, role=AccountRole.CHANNEL, *, health_hours_ago: float | None = None):
    _, persona = await ensure_defaults(s)
    acc = Account(
        persona_id=persona.id,
        platform=Platform.TIKTOK,
        handle=f"thu_{uuid.uuid4().hex[:10]}",
        status=AccountStatus.WARMING,
        role=role,
    )
    s.add(acc)
    await s.flush()
    prof = Profile(
        account_id=acc.id, fingerprint=fpm.generate(), os_family="windows", locale="auto"
    )
    prof.set_cookies(
        {"cookies": [{"name": "sessionid", "value": "x", "domain": ".tiktok.com", "path": "/"}]}
    )
    if health_hours_ago is not None:
        prof.last_health_at = datetime.now(UTC) - timedelta(hours=health_hours_ago)
    s.add(prof)
    await s.commit()
    return acc


async def _cleanup(*ids):
    async with SessionLocal() as s:
        for i in ids:
            obj = await s.get(Account, i)
            if obj is not None:
                await s.delete(obj)
        await s.commit()


async def test_claim_siblings_takes_due_per_target_jobs_of_the_same_account():
    async with SessionLocal() as s:
        acc = await _account(s, AccountRole.BOOSTER)
        other = await _account(s, AccountRole.BOOSTER)
        now = datetime.now(UTC)

        def job(account, kind, minutes):
            return ActivityJob(
                account_id=account.id,
                kind=kind,
                status=JobStatus.SCHEDULED,
                scheduled_at=now + timedelta(minutes=minutes),
                duration_seconds=30,
                target_url=f"https://www.tiktok.com/@x/video/{uuid.uuid4().int % 10**9}",
            )

        lead = job(acc, ActivityKind.ENGAGE, 0)
        soon = job(acc, ActivityKind.ENGAGE, 90)
        follow = job(acc, ActivityKind.FOLLOW, 120)
        far = job(acc, ActivityKind.ENGAGE, 60 * 10)
        sitting = ActivityJob(
            account_id=acc.id,
            kind=ActivityKind.BROWSE_FEED,
            status=JobStatus.SCHEDULED,
            scheduled_at=now,
            duration_seconds=100,
            target_url="sitting:{}",
        )
        others = job(other, ActivityKind.ENGAGE, 0)
        s.add_all([lead, soon, follow, far, sitting, others])
        await s.commit()
        try:
            claimed = await tasks._claim_siblings(s, lead)
            ids = {c.id for c in claimed}
            assert ids == {soon.id, follow.id}, "chi job mo thang link, cung acc, toi han"
            assert all(c.status is JobStatus.RUNNING and c.attempt_count == 1 for c in claimed)
            # nhan lan hai: khong con gi
            assert await tasks._claim_siblings(s, lead) == []
        finally:
            await _cleanup(acc.id, other.id)


async def test_boosters_are_health_checked_less_often():
    async with SessionLocal() as s:
        chan = await _account(s, AccountRole.CHANNEL, health_hours_ago=13)
        boost = await _account(s, AccountRole.BOOSTER, health_hours_ago=13)
        stale_boost = await _account(s, AccountRole.BOOSTER, health_hours_ago=30)
        try:
            due = await profiles_mod.due_for_health_check(
                s, 12, limit=1000, booster_interval_hours=24
            )
            due_accounts = {p.account_id for p in due}
            assert chan.id in due_accounts
            assert boost.id not in due_accounts
            assert stale_boost.id in due_accounts
        finally:
            await _cleanup(chan.id, boost.id, stale_boost.id)


async def test_prune_history_removes_only_old_finished_rows(monkeypatch):
    from seeding import config

    monkeypatch.setattr(
        tasks,
        "get_settings",
        lambda: config.get_settings().model_copy(update={"activity_retention_days": 30}),
    )
    async with SessionLocal() as s:
        acc = await _account(s)
        old = datetime.now(UTC) - timedelta(days=40)
        s.add_all(
            [
                ActivityJob(
                    account_id=acc.id,
                    kind=ActivityKind.ENGAGE,
                    status=JobStatus.SUCCEEDED,
                    scheduled_at=old,
                    duration_seconds=1,
                    target_url="x",
                ),
                ActivityJob(
                    account_id=acc.id,
                    kind=ActivityKind.ENGAGE,
                    status=JobStatus.SCHEDULED,
                    scheduled_at=old,
                    duration_seconds=1,
                    target_url="x",
                ),
                ActivityJob(
                    account_id=acc.id,
                    kind=ActivityKind.ENGAGE,
                    status=JobStatus.SUCCEEDED,
                    scheduled_at=datetime.now(UTC),
                    duration_seconds=1,
                    target_url="x",
                ),
            ]
        )
        prof = await profiles_mod.get_for_account(s, acc.id)
        s.add(
            SessionEvent(
                profile_id=prof.id, kind=SessionEventKind.HEALTH_OK, detail="cu", created_at=old
            )
        )
        await s.commit()
        try:
            removed = await tasks.prune_history({})
            assert removed >= 2
            left = (
                (
                    await s.execute(
                        __import__("sqlalchemy")
                        .select(ActivityJob)
                        .where(ActivityJob.account_id == acc.id)
                    )
                )
                .scalars()
                .all()
            )
            assert sorted(j.status.value for j in left) == ["scheduled", "succeeded"]
        finally:
            await _cleanup(acc.id)
