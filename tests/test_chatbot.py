"""Chatbot: nguoi viet cau (mau va LLM voi HTTP gia), doc binh luan TikTok, va engine
tren DB that voi kenh gia - khong tra loi hai lan, khong tra loi chinh minh, tran moi
gio, ti le, checkpoint -> hang doi cho nguoi."""

from __future__ import annotations

import json
import random
import uuid
from datetime import UTC, datetime, timedelta
from typing import ClassVar

import httpx
import pytest
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from seeding.content import chatbot as writer
from seeding.db import SessionLocal
from seeding.domain import fingerprint as fpm
from seeding.domain.defaults import ensure_defaults
from seeding.domain.models import (
    Account,
    AccountStatus,
    ActivityJob,
    ActivityKind,
    JobStatus,
    Platform,
    Profile,
    TakeoverRequest,
    TakeoverStatus,
)
from seeding.platforms import chatbot as engine
from seeding.platforms.tiktok import chatbot as tt

BRIEF = writer.PersonaBrief("Ngọc Trâm", None, ("làm đẹp",), "instagram", "ngoc.tram")

# ------------------------------------------------------------------ nguoi viet


async def test_template_replier_is_deterministic_and_silent_on_spam():
    r = writer.TemplateReplier()
    ctx = writer.CommentContext(BRIEF, "bài", "ban_a", "hay quá")
    a = await r.reply_comment(ctx)
    assert a and a == await r.reply_comment(ctx) and a in writer.COMMENT_REPLIES
    q = await r.reply_comment(writer.CommentContext(BRIEF, "bài", "ban_a", "mua ở đâu vậy?"))
    assert q in writer.QUESTION_REPLIES
    assert (
        await r.reply_comment(writer.CommentContext(BRIEF, "bài", "x", "kiếm tiền tại nhà ib mình"))
        is None
    )
    assert (
        await r.reply_dm(writer.DmContext(BRIEF, "ban_b", ((False, "chào bạn"),)))
        in writer.DM_REPLIES
    )
    assert (
        await r.reply_dm(writer.DmContext(BRIEF, "ban_b", ((False, "vào t.me/abc nhé"),))) is None
    )


def test_tidy_strips_quotes_prefix_and_skip():
    assert writer.tidy('"Cảm ơn bạn nha"', 100) == "Cảm ơn bạn nha"
    assert writer.tidy("Trả lời: ok nè", 100) == "ok nè"
    assert writer.tidy("[bỏ qua]", 100) is None
    assert writer.tidy("", 100) is None
    long = "Câu một dài dài. Câu hai dài dài. Câu ba dài dài dài."
    out = writer.tidy(long, 40)
    assert out and len(out) <= 40 and out.endswith(".")


class _Fake:
    """httpx.AsyncClient gia cho Anthropic API."""

    status: ClassVar[int] = 200
    text: ClassVar[str] = "Cảm ơn bạn nhiều nha 🥰"
    last: ClassVar[dict] = {}

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return None

    async def post(self, url, json=None, headers=None):
        _Fake.last = {"url": url, "json": json, "headers": headers}
        body = {"content": [{"type": "text", "text": _Fake.text}]}
        return httpx.Response(_Fake.status, json=body if _Fake.status == 200 else {"error": "x"})


async def test_llm_replier_builds_prompt_and_parses():
    r = writer.LLMReplier("sk-test", "claude-sonnet-5", client_factory=_Fake)
    out = await r.reply_comment(
        writer.CommentContext(BRIEF, "clip son mới", "ban_a", "màu này tên gì?")
    )
    assert out == "Cảm ơn bạn nhiều nha 🥰"
    sent = _Fake.last
    assert sent["headers"]["x-api-key"] == "sk-test"
    assert sent["json"]["model"] == "claude-sonnet-5"
    assert "Ngọc Trâm" in sent["json"]["system"] and "làm đẹp" in sent["json"]["system"]
    assert "màu này tên gì?" in sent["json"]["messages"][0]["content"]
    assert "clip son mới" in sent["json"]["messages"][0]["content"]

    _Fake.text = writer.SKIP
    assert await r.reply_comment(writer.CommentContext(BRIEF, "x", "a", "ok")) is None
    _Fake.text = "ok"
    out = await r.reply_dm(
        writer.DmContext(BRIEF, "ban_b", ((False, "hi"), (True, "chào"), (False, "bạn ở đâu?")))
    )
    assert out == "ok" and "@ban_b: bạn ở đâu?" in _Fake.last["json"]["messages"][0]["content"]

    _Fake.status = 401
    try:
        with pytest.raises(writer.ReplierError):
            await r.reply_comment(writer.CommentContext(BRIEF, "x", "a", "ok"))
    finally:
        _Fake.status = 200
    assert (
        await r.reply_comment(writer.CommentContext(BRIEF, "x", "a", "mua follow giá rẻ")) is None
    )


