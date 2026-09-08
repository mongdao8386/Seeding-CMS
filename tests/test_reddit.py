"""Reddit qua PRAW - khong mang. Doc URL dich, doc front page, dich ngoai le, runner nuoi,
adapter dang bai (subreddit bat buoc, chu / anh / video), xoa / sua, va lich nuoi voi
nguong diem thay vi luot xem."""

from __future__ import annotations

import random
import uuid
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from typing import ClassVar

import pytest
from prawcore import exceptions as pc

from seeding.domain.models import Account, ActivityJob, ActivityKind, Platform, Variant
from seeding.platforms import manage
from seeding.platforms.outreach import Budget, build_jobs, pick_targets
from seeding.platforms.reddit import client as rc
from seeding.platforms.reddit import interact as ri
from seeding.platforms.reddit import manage as rm
from seeding.platforms.reddit import publish as rp
from seeding.platforms.reddit import warm as rw


def test_parse_target():
    assert ri.parse_target("https://www.reddit.com/r/vietnam/comments/1abc2d/title/") == (
        None,
        "1abc2d",
    )
    assert ri.parse_target("https://www.reddit.com/user/some_one") == ("some_one", None)
    assert ri.parse_target("https://www.reddit.com/u/some_one/") == ("some_one", None)
    assert ri.parse_target("https://www.reddit.com/r/vietnam/") == (None, None)


def _sub(sid, author, score=500, stickied=False):
    return SimpleNamespace(
        id=sid,
        author=SimpleNamespace(name=author, id=f"u_{author}"),
        score=score,
        title="t",
        subreddit=SimpleNamespace(display_name="vietnam"),
        permalink=f"/r/vietnam/comments/{sid}/t/",
        stickied=stickied,
    )


def test_parse_feed_skips_stickied_and_deleted_authors():
    subs = [_sub("a", "one"), _sub("b", "two", stickied=True), SimpleNamespace(id="c", author=None)]
    items = rc.parse_feed(subs)
    assert [i.item_id for i in items] == ["a"]
    assert items[0].url == "https://www.reddit.com/r/vietnam/comments/a/t/"
    assert items[0].views == 500 and items[0].subreddit == "vietnam"


def test_missing_credentials():
    assert rc.missing_credentials({"client_id": "x"}) == ["client_secret", "username", "password"]
    assert rc.missing_credentials(dict.fromkeys(rc.REQUIRED, "v")) == []


def _resp(code: int):
    return SimpleNamespace(status_code=code, headers={}, text="", json=lambda: {})


@pytest.mark.parametrize(
    "exc, idempotent, expect",
    [
        (pc.OAuthException(_resp(401), "invalid_grant", "bad"), True, "human"),
        (pc.Forbidden(_resp(403)), True, "human"),
        (pc.TooManyRequests(_resp(429)), True, "retry"),
        (pc.ServerError(_resp(502)), True, "retry"),
        (pc.ServerError(_resp(502)), False, "human"),
        (RuntimeError("your account has been suspended"), True, "terminal"),
        (pc.NotFound(_resp(404)), True, "fail"),
    ],
)
def test_classify(exc, idempotent, expect):
    r = rc.classify_exc(exc, idempotent=idempotent)
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


# ------------------------------------------------------------------ runner


class _FakeRd:
    calls: ClassVar[list] = []

    def __init__(self, account, profile=None):
        self.account = account

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return None

    async def like(self, sid):
        _FakeRd.calls.append(("like", sid))
        return rc.ActionResult(True, "ok")

    async def comment(self, sid, text):
        _FakeRd.calls.append(("comment", sid, text))
        return rc.ActionResult(True, "ok")

    async def follow(self, handle):
        _FakeRd.calls.append(("follow", handle))
        return rc.ActionResult(True, "ok")

    async def submit(self, subreddit, title, body, media=None):
        _FakeRd.calls.append(("submit", subreddit, title, media.name if media else None))
        return SimpleNamespace(id="s1", permalink="/r/x/comments/s1/t/")

    async def reply_to(self, url, text):
        _FakeRd.calls.append(("reply", url, text))
        return SimpleNamespace(id="c1", permalink="/r/x/comments/s1/t/c1/")

    async def delete(self, sid):
        _FakeRd.calls.append(("delete", sid))

    async def edit(self, sid, body):
        _FakeRd.calls.append(("edit", sid, body))


class _NoSession:
    async def get(self, model, key):
        return None


