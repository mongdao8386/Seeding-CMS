"""Instagram qua aiograpi - khong mang, khong DB.

Cai duoc kiem: doc URL dich, doi shortcode <-> pk, dich ngoai le aiograpi thanh ket qua
(checkpoint -> nguoi, "please wait" -> thu lai, mang dut khi binh luan -> nguoi, khoa
han -> terminal), runner goi dung hanh dong voi dung pk, adapter dang anh/video dung
duong va khong bao gio bao thanh cong khi thieu media id, thiet bi giu co dinh theo
profile, va lich nuoi dung URL trang ca nhan Instagram.
"""

from __future__ import annotations

import random
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from typing import ClassVar

import httpx
import pytest
from aiograpi import exceptions as ex

from seeding.browser.checkpoints import CheckpointKind
from seeding.domain.models import Account, ActivityJob, ActivityKind, Profile, Proxy, Variant
from seeding.platforms.base import InteractResult
from seeding.platforms.instagram import client as igc
from seeding.platforms.instagram import interact as ii
from seeding.platforms.instagram import publish as ip
from seeding.platforms.instagram import warm as iw
from seeding.platforms.outreach import Budget, build_jobs

# ------------------------------------------------------------------ thuan tuy


def test_parse_target_reel_post_and_profile():
    assert ii.parse_target("https://www.instagram.com/reel/DDjhrq4S8Yw/") == (None, "DDjhrq4S8Yw")
    assert ii.parse_target("https://www.instagram.com/p/DDjhrq4S8Yw") == (None, "DDjhrq4S8Yw")
    assert ii.parse_target("https://www.instagram.com/some.creator_/") == ("some.creator_", None)
    assert ii.parse_target("https://www.instagram.com/explore/") == (None, None)
    assert ii.parse_target(None) == (None, None)


def test_code_and_pk_round_trip():
    pk = "3512345678901234567"
    assert igc.pk_from_code(igc.code_from_pk(pk)) == pk
    assert igc.pk_from_code("B") == "1"


def test_sessionid_is_read_from_storage_state():
    state = {
        "cookies": [
            {"name": "csrftoken", "value": "x"},
            {"name": "sessionid", "value": "123%3Aabc"},
        ]
    }
    assert igc.sessionid_from(state) == "123%3Aabc"
    assert igc.sessionid_from({"cookies": []}) is None
    assert igc.sessionid_from(None) is None


def test_parse_feed_skips_items_without_author():
    medias = [
        SimpleNamespace(
            pk=1,
            code="AAA",
            user=SimpleNamespace(pk=7, username="a"),
            play_count=50_000,
            like_count=3,
            caption_text="x",
        ),
        SimpleNamespace(pk=2, code="BBB", user=None, play_count=9, like_count=0, caption_text=""),
        SimpleNamespace(
            pk=3,
            code="CCC",
            user=SimpleNamespace(pk=8, username="c"),
            play_count=None,
            view_count=70_000,
            like_count=None,
            caption_text=None,
        ),
    ]
    items = igc.parse_feed(medias)
    assert [i.author_handle for i in items] == ["a", "c"]
    assert items[0].url == "https://www.instagram.com/reel/AAA/"
    assert items[1].views == 70_000 and items[1].likes == 0


@pytest.mark.parametrize(
    "exc, idempotent, expect",
    [
        (ex.ChallengeRequired("challenge"), True, "human"),
        (ex.LoginRequired("login"), True, "human"),
        (ex.SentryBlock("sentry"), True, "human"),
        (ex.AccountSuspended("bye"), True, "terminal"),
        (ex.PleaseWaitFewMinutes("wait"), False, "retry"),
        (ex.FeedbackRequired("blocked"), False, "retry"),
        (httpx.ConnectTimeout("t"), True, "retry"),
        (httpx.ConnectTimeout("t"), False, "human"),
        (ex.ClientError("weird"), True, "fail"),
    ],
)
def test_exceptions_are_classified(exc, idempotent, expect):
    r = igc.classify_exc(exc, idempotent=idempotent)
    assert not r.ok
    got = (
        "terminal"
        if r.terminal
        else "human"
        if r.needs_human
        else "retry"
        if r.retryable
        else "fail"
    )
    assert got == expect, r.detail


