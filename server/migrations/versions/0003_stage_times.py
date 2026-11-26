"""Stage times and the S4 result on episodes (spec §5.1, §2.4): display and replay of a judgment. Server DB only.

Revision ID: 0003
Revises: 0002
Create Date: 2026-11-26
"""
from alembic import context, op

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def _kb_target() -> bool:
    return context.get_x_argument(as_dictionary=True).get("db") == "kb"


def upgrade() -> None:
    if _kb_target():
        return
    op.execute("ALTER TABLE episodes ADD COLUMN stage_times jsonb NOT NULL DEFAULT '{}'")
    op.execute("ALTER TABLE episodes ADD COLUMN s4 jsonb")


def downgrade() -> None:
    if _kb_target():
        return
    op.execute("ALTER TABLE episodes DROP COLUMN s4")
    op.execute("ALTER TABLE episodes DROP COLUMN stage_times")
