"""Kenh chatbot TikTok: binh luan duoi video cua tai khoan, qua web API + signer.

Tin nhan TikTok di qua websocket rieng (frontier), khong lam duoc bang HTTP - kenh nay
khong ho tro DM. Endpoint binh luan: /api/comment/list/ (doc), /api/comment/publish/
voi reply_id (tra loi) - cai trang web goi. CHUA thu tren tai khoan that.
"""

from __future__ import annotations

from datetime import UTC, datetime

import structlog

from seeding.config import get_settings
from seeding.domain.models import Account, Platform, Profile
from seeding.platforms.base import register_chatbot
from seeding.platforms.chatbot import Comment, Message, Outcome, Post, Thread
from seeding.platforms.tiktok.web import ORIGIN, TikTokWeb

log = structlog.get_logger(__name__)


def parse_comments(body: dict, post: Post, own_uid: str) -> list[Comment]:
    out = []
    for c in body.get("comments") or []:
        cid = str(c.get("cid") or c.get("id") or "")
        user = c.get("user") or {}
        handle = str(user.get("unique_id") or user.get("uniqueId") or "")
        if not cid or not handle:
            continue
        replies = c.get("reply_comment") or []
        replied = any(
            str((r.get("user") or {}).get("uid") or "") == own_uid
            for r in replies
            if isinstance(r, dict)
        )
        ts = c.get("create_time")
        out.append(
            Comment(
                id=cid,
                post=post,
                author_handle=handle,
                author_id=str(user.get("uid") or user.get("id") or ""),
                text=str(c.get("text") or ""),
                created_at=datetime.fromtimestamp(int(ts), tz=UTC) if ts else None,
                url=f"{post.url}?comment={cid}",
                replied_by_me=replied,
            )
        )
    return out


class TikTokChannel:
    supports_dm = False

    def __init__(self, profile: Profile, account: Account, *, web_factory=TikTokWeb) -> None:
        self.profile = profile
        self.account = account
        self._factory = web_factory
        self.web: TikTokWeb | None = None
        self.sec_uid = ""
        self.uid = ""
        self.handle = account.handle.lstrip("@")

    async def __aenter__(self) -> TikTokChannel:
        self.web = await self._factory(self.profile).__aenter__()
        me = await self.web.user(self.handle)
        self.sec_uid, self.uid = me["secUid"], me["id"]
        return self

    async def __aexit__(self, *exc) -> None:
        if self.web is not None:
            await self.web.__aexit__(*exc)

    async def own_posts(self, count: int) -> list[Post]:
        assert self.web is not None
        items = await self.web.posts(self.sec_uid, count)
        return [
            Post(id=it.item_id, url=it.url, caption=it.desc)
            for it in items
            if it.author_handle == self.handle or not it.author_handle
        ] or [Post(id=it.item_id, url=it.url, caption=it.desc) for it in items]

    async def comments(self, post: Post, count: int) -> list[Comment]:
        assert self.web is not None
        body = await self.web.comments(post.id, count)
        return parse_comments(body, post, self.uid)

    async def reply_comment(self, comment: Comment, text: str) -> Outcome:
        assert self.web is not None
        res = await self.web.reply(comment.post.id, comment.id, text)
        return Outcome(res.ok, res.detail, needs_human=res.needs_human, retryable=res.retryable)

    async def unread_threads(self, count: int) -> list[Thread]:
        return []

    async def messages(self, thread: Thread, count: int) -> list[Message]:
        return []

    async def send_dm(self, thread: Thread, text: str) -> Outcome:
        return Outcome(False, "TikTok DM is not supported over HTTP")


def factory(profile: Profile, account: Account) -> TikTokChannel:
    return TikTokChannel(profile, account)


__all__ = ["ORIGIN", "TikTokChannel", "factory", "parse_comments"]

if get_settings().tiktok_interact_via_http:
    register_chatbot(Platform.TIKTOK, factory)
