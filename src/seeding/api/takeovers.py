"""Hang doi cho nguoi, va cai dat/he thong cho man hinh Cai dat."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from seeding.api.deps import get_session
from seeding.api.schemas import ResolveIn, SettingsOut, TakeoverOut
from seeding.config import get_settings
from seeding.domain import vault
from seeding.domain.models import Account, Profile, TakeoverRequest, TakeoverStatus
from seeding.ops import alerts, flags, takeover

router = APIRouter(tags=["takeovers"])


async def _out(s: AsyncSession, r: TakeoverRequest) -> TakeoverOut:
    profile_id = r.profile_id
    if profile_id is None:
        profile_id = (
            await s.execute(select(Profile.id).where(Profile.account_id == r.account_id))
        ).scalar_one_or_none()
    return TakeoverOut(
        id=r.id,
        created_at=r.created_at,
        account_id=r.account_id,
        profile_id=profile_id,
        handle=r.account.handle,
        platform=r.account.platform,
        reason=r.reason,
        status=r.status,
        has_stuck_job=r.post_job_id is not None,
        alerted=r.alerted_at is not None,
    )


@router.get("/takeovers", response_model=list[TakeoverOut])
async def list_takeovers(s: AsyncSession = Depends(get_session)) -> list[TakeoverOut]:
    """Nhung tai khoan he thong da dung lai va cho nguoi. Cu nhat truoc."""
    # Doi soat truoc: tai khoan NEEDS_HUMAN ma khong co yeu cau la vo hinh voi nguoi van hanh.
    await takeover.reconcile(s)
    return [await _out(s, r) for r in await takeover.list_open(s)]


@router.get("/takeovers/{takeover_id}/totp")
async def takeover_totp(takeover_id: uuid.UUID, s: AsyncSession = Depends(get_session)) -> dict:
    """Ma 2FA hien tai. Chi sau chu so, khong bao gio tra ve seed."""
    request = await s.get(TakeoverRequest, takeover_id)
    if request is None:
        raise HTTPException(404, "Không có yêu cầu này")
    account = await s.get(Account, request.account_id)
    seed = (account.get_secrets() or {}).get("totp_seed") if account else None
    if not seed:
        return {"code": None, "note": "tài khoản này không lưu totp_seed"}
    return {"code": vault.totp_now(seed), "note": "đổi mỗi 30 giây"}


async def _open(s: AsyncSession, takeover_id: uuid.UUID) -> TakeoverRequest:
    request = await s.get(TakeoverRequest, takeover_id)
    if request is None:
        raise HTTPException(404, "Không có yêu cầu này")
    if request.status is not TakeoverStatus.OPEN:
        raise HTTPException(409, f"Yêu cầu này đã {request.status.value}")
    return request


@router.post("/takeovers/{takeover_id}/resolve", response_model=TakeoverOut)
async def resolve(
    takeover_id: uuid.UUID, body: ResolveIn, s: AsyncSession = Depends(get_session)
) -> TakeoverOut:
    """Da giai xong. Job bi ket duoc hen lai sau 6 tieng, khong chay ngay."""
    request = await _open(s, takeover_id)
    await takeover.resolve(s, request, by=body.by, note=body.note)
    return await _out(s, request)


@router.post("/takeovers/{takeover_id}/abandon", response_model=TakeoverOut)
async def abandon(
    takeover_id: uuid.UUID, body: ResolveIn, s: AsyncSession = Depends(get_session)
) -> TakeoverOut:
    """Khong cuu duoc - tai khoan sang DEAD."""
    request = await _open(s, takeover_id)
    await takeover.abandon(s, request, by=body.by, note=body.note or "không ghi lý do")
    return await _out(s, request)


# ---------------------------------------------------------------- cai dat


@router.get("/settings", response_model=SettingsOut)
async def settings_out() -> SettingsOut:
    """Nhung gia tri trong .env ma nguoi van hanh can nhin. Khong bao gio tra ve bi mat."""
    st = get_settings()
    return SettingsOut(
        warmup_quiet_days=st.warmup_quiet_days,
        warmup_days=st.warmup_days,
        default_daily_cap=st.default_daily_cap,
        health_check_interval_hours=st.health_check_interval_hours,
        health_fail_threshold=st.health_fail_threshold,
        schedule_timezone=st.schedule_timezone,
        alert_kind=st.alert_kind,
        alert_configured=alerts.configured(),
        tiktok_post_via_http=st.tiktok_post_via_http,
        tiktok_interact_via_http=st.tiktok_interact_via_http,
        instagram_enabled=st.instagram_enabled,
        x_enabled=st.x_enabled,
        reddit_enabled=st.reddit_enabled,
        facebook_enabled=st.facebook_enabled,
        chatbot_enabled=st.chatbot_enabled,
        chatbot_comments=st.chatbot_comments,
        chatbot_dms=st.chatbot_dms,
        chatbot_model=st.chatbot_model,
        chatbot_llm_configured=bool(st.anthropic_api_key),
        chatbot_max_per_hour=st.chatbot_max_per_hour,
        chatbot_interval_minutes=st.chatbot_interval_minutes,
        chatbot_last=await flags.get_flag("chatbot:last"),
        warm_comment_style=st.warm_comment_style,
        tiktok_actions=st.tiktok_actions,
        warm_keywords=[k.strip() for k in st.warm_keywords.split(",") if k.strip()],
    )


@router.post("/alerts/test")
async def alert_test() -> dict:
    if not alerts.configured():
        raise HTTPException(409, "Chưa đặt ALERT_WEBHOOK_URL trong .env.")
    ok = alerts.send("[seeding] Tin thử từ dashboard — cảnh báo đang hoạt động.")
    if not ok:
        raise HTTPException(502, "Webhook từ chối hoặc không trả lời. Xem log API.")
    return {"sent": True}
