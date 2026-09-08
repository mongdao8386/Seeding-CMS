"""Dang bai Instagram qua aiograpi: anh -> bai thuong, video -> Reel.

Nhu buoc 7 cua TikTok: upload KHONG BAO GIO tu thu lai khi khong ro ket qua. Mot video
da len toi Instagram ma request cau hinh bi dut giua chung thi bai co the da ton tai;
dang lai la hai bai giong nhau tren mot tai khoan moi - dau vet xau nhat co the.
"""

from __future__ import annotations

from pathlib import Path

import structlog

from seeding.config import get_settings
from seeding.domain.models import Account, Platform, Profile, Variant
from seeding.platforms.base import PublishResult, register
from seeding.platforms.instagram.client import ORIGIN, VIDEO_EXT, InstagramClient, classify_exc

log = structlog.get_logger(__name__)


def caption_for(variant: Variant) -> str:
    return f"{variant.title}\n\n{variant.body}".strip() if variant.body else variant.title


def media_url(code: str, *, video: bool) -> str:
    return f"{ORIGIN}/reel/{code}/" if video else f"{ORIGIN}/p/{code}/"


class InstagramAdapter:
    platform = Platform.INSTAGRAM

    def __init__(self, *, client_factory=InstagramClient) -> None:
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
            return PublishResult(
                ok=False, error="Bình luận Instagram theo lịch chưa có — dùng phần nuôi."
            )
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
        if not variant.media_variant_ref:
            return PublishResult(
                ok=False,
                error="instagram cannot post text alone. Attach a media file to the content first.",
            )
        path = Path(variant.media_variant_ref)
        if not path.is_file():
            return PublishResult(ok=False, error=f"rendered media file is missing: {path}")

        video = path.suffix.lower() in VIDEO_EXT
        try:
            async with self._factory(profile) as ig:
                media = await ig.upload(path, caption_for(variant))
        except Exception as exc:
            r = classify_exc(exc, idempotent=False)
            log.warning("instagram.publish_failed", handle=account.handle, error=r.detail)
            return PublishResult(
                ok=False,
                error=r.detail,
                needs_human=r.needs_human,
                retryable=r.retryable,
            )

        code = str(getattr(media, "code", "") or "")
        pk = str(getattr(media, "pk", "") or "")
        if not pk:
            return PublishResult(
                ok=False,
                needs_human=True,
                error="Instagram answered without a media id - check the profile before retrying",
            )
        url = media_url(code, video=video) if code else None
        log.info("instagram.published", handle=account.handle, pk=pk, url=url)
        return PublishResult(
            ok=True, remote_id=pk, remote_url=url, metrics={"kind": "reel" if video else "photo"}
        )


if get_settings().instagram_enabled:
    register(InstagramAdapter())
