"""Chatbot - phan dung chung: tu tra loi binh luan duoi bai cua tai khoan va tin nhan.

Moi nen tang chi dua vao mot Channel (mo bang `async with`): doc bai cua minh, doc binh
luan, tra loi binh luan; doc hop thu chua doc, doc tin trong mot cuoc, gui tin. Cau tra
loi do Replier viet (content/chatbot.py). Con lai la chung:

  - Khong tra loi hai lan: moi binh luan / tin nhan da xu ly ghi thanh mot ActivityJob
    (REPLY / DM, ke ca khi bo qua), target_url la khoa. Vong sau doc lai khoa, khong hoi
    LLM lai.
  - Nhip nguoi: tran moi gio moi tai khoan, chi tra loi mot ti le, nghi vai giay giua
    hai lan gui. Khong tra loi binh luan cu qua (lookback).
  - Khong tra loi chinh minh; khong tra loi cuoc tro chuyen ma tin cuoi la cua minh.
  - Checkpoint / phien chet -> vao hang doi cho nguoi va DUNG tick nay cua tai khoan.
"""

from __future__ import annotations

import asyncio
import random
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Protocol

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from seeding.browser.checkpoints import CheckpointKind
from seeding.content import chatbot as writer
from seeding.domain.models import Account, ActivityJob, ActivityKind, JobStatus, Profile

log = structlog.get_logger(__name__)

_KEEP_DAYS = 30


@dataclass(frozen=True, slots=True)
class Post:
    id: str
    url: str
    caption: str
    created_at: datetime | None = None


@dataclass(frozen=True, slots=True)
class Comment:
    id: str
    post: Post
    author_handle: str
    author_id: str
    text: str
    created_at: datetime | None
    url: str
    replied_by_me: bool = False


@dataclass(frozen=True, slots=True)
class Thread:
    id: str
    peer_handle: str
    peer_id: str
    url: str


@dataclass(frozen=True, slots=True)
class Message:
    id: str
    from_me: bool
    text: str
    created_at: datetime | None = None


@dataclass(slots=True)
class Outcome:
    ok: bool
    detail: str
    needs_human: bool = False
    retryable: bool = False
    terminal: bool = False


class Channel(Protocol):
    supports_dm: bool

    async def own_posts(self, count: int) -> list[Post]: ...
    async def comments(self, post: Post, count: int) -> list[Comment]: ...
    async def reply_comment(self, comment: Comment, text: str) -> Outcome: ...
    async def unread_threads(self, count: int) -> list[Thread]: ...
    async def messages(self, thread: Thread, count: int) -> list[Message]: ...
    async def send_dm(self, thread: Thread, text: str) -> Outcome: ...


@dataclass(frozen=True, slots=True)
class Limits:
    max_per_hour: int = 8
    reply_ratio: float = 0.8
    lookback_hours: int = 48
    posts: int = 5
    comments_per_post: int = 20
    threads: int = 10
    pause: tuple[float, float] = (3.0, 10.0)


@dataclass(slots=True)
class Report:
    comments_seen: int = 0
    replied: int = 0
    dms_seen: int = 0
    dm_replied: int = 0
    skipped: int = 0
    failed: int = 0
    stopped: str | None = None
    notes: list[str] = field(default_factory=list)


def persona_brief(account: Account) -> writer.PersonaBrief:
    # Doc tu __dict__: khong lazy-load trong phien async (MissingGreenlet). Worker nap
    # persona bang selectinload; khong nap thi dung handle lam ten.
    persona = account.__dict__.get("persona")
    return writer.PersonaBrief(
        name=(persona.name if persona is not None and persona.name else account.handle),
        voice=persona.voice if persona is not None else None,
        interests=tuple(persona.interests or ()) if persona is not None else (),
        platform=account.platform.value,
        handle=account.handle.lstrip("@"),
    )


async def answered_targets(session: AsyncSession, account_id) -> set[str]:
    since = datetime.now(UTC) - timedelta(days=_KEEP_DAYS)
    rows = (
        await session.execute(
            select(ActivityJob.target_url).where(
                ActivityJob.account_id == account_id,
                ActivityJob.kind.in_([ActivityKind.REPLY, ActivityKind.DM]),
                ActivityJob.scheduled_at >= since,
            )
        )
    ).scalars()
    return {u for u in rows if u}


async def sent_last_hour(session: AsyncSession, account_id) -> int:
    since = datetime.now(UTC) - timedelta(hours=1)
    rows = (
        await session.execute(
            select(ActivityJob.id).where(
                ActivityJob.account_id == account_id,
                ActivityJob.kind.in_([ActivityKind.REPLY, ActivityKind.DM]),
                ActivityJob.status == JobStatus.SUCCEEDED,
                ActivityJob.scheduled_at >= since,
            )
        )
    ).scalars()
    return len(list(rows))


async def _record(
    session: AsyncSession,
    account: Account,
    kind: ActivityKind,
    key: str,
    status: JobStatus,
    detail: str,
) -> None:
    session.add(
        ActivityJob(
            account_id=account.id,
            kind=kind,
            status=status,
            scheduled_at=datetime.now(UTC),
            duration_seconds=20,
            target_url=key,
            detail=detail[:2000],
            last_error=None if status is JobStatus.SUCCEEDED else detail[:2000],
        )
    )
    await session.commit()


