"""Khung gio vang: nen tang -> thu trong tuan -> cac moc gio (gio dia phuong)."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from seeding.api.deps import get_session
from seeding.api.schemas import DeleteOut, SlotIn, SlotMeta, SlotOut
from seeding.config import get_settings
from seeding.domain.models import Platform, PostSlot

router = APIRouter(prefix="/slots", tags=["slots"])

WEEKDAYS_VI = ["Thứ Hai", "Thứ Ba", "Thứ Tư", "Thứ Năm", "Thứ Sáu", "Thứ Bảy", "Chủ Nhật"]


@router.get("", response_model=list[SlotOut])
async def list_slots(s: AsyncSession = Depends(get_session)) -> list[SlotOut]:
    rows = (
        await s.execute(
            select(PostSlot).order_by(
                PostSlot.platform, PostSlot.weekday, PostSlot.hour, PostSlot.minute
            )
        )
    ).scalars()
    return [SlotOut.model_validate(r) for r in rows]


@router.get("/meta", response_model=SlotMeta)
async def meta() -> SlotMeta:
    return SlotMeta(timezone=get_settings().schedule_timezone, weekdays=WEEKDAYS_VI)


@router.put("", response_model=list[SlotOut])
async def set_slots(body: SlotIn, s: AsyncSession = Depends(get_session)) -> list[SlotOut]:
    """Thay toan bo moc cua (nen tang, cac thu duoc nhac). Thu khong nhac thi giu nguyen."""
    if not body.weekdays:
        raise HTTPException(422, "Chọn ít nhất một thứ.")
    times = body.all_times()
    if not times:
        raise HTTPException(422, "Cần ít nhất một mốc giờ.")
    for t in times:
        if not (0 <= t.hour <= 23 and 0 <= t.minute <= 59):
            raise HTTPException(422, f"Giờ {t.hour}:{t.minute:02d} không hợp lệ.")

    await s.execute(
        delete(PostSlot).where(
            PostSlot.platform == body.platform, PostSlot.weekday.in_(body.weekdays)
        )
    )
    out: list[PostSlot] = []
    seen: set[tuple[int, int, int]] = set()
    for day in body.weekdays:
        for t in times:
            key = (day, t.hour, t.minute)
            if key in seen:
                continue
            seen.add(key)
            slot = PostSlot(platform=body.platform, weekday=day, hour=t.hour, minute=t.minute)
            s.add(slot)
            out.append(slot)
    await s.commit()
    return [
        SlotOut.model_validate(r) for r in sorted(out, key=lambda r: (r.weekday, r.hour, r.minute))
    ]


@router.delete("/{platform}", response_model=DeleteOut)
async def clear_platform(platform: Platform, s: AsyncSession = Depends(get_session)) -> DeleteOut:
    result = await s.execute(delete(PostSlot).where(PostSlot.platform == platform))
    await s.commit()
    return DeleteOut(deleted=True, detail=f"Đã xoá {result.rowcount} mốc của {platform.value}")
