"""Dang bai X qua twifork: chu, hoac chu kem mot anh / video.

Khac TikTok va Instagram, X dang duoc bai chi co chu. Gioi han 280 ky tu: dai hon thi
cat o ranh gioi tu - mot bai bi cat con hon mot job ket mai trong lich.

Dang bai KHONG BAO GIO tu thu lai khi khong ro ket qua (mang dut sau khi gui): co the
bai da len, dang lai la hai bai giong nhau.
"""

from __future__ import annotations

from pathlib import Path

import structlog

from seeding.config import get_settings
from seeding.domain.models import Account, Platform, Profile, Variant
from seeding.platforms.base import PublishResult, register
from seeding.platforms.x.client import ORIGIN, XClient, classify_exc, media_category, truncate

log = structlog.get_logger(__name__)


def caption_for(variant: Variant) -> str:
    text = f"{variant.title}\n\n{variant.body}".strip() if variant.body else variant.title
    return truncate(text)


def tweet_url(handle: str, tweet_id: str) -> str:
    return f"{ORIGIN}/{handle}/status/{tweet_id}"


class XAdapter:
    platform = Platform.X

    def __init__(self, *, client_factory=XClient) -> None:
        self._factory = client_factory

    async def publish(
        self,
        account: Account,
        variant: Variant,
        target: dict,
        *,
        profile: Profile | None = None,
    ) -> PublishResult:
        kind = (target.get("kind") or "post").lower()
        if kind == "comment":
            return PublishResult(ok=False, error="Trả lời X theo lịch chưa có — dùng phần nuôi.")
        if profile is None:
            return PublishResult(ok=False, error=f"{account.handle}: no profile yet")
        if not profile.cookies_enc:
            return PublishResult(
                ok=False,
                needs_human=True,
                error=f"{account.handle} has never signed in - import its cookie first",
            )
        if profile.proxy is None:
            return PublishResult(ok=False, error=f"{account.handle}: profile has no proxy")

        media: Path | None = None
        if variant.media_variant_ref:
            media = Path(variant.media_variant_ref)
            if not media.is_file():
                return PublishResult(ok=False, error=f"rendered media file is missing: {media}")
            if media_category(media) is None:
                return PublishResult(
                    ok=False, error=f"X does not accept this media type: {media.suffix}"
                )

        text = caption_for(variant)
        if not text and media is None:
            return PublishResult(ok=False, error="nothing to post: empty text and no media")

        try:
            async with self._factory(profile) as x:
                tweet = await x.post(text, media)
        except Exception as exc:
            r = classify_exc(exc, idempotent=False)
            log.warning("x.publish_failed", handle=account.handle, error=r.detail)
            return PublishResult(
                ok=False,
                error=r.detail,
                # Thu vien lech: thu lai sau khi cap nhat, khong phai viec cua tai khoan.
                needs_human=r.needs_human,
                retryable=r.retryable or r.library,
                metrics={"library": True} if r.library else {},
            )

        tid = str(getattr(tweet, "id", "") or "")
        if not tid:
            return PublishResult(
                ok=False,
                needs_human=True,
                error="X answered without a tweet id - check the profile before retrying",
            )
        url = tweet_url(account.handle.lstrip("@"), tid)
        log.info("x.published", handle=account.handle, id=tid, url=url)
        return PublishResult(
            ok=True,
            remote_id=tid,
            remote_url=url,
            metrics={"kind": media_category(media) if media else "text", "chars": len(text)},
        )


if get_settings().x_enabled:
    register(XAdapter())
