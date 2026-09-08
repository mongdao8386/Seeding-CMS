"""Mot phien Reddit cua MOT tai khoan qua PRAW (dong bo, boc trong asyncio.to_thread).

    async with RedditClient(account, profile) as rd:
        items = await rd.feed(24)
        await rd.like(items[0].item_id)

PRAW la thu vien dong bo; moi loi goi mang boc trong to_thread de khong chan worker.
Han muc cua Reddit tinh theo OAuth client, ma moi tai khoan la mot client rieng, nen
cac tai khoan khong chia nhau han muc.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import structlog

from seeding.config import get_settings
from seeding.domain.models import Account, Profile
from seeding.platforms.base import proxy_dsn

log = structlog.get_logger(__name__)

ORIGIN = "https://www.reddit.com"
# "Xu huong" tren Reddit do bang diem, khong phai luot xem. Bai front page thuong
# vai tram toi vai nghin diem.
MIN_SCORE = 100
REQUIRED = ("client_id", "client_secret", "username", "password")
VIDEO_EXT = {".mp4", ".mov", ".m4v"}
IMAGE_EXT = {".jpg", ".jpeg", ".png", ".gif", ".webp"}


@dataclass(frozen=True, slots=True)
class FeedItem:
    item_id: str
    author_handle: str
    author_id: str
    views: int  # diem (score)
    likes: int
    desc: str
    subreddit: str
    permalink: str

    @property
    def url(self) -> str:
        return f"{ORIGIN}{self.permalink}"


@dataclass(slots=True)
class ActionResult:
    ok: bool
    detail: str
    retryable: bool = False
    needs_human: bool = False
    terminal: bool = False
    raw: Any = field(default=None)


# ------------------------------------------------------------------ thuan tuy


def missing_credentials(secrets: dict) -> list[str]:
    return [k for k in REQUIRED if not (secrets or {}).get(k)]


def parse_feed(submissions: list) -> list[FeedItem]:
    out = []
    seen: set[str] = set()
    for s in submissions:
        sid = str(getattr(s, "id", "") or "")
        author = getattr(s, "author", None)
        handle = str(getattr(author, "name", "") or "") if author is not None else ""
        if not sid or not handle or sid in seen or getattr(s, "stickied", False):
            continue
        seen.add(sid)
        sub = getattr(s, "subreddit", None)
        out.append(
            FeedItem(
                item_id=sid,
                author_handle=handle,
                author_id=str(getattr(author, "id", "") or ""),
                views=int(getattr(s, "score", 0) or 0),
                likes=int(getattr(s, "score", 0) or 0),
                desc=str(getattr(s, "title", "") or ""),
                subreddit=str(getattr(sub, "display_name", "") or sub or ""),
                permalink=str(getattr(s, "permalink", "") or f"/comments/{sid}/"),
            )
        )
    return out


def classify_exc(exc: BaseException, *, idempotent: bool) -> ActionResult:
    """Ngoai le cua PRAW / prawcore thanh ket qua."""
    from prawcore import exceptions as pc

    name = type(exc).__name__
    text = f"{name}: {exc}"[:300]
    low = str(exc).lower()
    if "suspend" in low or ("banned" in low and "subreddit" not in low):
        return ActionResult(False, f"Reddit suspended the account: {text}", terminal=True)
    if isinstance(exc, (pc.OAuthException, pc.InvalidToken)) or "invalid_grant" in low:
        return ActionResult(False, f"Reddit rejected the credentials: {text}", needs_human=True)
    if isinstance(exc, pc.ResponseException) and getattr(exc, "response", None) is not None:
        status = getattr(exc.response, "status_code", 0)
        if status == 401:
            return ActionResult(False, f"Reddit rejected the credentials: {text}", needs_human=True)
    if isinstance(exc, pc.Forbidden):
        return ActionResult(False, f"Reddit refused (403): {text}", needs_human=True)
    if isinstance(exc, pc.TooManyRequests) or "ratelimit" in low:
        return ActionResult(False, f"Reddit rate limit: {text}", retryable=True)
    if isinstance(exc, (pc.ServerError, pc.RequestException, TimeoutError)):
        return ActionResult(
            False,
            f"network trouble, outcome unknown: {text}",
            retryable=idempotent,
            needs_human=not idempotent,
        )
    return ActionResult(False, f"Reddit refused: {text}")


# ------------------------------------------------------------------ phien


def build_reddit(account: Account, profile: Profile | None = None):
    """praw.Reddit cho tai khoan nay; qua proxy cua profile neu co."""
    import praw
    import requests

    secrets = account.get_secrets() or {}
    missing = missing_credentials(secrets)
    if missing:
        raise ValueError(f"missing reddit credentials for {account.handle}: {', '.join(missing)}")
    kwargs: dict = {}
    if profile is not None and profile.proxy is not None:
        session = requests.Session()
        dsn = proxy_dsn(profile.proxy)
        session.proxies = {"http": dsn, "https": dsn}
        kwargs["requestor_kwargs"] = {"session": session}
    return praw.Reddit(
        client_id=secrets["client_id"],
        client_secret=secrets["client_secret"],
        username=secrets["username"],
        password=secrets["password"],
        user_agent=get_settings().reddit_user_agent,
        check_for_async=False,
        **kwargs,
    )


class RedditClient:
    def __init__(self, account: Account, profile: Profile | None = None, *, reddit_factory=None):
        self.account = account
        self.profile = profile
        self._factory = reddit_factory or build_reddit
        self.reddit = None

    async def __aenter__(self) -> RedditClient:
        self.reddit = await asyncio.to_thread(self._factory, self.account, self.profile)
        return self

    async def __aexit__(self, *exc) -> None:
        return None

    async def _run(self, fn, *args):
        assert self.reddit is not None
        return await asyncio.to_thread(fn, *args)

    # ------------------------------------------------------------- doc

    async def feed(self, count: int = 24) -> list[FeedItem]:
        """Front page cua chinh tai khoan (hot). Chua subscribe gi thi Reddit tra r/popular."""

        def _hot():
            return list(self.reddit.front.hot(limit=count))

        return parse_feed(await self._run(_hot))

    async def search(self, keyword: str, count: int = 12) -> list[FeedItem]:
        def _search():
            return list(
                self.reddit.subreddit("all").search(
                    keyword, sort="hot", time_filter="week", limit=count
                )
            )

        return parse_feed(await self._run(_search))

    async def watch(self, submission_id: str) -> None:
        """Mo bai (doc title) - buoc "xem" truoc khi upvote / binh luan."""

        def _open():
            return self.reddit.submission(submission_id).title

        await self._run(_open)

    async def me(self):
        return await self._run(lambda: self.reddit.user.me())

    # ------------------------------------------------------------- hanh dong

    async def like(self, submission_id: str) -> ActionResult:
        try:
            await self._run(lambda: self.reddit.submission(submission_id).upvote())
        except Exception as exc:
            return classify_exc(exc, idempotent=True)
        return ActionResult(True, "ok")

    async def follow(self, handle: str) -> ActionResult:
        """Reddit khong co follow dung nghia tren API; "friend" la cai gan nhat."""
        try:
            await self._run(lambda: self.reddit.redditor(handle).friend())
        except Exception as exc:
            return classify_exc(exc, idempotent=True)
        return ActionResult(True, "ok")

    async def comment(self, submission_id: str, text: str) -> ActionResult:
        try:
            c = await self._run(lambda: self.reddit.submission(submission_id).reply(text))
        except Exception as exc:
            return classify_exc(exc, idempotent=False)
        if c is None:
            return ActionResult(False, "Reddit accepted nothing back - post locked or removed")
        return ActionResult(True, f"comment {getattr(c, 'id', '?')}", raw=c)

    async def submit(self, subreddit: str, title: str, body: str, media: Path | None = None):
        """Bai moi: chu, anh hoac video. Tra ve Submission (id, permalink)."""

        def _submit():
            sr = self.reddit.subreddit(subreddit)
            if media is None:
                return sr.submit(title=title, selftext=body or "")
            if media.suffix.lower() in VIDEO_EXT:
                return sr.submit_video(title=title, video_path=str(media))
            return sr.submit_image(title=title, image_path=str(media))

        return await self._run(_submit)

    async def reply_to(self, url: str, text: str):
        return await self._run(lambda: self.reddit.submission(url=url).reply(text))

    async def delete(self, submission_id: str) -> None:
        await self._run(lambda: self.reddit.submission(submission_id).delete())

    async def edit(self, submission_id: str, body: str) -> None:
        await self._run(lambda: self.reddit.submission(submission_id).edit(body))
