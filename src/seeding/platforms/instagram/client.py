"""Mot phien Instagram cua MOT tai khoan, qua aiograpi: proxy cua no, sessionid cua no,
thiet bi cua no.

    async with InstagramClient(profile) as ig:
        items = await ig.feed(24)
        await ig.like(items[0].item_id)

Ba luat:
  1. Khong bao gio di ra khong co proxy. Khoi tao ma profile.proxy la None thi nem loi.
  2. Thiet bi co dinh theo profile. aiograpi sinh uuids/device ngau nhien moi lan tao
     Client; doi thiet bi moi lan goi la dau vet ro nhat. Lan dau dung thi luu vao
     profile.fingerprint["instagram"], lan sau nap lai.
  3. Ket qua khong ro cua hanh dong KHONG idempotent (binh luan, dang bai) -> cho nguoi.
     Tha tim va follow thi thu lai duoc.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import httpx
import structlog
from aiograpi import Client
from aiograpi import exceptions as ex

from seeding.domain.models import Profile
from seeding.platforms.base import proxy_dsn

log = structlog.get_logger(__name__)

ORIGIN = "https://www.instagram.com"
DEVICE_KEY = "instagram"
# Nhung gi cua get_settings() duoc giu lai giua cac lan chay. KHONG co cookies hay
# authorization_data: sessionid nam trong cookie da ma hoa cua profile, khong nam o day.
_DEVICE_FIELDS = (
    "uuids",
    "device_settings",
    "user_agent",
    "mid",
    "ig_u_rur",
    "ig_www_claim",
    "country",
    "country_code",
    "locale",
    "timezone_offset",
    "timezone_name",
)
REQUEST_TIMEOUT = 30
VIDEO_EXT = {".mp4", ".mov", ".m4v"}

_ALPHABET = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_"


@dataclass(frozen=True, slots=True)
class FeedItem:
    item_id: str  # media pk - cai like/comment can
    code: str  # shortcode trong URL
    author_handle: str
    author_id: str
    views: int
    likes: int
    desc: str

    @property
    def url(self) -> str:
        return f"{ORIGIN}/reel/{self.code}/"


@dataclass(slots=True)
class ActionResult:
    ok: bool
    detail: str
    retryable: bool = False
    needs_human: bool = False
    # Tai khoan bi khoa han - khong ai cuu duoc.
    terminal: bool = False
    raw: Any = field(default=None)


# ------------------------------------------------------------------ thuan tuy


def pk_from_code(code: str) -> str:
    """Shortcode trong URL -> media pk. Base64 kieu Instagram, khong can mang."""
    n = 0
    for ch in code:
        n = n * 64 + _ALPHABET.index(ch)
    return str(n)


def code_from_pk(pk: str | int) -> str:
    n = int(pk)
    out = ""
    while n > 0:
        n, r = divmod(n, 64)
        out = _ALPHABET[r] + out
    return out or "A"


def sessionid_from(storage_state: dict | None) -> str | None:
    for c in (storage_state or {}).get("cookies", []):
        if c.get("name") == "sessionid" and c.get("value"):
            return str(c["value"])
    return None


def stored_device(profile: Profile) -> dict | None:
    dev = (profile.fingerprint or {}).get(DEVICE_KEY)
    return dev if isinstance(dev, dict) and dev.get("uuids") else None


def device_to_store(settings: dict) -> dict:
    return {k: settings[k] for k in _DEVICE_FIELDS if k in settings}


def parse_feed(medias: list) -> list[FeedItem]:
    out = []
    for m in medias:
        user = getattr(m, "user", None)
        if not getattr(m, "pk", None) or user is None or not getattr(user, "username", None):
            continue
        out.append(
            FeedItem(
                item_id=str(m.pk),
                code=str(getattr(m, "code", "") or code_from_pk(m.pk)),
                author_handle=str(user.username),
                author_id=str(getattr(user, "pk", "") or ""),
                views=int(getattr(m, "play_count", None) or getattr(m, "view_count", None) or 0),
                likes=int(getattr(m, "like_count", None) or 0),
                desc=str(getattr(m, "caption_text", "") or ""),
            )
        )
    return out


_HUMAN = (
    ex.ChallengeRequired,
    ex.CheckpointRequired,
    ex.TwoFactorRequired,
    ex.RecaptchaChallengeForm,
    ex.SelectContactPointRecoveryForm,
    ex.SubmitPhoneNumberForm,
    ex.ConsentRequired,
    ex.TermsAccept,
    ex.TermsUnblock,
    ex.LegacyForceSetNewPasswordForm,
    ex.AccountContactPointRequired,
    ex.ChallengeError,
    ex.ChallengeRedirection,
    ex.ChallengeSelfieCaptcha,
    ex.ChallengeUnknownStep,
    ex.CaptchaChallengeRequired,
    ex.SentryBlock,
    ex.LoginRequired,
    ex.ClientLoginRequired,
    ex.ReloginAttemptExceeded,
    ex.BadPassword,
    ex.BadCredentials,
)
_TERMINAL = (ex.AccountSuspended,)
_WAIT = (
    ex.PleaseWaitFewMinutes,
    ex.RateLimitError,
    ex.ClientThrottledError,
    ex.FeedbackRequired,
)
_NETWORK = (
    ex.ClientConnectionError,
    ex.ClientRequestTimeout,
    ex.ProxyError,
    ex.ConnectProxyError,
    ex.AuthRequiredProxyError,
    ex.ClientIncompleteReadError,
    ex.ClientJSONDecodeError,
    httpx.TransportError,
    TimeoutError,
)


def classify_exc(exc: BaseException, *, idempotent: bool) -> ActionResult:
    """Mot ngoai le cua aiograpi thanh ket qua. `idempotent` quyet dinh 'khong ro' la
    thu lai duoc hay phai cho nguoi."""
    name = type(exc).__name__
    text = f"{name}: {exc}"[:300]
    if isinstance(exc, _TERMINAL):
        return ActionResult(False, f"Instagram suspended the account: {text}", terminal=True)
    if isinstance(exc, _HUMAN):
        return ActionResult(False, f"Instagram wants a human: {text}", needs_human=True)
    if isinstance(exc, _WAIT):
        # "Please wait a few minutes" / action blocked: nghi roi thu lai, ke ca binh luan -
        # Instagram da tu choi ro rang, khong co gi duoc gui di.
        return ActionResult(False, f"Instagram asked to slow down: {text}", retryable=True)
    if isinstance(exc, _NETWORK):
        return ActionResult(
            False,
            f"network trouble, outcome unknown: {text}",
            retryable=idempotent,
            needs_human=not idempotent,
        )
    return ActionResult(False, f"Instagram refused: {text}")


# ------------------------------------------------------------------ phien


class InstagramClient:
    def __init__(self, profile: Profile, *, client_factory=Client) -> None:
        if profile.proxy is None:
            raise ValueError("profile has no proxy - refusing to touch Instagram from the host IP")
        self.profile = profile
        self._factory = client_factory
        self.client: Client | None = None
        self.username: str | None = None

    async def __aenter__(self) -> InstagramClient:
        sid = sessionid_from(self.profile.get_cookies())
        if not sid:
            raise RuntimeError("no sessionid cookie for instagram - import the cookie first")
        c = self._factory()
        stored = stored_device(self.profile)
        if stored:
            c.set_settings(stored)
        c.set_proxy(proxy_dsn(self.profile.proxy))
        if not stored:
            # Dia phuong hoa Viet Nam cho thiet bi moi; thiet bi da luu giu nguyen.
            c.set_locale("vi_VN")
            c.set_country("VN")
            c.set_timezone_offset(7 * 3600, "Asia/Ho_Chi_Minh")
        c.request_timeout = REQUEST_TIMEOUT
        await c.login_by_sessionid(sid)
        self.client = c
        self.username = getattr(c, "username", None)
        self._remember_device()
        return self

    async def __aexit__(self, *exc) -> None:
        self._remember_device()

    def _remember_device(self) -> None:
        """Ghi thiet bi vao profile.fingerprint. Gan dict MOI de SQLAlchemy thay doi."""
        if self.client is None:
            return
        device = device_to_store(self.client.get_settings())
        current = dict(self.profile.fingerprint or {})
        if current.get(DEVICE_KEY) != device:
            current[DEVICE_KEY] = device
            self.profile.fingerprint = current

    # ------------------------------------------------------------- doc

    async def feed(self, count: int = 24) -> list[FeedItem]:
        """Reels dang len ma Instagram de xuat cho tai khoan nay, qua proxy cua no."""
        assert self.client is not None
        return parse_feed(await self.client.explore_reels(count))

    async def watch(self, media_pk: str) -> None:
        """Mo trang bai (media_info) - buoc "xem" truoc khi tha tim / binh luan."""
        assert self.client is not None
        await self.client.media_info(media_pk)

    async def search(self, keyword: str, count: int = 12) -> list[FeedItem]:
        """Bai noi bat theo hashtag (tu khoa bo dau, bo khoang trang)."""
        from seeding.content.identity import strip_accents

        assert self.client is not None
        tag = "".join(ch for ch in strip_accents(keyword) if ch.isalnum())
        if not tag:
            return []
        return parse_feed(await self.client.hashtag_medias_top(tag, amount=count))

    async def user_id(self, username: str) -> str:
        assert self.client is not None
        return str(await self.client.user_id_from_username(username))

    async def me(self):
        assert self.client is not None
        return await self.client.account_info()

    # ------------------------------------------------------------- hanh dong

    async def like(self, media_pk: str) -> ActionResult:
        assert self.client is not None
        try:
            ok = await self.client.media_like(media_pk)
        except Exception as exc:
            return classify_exc(exc, idempotent=True)
        return ActionResult(bool(ok), "ok" if ok else "Instagram answered but did not like")

    async def follow(self, user_id: str) -> ActionResult:
        assert self.client is not None
        try:
            ok = await self.client.user_follow(user_id)
        except Exception as exc:
            return classify_exc(exc, idempotent=True)
        return ActionResult(bool(ok), "ok" if ok else "Instagram answered but did not follow")

    async def comment(self, media_pk: str, text: str) -> ActionResult:
        assert self.client is not None
        try:
            c = await self.client.media_comment(media_pk, text)
        except Exception as exc:
            return classify_exc(exc, idempotent=False)
        pk = getattr(c, "pk", None)
        if not pk:
            return ActionResult(False, "Instagram answered without a comment id", needs_human=True)
        return ActionResult(True, f"comment {pk}", raw=c)

    async def edit_profile(self, *, username: str | None = None, full_name: str | None = None):
        """Doi username / ten. aiograpi tu nap cac truong con lai tu account_info."""
        assert self.client is not None
        fields = {k: v for k, v in (("username", username), ("full_name", full_name)) if v}
        if not fields:
            raise ValueError("nothing to edit")
        return await self.client.account_edit(**fields)

    async def change_picture(self, path: Path):
        assert self.client is not None
        return await self.client.account_change_picture(Path(path))

    async def upload(self, path: Path, caption: str):
        """Anh -> bai thuong; video -> Reel. Tra ve Media cua aiograpi (pk, code)."""
        assert self.client is not None
        if path.suffix.lower() in VIDEO_EXT:
            return await self.client.clip_upload(path, caption)
        return await self.client.photo_upload(path, caption)


async def check(profile: Profile) -> tuple[bool, str]:
    """Kiem phien bang mot request nhe qua proxy - khong mo trinh duyet."""
    if not profile.cookies_enc:
        return False, "profile has never signed in"
    if profile.proxy is None:
        return False, "profile has no proxy"
    try:
        async with InstagramClient(profile) as ig:
            me = await ig.me()
    except Exception as exc:
        r = classify_exc(exc, idempotent=True)
        return False, r.detail
    return True, f"still signed in as @{getattr(me, 'username', '?')}"
