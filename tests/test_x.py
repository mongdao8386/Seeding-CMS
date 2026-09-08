"""X qua twifork - khong mang, khong DB.

Cai duoc kiem: doc URL dich, cookie auth_token/ct0, cat 280 ky tu, loai media, doc
timeline (retweet -> bai goc, bo tra loi), dich ngoai le (phien chet -> nguoi, handshake
hong -> THU VIEN chu khong phai tai khoan, khoa -> terminal, 429/404 -> thu lai), runner
goi dung hanh dong, adapter dang chu / kem media / cat dai, va kiem phien nem
LibraryBroken thay vi ghi len tai khoan.
"""

from __future__ import annotations

import random
import uuid
from pathlib import Path
from types import SimpleNamespace
from typing import ClassVar

import httpx
import pytest
from twikit import errors as ex

from seeding.browser.checkpoints import CheckpointKind
from seeding.content.comments import COMMENTS
from seeding.domain.models import Account, ActivityJob, ActivityKind, Profile, Proxy, Variant
from seeding.platforms.base import LibraryBroken
from seeding.platforms.x import client as xc
from seeding.platforms.x import interact as xi
from seeding.platforms.x import publish as xp
from seeding.platforms.x import warm as xw

# ------------------------------------------------------------------ thuan tuy


def test_parse_target_status_and_profile():
    assert xi.parse_target("https://x.com/some_one/status/1234567890") == ("some_one", "1234567890")
    assert xi.parse_target("https://x.com/some_one/status/1234567890?s=20") == (
        "some_one",
        "1234567890",
    )
    assert xi.parse_target("https://x.com/some_one") == ("some_one", None)
    assert xi.parse_target("https://x.com/home") == (None, None)
    assert xi.parse_target(None) == (None, None)


def test_cookies_from_storage_state():
    state = {
        "cookies": [
            {"name": "auth_token", "value": "a" * 40},
            {"name": "ct0", "value": "c" * 32},
            {"name": "guest_id", "value": "g"},
        ]
    }
    assert xc.cookies_from(state) == {"auth_token": "a" * 40, "ct0": "c" * 32}
    assert xc.cookies_from(None) == {}


def test_truncate_keeps_short_text_and_cuts_long_at_a_word():
    assert xc.truncate("ngắn thôi") == "ngắn thôi"
    long = " ".join(["từ"] * 200)
    out = xc.truncate(long)
    assert len(out) <= xc.TWEET_MAX and out.endswith("…") and not out.endswith(" …")


def test_media_category_by_extension():
    assert xc.media_category(Path("a.MP4")) == "tweet_video"
    assert xc.media_category(Path("a.png")) == "tweet_image"
    assert xc.media_category(Path("a.gif")) == "tweet_gif"
    assert xc.media_category(Path("a.txt")) is None


def _tweet(tid, handle, *, views=100_000, reply=None, retweet=None):
    return SimpleNamespace(
        id=tid,
        user=SimpleNamespace(id=f"u{tid}", screen_name=handle),
        view_count=views,
        favorite_count=5,
        text="x",
        in_reply_to=reply,
        retweeted_tweet=retweet,
    )


def test_parse_feed_unwraps_retweets_and_skips_replies():
    original = _tweet("1", "creator")
    tweets = [
        _tweet("9", "retweeter", retweet=original),
        _tweet("2", "replier", reply="1"),
        _tweet("3", "other", views=None),
        _tweet("1", "creator"),  # trung voi bai goc cua retweet
    ]
    items = xc.parse_feed(tweets)
    assert [(i.item_id, i.author_handle) for i in items] == [("1", "creator"), ("3", "other")]
    assert items[0].url == "https://x.com/creator/status/1"
    assert items[1].views == 0


@pytest.mark.parametrize(
    "exc, idempotent, expect",
    [
        (ex.InvalidSession("shell"), True, "human"),
        (ex.ClientTransactionError("ondemand"), True, "library"),
        (ex.AccountSuspended("bye"), True, "terminal"),
        (ex.Forbidden("your account is suspended"), True, "terminal"),
        (ex.AccountLocked("arkose"), True, "human"),
        (ex.Unauthorized("32"), True, "human"),
        (ex.Forbidden("226 automated"), True, "human"),
        (ex.TooManyRequests("88"), False, "retry"),
        (ex.NotFound("404"), False, "retry"),
        (ex.ServerError("500"), True, "retry"),
        (ex.ServerError("500"), False, "human"),
        (httpx.ReadTimeout("t"), False, "human"),
        (ex.DuplicateTweet("187"), False, "fail"),
        (ex.BadRequest("weird"), True, "fail"),
    ],
)
def test_exceptions_are_classified(exc, idempotent, expect):
    r = xc.classify_exc(exc, idempotent=idempotent)
    assert not r.ok
    got = (
        "library"
        if r.library
        else "terminal"
        if r.terminal
        else "human"
        if r.needs_human
        else "retry"
        if r.retryable
        else "fail"
    )
    assert got == expect, r.detail


