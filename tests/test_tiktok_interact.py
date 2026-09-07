"""Runner HTTP cho job nham dich tren TikTok: doc dich tu URL, goi dung hanh dong, va
dich ket qua sang InteractResult ma worker hieu."""

import random
import uuid
from typing import ClassVar

from seeding.browser.checkpoints import CheckpointKind
from seeding.core import tiktok_interact as ti
from seeding.core.tiktok_web import ActionResult
from seeding.models import ActivityJob, ActivityKind, Profile, Proxy


def test_parse_target_video_and_profile():
    assert ti.parse_target("https://www.tiktok.com/@abc.d/video/7682818232956341524") == (
        "abc.d",
        "7682818232956341524",
    )
    assert ti.parse_target("https://www.tiktok.com/@abc.d") == ("abc.d", None)
    assert ti.parse_target("https://www.tiktok.com/@abc.d/") == ("abc.d", None)
    assert ti.parse_target("https://www.tiktok.com/tag/x") == (None, None)
    assert ti.parse_target(None) == (None, None)


def test_comment_text_is_deterministic_per_job_and_from_the_pool():
    jid = uuid.uuid4()
    assert ti.comment_text(jid) == ti.comment_text(jid)
    assert ti.comment_text(jid) in ti.COMMENTS
    assert ti.comment_text(jid, random.Random(1)) in ti.COMMENTS


def test_result_mapping():
    ok = ti._to_result(ActionResult(True, "ok"))
    assert ok.ok
    human = ti._to_result(ActionResult(False, "verify", needs_human=True))
    assert human.checkpoint is not None and human.checkpoint.kind is CheckpointKind.VERIFY
    assert not human.checkpoint.is_terminal
    again = ti._to_result(ActionResult(False, "treo", retryable=True))
    assert again.retryable and again.checkpoint is None


class _FakeWeb:
    """TikTokWeb gia: ghi lai hanh dong duoc goi."""

    calls: ClassVar[list] = []

    def __init__(self, profile):
        self.profile = profile

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return None

    async def like(self, item_id):
        _FakeWeb.calls.append(("like", item_id))
        return ActionResult(True, "ok")

    async def comment(self, item_id, text):
        _FakeWeb.calls.append(("comment", item_id, text))
        return ActionResult(True, "ok")

    async def user(self, handle, sec_uid=""):
        _FakeWeb.calls.append(("user", handle))
        return {"id": "9", "secUid": "S", "uniqueId": handle, "followers": 1}

    async def follow(self, user_id, sec_uid):
        _FakeWeb.calls.append(("follow", user_id, sec_uid))
        return ActionResult(True, "ok")


class _NoSession:
    async def get(self, model, key):  # khong bao gio duoc goi trong cac test duoi
        raise AssertionError("session.get duoc goi")


def _profile() -> Profile:
    p = Profile(id=uuid.uuid4(), proxy_id=uuid.uuid4())
    p.proxy = Proxy(host="1.2.3.4", port=8080, scheme="http")
    return p


def _job(kind, url) -> ActivityJob:
    return ActivityJob(
        id=uuid.uuid4(), kind=kind, target_url=url, target_account_id=None, duration_seconds=30
    )


async def test_like_follow_comment_dispatch():
    _FakeWeb.calls.clear()
    p = _profile()
    r = await ti.run(
        _NoSession(),
        p,
        _job(ActivityKind.ENGAGE, "https://www.tiktok.com/@c/video/11"),
        web_factory=_FakeWeb,
    )
    assert r.ok
    r = await ti.run(
        _NoSession(),
        p,
        _job(ActivityKind.FOLLOW, "https://www.tiktok.com/@c"),
        web_factory=_FakeWeb,
    )
    assert r.ok
    r = await ti.run(
        _NoSession(),
        p,
        _job(ActivityKind.COMMENT, "https://www.tiktok.com/@c/video/11"),
        web_factory=_FakeWeb,
    )
    assert r.ok
    kinds = [c[0] for c in _FakeWeb.calls]
    assert kinds == ["like", "user", "follow", "comment"]
    assert _FakeWeb.calls[2] == ("follow", "9", "S")
    assert _FakeWeb.calls[3][2] in ti.COMMENTS


async def test_missing_target_is_a_clear_failure_without_touching_tiktok():
    _FakeWeb.calls.clear()
    r = await ti.run(
        _NoSession(),
        _profile(),
        _job(ActivityKind.ENGAGE, "https://www.tiktok.com/@c"),
        web_factory=_FakeWeb,
    )
    assert not r.ok and "no video url" in r.detail and _FakeWeb.calls == []


async def test_repost_over_http_is_refused_explicitly():
    r = await ti.run(
        _NoSession(),
        _profile(),
        _job(ActivityKind.REPOST, "https://www.tiktok.com/@c/video/1"),
        web_factory=_FakeWeb,
    )
    assert not r.ok and "not implemented" in r.detail


async def test_profile_without_proxy_is_refused():
    p = Profile(id=uuid.uuid4(), proxy_id=None)
    p.proxy = None
    r = await ti.run(
        _NoSession(),
        p,
        _job(ActivityKind.ENGAGE, "https://www.tiktok.com/@c/video/1"),
        web_factory=_FakeWeb,
    )
    assert not r.ok and "no proxy" in r.detail
