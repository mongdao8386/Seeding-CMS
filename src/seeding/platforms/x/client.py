"""Mot phien X cua MOT tai khoan qua twifork: proxy cua no, cookie cua no.

    async with XClient(profile) as x:
        items = await x.feed(24)
        await x.like(items[0].item_id)

Ba luat:
  1. Khong bao gio di ra khong co proxy.
  2. Loi cua THU VIEN (handshake x-client-transaction-id hong, query id lech) khong phai
     loi cua tai khoan. No thanh LibraryBroken / ActionResult.library, khong bao gio
     thanh "phien chet" hay "can nguoi".
  3. Ket qua khong ro cua hanh dong KHONG idempotent (tra loi, dang bai) -> cho nguoi.
     Tha tim va follow thi thu lai duoc.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import httpx
import structlog
from twikit import Client
from twikit import errors as ex

from seeding.domain.models import Profile
from seeding.platforms.base import LibraryBroken, proxy_dsn

log = structlog.get_logger(__name__)

ORIGIN = "https://x.com"
TWEET_MAX = 280
IMAGE_EXT = {".jpg", ".jpeg", ".png", ".webp"}
VIDEO_EXT = {".mp4", ".mov", ".m4v"}
GIF_EXT = {".gif"}


@dataclass(frozen=True, slots=True)
class FeedItem:
    item_id: str
    author_handle: str
    author_id: str
    views: int
    likes: int
    desc: str

    @property
    def url(self) -> str:
        return f"{ORIGIN}/{self.author_handle}/status/{self.item_id}"


@dataclass(slots=True)
class ActionResult:
    ok: bool
    detail: str
    retryable: bool = False
    needs_human: bool = False
    terminal: bool = False
    # Thu vien lech voi X (khong phai tai khoan). Worker bao he thong, khong bao tai khoan.
    library: bool = False
    raw: Any = field(default=None)


# ------------------------------------------------------------------ thuan tuy


def cookies_from(storage_state: dict | None) -> dict[str, str]:
    """{auth_token, ct0} tu storage_state. Thieu cai nao thi thieu."""
    out: dict[str, str] = {}
    for c in (storage_state or {}).get("cookies", []):
        if c.get("name") in ("auth_token", "ct0") and c.get("value"):
            out[c["name"]] = str(c["value"])
    return out


def truncate(text: str, limit: int = TWEET_MAX) -> str:
    """X dem theo ky tu (gan dung). Cat o ranh gioi tu, them dau ba cham."""
    text = text.strip()
    if len(text) <= limit:
        return text
    cut = text[: limit - 1]
    if " " in cut[limit // 2 :]:
        cut = cut[: cut.rfind(" ")]
    return cut.rstrip() + "…"


def media_category(path: Path) -> str | None:
    ext = path.suffix.lower()
    if ext in VIDEO_EXT:
        return "tweet_video"
    if ext in GIF_EXT:
        return "tweet_gif"
    if ext in IMAGE_EXT:
        return "tweet_image"
    return None


def parse_feed(tweets: list) -> list[FeedItem]:
    """Timeline -> dich. Retweet thi lay bai goc; tra loi va quang cao thi bo."""
    out = []
    seen: set[str] = set()
    for t in tweets:
        original = getattr(t, "retweeted_tweet", None) or t
        if getattr(original, "in_reply_to", None):
            continue
        user = getattr(original, "user", None)
        tid = str(getattr(original, "id", "") or "")
        handle = str(getattr(user, "screen_name", "") or "") if user is not None else ""
        if not tid or not handle or tid in seen:
            continue
        seen.add(tid)
        out.append(
            FeedItem(
                item_id=tid,
                author_handle=handle,
                author_id=str(getattr(user, "id", "") or ""),
                views=int(getattr(original, "view_count", None) or 0),
                likes=int(getattr(original, "favorite_count", None) or 0),
                desc=str(getattr(original, "text", "") or ""),
            )
        )
    return out


_NETWORK = (ex.RequestTimeout, ex.ServerError, httpx.TransportError, TimeoutError)


def classify_exc(exc: BaseException, *, idempotent: bool) -> ActionResult:
    """Mot ngoai le cua twifork thanh ket qua. Thu tu quan trong: InvalidSession la con
    cua ClientTransactionError nhung nghia nguoc han (tai khoan, khong phai thu vien)."""
    name = type(exc).__name__
    text = f"{name}: {exc}"[:300]
    low = str(exc).lower()
    if isinstance(exc, ex.InvalidSession):
        return ActionResult(False, f"X says the session is dead: {text}", needs_human=True)
    if isinstance(exc, ex.ClientTransactionError):
        return ActionResult(False, f"twifork is out of step with X: {text}", library=True)
    if isinstance(exc, ex.AccountSuspended) or "suspend" in low:
        return ActionResult(False, f"X suspended the account: {text}", terminal=True)
    if isinstance(exc, (ex.AccountLocked, ex.Unauthorized)):
        return ActionResult(False, f"X wants a human: {text}", needs_human=True)
    if isinstance(exc, ex.Forbidden):
        # 403 co the la ct0 lech, tai khoan bi han che, hay X nghi la may (code 226).
        return ActionResult(False, f"X refused (403): {text}", needs_human=True)
    if isinstance(exc, ex.TooManyRequests):
        return ActionResult(False, f"X rate limit: {text}", retryable=True)
    if isinstance(exc, ex.NotFound):
        # 404 luc co luc khong la handshake hoac query id vua xoay; client moi cho moi job
        # nen thu lai co ich, ke ca voi tra loi - 404 la bi tu choi, chua co gi duoc gui.
        return ActionResult(False, f"X 404 (handshake or rotated query id): {text}", retryable=True)
    if isinstance(exc, _NETWORK):
        return ActionResult(
            False,
            f"network trouble, outcome unknown: {text}",
            retryable=idempotent,
            needs_human=not idempotent,
        )
    if isinstance(exc, ex.DuplicateTweet):
        return ActionResult(False, f"X rejected a duplicate: {text}")
    return ActionResult(False, f"X refused: {text}")


# ------------------------------------------------------------------ phien


class XClient:
    def __init__(self, profile: Profile, *, client_factory=Client) -> None:
        if profile.proxy is None:
            raise ValueError("profile has no proxy - refusing to touch X from the host IP")
        self.profile = profile
        self._factory = client_factory
        self.client: Client | None = None
        self.handle: str | None = None

    async def __aenter__(self) -> XClient:
        cookies = cookies_from(self.profile.get_cookies())
        if "auth_token" not in cookies or "ct0" not in cookies:
            raise RuntimeError("X needs both auth_token and ct0 cookies - import the cookie first")
        c = self._factory(language="vi", proxy=proxy_dsn(self.profile.proxy))
        c.set_cookies(cookies)
        self.client = c
        return self

    async def __aexit__(self, *exc) -> None:
        return None

    # ------------------------------------------------------------- doc

    async def feed(self, count: int = 24) -> list[FeedItem]:
        """For You cua tai khoan nay, qua proxy cua no."""
        assert self.client is not None
        return parse_feed(list(await self.client.get_timeline(count)))

    async def watch(self, tweet_id: str) -> None:
        """Mo bai (TweetDetail) - buoc "xem" truoc khi tha tim / tra loi / dang lai."""
        assert self.client is not None
        await self.client.get_tweet_by_id(tweet_id)

    async def repost(self, tweet_id: str) -> ActionResult:
        assert self.client is not None
        try:
            await self.client.retweet(tweet_id)
        except Exception as exc:
            if "already" in str(exc).lower() or "327" in str(exc):
                return ActionResult(True, "already reposted")
            return classify_exc(exc, idempotent=True)
        return ActionResult(True, "ok")

    async def search(self, keyword: str, count: int = 12) -> list[FeedItem]:
        assert self.client is not None
        return parse_feed(list(await self.client.search_tweet(keyword, "Top", count)))

    async def user_id(self, handle: str) -> str:
        assert self.client is not None
        user = await self.client.get_user_by_screen_name(handle)
        return str(getattr(user, "id", "") or "")

    async def me(self):
        assert self.client is not None
        return await self.client.user()

    # ------------------------------------------------------------- hanh dong

    async def like(self, tweet_id: str) -> ActionResult:
        assert self.client is not None
        try:
            await self.client.favorite_tweet(tweet_id)
        except Exception as exc:
            if "139" in str(exc) or "already" in str(exc).lower():
                return ActionResult(True, "already liked")
            return classify_exc(exc, idempotent=True)
        return ActionResult(True, "ok")

    async def follow(self, user_id: str) -> ActionResult:
        assert self.client is not None
        try:
            await self.client.follow_user(user_id)
        except Exception as exc:
            return classify_exc(exc, idempotent=True)
        return ActionResult(True, "ok")

    async def comment(self, tweet_id: str, text: str) -> ActionResult:
        """Tra loi bai. KHONG idempotent."""
        assert self.client is not None
        try:
            t = await self.client.create_tweet(text, reply_to=tweet_id)
        except Exception as exc:
            return classify_exc(exc, idempotent=False)
        tid = getattr(t, "id", None)
        if not tid:
            return ActionResult(False, "X answered without a tweet id", needs_human=True)
        return ActionResult(True, f"reply {tid}", raw=t)

    async def edit_profile(self, *, name: str | None = None):
        assert self.client is not None
        return await self.client.update_profile(name=name)

    async def change_username(self, username: str):
        """v1.1 account/settings.json nhan screen_name. Form body, khong phai JSON."""
        assert self.client is not None
        headers = self.client._base_headers | {"content-type": "application/x-www-form-urlencoded"}
        return await self.client.post(
            "https://api.x.com/1.1/account/settings.json",
            data={"screen_name": username.lstrip("@")},
            headers=headers,
        )

    async def change_picture(self, path: Path):
        """v1.1 account/update_profile_image.json, multipart `image`."""
        assert self.client is not None
        headers = {k: v for k, v in self.client._base_headers.items() if k != "content-type"}
        with open(path, "rb") as f:
            data = f.read()
        return await self.client.post(
            "https://api.x.com/1.1/account/update_profile_image.json",
            files={"image": (Path(path).name, data, "image/jpeg")},
            headers=headers,
        )

    async def post(self, text: str, media: Path | None = None):
        """Dang mot bai (co the kem mot file). Tra ve Tweet cua twifork."""
        assert self.client is not None
        media_ids: list[str] = []
        if media is not None:
            category = media_category(media)
            media_ids.append(
                await self.client.upload_media(
                    str(media), wait_for_completion=True, media_category=category
                )
            )
        return await self.client.create_tweet(text, media_ids=media_ids or None)


async def check(profile: Profile) -> tuple[bool, str]:
    """Kiem phien bang mot request nhe qua proxy. Thu vien lech -> LibraryBroken, khong
    phai (False, ...): loi do khong duoc tinh len tai khoan."""
    if not profile.cookies_enc:
        return False, "profile has never signed in"
    if profile.proxy is None:
        return False, "profile has no proxy"
    try:
        async with XClient(profile) as x:
            me = await x.me()
    except Exception as exc:
        r = classify_exc(exc, idempotent=True)
        if r.library:
            raise LibraryBroken(r.detail) from exc
        return False, r.detail
    return True, f"still signed in as @{getattr(me, 'screen_name', '?')}"
