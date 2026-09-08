"""Facebook bang trinh duyet - khong mo trinh duyet that. Kiem: nhip go/nghi do duoc bang
sleep gia, precheck chan truoc khi mo trinh duyet, va adapter di dung buoc voi mot
trang gia (composer -> editor -> post -> dau hieu)."""

from __future__ import annotations

import random
import uuid
from types import SimpleNamespace

from seeding.browser import actions, humanize
from seeding.domain.models import Account, Profile, Proxy, Variant
from seeding.platforms.facebook import publish as fb


class _Locator:
    def __init__(self, log):
        self.log = log
        self.typed = ""

    async def click(self):
        self.log.append("click")

    async def type(self, ch, delay=0):
        self.typed += ch

    async def press(self, key):
        self.log.append(f"press:{key}")


async def test_type_like_person_pauses_more_after_punctuation():
    waits: list[float] = []

    async def sleep(s):
        waits.append(s)

    loc = _Locator([])
    await humanize.type_like_person(loc, "ok. ok", rng=random.Random(1), sleep=sleep, cps=10)
    assert loc.typed == "ok. ok"
    # 1 nhin + 6 ky tu; sau dau cham nghi lau hon trung binh
    assert len(waits) == 7
    assert waits[3] > sum(waits[1:3]) / 2


def test_precheck_refuses_before_opening_a_browser():
    acc = Account(handle="fb")
    v = Variant(title="t", body="b")
    assert fb.precheck(acc, v, {}, None) is not None
    p = Profile(id=uuid.uuid4(), proxy_id=None, fingerprint={})
    p.proxy = None
    assert "never signed in" in fb.precheck(acc, v, {}, p).error
    p.cookies_enc = "enc"
    assert "no proxy" in fb.precheck(acc, v, {}, p).error
    p.proxy = Proxy(host="proxy.example.com", port=1)
    assert fb.precheck(acc, v, {}, p) is None
    assert fb.precheck(acc, Variant(title="", body=""), {}, p) is not None
    assert "url" in fb.precheck(acc, v, {"kind": "comment"}, p).error
    assert fb.precheck(acc, v, {"kind": "comment", "url": "https://www.facebook.com/x"}, p) is None


class _Page:
    """Trang gia: selector nao ton tai thi hien, wait_for_selector chi thanh cong voi dau hieu."""

    def __init__(self, visible: set[str], signal: str | None):
        self.visible = visible
        self.signal = signal
        self.log: list[str] = []
        self.url = "https://www.facebook.com/"
        self.mouse = SimpleNamespace(wheel=self._wheel)
        self.locators: dict[str, _Locator] = {}

    async def _wheel(self, x, y):
        self.log.append("wheel")

    async def goto(self, url, **kw):
        self.log.append(f"goto:{url}")

    def locator(self, selector):
        loc = self.locators.setdefault(selector, _Locator(self.log))
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

    async def wait_for_selector(self, selector, timeout=0):
        if selector == self.signal:
            return True
        raise TimeoutError(selector)

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


def _ready_profile():
    p = Profile(id=uuid.uuid4(), proxy_id=uuid.uuid4(), fingerprint={})
    p.proxy = Proxy(host="proxy.example.com", port=1)
    p.cookies_enc = "enc"
    return p


async def test_post_walks_composer_editor_submit_and_confirms(monkeypatch):
    async def no_sleep(_):
        return None

    monkeypatch.setattr(humanize.asyncio, "sleep", no_sleep)

    async def no_checkpoint(page, platform=None):
        return None

    monkeypatch.setattr(fb, "detect", no_checkpoint)
    page = _Page(
        visible={fb.POST.open_composer[0], fb.POST.editor[0], fb.POST.submit[0]},
        signal=fb.POST.posted_signal[0],
    )
    adapter = fb.FacebookBrowserAdapter(open=_Open(page))
    r = await adapter.publish(
        Account(handle="fb"), Variant(title="xin chào", body=""), {}, profile=_ready_profile()
    )
    assert r.ok, r.error
    assert page.locators[fb.POST.editor[0]].typed == "xin chào"
    assert page.log[0].startswith("goto:https://www.facebook.com/")


async def test_post_without_confirmation_goes_to_a_human(monkeypatch):
    async def no_sleep(_):
        return None

    monkeypatch.setattr(humanize.asyncio, "sleep", no_sleep)

    async def no_checkpoint(page, platform=None):
        return None

    monkeypatch.setattr(fb, "detect", no_checkpoint)
    page = _Page(
        visible={fb.POST.open_composer[0], fb.POST.editor[0], fb.POST.submit[0]}, signal=None
    )
    adapter = fb.FacebookBrowserAdapter(open=_Open(page))
    r = await adapter.publish(
        Account(handle="fb"), Variant(title="t", body=""), {}, profile=_ready_profile()
    )
    assert not r.ok and r.needs_human and not r.retryable


async def test_missing_selector_is_a_code_error_not_an_account_error(monkeypatch):
    async def no_sleep(_):
        return None

    monkeypatch.setattr(humanize.asyncio, "sleep", no_sleep)

    async def no_checkpoint(page, platform=None):
        return None

    monkeypatch.setattr(fb, "detect", no_checkpoint)
    page = _Page(visible=set(), signal=None)
    adapter = fb.FacebookBrowserAdapter(open=_Open(page))
    r = await adapter.publish(
        Account(handle="fb"), Variant(title="t", body=""), {}, profile=_ready_profile()
    )
    assert not r.ok and not r.needs_human and not r.retryable
    assert "composer" in r.error and "update the recipe" in r.error
    assert actions.selector_miss("x", ("a",)).startswith("Could not find x")