def _job(kind, url):
    j = ActivityJob(id=uuid.uuid4(), account_id=uuid.uuid4(), kind=kind, target_url=url)
    j.account = Account(handle="me", platform=Platform.REDDIT)
    return j


async def test_interact_calls_the_right_thing():
    _FakeRd.calls.clear()
    post = "https://www.reddit.com/r/vietnam/comments/1abc2d/t/"
    assert (
        await ri.run(_NoSession(), None, _job(ActivityKind.ENGAGE, post), client_factory=_FakeRd)
    ).ok
    assert (
        await ri.run(
            _NoSession(),
            None,
            _job(ActivityKind.COMMENT, post),
            client_factory=_FakeRd,
            rng=random.Random(1),
        )
    ).ok
    assert (
        await ri.run(
            _NoSession(),
            None,
            _job(ActivityKind.FOLLOW, "https://www.reddit.com/user/creator"),
            client_factory=_FakeRd,
        )
    ).ok
    assert _FakeRd.calls[0] == ("like", "1abc2d")
    assert _FakeRd.calls[1][:2] == ("comment", "1abc2d")
    assert _FakeRd.calls[2] == ("follow", "creator")


def _account(with_secrets=True) -> Account:
    a = Account(handle="me", platform=Platform.REDDIT)
    if with_secrets:
        a.set_secrets(dict.fromkeys(rc.REQUIRED, "v"))
    return a


async def test_publish_needs_subreddit_and_credentials(tmp_path):
    _FakeRd.calls.clear()
    adapter = rp.RedditAdapter(client_factory=_FakeRd)
    r = await adapter.publish(_account(False), Variant(title="t", body="b"), {"subreddit": "x"})
    assert not r.ok and r.needs_human and "client_id" in r.error
    r = await adapter.publish(_account(), Variant(title="t", body="b"), {})
    assert not r.ok and "subreddit" in r.error.lower()
    r = await adapter.publish(_account(), Variant(title="t", body="b"), {"subreddit": "r/vietnam/"})
    assert r.ok and r.remote_url == "https://www.reddit.com/r/x/comments/s1/t/"
    assert _FakeRd.calls[-1] == ("submit", "vietnam", "t", None)
    f = tmp_path / "pic.png"
    f.write_bytes(b"x")
    r = await adapter.publish(
        _account(), Variant(title="t", body="", media_variant_ref=str(f)), {"subreddit": "vietnam"}
    )
    assert r.ok and _FakeRd.calls[-1] == ("submit", "vietnam", "t", "pic.png")
    r = await adapter.publish(
        _account(),
        Variant(title="t", body="hay"),
        {"kind": "comment", "url": "https://www.reddit.com/r/x/comments/s1/t/"},
    )
    assert r.ok and r.remote_id == "c1"


async def test_manage_delete_and_edit():
    _FakeRd.calls.clear()
    job = _job(ActivityKind.DELETE, manage.encode(manage.Plan("delete", "a", "s1", "u")))
    assert (await rm.run(_NoSession(), None, job, client_factory=_FakeRd)).ok
    job = _job(ActivityKind.EDIT, manage.encode(manage.Plan("edit", "a", "s1", "u", caption="mới")))
    assert (await rm.run(_NoSession(), None, job, client_factory=_FakeRd)).ok
    assert _FakeRd.calls == [("delete", "s1"), ("edit", "s1", "mới")]


def test_warm_uses_score_threshold_and_user_urls():
    items = rc.parse_feed([_sub("a", "one", score=50), _sub("b", "two", score=900)])
    picked = pick_targets(items, own_handles=set(), rng=random.Random(1), min_views=rc.MIN_SCORE)
    assert [i.item_id for i in picked] == ["b"]
    account = Account(
        id=uuid.uuid4(), handle="me", warmup_started_at=datetime.now(UTC) - timedelta(days=3)
    )
    day = datetime.now(UTC).date()
    start = datetime.combine(day, datetime.min.time(), tzinfo=UTC) + timedelta(hours=8)
    jobs = build_jobs(
        account,
        picked,
        Budget(1, 1, 0),
        day=day,
        window=(start, start + timedelta(hours=4)),
        rng=random.Random(1),
        profile_url=rw.profile_url,
    )
    assert [j.kind for j in jobs] == [ActivityKind.ENGAGE, ActivityKind.FOLLOW]
    assert jobs[1].target_url == "https://www.reddit.com/user/two"
