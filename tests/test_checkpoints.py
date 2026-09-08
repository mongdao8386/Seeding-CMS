"""Phan biet ba tinh huong: checkpoint, loi tam, tai khoan bi khoa.

Doan sai theo huong nao cung ton kem. Coi checkpoint la loi tam thi bot dam dau vao
tuong lien tuc; coi loi mang la checkpoint thi bao dong gia lam nguoi van hanh mat
long tin vao hang doi.
"""

from seeding.browser.checkpoints import CheckpointKind, detect
from seeding.domain.models import Platform


class FakePage:
    """Du de detect() lam viec: mot URL, mot than trang, va locator dem duoc."""

    def __init__(self, url: str = "https://www.threads.net/", body: str = "", selectors=()):
        self.url = url
        self._body = body
        self._selectors = set(selectors)

    def locator(self, selector: str):
        page = self

        class _Loc:
            async def count(self):
                return 1 if selector in page._selectors else 0

        return _Loc()

    async def inner_text(self, _selector: str) -> str:
        return self._body


async def test_a_normal_page_is_not_a_checkpoint():
    assert await detect(FakePage(body="Home Feed For you Following")) is None


async def test_checkpoint_url_is_detected():
    found = await detect(FakePage(url="https://www.facebook.com/checkpoint/12345"))
    assert found and found.kind is CheckpointKind.VERIFY
    assert "checkpoint" in found.evidence


async def test_being_bounced_to_login_is_detected_as_logged_out():
    found = await detect(FakePage(url="https://x.com/i/flow/login"))
    assert found and found.kind is CheckpointKind.LOGGED_OUT


async def test_suspended_account_is_terminal():
    """Bi khoa han thi nguoi cung khong cuu duoc - dung lam ban hang doi cho nguoi."""
    found = await detect(FakePage(body="Your account has been suspended for violating"))
    assert found and found.kind is CheckpointKind.SUSPENDED
    assert found.is_terminal


async def test_a_solvable_checkpoint_is_not_terminal():
    found = await detect(FakePage(body="We need to confirm your identity"))
    assert found and found.kind is CheckpointKind.VERIFY
    assert not found.is_terminal


async def test_captcha_iframe_is_detected():
    page = FakePage(selectors=["iframe[src*='recaptcha']"])
    found = await detect(page)
    assert found and found.kind is CheckpointKind.CAPTCHA


async def test_vietnamese_wording_is_detected_too():
    found = await detect(FakePage(body="Chung toi phat hien hoat dong bat thuong"))
    assert found and found.kind is CheckpointKind.VERIFY


async def test_detection_is_case_insensitive():
    found = await detect(FakePage(body="ACCOUNT SUSPENDED"))
    assert found and found.kind is CheckpointKind.SUSPENDED


async def test_url_wins_over_body_because_it_is_cheaper():
    """URL duoc kiem truoc, khong phai doc ca than trang."""
    page = FakePage(url="https://www.instagram.com/challenge/abc", body="Home feed")
    found = await detect(page)
    assert found and found.kind is CheckpointKind.VERIFY


async def test_a_page_that_cannot_be_read_is_not_reported_as_a_checkpoint():
    """Trang dang chuyen huong thi khong ket luan gi - khong bao dong gia."""

    class Broken(FakePage):
        async def inner_text(self, _selector: str) -> str:
            raise RuntimeError("Execution context was destroyed")

    assert await detect(Broken()) is None


async def test_tiktok_login_button_means_the_session_is_dead():
    """TikTok voi phien chet van hien trang video va nut tim binh thuong; dau hieu duy
    nhat la nut Dang nhap tren dau trang."""
    page = FakePage(url="https://www.tiktok.com/@a/video/1", selectors=("#header-login-button",))
    found = await detect(page, Platform.TIKTOK)
    assert found and found.kind is CheckpointKind.LOGGED_OUT
    assert "header-login-button" in found.evidence


async def test_login_button_selector_is_per_platform():
    page = FakePage(url="https://x.com/home", selectors=("#header-login-button",))
    assert await detect(page, Platform.X) is None


async def test_tiktok_captcha_overlay_is_a_captcha_checkpoint():
    page = FakePage(
        url="https://www.tiktok.com/@a/video/1", selectors=("#captcha-verify-container-main-page",)
    )
    found = await detect(page, Platform.TIKTOK)
    assert found and found.kind is CheckpointKind.CAPTCHA
