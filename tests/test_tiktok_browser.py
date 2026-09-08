"""TikTok bam bang trinh duyet - trang gia, khong mo Camoufox. Kiem: xem dung thoi gian
cua job truoc khi bam, tha tim xac nhan bang aria-pressed, da tha thi khong bam lai,
follow doc nut Following, binh luan sticker xac nhan bang o soan trong, va selector
lech la loi code chu khong phai loi tai khoan."""

from __future__ import annotations

import random
import uuid
from types import SimpleNamespace

import pytest

from seeding.domain.models import ActivityJob, ActivityKind, Profile, Proxy
from seeding.platforms.tiktok import interact_browser as tb


@pytest.fixture(autouse=True)
def _session_alive(monkeypatch):
    """Mac dinh phien song; khong hoi TikTok that trong test."""

    async def alive(profile):
        return None

    monkeypatch.setattr(tb, "session_dead", alive)


VIDEO = "https://www.tiktok.com/@creator/video/7680526558917840148"


class _Locator:
    def __init__(self, page, selector):
        self.page = page
        self.selector = selector
        self.typed = ""

    async def click(self, **kw):
        if self.page.click_raises is not None:
            raise self.page.click_raises
        self.page.log.append(f"click:{self.selector}")
        self.page.after_click(self.selector)

    async def hover(self):
        self.page.log.append(f"hover:{self.selector}")

    async def type(self, ch, delay=0):
        self.typed += ch

    async def press(self, key):
        self.page.log.append(f"press:{key}")

    async def inner_text(self):
        return "" if self.page.cleared else self.typed


class _Keyboard:
    def __init__(self, page):
        self.page = page

    async def press(self, key):
        self.page.log.append(f"key:{key}")
        if key == "ArrowDown" and self.page.next_urls:
            self.page.url = self.page.next_urls.pop(0)
            self.page.visible = {s for s in self.page.visible if "aria-pressed='true'" not in s}


class _Page:
    def __init__(self, visible: set[str]):
        self.click_raises = None
        self.url = VIDEO
        self.next_urls: list[str] = []
        self.keyboard = _Keyboard(self)
        self.visible = set(visible)
        self.log: list[str] = []
        self.url = VIDEO
        self.cleared = False
        self.locators: dict[str, _Locator] = {}

    def after_click(self, selector):
        r = tb.RECIPE
        if selector in r.like:
            self.visible |= set(r.liked)
        if selector in r.follow:
            self.visible |= set(r.following)
        if selector in r.comment_submit:
            self.cleared = True
        if selector in r.repost:
            self.visible |= set(r.reposted)

    async def goto(self, url, **kw):
        self.log.append(f"goto:{url}")

    def locator(self, selector):
        loc = self.locators.setdefault(selector, _Locator(self, selector))
        page = self

        class _First:
            first = loc

            async def is_visible(self_inner, timeout=0):
                return selector in page.visible

            async def count(self_inner):
                return 1 if selector in page.visible else 0

        f = _First()
        loc.is_visible = f.is_visible  # type: ignore[attr-defined]
        loc.count = f.count  # type: ignore[attr-defined]
        return f

    async def evaluate(self, *a, **k):
        return ""

    async def content(self):
        return "<html></html>"


class _Open:
    def __init__(self, page):
        self.page = page

    def __call__(self, profile, *, headless, humanize):
        page = self.page

        class _Ctx:
            async def __aenter__(self_inner):
                class _Context:
                    async def new_page(self_c):
                        return page

                return None, _Context()

            async def __aexit__(self_inner, *exc):
                return None

        return _Ctx()


class _NoSession:
    async def get(self, model, key):
        raise AssertionError("session.get duoc goi")


WAITS: list[float] = []


async def _sleep(s):
    WAITS.append(s)


def _profile():
    p = Profile(id=uuid.uuid4(), proxy_id=uuid.uuid4(), fingerprint={})
    p.proxy = Proxy(host="proxy.example.com", port=1)
    p.cookies_enc = "enc"
    return p


def _job(kind, url, seconds=37):
    return ActivityJob(id=uuid.uuid4(), kind=kind, target_url=url, duration_seconds=seconds)


async def _no_checkpoint(page, platform=None):
    return None