async def _handle_failure(
    session: AsyncSession, account: Account, outcome: Outcome, report: Report
) -> bool:
    """True = dung tick nay cua tai khoan (checkpoint / khoa)."""
    from seeding.ops import takeover

    if outcome.terminal:
        from seeding.domain.models import AccountStatus

        account.status = AccountStatus.SUSPENDED
        await session.commit()
        report.stopped = outcome.detail
        return True
    if outcome.needs_human:
        await takeover.open_request(session, account, f"chatbot: {outcome.detail}")
        report.stopped = outcome.detail
        return True
    return False


async def run_for_account(
    session: AsyncSession,
    account: Account,
    profile: Profile | None,
    *,
    channel_factory,
    replier: writer.Replier,
    limits: Limits = Limits(),
    rng: random.Random | None = None,
    now: datetime | None = None,
    sleep=asyncio.sleep,
    do_comments: bool = True,
    do_dms: bool = True,
) -> Report:
    rng = rng or random.Random()
    now = now or datetime.now(UTC)
    report = Report()
    brief = persona_brief(account)
    answered = await answered_targets(session, account.id)
    budget = max(0, limits.max_per_hour - await sent_last_hour(session, account.id))
    if budget == 0:
        report.stopped = "hết hạn mức giờ này"
        return report
    oldest = now - timedelta(hours=limits.lookback_hours)
    me = account.handle.lstrip("@").lower()

    try:
        async with channel_factory(profile, account) as ch:
            if do_comments:
                posts = await ch.own_posts(limits.posts)
                for post in posts:
                    for c in await ch.comments(post, limits.comments_per_post):
                        report.comments_seen += 1
                        if c.author_handle.lstrip("@").lower() == me or c.replied_by_me:
                            continue
                        if c.url in answered:
                            continue
                        if c.created_at is not None and c.created_at < oldest:
                            continue
                        if rng.random() > limits.reply_ratio:
                            await _record(
                                session,
                                account,
                                ActivityKind.REPLY,
                                c.url,
                                JobStatus.SKIPPED,
                                "bỏ qua theo tỉ lệ",
                            )
                            answered.add(c.url)
                            report.skipped += 1
                            continue
                        text = await replier.reply_comment(
                            writer.CommentContext(brief, post.caption, c.author_handle, c.text)
                        )
                        if not text:
                            await _record(
                                session,
                                account,
                                ActivityKind.REPLY,
                                c.url,
                                JobStatus.SKIPPED,
                                f"chatbot bỏ qua: @{c.author_handle}: {c.text[:120]}",
                            )
                            answered.add(c.url)
                            report.skipped += 1
                            continue
                        if budget <= 0:
                            report.stopped = "hết hạn mức giờ này"
                            return report
                        outcome = await ch.reply_comment(c, text)
                        status = JobStatus.SUCCEEDED if outcome.ok else JobStatus.FAILED
                        detail = (
                            f"@{c.author_handle}: {c.text[:120]} → {text}"
                            if outcome.ok
                            else f"@{c.author_handle}: {c.text[:120]} → {outcome.detail}"
                        )
                        await _record(session, account, ActivityKind.REPLY, c.url, status, detail)
                        answered.add(c.url)
                        if outcome.ok:
                            budget -= 1
                            report.replied += 1
                        else:
                            report.failed += 1
                            if await _handle_failure(session, account, outcome, report):
                                return report
                        await sleep(rng.uniform(*limits.pause))

            if do_dms and getattr(ch, "supports_dm", False):
                for t in await ch.unread_threads(limits.threads):
                    report.dms_seen += 1
                    msgs = await ch.messages(t, 8)
                    if not msgs or msgs[-1].from_me:
                        continue
                    key = f"{t.url}#{msgs[-1].id}"
                    if key in answered:
                        continue
                    text = await replier.reply_dm(
                        writer.DmContext(
                            brief, t.peer_handle, tuple((m.from_me, m.text) for m in msgs)
                        )
                    )
                    if not text:
                        await _record(
                            session,
                            account,
                            ActivityKind.DM,
                            key,
                            JobStatus.SKIPPED,
                            f"chatbot bỏ qua: @{t.peer_handle}: {msgs[-1].text[:120]}",
                        )
                        answered.add(key)
                        report.skipped += 1
                        continue
                    if budget <= 0:
                        report.stopped = "hết hạn mức giờ này"
                        return report
                    outcome = await ch.send_dm(t, text)
                    status = JobStatus.SUCCEEDED if outcome.ok else JobStatus.FAILED
                    detail = (
                        f"@{t.peer_handle}: {msgs[-1].text[:120]} → {text}"
                        if outcome.ok
                        else f"@{t.peer_handle}: {msgs[-1].text[:120]} → {outcome.detail}"
                    )
                    await _record(session, account, ActivityKind.DM, key, status, detail)
                    answered.add(key)
                    if outcome.ok:
                        budget -= 1
                        report.dm_replied += 1
                    else:
                        report.failed += 1
                        if await _handle_failure(session, account, outcome, report):
                            return report
                    await sleep(rng.uniform(*limits.pause))
    except writer.ReplierError as exc:
        report.stopped = f"chatbot: {exc}"
        log.warning("chatbot.replier_failed", handle=account.handle, error=str(exc))
    except Exception as exc:
        # Dang nhap hong, proxy treo, thu vien lech - ha tang; tick sau thu lai.
        report.stopped = f"{type(exc).__name__}: {exc}"
        log.warning("chatbot.channel_failed", handle=account.handle, error=report.stopped)
    return report


def checkpoint_kind(outcome: Outcome) -> CheckpointKind | None:
    if outcome.terminal:
        return CheckpointKind.SUSPENDED
    if outcome.needs_human:
        return CheckpointKind.VERIFY
    return None