def test_result_mapping_to_worker_contract():
    human = ii._to_result(igc.ActionResult(False, "verify", needs_human=True))
    assert human.checkpoint is not None and human.checkpoint.kind is CheckpointKind.VERIFY
    dead = ii._to_result(igc.ActionResult(False, "suspended", terminal=True))
    assert dead.checkpoint is not None and dead.checkpoint.is_terminal
    again = ii._to_result(igc.ActionResult(False, "wait", retryable=True))
    assert again.retryable and again.checkpoint is None
    assert isinstance(again, InteractResult)


# ------------------------------------------------------------------ runner


class _FakeIG:
    calls: ClassVar[list] = []
    raise_on_enter: ClassVar[BaseException | None] = None

    def __init__(self, profile):
        self.profile = profile

    async def __aenter__(self):
        if _FakeIG.raise_on_enter:
            raise _FakeIG.raise_on_enter
        return self

    async def __aexit__(self, *exc):
        return None

    async def watch(self, pk):
        _FakeIG.calls.append(("watch", pk))

    async def like(self, pk):
        _FakeIG.calls.append(("like", pk))
        return igc.ActionResult(True, "ok")

    async def comment(self, pk, text):
        _FakeIG.calls.append(("comment", pk, text))
        return igc.ActionResult(True, "ok")

    async def user_id(self, handle):
        _FakeIG.calls.append(("user_id", handle))
        return "42"

    async def follow(self, user_id):
        _FakeIG.calls.append(("follow", user_id))
        return igc.ActionResult(True, "ok")


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


async def test_like_and_comment_use_the_media_pk_from_the_code():
    _FakeIG.calls.clear()
    code = "DDjhrq4S8Yw"
    r = await ii.run(
        _NoSession(),
        _profile(),
        _job(ActivityKind.ENGAGE, f"https://www.instagram.com/reel/{code}/"),
        client_factory=_FakeIG,
        sleep=_no_sleep,
    )
    assert r.ok
    r = await ii.run(
        _NoSession(),
        _profile(),
        _job(ActivityKind.COMMENT, f"https://www.instagram.com/p/{code}/"),
        client_factory=_FakeIG,
        rng=random.Random(3),
    )
    assert r.ok
    pk = igc.pk_from_code(code)
    assert _FakeIG.calls[0] == ("watch", pk) and _FakeIG.calls[1] == ("like", pk)
    assert _FakeIG.calls[2] == ("watch", pk)
    assert _FakeIG.calls[3][:2] == ("comment", pk) and _FakeIG.calls[3][2]


async def test_follow_resolves_the_handle_first():
    _FakeIG.calls.clear()
    r = await ii.run(
        _NoSession(),
        _profile(),
        _job(ActivityKind.FOLLOW, "https://www.instagram.com/some.one/"),
        client_factory=_FakeIG,
        sleep=_no_sleep,
    )
    assert r.ok
    assert _FakeIG.calls == [("user_id", "some.one"), ("follow", "42")]


async def test_refuses_without_proxy_and_without_media():
    p = Profile(id=uuid.uuid4(), proxy_id=None, fingerprint={})
    p.proxy = None
    r = await ii.run(
        _NoSession(),
        p,
        _job(ActivityKind.ENGAGE, "https://www.instagram.com/reel/AAA/"),
        client_factory=_FakeIG,
        sleep=_no_sleep,
    )
    assert not r.ok and "proxy" in r.detail
    r = await ii.run(
        _NoSession(),
        _profile(),
        _job(ActivityKind.ENGAGE, "https://www.instagram.com/some.one/"),
        client_factory=_FakeIG,
        sleep=_no_sleep,
    )
    assert not r.ok and "no media url" in r.detail


