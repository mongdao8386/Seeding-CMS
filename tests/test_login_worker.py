"""Job dang nhap trong worker: chay duoc cho acc CHUA co phien, mot cua so mot luc,
dang nhap xong thi tu dong yeu cau "can nguoi" cua acc do."""

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
from seeding.ops import takeover
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


async def _account_with_login_job(*, status=AccountStatus.WARMING, role=AccountRole.BOOSTER):
    """Acc KHONG co cookie nao - dung loai ma readiness.check tu choi."""
    async with SessionLocal() as s:
        _, persona = await ensure_defaults(s)
        acc = Account(
            persona_id=persona.id,
            platform=Platform.TIKTOK,
            handle=f"lw_{uuid.uuid4().hex[:10]}",
            status=status,
            role=role,
        )
        acc.set_secrets({"username": "u", "password": "p"})
        s.add(acc)
        await s.flush()
        s.add(
            Profile(
                account_id=acc.id, fingerprint=fpm.generate(), os_family="windows", locale="auto"
            )
        )
        job = ActivityJob(
            account_id=acc.id,
            kind=ActivityKind.LOGIN,
            status=JobStatus.RUNNING,
            scheduled_at=datetime.now(UTC),
            duration_seconds=60,
            target_url="login:saved-credentials",
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


async def test_a_login_job_runs_for_an_account_that_has_no_session_yet(monkeypatch):
    account_id, job_id = await _account_with_login_job()
    ran = []

    async def runner(session, profile, job):
        ran.append(job.id)
        return adapters.InteractResult(True, "đăng nhập bằng mật khẩu đã lưu")

    monkeypatch.setitem(adapters._LOGIN, Platform.TIKTOK, runner)
    redis = _Redis()
    try:
        status = await tasks.run_activity_job({"redis": redis}, str(job_id))
        assert status == "succeeded" and ran == [job_id]
        assert redis.keys == {}, "khoa acc va khoa cua so dang nhap phai duoc tra"
    finally:
        await _cleanup(account_id)


async def test_only_one_login_window_is_open_at_a_time(monkeypatch):
    account_id, job_id = await _account_with_login_job()
    ran = []

    async def runner(session, profile, job):
        ran.append(job.id)
        return adapters.InteractResult(True, "ok")

    monkeypatch.setitem(adapters._LOGIN, Platform.TIKTOK, runner)
    redis = _Redis()
    redis.keys["lock:login-window"] = "job-cua-acc-khac"
    try:
        status = await tasks.run_activity_job({"redis": redis}, str(job_id))
        assert status == "deferred" and ran == []
        assert redis.keys == {"lock:login-window": "job-cua-acc-khac"}, "khong dung khoa nguoi khac"
        async with SessionLocal() as s:
            fresh = await s.get(ActivityJob, job_id)
            assert fresh.status is JobStatus.SCHEDULED and fresh.attempt_count == 0
            assert fresh.scheduled_at > datetime.now(UTC)
    finally:
        await _cleanup(account_id)


async def test_a_channel_account_without_a_proxy_is_skipped_not_logged_in(monkeypatch):
    account_id, job_id = await _account_with_login_job(role=AccountRole.CHANNEL)
    ran = []

    async def runner(session, profile, job):
        ran.append(job.id)
        return adapters.InteractResult(True, "ok")

    monkeypatch.setitem(adapters._LOGIN, Platform.TIKTOK, runner)
    try:
        status = await tasks.run_activity_job({"redis": _Redis()}, str(job_id))
        assert status == "skipped" and ran == []
    finally:
        await _cleanup(account_id)


async def test_a_successful_login_closes_the_open_takeover(monkeypatch):
    account_id, job_id = await _account_with_login_job(status=AccountStatus.NEEDS_HUMAN)
    async with SessionLocal() as s:
        acc = await s.get(Account, account_id)
        await takeover.open_request(s, acc, "phiên đã chết, cần đăng nhập lại")
        await s.commit()

    async def runner(session, profile, job):
        profile.session_alive = True
        return adapters.InteractResult(True, "ok")

    monkeypatch.setitem(adapters._LOGIN, Platform.TIKTOK, runner)
    try:
        status = await tasks.run_activity_job({"redis": _Redis()}, str(job_id))
        assert status == "succeeded"
        async with SessionLocal() as s:
            assert await takeover.open_for_account(s, account_id) is None
            acc = await s.get(Account, account_id)
            assert acc.status is not AccountStatus.NEEDS_HUMAN
    finally:
        await _cleanup(account_id)


async def test_a_failed_login_leaves_the_takeover_open(monkeypatch):
    account_id, job_id = await _account_with_login_job(status=AccountStatus.NEEDS_HUMAN)
    async with SessionLocal() as s:
        acc = await s.get(Account, account_id)
        await takeover.open_request(s, acc, "phiên đã chết")
        await s.commit()

    async def runner(session, profile, job):
        return adapters.InteractResult(False, "sai mật khẩu")

    monkeypatch.setitem(adapters._LOGIN, Platform.TIKTOK, runner)
    try:
        status = await tasks.run_activity_job({"redis": _Redis()}, str(job_id))
        assert status == "failed"
        async with SessionLocal() as s:
            assert await takeover.open_for_account(s, account_id) is not None
    finally:
        await _cleanup(account_id)
