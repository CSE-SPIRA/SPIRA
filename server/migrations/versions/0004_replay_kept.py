"""Episodes kept for the demo replay (spec §12.5): survive a demo home reset in the household's replay archive.

Revision ID: 0004
Revises: 0003
Create Date: 2026-11-26
"""
from alembic import context, op

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None


def _kb_target() -> bool:
    return context.get_x_argument(as_dictionary=True).get("db") == "kb"


def upgrade() -> None:
    if _kb_target():
        return
    op.execute("ALTER TABLE episodes ADD COLUMN replay_kept boolean NOT NULL DEFAULT false")


def downgrade() -> None:
    if _kb_target():
        return
    op.execute("ALTER TABLE episodes DROP COLUMN replay_kept")