async def test_dead_session_at_login_goes_to_a_human():
    _FakeIG.raise_on_enter = ex.LoginRequired("expired")
    try:
        r = await ii.run(
            _NoSession(),
            _profile(),
            _job(ActivityKind.ENGAGE, "https://www.instagram.com/reel/AAA/"),
            client_factory=_FakeIG,
        )
    finally:
        _FakeIG.raise_on_enter = None
    assert not r.ok and r.checkpoint is not None and not r.checkpoint.is_terminal


# ------------------------------------------------------------------ dang bai


class _FakeUploader:
    uploaded: ClassVar[list] = []
    raise_with: ClassVar[BaseException | None] = None
    answer: ClassVar[object] = SimpleNamespace(pk="999", code="XYZ")

    def __init__(self, profile):
        self.profile = profile

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return None

    async def upload(self, path, caption):
        if _FakeUploader.raise_with:
            raise _FakeUploader.raise_with
        _FakeUploader.uploaded.append((path.name, caption))
        return _FakeUploader.answer


def _variant(tmp_path: Path, name: str) -> Variant:
    f = tmp_path / name
    f.write_bytes(b"x")
    return Variant(title="tiêu đề", body="thân bài", media_variant_ref=str(f))


def _ready_profile() -> Profile:
    p = _profile()
    p.cookies_enc = "enc"
    return p


async def test_photo_and_video_get_their_own_urls(tmp_path):
    _FakeUploader.uploaded.clear()
    adapter = ip.InstagramAdapter(client_factory=_FakeUploader)
    acc = Account(handle="ig.one")
    r = await adapter.publish(acc, _variant(tmp_path, "a.jpg"), {}, profile=_ready_profile())
    assert r.ok and r.remote_url == "https://www.instagram.com/p/XYZ/" and r.remote_id == "999"
    r = await adapter.publish(acc, _variant(tmp_path, "b.mp4"), {}, profile=_ready_profile())
    assert r.ok and r.remote_url == "https://www.instagram.com/reel/XYZ/"
    assert _FakeUploader.uploaded[0][1] == "tiêu đề\n\nthân bài"


async def test_publish_refuses_text_only_and_missing_profile(tmp_path):
    adapter = ip.InstagramAdapter(client_factory=_FakeUploader)
    acc = Account(handle="ig.one")
    r = await adapter.publish(acc, Variant(title="t", body=""), {}, profile=_ready_profile())
    assert not r.ok and "media" in r.error
    r = await adapter.publish(acc, _variant(tmp_path, "a.jpg"), {}, profile=None)
    assert not r.ok and not r.retryable


async def test_unknown_outcome_during_upload_waits_for_a_human(tmp_path):
    adapter = ip.InstagramAdapter(client_factory=_FakeUploader)
    acc = Account(handle="ig.one")
    _FakeUploader.raise_with = httpx.ReadTimeout("mid-configure")
    try:
        r = await adapter.publish(acc, _variant(tmp_path, "a.mp4"), {}, profile=_ready_profile())
    finally:
        _FakeUploader.raise_with = None
    assert not r.ok and r.needs_human and not r.retryable

    _FakeUploader.raise_with = ex.PleaseWaitFewMinutes("slow")
    try:
        r = await adapter.publish(acc, _variant(tmp_path, "a.mp4"), {}, profile=_ready_profile())
    finally:
        _FakeUploader.raise_with = None
    assert not r.ok and r.retryable and not r.needs_human


async def test_answer_without_media_id_is_never_a_success(tmp_path):
    adapter = ip.InstagramAdapter(client_factory=_FakeUploader)
    _FakeUploader.answer = SimpleNamespace(pk=None, code=None)
    try:
        r = await adapter.publish(
            Account(handle="x"), _variant(tmp_path, "a.jpg"), {}, profile=_ready_profile()
        )
    finally:
        _FakeUploader.answer = SimpleNamespace(pk="999", code="XYZ")
    assert not r.ok and r.needs_human


# ------------------------------------------------------------------ thiet bi


