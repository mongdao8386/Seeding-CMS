"""TikTok bam bang trinh duyet - trang gia, khong mo Camoufox. Kiem: xem dung thoi gian
cua job truoc khi bam, tha tim xac nhan bang aria-pressed, da tha thi khong bam lai,
follow doc nut Following, binh luan sticker xac nhan bang o soan trong, va selector
lech la loi code chu khong phai loi tai khoan."""

from __future__ import annotations

import random
import uuid
from types import SimpleNamespace

from seeding.domain.models import ActivityJob, ActivityKind, Profile, Proxy
from seeding.platforms.tiktok import interact_browser as tb

VIDEO = "https://www.tiktok.com/@creator/video/7680526558917840148"


class _Locator:
    def __init__(self, page, selector):
        self.page = page
        self.selector = selector
        self.typed = ""

    async def click(self):
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


class _Page:
    def __init__(self, visible: set[str]):
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
    assert res.ok and res.detail == "liked", res.detail
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
    assert res.ok and res.detail == "already liked"
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
    assert res.ok and res.detail == "followed"
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
    assert "never rendered" in res.detail


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
