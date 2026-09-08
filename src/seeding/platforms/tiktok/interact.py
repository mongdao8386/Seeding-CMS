"""Chay mot ActivityJob nham dich tren TikTok bang HTTP: tha tim, theo doi, binh luan.

Thay cho browser/interact.py tren TikTok - trang web khong tai noi qua proxy dan cu,
con endpoint thi 1-3 giay. Cung hop dong ket qua (InteractResult) de worker khong
phai biet duong nao da chay.

Hai luat giu nguyen tu ban trinh duyet:
  1. Khong bao gio bao thanh cong khi chua thay bang chung - o day la status_code=0
     (va is_digg=1 voi tha tim) trong body TikTok tra ve.
  2. Binh luan khong tu thu lai khi khong ro ket qua. Tha tim va theo doi thi duoc:
     TikTok coi chung la idempotent.
"""

from __future__ import annotations

import random
import re
from urllib.parse import urlparse

import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from seeding.browser.checkpoints import Checkpoint, CheckpointKind
from seeding.config import get_settings
from seeding.content.comments import COMMENTS, comment_text
from seeding.domain.models import Account, ActivityJob, ActivityKind, Platform, Profile
from seeding.platforms.base import InteractResult, register_interact
from seeding.platforms.outreach import ensure_proxy_loaded
from seeding.platforms.tiktok.web import ActionResult, TikTokWeb

log = structlog.get_logger(__name__)


_VIDEO = re.compile(r"^/@([^/]+)/video/(\d+)")
_PROFILE = re.compile(r"^/@([^/]+)/?$")


def parse_target(url: str | None) -> tuple[str | None, str | None]:
    """(handle, item_id). item_id None neu la trang ca nhan."""
    if not url:
        return None, None
    path = urlparse(url).path
    if m := _VIDEO.match(path):
        return m.group(1), m.group(2)
    if m := _PROFILE.match(path):
        return m.group(1), None
    return None, None


def _to_result(res: ActionResult) -> InteractResult:
    if res.ok:
        return InteractResult(True, res.detail)
    if res.needs_human:
        # Worker doc `checkpoint` de day sang NEEDS_HUMAN; VERIFY la loai khong terminal.
        return InteractResult(
            False, res.detail, checkpoint=Checkpoint(CheckpointKind.VERIFY, res.detail)
        )
    return InteractResult(False, res.detail, retryable=res.retryable)


async def run(
    session: AsyncSession,
    profile: Profile,
    job: ActivityJob,
    *,
    web_factory=TikTokWeb,
    rng: random.Random | None = None,
) -> InteractResult:
    await ensure_proxy_loaded(session, profile)
    if profile.proxy is None:
        return InteractResult(
            False, "profile has no proxy - refusing to touch TikTok from the host IP"
        )

    handle, item_id = parse_target(job.target_url)
    if job.kind is ActivityKind.FOLLOW and job.target_account_id is not None:
        target = await session.get(Account, job.target_account_id)
        handle = target.handle if target else handle

    if job.kind in (ActivityKind.ENGAGE, ActivityKind.COMMENT) and not item_id:
        return InteractResult(False, f"{job.kind.value} job has no video url")
    if job.kind is ActivityKind.FOLLOW and not handle:
        return InteractResult(False, "follow job has no target handle")
    if job.kind is ActivityKind.REPOST:
        return InteractResult(False, "repost over HTTP is not implemented yet")

    try:
        async with web_factory(profile) as tt:
            if job.kind is ActivityKind.ENGAGE:
                res = await tt.like(item_id)
            elif job.kind is ActivityKind.COMMENT:
                res = await tt.comment(item_id, comment_text(job.id, rng))
            else:
                user = await tt.user(handle)
                if not user["id"] or not user["secUid"]:
                    return InteractResult(
                        False, f"could not resolve @{handle} to a user id", retryable=True
                    )
                res = await tt.follow(user["id"], user["secUid"])
    except Exception as exc:
        # Signer chet, proxy treo tu dau, feed hong... ha tang, khong phai tai khoan.
        log.warning("tiktok_interact.failed", job=str(job.id), error=f"{type(exc).__name__}: {exc}")
        return InteractResult(False, f"{type(exc).__name__}: {exc}", retryable=True)

    result = _to_result(res)
    log.info(
        "tiktok_interact.done",
        job=str(job.id),
        kind=job.kind.value,
        target=job.target_url,
        ok=result.ok,
        detail=result.detail,
    )
    return result


if get_settings().tiktok_interact_via_http:
    register_interact(Platform.TIKTOK, run)


__all__ = ["COMMENTS", "InteractResult", "comment_text", "parse_target", "run"]