class _FakeAio:
    """aiograpi.Client gia: ghi lai settings/proxy/sessionid duoc dat."""

    made: ClassVar[list] = []

    def __init__(self):
        self.settings = {
            "uuids": {"phone_id": "fresh"},
            "device_settings": {"model": "fresh"},
            "user_agent": "UA/fresh",
            "country": "US",
            "locale": "en_US",
            "timezone_offset": 0,
        }
        self.proxy = None
        self.username = None
        self.request_timeout = 1
        _FakeAio.made.append(self)

    def set_settings(self, s):
        self.settings = dict(s)
        return True

    def get_settings(self):
        return dict(self.settings)

    def set_proxy(self, dsn):
        self.proxy = dsn

    def set_locale(self, loc):
        self.settings["locale"] = loc

    def set_country(self, c):
        self.settings["country"] = c

    def set_timezone_offset(self, seconds, name=None):
        self.settings["timezone_offset"] = seconds

    async def login_by_sessionid(self, sid):
        self.sid = sid
        self.username = "me"
        return True


def _profile_with_session() -> Profile:
    p = _profile()
    p.proxy = Proxy(host="proxy.example.com", port=8080, scheme="http", username="u")
    p.set_cookies(
        {"cookies": [{"name": "sessionid", "value": "123%3Aabcdefghijklmnopqrstuvwxyz0123456789"}]}
    )
    return p


async def test_device_is_generated_once_then_reused():
    _FakeAio.made.clear()
    p = _profile_with_session()
    async with igc.InstagramClient(p, client_factory=_FakeAio) as ig:
        assert ig.username == "me"
    first = _FakeAio.made[0]
    assert first.proxy.startswith("http://u:") and first.proxy.endswith("@proxy.example.com:8080")
    assert first.settings["locale"] == "vi_VN" and first.settings["country"] == "VN"
    stored = p.fingerprint[igc.DEVICE_KEY]
    assert stored["uuids"] == {"phone_id": "fresh"} and "cookies" not in stored

    async with igc.InstagramClient(p, client_factory=_FakeAio):
        pass
    second = _FakeAio.made[1]
    assert second.settings["uuids"] == {"phone_id": "fresh"}
    assert second.settings["locale"] == "vi_VN", "thiet bi da luu giu nguyen, khong dat lai"


async def test_client_refuses_without_proxy_or_sessionid():
    p = Profile(id=uuid.uuid4(), proxy_id=None, fingerprint={})
    p.proxy = None
    with pytest.raises(ValueError):
        igc.InstagramClient(p, client_factory=_FakeAio)
    p = _profile()
    p.set_cookies({"cookies": [{"name": "csrftoken", "value": "x"}]})
    with pytest.raises(RuntimeError):
        async with igc.InstagramClient(p, client_factory=_FakeAio):
            pass


# ------------------------------------------------------------------ nuoi


def test_follow_jobs_point_at_instagram_profiles():
    account = Account(
        id=uuid.uuid4(), handle="mine", warmup_started_at=datetime.now(UTC) - timedelta(days=3)
    )
    targets = [
        igc.FeedItem(
            item_id=str(i),
            code=f"C{i}",
            author_handle=f"creator{i}",
            author_id=str(i),
            views=100_000,
            likes=1,
            desc="",
        )
        for i in range(4)
    ]
    day = datetime.now(UTC).date()
    start = datetime.combine(day, datetime.min.time(), tzinfo=UTC) + timedelta(hours=8)
    jobs = build_jobs(
        account,
        targets,
        Budget(2, 1, 1),
        day=day,
        window=(start, start + timedelta(hours=6)),
        rng=random.Random(1),
        profile_url=iw.profile_url,
    )
    follows = [j for j in jobs if j.kind is ActivityKind.FOLLOW]
    assert (
        follows
        and follows[0].target_url == f"https://www.instagram.com/{targets[0].author_handle}/"
    )
    likes = [j for j in jobs if j.kind is ActivityKind.ENGAGE]
    assert likes[0].target_url.startswith("https://www.instagram.com/reel/")