async def test_like_watches_then_clicks_and_confirms_by_aria_pressed(monkeypatch):
    monkeypatch.setattr(tb, "detect", _no_checkpoint)
    WAITS.clear()
    r = tb.RECIPE
    page = _Page(visible={r.like[0]})
    res = await tb.run(
        _NoSession(), _profile(), _job(ActivityKind.ENGAGE, VIDEO), open=_Open(page), sleep=_sleep
    )
    assert res.ok and res.detail == "đã thả tim", res.detail
    assert page.log[0] == f"goto:{VIDEO}"
    assert WAITS[0] == 37, "xem dung duration_seconds cua job truoc khi bam"
    assert any(line.startswith("click:") for line in page.log)


async def test_already_liked_does_not_click_again(monkeypatch):
    monkeypatch.setattr(tb, "detect", _no_checkpoint)
    r = tb.RECIPE
    page = _Page(visible={r.like[0], r.liked[0]})
    res = await tb.run(
        _NoSession(), _profile(), _job(ActivityKind.ENGAGE, VIDEO), open=_Open(page), sleep=_sleep
    )
    assert res.ok and res.detail == "đã thả tim từ trước"
    assert not any(line.startswith("click:") for line in page.log)


async def test_follow_opens_profile_and_reads_following(monkeypatch):
    monkeypatch.setattr(tb, "detect", _no_checkpoint)
    r = tb.RECIPE
    page = _Page(visible={r.follow[0]})
    res = await tb.run(
        _NoSession(),
        _profile(),
        _job(ActivityKind.FOLLOW, "https://www.tiktok.com/@creator", seconds=12),
        open=_Open(page),
        sleep=_sleep,
    )
    assert res.ok and res.detail == "đã follow"
    assert page.log[0] == "goto:https://www.tiktok.com/@creator"


async def test_sticker_comment_is_typed_and_confirmed_by_cleared_box(monkeypatch):
    monkeypatch.setattr(tb, "detect", _no_checkpoint)
    r = tb.RECIPE
    page = _Page(visible={r.comment_open[0], r.comment_editor[0], r.comment_submit[0]})
    res = await tb.run(
        _NoSession(),
        _profile(),
        _job(ActivityKind.COMMENT, VIDEO, seconds=25),
        open=_Open(page),
        sleep=_sleep,
        rng=random.Random(2),
    )
    assert res.ok, res.detail
    typed = page.locators[r.comment_editor[0]].typed
    assert typed.startswith("[") and typed.endswith("]"), "binh luan nuoi la sticker TikTok"


async def test_page_that_never_renders_is_retried_later(monkeypatch):
    monkeypatch.setattr(tb, "detect", _no_checkpoint)
    monkeypatch.setattr(tb, "GOTO_TIMEOUT_MS", 1_500)
    page = _Page(visible=set())
    res = await tb.run(
        _NoSession(), _profile(), _job(ActivityKind.ENGAGE, VIDEO), open=_Open(page), sleep=_sleep
    )
    assert not res.ok and res.retryable and res.checkpoint is None
    assert "page never rendered" in res.detail


async def test_checkpoint_on_the_page_goes_to_a_human(monkeypatch):
    from seeding.browser.checkpoints import Checkpoint, CheckpointKind

    async def blocked(page, platform=None):
        return Checkpoint(CheckpointKind.CAPTCHA, "captcha wall")

    monkeypatch.setattr(tb, "detect", blocked)
    monkeypatch.setattr(tb, "GOTO_TIMEOUT_MS", 1_500)
    page = _Page(visible=set())
    res = await tb.run(
        _NoSession(), _profile(), _job(ActivityKind.ENGAGE, VIDEO), open=_Open(page), sleep=_sleep
    )
    assert not res.ok and res.checkpoint is not None and not res.checkpoint.is_terminal


async def test_refuses_without_proxy():
    p = Profile(id=uuid.uuid4(), proxy_id=None, fingerprint={})
    p.proxy = None
    res = await tb.run(_NoSession(), p, _job(ActivityKind.ENGAGE, VIDEO), open=_Open(_Page(set())))
    assert not res.ok and "proxy" in res.detail
    assert isinstance(SimpleNamespace(), SimpleNamespace)


async def test_dead_session_goes_to_a_human_without_opening_a_browser(monkeypatch):
    async def dead(profile):
        return "phiên chết: session_expired"

    monkeypatch.setattr(tb, "session_dead", dead)
    r = tb.Recipe()
    page = _Page(visible={r.like[0]})
    opened = _Open(page)
    res = await tb.run(
        _NoSession(), _profile(), _job(ActivityKind.ENGAGE, VIDEO), open=opened, sleep=_sleep
    )
    assert not res.ok and res.checkpoint is not None
    assert res.checkpoint.kind.value == "logged_out"
    assert not page.log, "browser must not have been opened"


