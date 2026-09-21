"""Worker khong duoc de job ket, chay hai lan, hay giu khoa cua nguoi khac (soat loi 21/09/2026)."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from seeding.db import SessionLocal
from seeding.domain import fingerprint as fpm
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
)
from seeding.platforms import base as adapters
from seeding.worker import tasks


class _Redis:
    def __init__(self):
        self.keys: dict[str, str] = {}

    async def set(self, key, value, nx=False, ex=None):
        if nx and key in self.keys:
            return None
        self.keys[key] = value
        return True

    async def get(self, key):
        return self.keys.get(key)

    async def delete(self, key):
        self.keys.pop(key, None)

    async def scan_iter(self, match=None):
        prefix = (match or "").rstrip("*")
        for key in list(self.keys):
            if key.startswith(prefix):
                yield key


async def _booster_with_job(status=JobStatus.RUNNING):
    async with SessionLocal() as s:
        _, persona = await ensure_defaults(s)
        acc = Account(
            persona_id=persona.id,
            platform=Platform.TIKTOK,
            handle=f"thu_{uuid.uuid4().hex[:10]}",
            status=AccountStatus.ACTIVE,
            role=AccountRole.BOOSTER,
        )
        s.add(acc)
        await s.flush()
        prof = Profile(
            account_id=acc.id, fingerprint=fpm.generate(), os_family="windows", locale="auto"
        )
        prof.set_cookies(
            {"cookies": [{"name": "sessionid", "value": "x", "domain": ".tiktok.com", "path": "/"}]}
        )
        s.add(prof)
        job = ActivityJob(
            account_id=acc.id,
            kind=ActivityKind.ENGAGE,
            status=status,
            scheduled_at=datetime.now(UTC),
            duration_seconds=30,
            target_url="https://www.tiktok.com/@x/video/1",
        )
        s.add(job)
        await s.commit()
        return acc.id, job.id


async def _cleanup(account_id):
    async with SessionLocal() as s:
        obj = await s.get(Account, account_id)
        if obj is not None:
            await s.delete(obj)
        await s.commit()


async def test_a_stale_arq_delivery_does_not_run_the_job_a_second_time(monkeypatch):
    """Worker bi tat ngang -> reclaim_orphans tra job ve SCHEDULED -> ARQ van giao lai job cu."""
    account_id, job_id = await _booster_with_job(status=JobStatus.SCHEDULED)
    ran = []

    async def runner(session, profile, job):
        ran.append(job.id)
        return adapters.InteractResult(True, "ok")

    monkeypatch.setitem(adapters._INTERACT, Platform.TIKTOK, runner)
    try:
        status = await tasks.run_activity_job({"redis": _Redis()}, str(job_id))
        assert status == "stale" and ran == []
        async with SessionLocal() as s:
            fresh = await s.get(ActivityJob, job_id)
            assert fresh.status is JobStatus.SCHEDULED and fresh.attempt_count == 0
    finally:
        await _cleanup(account_id)


async def test_a_crashing_runner_leaves_no_job_running_and_no_lock_held(monkeypatch):
    account_id, job_id = await _booster_with_job()

    async def runner(session, profile, job):
        raise RuntimeError("thu vien no")

    monkeypatch.setitem(adapters._INTERACT, Platform.TIKTOK, runner)
    monkeypatch.setitem(adapters._INTERACT_MANY, Platform.TIKTOK, None)
    monkeypatch.setattr(adapters, "get_interact_many", lambda platform: None)
    redis = _Redis()
    try:
        status = await tasks.run_activity_job({"redis": redis}, str(job_id))
        assert status == "scheduled", "loi thu lai duoc, khong phai ket RUNNING"
        async with SessionLocal() as s:
            fresh = await s.get(ActivityJob, job_id)
            assert fresh.status is JobStatus.SCHEDULED
            assert "RuntimeError" in (fresh.last_error or "")
        assert redis.keys == {}, "khoa acc phai duoc tra"
    finally:
        await _cleanup(account_id)


async def test_only_the_owner_releases_a_lock():
    redis = _Redis()
    redis.keys["lock:proxy:p1"] = "job-b"  # job-a het TTL, job-b da lay khoa
    await tasks._release_lock(redis, "lock:proxy:p1", "job-a")
    assert redis.keys["lock:proxy:p1"] == "job-b"
    await tasks._release_lock(redis, "lock:proxy:p1", "job-b")
    assert "lock:proxy:p1" not in redis.keys
    await tasks._release_lock(None, "x", "y")  # khong co redis: khong nem
    await tasks._release_lock(redis, None, "y")


async def test_startup_clears_locks_left_by_a_hard_kill():
    redis = _Redis()
    redis.keys.update(
        {"lock:account:a": "j1", "lock:proxy:p": "j1", "seeding:flag:proxy:p:tiktok": "{}"}
    )
    removed = await tasks.clear_stale_locks(redis)
    assert removed == 2
    assert list(redis.keys) == ["seeding:flag:proxy:p:tiktok"], "co (flag) khong bi dung toi"
