"""Kiem phien TikTok bang HTTP qua proxy cua acc: ~2 giay, khong mo trinh duyet.

passport/web/account/info tra user_id khi phien song, {"name": "session_expired"} khi
sessionid da chet. Do 08/09/2026: 13/14 acc song; acc P03 chet - va chinh acc do da
"tha tim thanh cong" tren giao dien (nut chuyen sang da thich) ma TikTok khong luu.
Nen kiem phien phai di TRUOC moi hanh dong trinh duyet, va quet suc khoe dung duong
nay thay vi mo trinh duyet 400MB.
"""

from __future__ import annotations

import httpx

from seeding.domain.models import Platform, Profile
from seeding.platforms.base import register_health
from seeding.platforms.tiktok.web import TikTokWeb


async def account_state(profile: Profile) -> tuple[bool, str]:
    """(song, chi tiet). Nem httpx.HTTPError khi khong toi duoc TikTok (proxy/mang)."""
    async with TikTokWeb(profile, allow_direct=True) as tt:
        body = await tt.account_info()
    data = body.get("data") or {}
    if data.get("user_id"):
        return True, f"user_id={data['user_id']}"
    why = data.get("name") or data.get("description") or body.get("message") or "no user_id"
    return False, f"phiên chết: {why}"


async def check(profile: Profile) -> tuple[bool, str]:
    """Dau kiem cho health_sweep. Mang hong cung tinh la mot lan hong (nguong 2 lan
    truoc khi goi nguoi), vi acc nam sau proxy khong toi duoc TikTok thi cung khong
    nuoi duoc."""
    try:
        return await account_state(profile)
    except (httpx.HTTPError, ValueError) as exc:
        return False, f"không tới được TikTok qua proxy: {type(exc).__name__}: {exc}"


async def session_dead(profile: Profile) -> str | None:
    """Ly do neu phien CHAC CHAN chet; None khi song hoac khong kiem duoc (mang hong thi
    de trinh duyet tu thu, checkpoint detector se bat)."""
    try:
        alive, detail = await account_state(profile)
    except (httpx.HTTPError, ValueError):
        return None
    return None if alive else detail


register_health(Platform.TIKTOK, check)