def test_build_replier_picks_llm_only_with_a_key():
    assert writer.build_replier(api_key="", model="m").name == "template"
    assert writer.build_replier(api_key="k", model="m").name == "llm"


# ------------------------------------------------------------------ tiktok parse


def test_tiktok_parse_comments_marks_own_replies():
    post = engine.Post(id="1", url="https://www.tiktok.com/@me/video/1", caption="c")
    body = {
        "comments": [
            {
                "cid": "10",
                "text": "hay",
                "user": {"uid": "u1", "unique_id": "ban_a"},
                "create_time": 1700000000,
                "reply_comment": [{"user": {"uid": "ME"}}],
            },
            {
                "cid": "11",
                "text": "ok",
                "user": {"uid": "u2", "unique_id": "ban_b"},
                "create_time": None,
                "reply_comment": None,
            },
            {"cid": "", "text": "x", "user": {"unique_id": "y"}},
        ]
    }
    got = tt.parse_comments(body, post, "ME")
    assert [c.id for c in got] == ["10", "11"]
    assert got[0].replied_by_me and not got[1].replied_by_me
    assert got[0].created_at is not None and got[1].created_at is None
    assert got[0].url == "https://www.tiktok.com/@me/video/1?comment=10"


# ------------------------------------------------------------------ engine


POST = engine.Post(id="p1", url="https://www.instagram.com/p/AAA/", caption="clip mới")


def _comment(cid, author, text, *, age_hours=1, replied=False):
    return engine.Comment(
        id=cid,
        post=POST,
        author_handle=author,
        author_id=cid,
        text=text,
        created_at=datetime.now(UTC) - timedelta(hours=age_hours),
        url=f"{POST.url}c/{cid}/",
        replied_by_me=replied,
    )


class _Channel:
    supports_dm = True
    sent: ClassVar[list] = []
    outcome: ClassVar[engine.Outcome] = engine.Outcome(True, "ok")
    pool: ClassVar[list] = []
    threads: ClassVar[list] = []
    msgs: ClassVar[dict] = {}

    def __init__(self, profile, account):
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return None

    async def own_posts(self, count):
        return [POST]

    async def comments(self, post, count):
        return list(_Channel.pool)

    async def reply_comment(self, comment, text):
        _Channel.sent.append(("reply", comment.id, text))
        return _Channel.outcome

    async def unread_threads(self, count):
        return list(_Channel.threads)

    async def messages(self, thread, count):
        return list(_Channel.msgs.get(thread.id, []))

    async def send_dm(self, thread, text):
        _Channel.sent.append(("dm", thread.id, text))
        return _Channel.outcome


class _Replier:
    name = "fake"

    async def reply_comment(self, ctx):
        return None if "spam" in ctx.text else f"rep:{ctx.author_handle}"

    async def reply_dm(self, ctx):
        return f"dm:{ctx.peer_handle}"


async def _no_sleep(_):
    return None


@pytest.fixture
async def account():
    async with SessionLocal() as s:
        _, persona = await ensure_defaults(s)
        acc = Account(
            persona_id=persona.id,
            platform=Platform.INSTAGRAM,
            handle=f"me_{uuid.uuid4().hex[:8]}",
            status=AccountStatus.ACTIVE,
        )
        s.add(acc)
        await s.flush()
        s.add(
            Profile(
                account_id=acc.id, fingerprint=fpm.generate(), os_family="windows", locale="auto"
            )
        )
        await s.commit()
        aid = acc.id
    yield aid
    async with SessionLocal() as s:
        obj = await s.get(Account, aid)
        if obj is not None:
            await s.delete(obj)
        await s.commit()


async def _load(s, aid):
    return await s.get(Account, aid, options=[selectinload(Account.persona)])


async def _run(aid, **kw):
    async with SessionLocal() as s:
        acc = await _load(s, aid)
        return await engine.run_for_account(
            s,
            acc,
            None,
            channel_factory=_Channel,
            replier=_Replier(),
            rng=random.Random(1),
            sleep=_no_sleep,
            **kw,
        )


