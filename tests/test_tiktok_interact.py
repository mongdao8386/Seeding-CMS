"""Runner HTTP cho job nham dich tren TikTok: doc dich tu URL, goi dung hanh dong, va
dich ket qua sang InteractResult ma worker hieu."""

import random
import uuid
from typing import ClassVar

from seeding.browser.checkpoints import CheckpointKind
from seeding.domain.models import ActivityJob, ActivityKind, Profile, Proxy
from seeding.platforms.tiktok import interact as ti
from seeding.platforms.tiktok.web import ActionResult


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

    async def item(self, item_id):
        _FakeWeb.calls.append(("item", item_id))
        return {"itemInfo": {}}

    async def repost(self, item_id):
        _FakeWeb.calls.append(("repost", item_id))
        return ActionResult(True, "ok")

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


WAITS: list[float] = []


async def _sleep(seconds):
    WAITS.append(seconds)


async def test_like_follow_comment_dispatch_watches_first():
    _FakeWeb.calls.clear()
    WAITS.clear()
    p = _profile()
    r = await ti.run(
        _NoSession(),
        p,
        _job(ActivityKind.ENGAGE, "https://www.tiktok.com/@c/video/11"),
        web_factory=_FakeWeb,
        sleep=_sleep,
    )
    assert r.ok
    r = await ti.run(
        _NoSession(),
        p,
        _job(ActivityKind.FOLLOW, "https://www.tiktok.com/@c"),
        web_factory=_FakeWeb,
        sleep=_sleep,
    )
    assert r.ok
    r = await ti.run(
        _NoSession(),
        p,
        _job(ActivityKind.COMMENT, "https://www.tiktok.com/@c/video/11"),
        web_factory=_FakeWeb,
        sleep=_sleep,
    )
    assert r.ok
    kinds = [c[0] for c in _FakeWeb.calls]
    # Mo trang truoc, xem, roi moi bam - khong bao gio bam ngay.
    assert kinds == ["item", "like", "user", "follow", "item", "comment"]
    assert _FakeWeb.calls[3] == ("follow", "9", "S")
    # Binh luan nuoi mac dinh la sticker TikTok ([ten]), khong chu.
    assert _FakeWeb.calls[5][2].startswith("[") and _FakeWeb.calls[5][2].endswith("]")
    assert WAITS == [30, 30, 30], "cho dung duration_seconds cua job truoc moi hanh dong"


async def test_repost_opens_the_video_then_reposts():
    _FakeWeb.calls.clear()
    WAITS.clear()
    r = await ti.run(
        _NoSession(),
        _profile(),
        _job(ActivityKind.REPOST, "https://www.tiktok.com/@c/video/1"),
        web_factory=_FakeWeb,
        sleep=_sleep,
    )
    assert r.ok and [c[0] for c in _FakeWeb.calls] == ["item", "repost"] and WAITS == [30]


async def test_missing_target_is_a_clear_failure_without_touching_tiktok():
    _FakeWeb.calls.clear()
    r = await ti.run(
        _NoSession(),
        _profile(),
        _job(ActivityKind.ENGAGE, "https://www.tiktok.com/@c"),
        web_factory=_FakeWeb,
    )
    assert not r.ok and "no video url" in r.detail and _FakeWeb.calls == []


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
