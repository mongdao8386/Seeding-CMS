"""Chi muc cho nghin acc: lich nuoi theo acc, su kien phien theo profile.

Revision ID: d5e1a7c3b9f2
Revises: c41e9a2b7d10
"""

from __future__ import annotations

from alembic import op

revision: str = "d5e1a7c3b9f2"
down_revision: str | None = "c41e9a2b7d10"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_activity_account_time "
        "ON activity_jobs (account_id, scheduled_at)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_session_events_profile_time "
        "ON session_events (profile_id, created_at)"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_session_events_profile_time")
    op.execute("DROP INDEX IF EXISTS ix_activity_account_time")
