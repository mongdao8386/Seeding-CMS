"""Phat hien checkpoint: captcha, xac minh, tai khoan bi khoa.

Phan biet ba tinh huong that su khac nhau, vi cach xu ly khac han nhau:

    CHECKPOINT  -> nguoi phai vao giai. Dung retry, retry chi lam nang them.
    LOI TAM     -> mang chap chon, trang cham. Retry co ich.
    BI KHOA     -> tai khoan xong roi. Dung ca retry lan cho nguoi.

Doan sai theo huong nao cung ton kem: coi checkpoint la loi tam thi bot se dam dau
vao tuong lien tuc, con coi loi mang la checkpoint thi bao dong gia lam nguoi van
hanh mat long tin vao hang doi.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from seeding.domain.models import Platform


class CheckpointKind(StrEnum):
    CAPTCHA = "captcha"
    VERIFY = "verify"  # xac minh SMS / email / anh
    SUSPENDED = "suspended"  # tai khoan bi khoa han
    LOGGED_OUT = "logged_out"  # phien chet giua chung


@dataclass(frozen=True, slots=True)
class Checkpoint:
    kind: CheckpointKind
    evidence: str

    @property
    def is_terminal(self) -> bool:
        """Bi khoa thi khong ai cuu duoc - dung dua vao hang doi cho nguoi."""
        return self.kind is CheckpointKind.SUSPENDED


# Dau hieu doc tu URL. Re nhat, kiem truoc.
_URL_MARKERS: dict[str, CheckpointKind] = {
    "/checkpoint": CheckpointKind.VERIFY,
    "/challenge": CheckpointKind.VERIFY,
    "/i/flow/login": CheckpointKind.LOGGED_OUT,
    "/accounts/login": CheckpointKind.LOGGED_OUT,
    "/account/suspended": CheckpointKind.SUSPENDED,
    "/suspended": CheckpointKind.SUSPENDED,
}

# Dau hieu doc tu noi dung trang. Chu thuong, so khop kieu "co chua".
_TEXT_MARKERS: list[tuple[str, CheckpointKind]] = [
    ("your account has been suspended", CheckpointKind.SUSPENDED),
    ("account suspended", CheckpointKind.SUSPENDED),
    ("tai khoan cua ban da bi khoa", CheckpointKind.SUSPENDED),
    ("confirm your identity", CheckpointKind.VERIFY),
    ("verify your identity", CheckpointKind.VERIFY),
    ("we need to confirm", CheckpointKind.VERIFY),
    ("enter the code", CheckpointKind.VERIFY),
    ("xac minh danh tinh", CheckpointKind.VERIFY),
    ("unusual activity", CheckpointKind.VERIFY),
    ("hoat dong bat thuong", CheckpointKind.VERIFY),
    ("solve this puzzle", CheckpointKind.CAPTCHA),
    ("i'm not a robot", CheckpointKind.CAPTCHA),
    ("are you a robot", CheckpointKind.CAPTCHA),
    ("log in to continue", CheckpointKind.LOGGED_OUT),
    ("sign in to continue", CheckpointKind.LOGGED_OUT),
]

# Khung captcha nhung dich vu pho bien.
_CAPTCHA_SELECTORS = (
    "iframe[src*='recaptcha']",
    "iframe[src*='hcaptcha']",
    "iframe[title*='challenge']",
    "#arkose",
    "[data-testid='ocfEnterTextTextInput']",  # X: buoc xac minh giua luong
)


async def detect(page, platform: Platform | None = None) -> Checkpoint | None:
    """Trang hien tai co dang chan lai khong? Tra ve None neu moi thu binh thuong."""
    url = (page.url or "").lower()
    for marker, kind in _URL_MARKERS.items():
        if marker in url:
            return Checkpoint(kind, f"url contains {marker!r}: {page.url}")

    for selector in _CAPTCHA_SELECTORS:
        try:
            if await page.locator(selector).count():
                return Checkpoint(CheckpointKind.CAPTCHA, f"found {selector}")
        except Exception:
            # Trang dang chuyen huong thi locator co the nem - khong ket luan gi.
            continue

    try:
        body = (await page.inner_text("body"))[:4000].lower()
    except Exception:
        return None

    for phrase, kind in _TEXT_MARKERS:
        if phrase in body:
            return Checkpoint(kind, f"page contains {phrase!r}")

    return None
