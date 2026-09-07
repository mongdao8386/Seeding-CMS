"""Xac nhan bai da len - va chuyen gi xay ra khi KHONG xac nhan duoc.

Day la cho nguy hiem nhat cua ca duong dang bai. Khong phai vi no hay hong, ma vi
kieu hong cua no khong nhin thay duoc: adapter bam Post thanh cong, bai len that,
nhung khong nhan ra dau hieu thanh cong -> bao that bai -> job duoc thu lai -> dang
LAN HAI len mot tai khoan that. Khong go lai duoc.

Chuyen do gan xay ra that. Cong thuc TikTok truoc day chi tim chu tieng Anh
("Your video is being uploaded"), trong khi profile chay qua proxy Viet Nam nen
TikTok Studio ra `lang=vi-VN` va khong he co chuoi tieng Anh nao tren trang.
"""

import pytest

from seeding.adapters.browser import RECIPES, BrowserAdapter
from seeding.models import Platform


class _FakePage:
    """Trang gia du de chay `_confirm`, khong can mo trinh duyet.

    `url_becomes` la URL trang se chuyen sang (None = khong bao gio chuyen), `texts`
    la cac selector chu ma trang co.
    """

    def __init__(self, *, url: str = "https://example.test/upload", url_becomes=None, texts=()):
        self.url = url
        self._url_becomes = url_becomes
        self._texts = set(texts)
        self.body = "binh thuong"

    async def wait_for_url(self, matcher, timeout=0):
        if self._url_becomes is not None and matcher(self._url_becomes):
            self.url = self._url_becomes
            return
        raise TimeoutError("url khong doi")

    async def wait_for_selector(self, selector, timeout=0):
        if selector in self._texts:
            return object()
        raise TimeoutError(f"khong thay {selector}")

    def locator(self, _selector):
        page = self

        class _Loc:
            async def count(self):
                return 0

            async def is_visible(self, timeout=0):
                return False

            @property
            def first(self):
                return self

        del page
        return _Loc()

    async def inner_text(self, _selector):
        return self.body


def _tiktok() -> BrowserAdapter:
    return BrowserAdapter(Platform.TIKTOK, RECIPES[Platform.TIKTOK])


async def test_url_change_alone_is_enough_to_call_it_posted():
    """Doi URL la dau hieu KHONG phu thuoc ngon ngu giao dien.

    Trang o day khong co mot chu nao khop posted_signal - dung nhu giao dien tieng
    Viet that. Neu test nay hong, nghia la ta lai dang phu thuoc vao chu tieng Anh.
    """
    page = _FakePage(url_becomes="https://www.tiktok.com/tiktokstudio/content")
    result = await _tiktok()._confirm(page, rng=None)

    assert result.ok
    assert result.remote_url == "https://www.tiktok.com/tiktokstudio/content"


async def test_vietnamese_success_text_counts_too():
    """Luoi do thu hai: URL khong doi nhung trang bao bang tieng Viet."""
    page = _FakePage(texts=("text=Video của bạn đang được tải lên",))
    result = await _tiktok()._confirm(page, rng=None)

    assert result.ok


async def test_unconfirmed_post_is_never_retried_automatically():
    """BAT BIEN: da bam Post ma khong xac nhan duoc thi KHONG duoc tu dong thu lai.

    Retry o day la dang bai lan hai len tai khoan that. Phai day sang hang doi cho
    nguoi mo ra nhin, chu khong phai xep lich chay lai.
    """
    page = _FakePage()  # url khong doi, khong co chu nao khop
    result = await _tiktok()._confirm(page, rng=None)

    assert not result.ok
    assert result.needs_human, "phai vao hang doi cho nguoi"
    assert not result.retryable, "retry o day la dang bai lan hai"
    assert "MAY already be live" in (result.error or "")


async def test_unconfirmed_comment_is_never_retried_either():
    """Cung ly do: thu lai mot binh luan da gui la de lai hai binh luan."""
    from seeding.adapters.browser import COMMENT_RECIPES

    adapter = BrowserAdapter(
        Platform.TIKTOK, RECIPES[Platform.TIKTOK], COMMENT_RECIPES[Platform.TIKTOK]
    )
    result = await adapter._confirm_comment(_FakePage(), "mot binh luan nao do")

    assert not result.ok
    assert result.needs_human
    assert not result.retryable


@pytest.mark.parametrize("platform", sorted(RECIPES, key=lambda p: p.value))
def test_text_selectors_never_come_before_stable_ones(platform):
    """Selector theo CHU phai xep sau selector theo thuoc tinh.

    Chu doi theo ngon ngu giao dien, `data-testid` / `data-e2e` thi khong. Xep chu len
    truoc khong lam sai ket qua - no chi lam moi buoc ton them mot lan timeout, va
    tren proxy dan cu thi vai lan nhu vay cong lai thanh phut.
    """
    recipe = RECIPES[platform]
    for name in ("open_composer", "editor", "submit"):
        selectors = getattr(recipe, name)
        by_text = [i for i, s in enumerate(selectors) if ":has-text(" in s or s.startswith("text=")]
        stable = [i for i, s in enumerate(selectors) if "data-testid=" in s or "data-e2e=" in s]
        if by_text and stable:
            assert min(stable) < min(by_text), (
                f"{platform.value}.{name}: selector theo chu {selectors[min(by_text)]!r} dung "
                f"truoc {selectors[min(stable)]!r}"
            )
