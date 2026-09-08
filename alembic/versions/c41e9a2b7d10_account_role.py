"""account role: channel | booster

Revision ID: c41e9a2b7d10
Revises: 9279fd297a14
Create Date: 2026-09-08 16:20:00

Hai loai tai khoan: XAY KENH (dang bai, nuoi huong ra ngoai, duoc nguoi khac tuong tac)
va TUONG TAC CHEO (chi tha tim / follow / binh luan / dang lai vao bai cua tai khoan xay
kenh; khong dang bai; khong can proxy). Tat ca tai khoan hien co la xay kenh.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "c41e9a2b7d10"
down_revision: str | None = "9279fd297a14"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "accounts",
        sa.Column(
            "role",
            sa.Enum("CHANNEL", "BOOSTER", name="accountrole", native_enum=False),
            nullable=False,
            server_default="CHANNEL",
        ),
    )
    op.create_index("ix_accounts_role", "accounts", ["role"])


def downgrade() -> None:
    op.drop_index("ix_accounts_role", table_name="accounts")
    op.drop_column("accounts", "role")
