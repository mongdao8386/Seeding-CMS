"""Dang bai Reddit qua PRAW: bai chu / anh / video vao mot subreddit, hoac binh luan
vao mot bai co san (target.kind = comment, target.url).

Subreddit lay tu target["subreddit"] (chon khi len lich). Khong co thi tu choi ngay,
khong doan: dang nham subreddit la cach nhanh nhat de bi ban.
"""

from __future__ import annotations

from pathlib import Path

import structlog

from seeding.config import get_settings
from seeding.domain.models import Account, Platform, Profile, Variant
from seeding.platforms.base import PublishResult, register
from seeding.platforms.reddit.client import ORIGIN, RedditClient, classify_exc, missing_credentials

log = structlog.get_logger(__name__)


class RedditAdapter:
    platform = Platform.REDDIT

    def __init__(self, *, client_factory=RedditClient) -> None:
        self._factory = client_factory

    async def publish(
        self,
        account: Account,
        variant: Variant,
        target: dict,
        *,
        profile: Profile | None = None,
    ) -> PublishResult:
        missing = missing_credentials(account.get_secrets() or {})
        if missing:
            return PublishResult(
                ok=False,
                needs_human=True,
                error=f"{account.handle}: thiếu bí mật Reddit ({', '.join(missing)})",
            )
        kind = (target.get("kind") or "post").lower()
        if kind == "comment":
            url = target.get("url")
            text = (variant.body or "").strip()
            if not url:
                return PublishResult(ok=False, error="target is missing 'url' to comment on")
            if not text:
                return PublishResult(
                    ok=False, error="Bình luận cần thân bài - tiêu đề không có chỗ trong bình luận."
                )
            try:
                async with self._factory(account, profile) as rd:
                    c = await rd.reply_to(url, text)
            except Exception as exc:
                return _failed(classify_exc(exc, idempotent=False))
            if c is None:
                return PublishResult(ok=False, error=f"Reddit accepted nothing for {url} - locked?")
            return PublishResult(ok=True, remote_id=str(c.id), remote_url=f"{ORIGIN}{c.permalink}")

        subreddit = str(target.get("subreddit") or "").strip().lstrip("r/").strip("/")
        if not subreddit:
            return PublishResult(
                ok=False, error="Reddit cần subreddit - chọn khi lên lịch (ô Subreddit)."
            )
        media: Path | None = None
        if variant.media_variant_ref:
            media = Path(variant.media_variant_ref)
            if not media.is_file():
                return PublishResult(ok=False, error=f"rendered media file is missing: {media}")
        try:
            async with self._factory(account, profile) as rd:
                s = await rd.submit(subreddit, variant.title, variant.body or "", media)
        except Exception as exc:
            r = classify_exc(exc, idempotent=False)
            log.warning("reddit.publish_failed", handle=account.handle, error=r.detail)
            return _failed(r)
        sid = str(getattr(s, "id", "") or "")
        if not sid:
            return PublishResult(
                ok=False, needs_human=True, error="Reddit answered without a submission id"
            )
        url = f"{ORIGIN}{getattr(s, 'permalink', f'/comments/{sid}/')}"
        log.info("reddit.published", handle=account.handle, id=sid, url=url)
        return PublishResult(
            ok=True,
            remote_id=sid,
            remote_url=url,
            metrics={"subreddit": subreddit, "kind": "media" if media else "text"},
        )


def _failed(r) -> PublishResult:
    return PublishResult(ok=False, error=r.detail, needs_human=r.needs_human, retryable=r.retryable)


if get_settings().reddit_enabled:
    register(RedditAdapter())
