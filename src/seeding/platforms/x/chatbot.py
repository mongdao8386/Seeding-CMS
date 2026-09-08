"""Kenh chatbot X qua twifork: reply duoi bai cua tai khoan va tin nhan (DM)."""

from __future__ import annotations

from datetime import UTC, datetime

import structlog

from seeding.config import get_settings
from seeding.domain.models import Account, Platform, Profile
from seeding.platforms.base import register_chatbot
from seeding.platforms.chatbot import Comment, Message, Outcome, Post, Thread
from seeding.platforms.x.client import ORIGIN, XClient, classify_exc

log = structlog.get_logger(__name__)


def _outcome(exc: BaseException, *, idempotent: bool) -> Outcome:
    r = classify_exc(exc, idempotent=idempotent)
    return Outcome(
        False,
        r.detail,
        needs_human=r.needs_human,
        retryable=r.retryable or r.library,
        terminal=r.terminal,
    )


def _ts(value) -> datetime | None:
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=UTC)
    return None


class XChannel:
    supports_dm = True

    def __init__(self, profile: Profile, account: Account, *, client_factory=XClient):
        self.profile = profile
        self.account = account
        self._factory = client_factory
        self.x: XClient | None = None
        self.user_id = ""
        self.handle = account.handle.lstrip("@")

    async def __aenter__(self) -> XChannel:
        self.x = await self._factory(self.profile).__aenter__()
        assert self.x.client is not None
        self.user_id = str(await self.x.client.user_id())
        return self

    async def __aexit__(self, *exc) -> None:
        if self.x is not None:
            await self.x.__aexit__(*exc)

    async def own_posts(self, count: int) -> list[Post]:
        assert self.x is not None and self.x.client is not None
        tweets = await self.x.client.get_user_tweets(self.user_id, "Tweets", count)
        out = []
        for t in tweets:
            if getattr(t, "retweeted_tweet", None):
                continue
            tid = str(getattr(t, "id", "") or "")
            if not tid:
                continue
            out.append(
                Post(
                    id=tid,
                    url=f"{ORIGIN}/{self.handle}/status/{tid}",
                    caption=str(getattr(t, "text", "") or ""),
                    created_at=_ts(getattr(t, "created_at_datetime", None)),
                )
            )
        return out

    async def comments(self, post: Post, count: int) -> list[Comment]:
        assert self.x is not None and self.x.client is not None
        tweet = await self.x.client.get_tweet_by_id(post.id)
        replies = list(getattr(tweet, "replies", None) or [])[:count]
        out = []
        for r in replies:
            user = getattr(r, "user", None)
            handle = str(getattr(user, "screen_name", "") or "")
            rid = str(getattr(r, "id", "") or "")
            if not rid or not handle:
                continue
            out.append(
                Comment(
                    id=rid,
                    post=post,
                    author_handle=handle,
                    author_id=str(getattr(user, "id", "") or ""),
                    text=str(getattr(r, "text", "") or ""),
                    created_at=_ts(getattr(r, "created_at_datetime", None)),
                    url=f"{ORIGIN}/{handle}/status/{rid}",
                )
            )
        return out

    async def reply_comment(self, comment: Comment, text: str) -> Outcome:
        assert self.x is not None
        res = await self.x.comment(comment.id, text)
        return Outcome(
            res.ok,
            res.detail,
            needs_human=res.needs_human,
            retryable=res.retryable or res.library,
            terminal=res.terminal,
        )

    async def unread_threads(self, count: int) -> list[Thread]:
        assert self.x is not None and self.x.client is not None
        inbox = await self.x.client.get_dm_inbox()
        out = []
        for conv in list(inbox)[:count]:
            if getattr(conv, "is_group", False):
                continue
            peer = str(getattr(conv, "partner_id", "") or "")
            if not peer:
                ids = [
                    str(i)
                    for i in (getattr(conv, "participant_ids", None) or [])
                    if str(i) != self.user_id
                ]
                peer = ids[0] if ids else ""
            if not peer:
                continue
            name = str(getattr(conv, "name", "") or peer)
            out.append(
                Thread(
                    id=str(getattr(conv, "id", peer)),
                    peer_handle=name,
                    peer_id=peer,
                    url=f"{ORIGIN}/messages/{getattr(conv, 'id', peer)}",
                )
            )
        return out

    async def messages(self, thread: Thread, count: int) -> list[Message]:
        assert self.x is not None and self.x.client is not None
        history = list(await self.x.client.get_dm_history(thread.peer_id))[:count]
        msgs = [
            Message(
                id=str(getattr(m, "id", "")),
                from_me=str(getattr(m, "sender_id", "")) == self.user_id,
                text=str(getattr(m, "text", "") or ""),
                created_at=_ts(getattr(m, "time", None))
                if isinstance(getattr(m, "time", None), datetime)
                else None,
            )
            for m in history
            if getattr(m, "text", None)
        ]
        # twikit tra ve moi truoc; engine muon cu truoc moi sau.
        return list(reversed(msgs))

    async def send_dm(self, thread: Thread, text: str) -> Outcome:
        assert self.x is not None and self.x.client is not None
        try:
            m = await self.x.client.send_dm(thread.peer_id, text)
        except Exception as exc:
            return _outcome(exc, idempotent=False)
        return Outcome(
            bool(getattr(m, "id", None)), "ok" if getattr(m, "id", None) else "no message id"
        )


def factory(profile: Profile, account: Account) -> XChannel:
    return XChannel(profile, account)


if get_settings().x_enabled:
    register_chatbot(Platform.X, factory)
