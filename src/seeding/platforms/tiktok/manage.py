"""Xoa video TikTok da dang, qua web API (khong trinh duyet).

Endpoint: POST /api/aweme/delete/?aweme_id=<id>&target=<id> - cai ma nut "Xoa" tren
trang web goi (tham khao raracraz/tiktok-delete-video-script). Can cookie phien va
x-secsdk-csrf-token; TikTokWeb lay token do bang mot HEAD toi passport/web/account/info.
Sua chu thich thi web TikTok khong co - lam tay trong trinh duyet.
"""

from __future__ import annotations

import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from seeding.browser.checkpoints import Checkpoint, CheckpointKind
from seeding.config import get_settings
from seeding.domain.models import ActivityJob, Platform, Profile
from seeding.platforms import manage
from seeding.platforms.base import InteractResult, register_manage
from seeding.platforms.outreach import ensure_proxy_loaded
from seeding.platforms.tiktok.web import TikTokWeb

log = structlog.get_logger(__name__)


async def run(
    session: AsyncSession,
    profile: Profile,
    job: ActivityJob,
    *,
    web_factory=TikTokWeb,
) -> InteractResult:
    plan = manage.decode(job.target_url)
    if plan is None or not plan.remote_id:
        return InteractResult(False, "manage job has no plan or no video id")
    if plan.action != "delete":
        return InteractResult(False, "TikTok không sửa được chú thích qua web — mở trình duyệt")
    await ensure_proxy_loaded(session, profile)
    if profile.proxy is None:
        return InteractResult(False, "profile has no proxy - refusing to touch TikTok")

    try:
        async with web_factory(profile) as tt:
            res = await tt.delete_video(plan.remote_id)
    except Exception as exc:
        log.warning("tiktok_manage.failed", job=str(job.id), error=f"{type(exc).__name__}: {exc}")
        return InteractResult(False, f"{type(exc).__name__}: {exc}", retryable=True)

    if not res.ok:
        cp = Checkpoint(CheckpointKind.VERIFY, res.detail) if res.needs_human else None
        return InteractResult(False, res.detail, checkpoint=cp, retryable=res.retryable)

    await manage.mark_done(session, job, plan)
    return InteractResult(True, "đã xoá")


if get_settings().tiktok_interact_via_http:
    register_manage(Platform.TIKTOK, run)
