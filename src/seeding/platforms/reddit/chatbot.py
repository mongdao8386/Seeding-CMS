"""Kenh chatbot Reddit qua PRAW: tra loi binh luan duoi bai cua tai khoan. Khong DM."""

from __future__ import annotations

from datetime import UTC, datetime

import structlog

from seeding.config import get_settings
from seeding.domain.models import Account, Platform, Profile
from seeding.platforms.base import register_chatbot
from seeding.platforms.chatbot import Comment, Message, Outcome, Post, Thread
from seeding.platforms.reddit.client import ORIGIN, RedditClient, classify_exc

log = structlog.get_logger(__name__)


class RedditChannel:
    supports_dm = False

    def __init__(self, profile: Profile | None, account: Account, *, client_factory=RedditClient):
        self.profile = profile
        self.account = account
        self._factory = client_factory
        self.rd: RedditClient | None = None
        self.me = ""

    async def __aenter__(self) -> RedditChannel:
        self.rd = await self._factory(self.account, self.profile).__aenter__()
        me = await self.rd.me()
        self.me = str(getattr(me, "name", "") or "")
        return self

    async def __aexit__(self, *exc) -> None:
        if self.rd is not None:
            await self.rd.__aexit__(*exc)

    async def own_posts(self, count: int) -> list[Post]:
        assert self.rd is not None

        def _new():
            return list(self.rd.reddit.redditor(self.me).submissions.new(limit=count))

        subs = await self.rd._run(_new)
        return [
            Post(
                id=str(s.id),
                url=f"{ORIGIN}{getattr(s, 'permalink', '')}",
                caption=str(getattr(s, "title", "") or ""),
                created_at=datetime.fromtimestamp(float(getattr(s, "created_utc", 0) or 0), tz=UTC),
            )
            for s in subs
        ]

    async def comments(self, post: Post, count: int) -> list[Comment]:
        assert self.rd is not None

        def _top():
            sub = self.rd.reddit.submission(post.id)
            sub.comments.replace_more(limit=0)
            return list(sub.comments)[:count]

        rows = await self.rd._run(_top)
        out = []
        for c in rows:
            author = getattr(c, "author", None)
            handle = str(getattr(author, "name", "") or "") if author is not None else ""
            if not handle:
                continue
            replied = any(
                str(getattr(getattr(r, "author", None), "name", "") or "") == self.me
                for r in (getattr(c, "replies", None) or [])
            )
            out.append(
                Comment(
                    id=str(c.id),
                    post=post,
                    author_handle=handle,
                    author_id=str(getattr(author, "id", "") or ""),
                    text=str(getattr(c, "body", "") or ""),
                    created_at=datetime.fromtimestamp(
                        float(getattr(c, "created_utc", 0) or 0), tz=UTC
                    ),
                    url=f"{ORIGIN}{getattr(c, 'permalink', '')}",
                    replied_by_me=replied,
                )
            )
        return out

    async def reply_comment(self, comment: Comment, text: str) -> Outcome:
        assert self.rd is not None
        try:
            r = await self.rd._run(lambda: self.rd.reddit.comment(comment.id).reply(text))
        except Exception as exc:
            c = classify_exc(exc, idempotent=False)
            return Outcome(
                False,
                c.detail,
                needs_human=c.needs_human,
                retryable=c.retryable,
                terminal=c.terminal,
            )
        return Outcome(r is not None, "ok" if r is not None else "Reddit accepted nothing back")

    async def unread_threads(self, count: int) -> list[Thread]:
        return []

    async def messages(self, thread: Thread, count: int) -> list[Message]:
        return []

    async def send_dm(self, thread: Thread, text: str) -> Outcome:
        return Outcome(False, "Reddit DM is not supported")


def factory(profile: Profile | None, account: Account) -> RedditChannel:
    return RedditChannel(profile, account)


if get_settings().reddit_enabled:
    register_chatbot(Platform.REDDIT, factory)
