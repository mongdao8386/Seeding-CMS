"""Phu thuoc dung chung cho cac route: phien DB, phan trang."""

from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from seeding.db import get_session

__all__ = ["DEFAULT_PAGE", "MAX_PAGE", "get_session", "paginate"]

DEFAULT_PAGE = 50
MAX_PAGE = 500


async def paginate(s: AsyncSession, stmt, limit: int, offset: int) -> tuple[list, int]:
    """Mot trang, kem tong so ban ghi KHOP DIEU KIEN LOC.

    Dem bang mot cau rieng tren cung WHERE. Dem trong Python sau LIMIT thi con so luon
    bang so dong cua trang - dung cai khong ai can.
    """
    total = int(
        (
            await s.execute(select(func.count()).select_from(stmt.order_by(None).subquery()))
        ).scalar_one()
    )
    rows = (await s.execute(stmt.limit(limit).offset(offset))).unique().all()
    return rows, total