async def test_captcha_overlay_blocking_the_click_goes_to_a_human(monkeypatch):
    """P05 08/09/2026: nut tim hien, on dinh, nhung hop captcha cua TikTok de len va chan
    cu bam. Playwright bao TimeoutError; do phai thanh checkpoint captcha, khong thu lai."""
    from playwright.async_api import TimeoutError as PlaywrightTimeoutError

    from seeding.browser.checkpoints import Checkpoint, CheckpointKind

    async def captcha(page, platform=None):
        return Checkpoint(CheckpointKind.CAPTCHA, "found #captcha-verify-container-main-page")

    monkeypatch.setattr(tb, "detect", captcha)
    r = tb.Recipe()
    page = _Page(visible={r.like[0]})
    page.click_raises = PlaywrightTimeoutError("Locator.click: Timeout 10000ms exceeded.")
    res = await tb.run(
        _NoSession(), _profile(), _job(ActivityKind.ENGAGE, VIDEO), open=_Open(page), sleep=_sleep
    )
    assert not res.ok and res.checkpoint is not None
    assert res.checkpoint.kind is CheckpointKind.CAPTCHA
    assert not res.retryable


class _Collect:
    """Session gia: gom job con ma phien luot ghi lai."""

    def __init__(self):
        self.added: list = []

    def add_all(self, items):
        self.added.extend(items)

    async def get(self, model, key):
        raise AssertionError("session.get duoc goi")


def _sitting_job(**plan):
    from seeding.platforms.tiktok import sitting

    return ActivityJob(
        id=uuid.uuid4(),
        kind=ActivityKind.BROWSE_FEED,
        target_url=sitting.Plan(**plan).dumps(),
        duration_seconds=120,
    )


def _feed_page(visible, videos: int):
    page = _Page(visible=set(visible))
    page.url = "https://www.tiktok.com/@a/video/1"
    page.next_urls = [f"https://www.tiktok.com/@c{i}/video/{i}" for i in range(2, videos + 1)]
    return page


async def test_sitting_watches_every_video_and_spends_the_budget(monkeypatch):
    """4 video, 3 tim, 1 follow: video dau khong bam; ba video sau moi cai mot tim (tim con
    lai == video con lai), follow ngay sau tim dau; moi hanh dong thanh mot job con."""
    monkeypatch.setattr(tb, "detect", _no_checkpoint)
    r = tb.Recipe()
    page = _feed_page({r.like[0], r.follow[0]}, videos=4)
    session = _Collect()
    res = await tb.run(
        session,
        _profile(),
        _sitting_job(videos=4, likes=3, follows=1),
        open=_Open(page),
        rng=random.Random(3),
        sleep=_sleep,
    )
    assert res.ok, res.detail
    assert page.log.count(f"click:{r.like[0]}") == 3
    assert page.log.count(f"click:{r.follow[0]}") == 1
    assert page.log.count("key:ArrowDown") == 3
    kinds = sorted(j.kind.value for j in session.added)
    assert kinds == ["engage", "engage", "engage", "follow"]
    assert all(j.status.value == "succeeded" for j in session.added)
    assert {j.target_url for j in session.added} <= {
        "https://www.tiktok.com/@c2/video/2",
        "https://www.tiktok.com/@c3/video/3",
        "https://www.tiktok.com/@c4/video/4",
    }, "job con mang link video that, khong phai link ke hoach"
    assert "xem 4 video" in res.detail and "thả tim 3" in res.detail and "follow 1" in res.detail


async def test_watch_only_sitting_never_clicks(monkeypatch):
    monkeypatch.setattr(tb, "detect", _no_checkpoint)
    r = tb.Recipe()
    page = _feed_page({r.like[0], r.follow[0]}, videos=3)
    session = _Collect()
    res = await tb.run(session, _profile(), _sitting_job(videos=3), open=_Open(page), sleep=_sleep)
    assert res.ok and "chỉ xem" in res.detail and "xem 3 video" in res.detail
    assert not [e for e in page.log if e.startswith("click:")]
    assert session.added == []
    assert page.log.count("key:ArrowDown") == 2


async def test_sitting_that_cannot_advance_stops_but_keeps_what_it_did(monkeypatch):
    monkeypatch.setattr(tb, "detect", _no_checkpoint)
    monkeypatch.setattr(tb, "NEXT_WAIT_S", 2)
    r = tb.Recipe()
    page = _feed_page({r.like[0]}, videos=5)
    page.next_urls = page.next_urls[:1]  # chi sang duoc mot lan
    session = _Collect()
    res = await tb.run(
        session,
        _profile(),
        _sitting_job(videos=5, likes=1),
        open=_Open(page),
        rng=random.Random(1),
        sleep=_sleep,
    )
    assert res.ok and "xem 2 video" in res.detail and "không sang được" in res.detail


