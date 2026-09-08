"""Workspace va persona mac dinh.

Bang `accounts` doi moi tai khoan phai thuoc mot persona, va persona thuoc mot
workspace. Giao dien moi khong bat nguoi van hanh tao hai thu do truoc khi dan tai
khoan vao - chung duoc tao ngam mot lan va dung cho tat ca. Khi nao can tach doi tai
khoan theo khach hang thi them lai o giao dien, khong phai bay gio.
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from seeding.domain.models import Persona, Workspace

DEFAULT_NAME = "Mặc định"


async def ensure_defaults(session: AsyncSession) -> tuple[Workspace, Persona]:
    """Tra ve (workspace, persona) mac dinh, tao neu chua co. Idempotent."""
    workspace = (
        (await session.execute(select(Workspace).order_by(Workspace.created_at))).scalars().first()
    )
    if workspace is None:
        workspace = Workspace(name=DEFAULT_NAME)
        session.add(workspace)
        await session.flush()

    persona = (
        (
            await session.execute(
                select(Persona)
                .where(Persona.workspace_id == workspace.id)
                .order_by(Persona.created_at)
            )
        )
        .scalars()
        .first()
    )
    if persona is None:
        persona = Persona(workspace_id=workspace.id, name=DEFAULT_NAME)
        session.add(persona)
        await session.flush()

    return workspace, persona