async def test_engine_replies_once_skips_self_and_spam_and_answers_dms(account):
    _Channel.sent.clear()
    _Channel.outcome = engine.Outcome(True, "ok")
    async with SessionLocal() as s:
        me = (await s.get(Account, account)).handle
    _Channel.pool = [
        _comment("c1", "ban_a", "hay quá"),
        _comment("c2", me, "cảm ơn mọi người"),
        _comment("c3", "ban_c", "spam ib"),
        _comment("c4", "ban_d", "cũ rồi", age_hours=100),
        _comment("c5", "ban_e", "đã rep", replied=True),
    ]
    _Channel.threads = [
        engine.Thread("t1", "ban_f", "9", "https://www.instagram.com/direct/t/t1/"),
        engine.Thread("t2", "ban_g", "8", "https://www.instagram.com/direct/t/t2/"),
    ]
    _Channel.msgs = {
        "t1": [engine.Message("m1", False, "chào bạn")],
        "t2": [engine.Message("m2", False, "hi"), engine.Message("m3", True, "chào")],
    }
    report = await _run(account, limits=engine.Limits(reply_ratio=1.0, pause=(0, 0)))
    assert report.replied == 1 and report.dm_replied == 1 and report.skipped == 1, report
    assert ("reply", "c1", "rep:ban_a") in _Channel.sent
    assert ("dm", "t1", "dm:ban_f") in _Channel.sent
    assert len(_Channel.sent) == 2

    # Chay lai: khong gui gi them - moi thu da co khoa.
    report = await _run(account, limits=engine.Limits(reply_ratio=1.0, pause=(0, 0)))
    assert report.replied == 0 and report.dm_replied == 0 and len(_Channel.sent) == 2

    async with SessionLocal() as s:
        rows = list(
            (
                await s.execute(
                    select(ActivityJob).where(
                        ActivityJob.account_id == account,
                        ActivityJob.kind.in_([ActivityKind.REPLY, ActivityKind.DM]),
                    )
                )
            ).scalars()
        )
    kinds = sorted((r.kind.value, r.status.value) for r in rows)
    assert kinds == [("dm", "succeeded"), ("reply", "skipped"), ("reply", "succeeded")]
    ok = next(r for r in rows if r.kind is ActivityKind.REPLY and r.status is JobStatus.SUCCEEDED)
    assert "@ban_a: hay quá → rep:ban_a" == ok.detail


async def test_engine_respects_hourly_budget_and_ratio(account):
    _Channel.sent.clear()
    _Channel.threads = []
    _Channel.pool = [_comment(f"c{i}", f"ban_{i}", "hay") for i in range(5)]
    report = await _run(
        account, limits=engine.Limits(max_per_hour=2, reply_ratio=1.0, pause=(0, 0))
    )
    assert report.replied == 2 and report.stopped == "hết hạn mức giờ này"
    assert len(_Channel.sent) == 2
    _Channel.sent.clear()
    report = await _run(
        account, limits=engine.Limits(max_per_hour=2, reply_ratio=1.0, pause=(0, 0))
    )
    assert report.replied == 0 and report.stopped == "hết hạn mức giờ này" and not _Channel.sent

    async with SessionLocal() as s:
        # Xoa lich su de thu ti le
        for r in list(
            (
                await s.execute(select(ActivityJob).where(ActivityJob.account_id == account))
            ).scalars()
        ):
            await s.delete(r)
        await s.commit()
    report = await _run(
        account, limits=engine.Limits(max_per_hour=50, reply_ratio=0.0, pause=(0, 0))
    )
    assert report.replied == 0 and report.skipped == 5 and not _Channel.sent


async def test_engine_stops_and_opens_takeover_on_checkpoint(account):
    _Channel.sent.clear()
    _Channel.threads = []
    _Channel.pool = [_comment("x1", "ban_x", "hay"), _comment("x2", "ban_y", "hay")]
    _Channel.outcome = engine.Outcome(False, "challenge_required", needs_human=True)
    try:
        report = await _run(account, limits=engine.Limits(reply_ratio=1.0, pause=(0, 0)))
    finally:
        _Channel.outcome = engine.Outcome(True, "ok")
    assert report.failed == 1 and report.stopped and len(_Channel.sent) == 1
    async with SessionLocal() as s:
        acc = await s.get(Account, account)
        assert acc.status is AccountStatus.NEEDS_HUMAN
        req = (
            await s.execute(
                select(TakeoverRequest).where(
                    TakeoverRequest.account_id == account,
                    TakeoverRequest.status == TakeoverStatus.OPEN,
                )
            )
        ).scalar_one()
        assert "chatbot" in req.reason


async def test_engine_survives_a_dead_replier(account):
    class _Broken:
        name = "broken"

        async def reply_comment(self, ctx):
            raise writer.ReplierError("Anthropic API 401")

        async def reply_dm(self, ctx):
            raise writer.ReplierError("Anthropic API 401")

    _Channel.sent.clear()
    _Channel.threads = []
    _Channel.pool = [_comment("z1", "ban_z", "hay")]
    async with SessionLocal() as s:
        acc = await _load(s, account)
        report = await engine.run_for_account(
            s,
            acc,
            None,
            channel_factory=_Channel,
            replier=_Broken(),
            limits=engine.Limits(reply_ratio=1.0, pause=(0, 0)),
            rng=random.Random(1),
            sleep=_no_sleep,
        )
    assert report.stopped and "401" in report.stopped and not _Channel.sent


def test_prompt_json_is_serialisable():
    ctx = writer.CommentContext(BRIEF, "x", "a", "b")
    json.dumps({"system": writer.system_prompt(BRIEF), "user": writer.comment_prompt(ctx)})
