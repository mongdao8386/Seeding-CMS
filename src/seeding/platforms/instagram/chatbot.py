"""Kenh chatbot Instagram qua aiograpi: binh luan duoi bai cua tai khoan va tin nhan."""

from __future__ import annotations

from datetime import UTC, datetime

import structlog

from seeding.config import get_settings
from seeding.domain.models import Account, Platform, Profile
from seeding.platforms.base import register_chatbot
from seeding.platforms.chatbot import Comment, Message, Outcome, Post, Thread
from seeding.platforms.instagram.client import ORIGIN, InstagramClient, classify_exc

log = structlog.get_logger(__name__)


def _outcome(exc: BaseException, *, idempotent: bool) -> Outcome:
    r = classify_exc(exc, idempotent=idempotent)
    return Outcome(
        False, r.detail, needs_human=r.needs_human, retryable=r.retryable, terminal=r.terminal
    )


def _ts(value) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=UTC)
    try:
        return datetime.fromtimestamp(
            int(value) / (1_000_000 if int(value) > 10**12 else 1), tz=UTC
        )
    except (TypeError, ValueError):
        return None


class InstagramChannel:
    supports_dm = True

    def __init__(self, profile: Profile, account: Account, *, client_factory=InstagramClient):
        self.profile = profile
        self.account = account
        self._factory = client_factory
        self.ig: InstagramClient | None = None
        self.user_id = ""

    async def __aenter__(self) -> InstagramChannel:
        self.ig = await self._factory(self.profile).__aenter__()
        c = self.ig.client
        auth = getattr(c, "authorization_data", None) or {}
        self.user_id = str(auth.get("ds_user_id") or getattr(c, "user_id", "") or "")
        return self

    async def __aexit__(self, *exc) -> None:
        if self.ig is not None:
            await self.ig.__aexit__(*exc)

    async def own_posts(self, count: int) -> list[Post]:
        assert self.ig is not None and self.ig.client is not None
        medias = await self.ig.client.user_medias(int(self.user_id), amount=count)
        out = []
        for m in medias:
            code = str(getattr(m, "code", "") or "")
            out.append(
                Post(
                    id=str(getattr(m, "id", None) or getattr(m, "pk", "")),
                    url=f"{ORIGIN}/p/{code}/" if code else "",
                    caption=str(getattr(m, "caption_text", "") or ""),
                    created_at=_ts(getattr(m, "taken_at", None)),
                )
            )
        return out

    async def comments(self, post: Post, count: int) -> list[Comment]:
        assert self.ig is not None and self.ig.client is not None
        rows = await self.ig.client.media_comments(post.id, amount=count)
        out = []
        for c in rows:
            user = getattr(c, "user", None)
            handle = str(getattr(user, "username", "") or "")
            pk = str(getattr(c, "pk", "") or "")
            if not pk or not handle:
                continue
            out.append(
                Comment(
                    id=pk,
                    post=post,
                    author_handle=handle,
                    author_id=str(getattr(user, "pk", "") or ""),
                    text=str(getattr(c, "text", "") or ""),
                    created_at=_ts(getattr(c, "created_at_utc", None)),
                    url=f"{post.url}c/{pk}/",
                )
            )
        return out

    async def reply_comment(self, comment: Comment, text: str) -> Outcome:
        assert self.ig is not None and self.ig.client is not None
        try:
            c = await self.ig.client.media_comment(
                comment.post.id, text, replied_to_comment_id=int(comment.id)
            )
        except Exception as exc:
            return _outcome(exc, idempotent=False)
        return Outcome(
            bool(getattr(c, "pk", None)), "ok" if getattr(c, "pk", None) else "no comment id"
        )

    async def unread_threads(self, count: int) -> list[Thread]:
        assert self.ig is not None and self.ig.client is not None
        threads = await self.ig.client.direct_threads(amount=count, selected_filter="unread")
        out = []
        for t in threads:
            users = [
                u
                for u in (getattr(t, "users", None) or [])
                if str(getattr(u, "pk", "")) != self.user_id
            ]
            if not users:
                continue
            tid = str(getattr(t, "id", "") or getattr(t, "pk", ""))
            peer = users[0]
            out.append(
                Thread(
                    id=tid,
                    peer_handle=str(getattr(peer, "username", "") or ""),
                    peer_id=str(getattr(peer, "pk", "") or ""),
                    url=f"{ORIGIN}/direct/t/{tid}/",
                )
            )
        return out

    async def messages(self, thread: Thread, count: int) -> list[Message]:
        assert self.ig is not None and self.ig.client is not None
        rows = await self.ig.client.direct_messages(int(thread.id), amount=count)
        msgs = []
        for m in rows:
            text = getattr(m, "text", None)
            if not text:
                continue
            mine = (
                bool(getattr(m, "is_sent_by_viewer", False))
                or str(getattr(m, "user_id", "")) == self.user_id
            )
            msgs.append(
                Message(
                    id=str(getattr(m, "id", "")),
                    from_me=mine,
                    text=str(text),
                    created_at=_ts(getattr(m, "timestamp", None)),
                )
            )
        msgs.sort(key=lambda m: m.created_at or datetime.min.replace(tzinfo=UTC))
        return msgs

    async def send_dm(self, thread: Thread, text: str) -> Outcome:
        assert self.ig is not None and self.ig.client is not None
        try:
            m = await self.ig.client.direct_answer(int(thread.id), text)
        except Exception as exc:
            return _outcome(exc, idempotent=False)
        return Outcome(
            bool(getattr(m, "id", None)), "ok" if getattr(m, "id", None) else "no message id"
        )


def factory(profile: Profile, account: Account) -> InstagramChannel:
    return InstagramChannel(profile, account)


if get_settings().instagram_enabled:
    register_chatbot(Platform.INSTAGRAM, factory)