async def test_sitting_hands_a_checkpoint_to_a_human_with_actions_so_far(monkeypatch):
    calls = {"n": 0}

    async def captcha_on_third_video(page, platform=None):
        from seeding.browser.checkpoints import Checkpoint, CheckpointKind

        calls["n"] += 1
        if calls["n"] >= 4:  # 1 sau goto, 2-3 truoc hai video dau, 4 truoc video thu ba
            return Checkpoint(CheckpointKind.CAPTCHA, "found #captcha-verify-container-main-page")
        return None

    monkeypatch.setattr(tb, "detect", captcha_on_third_video)
    r = tb.Recipe()
    page = _feed_page({r.like[0]}, videos=4)
    session = _Collect()
    res = await tb.run(
        session,
        _profile(),
        _sitting_job(videos=4, likes=3),
        open=_Open(page),
        rng=random.Random(3),
        sleep=_sleep,
    )
    assert not res.ok and res.checkpoint is not None and res.checkpoint.kind.value == "captcha"
    assert len(session.added) == 1, "tim cua video thu hai da ghi lai truoc khi dung"


async def test_run_many_shares_one_browser_across_an_accounts_jobs(monkeypatch):
    """Clone: 2 luot thich + 1 follow trong MOT trinh duyet - ba lan goto, mot lan mo."""
    monkeypatch.setattr(tb, "detect", _no_checkpoint)
    r = tb.Recipe()
    page = _Page(visible={r.like[0], r.follow[0]})
    opened = _Open(page)
    opens = {"n": 0}
    real_call = opened.__call__

    def counting(profile, *, headless, humanize):
        opens["n"] += 1
        return real_call(profile, headless=headless, humanize=humanize)

    jobs = [
        _job(ActivityKind.ENGAGE, "https://www.tiktok.com/@a/video/1"),
        _job(ActivityKind.ENGAGE, "https://www.tiktok.com/@b/video/2"),
        _job(ActivityKind.FOLLOW, "https://www.tiktok.com/@b"),
    ]
    res = await tb.run_many(
        _NoSession(), _profile(), jobs, open=counting, rng=random.Random(1), sleep=_sleep
    )
    assert opens["n"] == 1
    assert [res[j.id].ok for j in jobs] == [True, True, True]
    assert [e for e in page.log if e.startswith("goto:")] == [
        "goto:https://www.tiktok.com/@a/video/1",
        "goto:https://www.tiktok.com/@b/video/2",
        "goto:https://www.tiktok.com/@b",
    ]


async def test_run_many_stops_at_a_checkpoint_and_leaves_the_rest_unclaimed(monkeypatch):
    calls = {"n": 0}

    async def captcha_second_page(page, platform=None):
        from seeding.browser.checkpoints import Checkpoint, CheckpointKind

        calls["n"] += 1
        # goto 1 -> detect (1) ok; goto 2 -> detect (2) captcha
        return Checkpoint(CheckpointKind.CAPTCHA, "found captcha") if calls["n"] == 2 else None

    monkeypatch.setattr(tb, "detect", captcha_second_page)
    r = tb.Recipe()
    page = _Page(visible={r.like[0]})
    jobs = [_job(ActivityKind.ENGAGE, f"https://www.tiktok.com/@c/video/{i}") for i in range(3)]
    res = await tb.run_many(
        _NoSession(), _profile(), jobs, open=_Open(page), rng=random.Random(1), sleep=_sleep
    )
    assert res[jobs[0].id].ok
    assert res[jobs[1].id].checkpoint is not None
    assert jobs[2].id not in res, "job chua toi luot khong co ket qua - worker tra ve hang doi"


async def test_run_many_refuses_everything_when_the_session_is_dead(monkeypatch):
    async def dead(profile):
        return "phiên chết: session_expired"

    monkeypatch.setattr(tb, "session_dead", dead)
    jobs = [_job(ActivityKind.ENGAGE, VIDEO), _job(ActivityKind.ENGAGE, VIDEO)]
    page = _Page(visible=set())
    res = await tb.run_many(_NoSession(), _profile(), jobs, open=_Open(page), sleep=_sleep)
    assert all(res[j.id].checkpoint is not None for j in jobs)
    assert not page.log, "khong mo trinh duyet"
