"""Kiem chung co che dang bai tren DOM that, khong dung toi mang xa hoi nao.

Trang duoc dung tai cho bang set_content(). Cai duoc kiem o day la nhung thu THUOC VE
minh: go chu vao contenteditable, tim selector, nhan dien checkpoint. Con selector
that cua Threads va X thi chi kiem chung duoc bang tai khoan that.
"""

import random

import pytest

from seeding.adapters.browser import _first_visible
from seeding.browser import humanize
from seeding.browser.checkpoints import CheckpointKind, detect
from seeding.browser.session import open_profile
from seeding.core import fingerprint as fpm
from seeding.models import Profile

pytestmark = pytest.mark.browser


async def _fast(_seconds: float) -> None:
    """Bo qua do tre - o day dang do co che DOM, khong do nhip."""
    return None


def _profile() -> Profile:
    return Profile(fingerprint=fpm.generate(), os_family="windows", locale="en-US")


async def test_types_into_a_real_contenteditable():
    """Threads va X deu dung contenteditable chu khong phai <textarea>.

    Neu co che go chu khong chay tren contenteditable thi ca hai recipe deu vo dung.
    """
    async with open_profile(_profile(), headless=True, humanize=False) as (_b, context):
        page = await context.new_page()
        await page.set_content("<div contenteditable='true' role='textbox' id='soan'></div>")
        editor = page.locator("div[contenteditable='true'][role='textbox']")
        await humanize.type_like_person(
            editor, "Xin chao, day la bai thu.", rng=random.Random(1), sleep=_fast
        )
        assert await editor.inner_text() == "Xin chao, day la bai thu."


async def test_finds_the_first_selector_that_is_actually_visible():
    async with open_profile(_profile(), headless=True, humanize=False) as (_b, context):
        page = await context.new_page()
        await page.set_content(
            "<button id='an' style='display:none'>An</button><button id='hien'>Hien</button>"
        )
        found = await _first_visible(page, ("#khong-ton-tai", "#an", "#hien"))
        assert found is not None
        assert await found.inner_text() == "Hien"


async def test_returns_nothing_when_no_selector_matches():
    """Truong hop nay phai bao loi ro rang, khong duoc im lang bao thanh cong."""
    async with open_profile(_profile(), headless=True, humanize=False) as (_b, context):
        page = await context.new_page()
        await page.set_content("<p>trang trong</p>")
        assert await _first_visible(page, ("#a", "#b")) is None


async def test_detects_a_captcha_iframe_on_a_real_page():
    async with open_profile(_profile(), headless=True, humanize=False) as (_b, context):
        page = await context.new_page()
        await page.set_content(
            "<h1>Xac minh</h1><iframe src='https://www.google.com/recaptcha/api2/anchor'></iframe>"
        )
        found = await detect(page)
        assert found and found.kind is CheckpointKind.CAPTCHA


async def test_detects_a_suspended_account_on_a_real_page():
    async with open_profile(_profile(), headless=True, humanize=False) as (_b, context):
        page = await context.new_page()
        await page.set_content("<main><h1>Your account has been suspended</h1></main>")
        found = await detect(page)
        assert found and found.kind is CheckpointKind.SUSPENDED
        assert found.is_terminal


async def test_a_normal_looking_feed_is_left_alone():
    async with open_profile(_profile(), headless=True, humanize=False) as (_b, context):
        page = await context.new_page()
        await page.set_content("<main><article>Hom nay troi dep</article></main>")
        assert await detect(page) is None