def test_reply_text_comes_from_the_pool_with_a_suffix():
    jid = uuid.uuid4()
    # Mac dinh (sticker): chi emoji, khong chu, khong duoi.
    sticker = xi.reply_text(jid)
    assert sticker == xi.reply_text(jid) and not any(ch.isalnum() for ch in sticker)
    # Kieu chu: cau tu bo chung + mot duoi nho de X khong chan trung.
    text = xi.reply_text(jid, style="text")
    assert text == xi.reply_text(jid, style="text")
    assert any(text.startswith(c) for c in COMMENTS)
    assert text[len(next(c for c in COMMENTS if text.startswith(c))) :] in xi.SUFFIXES


def test_result_mapping_treats_library_trouble_as_retry_not_checkpoint():
    lib = xi._to_result(xc.ActionResult(False, "lệch", library=True))
    assert lib.retryable and lib.checkpoint is None
    human = xi._to_result(xc.ActionResult(False, "verify", needs_human=True))
    assert human.checkpoint is not None and human.checkpoint.kind is CheckpointKind.VERIFY
    dead = xi._to_result(xc.ActionResult(False, "suspended", terminal=True))
    assert dead.checkpoint is not None and dead.checkpoint.is_terminal


# ------------------------------------------------------------------ runner


class _FakeX:
    calls: ClassVar[list] = []
    raise_on_enter: ClassVar[BaseException | None] = None

    def __init__(self, profile):
        self.profile = profile

    async def __aenter__(self):
        if _FakeX.raise_on_enter:
            raise _FakeX.raise_on_enter
        return self

    async def __aexit__(self, *exc):
        return None

    async def watch(self, tid):
        _FakeX.calls.append(("watch", tid))

    async def repost(self, tid):
        _FakeX.calls.append(("repost", tid))
        return xc.ActionResult(True, "ok")

    async def like(self, tid):
        _FakeX.calls.append(("like", tid))
        return xc.ActionResult(True, "ok")

    async def comment(self, tid, text):
        _FakeX.calls.append(("comment", tid, text))
        return xc.ActionResult(True, "ok")

    async def user_id(self, handle):
        _FakeX.calls.append(("user_id", handle))
        return "42"

    async def follow(self, user_id):
        _FakeX.calls.append(("follow", user_id))
        return xc.ActionResult(True, "ok")


async def _no_sleep(_seconds):
    return None


class _NoSession:
    async def get(self, model, key):
        raise AssertionError("session.get duoc goi")


def _profile() -> Profile:
    p = Profile(id=uuid.uuid4(), proxy_id=uuid.uuid4(), fingerprint={})
    p.proxy = Proxy(host="proxy.example.com", port=8080, scheme="http")
    return p


def _job(kind, url):
    return ActivityJob(id=uuid.uuid4(), account_id=uuid.uuid4(), kind=kind, target_url=url)


async def test_like_comment_follow_call_the_right_thing():
    _FakeX.calls.clear()
    url = "https://x.com/creator/status/777"
    assert (
        await xi.run(
            _NoSession(),
            _profile(),
            _job(ActivityKind.ENGAGE, url),
            client_factory=_FakeX,
            sleep=_no_sleep,
        )
    ).ok
    assert (
        await xi.run(
            _NoSession(),
            _profile(),
            _job(ActivityKind.COMMENT, url),
            client_factory=_FakeX,
            rng=random.Random(1),
            sleep=_no_sleep,
        )
    ).ok
    assert (
        await xi.run(
            _NoSession(),
            _profile(),
            _job(ActivityKind.FOLLOW, "https://x.com/creator"),
            client_factory=_FakeX,
            sleep=_no_sleep,
        )
    ).ok
    assert _FakeX.calls[0] == ("watch", "777") and _FakeX.calls[1] == ("like", "777")
    assert _FakeX.calls[2] == ("watch", "777")
    assert _FakeX.calls[3][:2] == ("comment", "777") and _FakeX.calls[3][2]
    assert _FakeX.calls[4:] == [("user_id", "creator"), ("follow", "42")]
    _FakeX.calls.clear()
    assert (
        await xi.run(
            _NoSession(),
            _profile(),
            _job(ActivityKind.REPOST, url),
            client_factory=_FakeX,
            sleep=_no_sleep,
        )
    ).ok
    assert _FakeX.calls == [("watch", "777"), ("repost", "777")]


