"""Profile: mo cua so trinh duyet that de nguoi van hanh nhin tan mat."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from seeding.api.deps import get_session
from seeding.api.schemas import OpenProfileIn, OpenProfileOut
from seeding.domain.models import Account, Profile
from seeding.ops import desktop

router = APIRouter(prefix="/profiles", tags=["profiles"])


@router.post("/{profile_id}/open", response_model=OpenProfileOut)
async def open_profile_window(
    profile_id: uuid.UUID,
    body: OpenProfileIn | None = None,
    s: AsyncSession = Depends(get_session),
) -> OpenProfileOut:
    """Mo Camoufox voi dung fingerprint, proxy, cookie cua profile - tren may dang chay API.

    KHONG mo khi chua co proxy. Mo tay khong phai ngoai le: cua so van di ra bang IP
    nha ban, va nen tang ghi lai dieu do y het nhu khi worker chay.
    """
    profile = await s.get(Profile, profile_id)
    if profile is None:
        raise HTTPException(404, "Không có profile này")
    account = await s.get(Account, profile.account_id)
    if account is None:
        raise HTTPException(409, "Profile này không gắn với tài khoản nào")
    if profile.proxy_id is None:
        raise HTTPException(409, "Chưa có proxy — mở ra là đi bằng IP thật của bạn.")

    url = body.url if body else None
    pid = desktop.spawn(profile.id, url)
    note = (
        "Đang mở. Đóng cửa sổ là cookie được lưu lại."
        if profile.cookies_enc
        else "Đang mở, nhưng profile này chưa đăng nhập bao giờ — sẽ thấy màn hình đăng nhập."
    )
    return OpenProfileOut(
        profile_id=profile.id, handle=account.handle, pid=pid, url=url, detail=note
    )