async def test_library_trouble_at_login_is_a_retry_not_a_checkpoint():
    _FakeX.raise_on_enter = ex.ClientTransactionError("chunk map changed")
    try:
        r = await xi.run(
            _NoSession(),
            _profile(),
            _job(ActivityKind.ENGAGE, "https://x.com/creator/status/1"),
            client_factory=_FakeX,
            sleep=_no_sleep,
        )
    finally:
        _FakeX.raise_on_enter = None
    assert not r.ok and r.retryable and r.checkpoint is None


# ------------------------------------------------------------------ dang bai


class _FakePoster:
    posted: ClassVar[list] = []
    raise_with: ClassVar[BaseException | None] = None

    def __init__(self, profile):
        self.profile = profile

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return None

    async def post(self, text, media=None):
        if _FakePoster.raise_with:
            raise _FakePoster.raise_with
        _FakePoster.posted.append((text, media.name if media else None))
        return SimpleNamespace(id="555")


def _ready_profile() -> Profile:
    p = _profile()
    p.cookies_enc = "enc"
    return p


async def test_text_only_and_media_posts(tmp_path):
    _FakePoster.posted.clear()
    adapter = xp.XAdapter(client_factory=_FakePoster)
    acc = Account(handle="@x_one")
    r = await adapter.publish(acc, Variant(title="chào", body="thân"), {}, profile=_ready_profile())
    assert r.ok and r.remote_url == "https://x.com/x_one/status/555" and r.metrics["kind"] == "text"
    f = tmp_path / "v.mp4"
    f.write_bytes(b"x")
    r = await adapter.publish(
        acc, Variant(title="video", body="", media_variant_ref=str(f)), {}, profile=_ready_profile()
    )
    assert r.ok and r.metrics["kind"] == "tweet_video"
    assert _FakePoster.posted == [("chào\n\nthân", None), ("video", "v.mp4")]


async def test_long_text_is_cut_and_bad_media_refused(tmp_path):
    _FakePoster.posted.clear()
    adapter = xp.XAdapter(client_factory=_FakePoster)
    acc = Account(handle="x_one")
    r = await adapter.publish(acc, Variant(title="a " * 300, body=""), {}, profile=_ready_profile())
    assert r.ok and r.metrics["chars"] <= xc.TWEET_MAX
    f = tmp_path / "doc.pdf"
    f.write_bytes(b"x")
    r = await adapter.publish(
        acc, Variant(title="t", body="", media_variant_ref=str(f)), {}, profile=_ready_profile()
    )
    assert not r.ok and "media type" in r.error


async def test_library_trouble_while_posting_is_retryable_not_human():
    adapter = xp.XAdapter(client_factory=_FakePoster)
    _FakePoster.raise_with = ex.ClientTransactionError("KEY_BYTE")
    try:
        r = await adapter.publish(
            Account(handle="x"), Variant(title="t", body=""), {}, profile=_ready_profile()
        )
    finally:
        _FakePoster.raise_with = None
    assert not r.ok and r.retryable and not r.needs_human and r.metrics.get("library")

    _FakePoster.raise_with = httpx.ReadTimeout("after send")
    try:
        r = await adapter.publish(
            Account(handle="x"), Variant(title="t", body=""), {}, profile=_ready_profile()
        )
    finally:
        _FakePoster.raise_with = None
    assert not r.ok and r.needs_human and not r.retryable


# ------------------------------------------------------------------ kiem phien


class _FakeXClient:
    fail_with: ClassVar[BaseException | None] = None

    def __init__(self, profile):
        self.profile = profile

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return None

    async def me(self):
        if _FakeXClient.fail_with:
            raise _FakeXClient.fail_with
        return SimpleNamespace(screen_name="me")


async def test_health_check_separates_library_from_account(monkeypatch):
    monkeypatch.setattr(xc, "XClient", _FakeXClient)
    p = _ready_profile()
    assert await xc.check(p) == (True, "still signed in as @me")

    _FakeXClient.fail_with = ex.Unauthorized("32")
    ok, detail = await xc.check(p)
    assert not ok and "human" in detail

    _FakeXClient.fail_with = ex.ClientTransactionError("ondemand")
    with pytest.raises(LibraryBroken):
        await xc.check(p)
    _FakeXClient.fail_with = None


# ------------------------------------------------------------------ nuoi


def test_profile_url_strips_the_at():
    assert xw.profile_url("@creator") == "https://x.com/creator"
    assert xw.profile_url("creator") == "https://x.com/creator"


async def test_client_refuses_without_proxy_or_cookies():
    p = Profile(id=uuid.uuid4(), proxy_id=None, fingerprint={})
    p.proxy = None
    with pytest.raises(ValueError):
        xc.XClient(p)
    p = _profile()
    p.set_cookies({"cookies": [{"name": "auth_token", "value": "a"}]})
    with pytest.raises(RuntimeError):
        async with xc.XClient(
            p, client_factory=lambda **kw: SimpleNamespace(set_cookies=lambda c: None)
        ):
            pass
