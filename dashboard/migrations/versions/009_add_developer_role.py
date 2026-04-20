"""Add developer role to project memberships.

No schema change needed — the role column is already String(20),
which accommodates 'developer'. This migration exists as a marker
and provides a safe downgrade path.

Revision ID: 009
Revises: 008
"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "009"
down_revision = "008"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # No schema change needed.
    # 'developer' fits within the existing String(20) role column.
    # The new role value is enforced at the application level.
    pass


def downgrade() -> None:
    # Convert any 'developer' memberships back to 'viewer'
    op.execute(
        "UPDATE project_memberships SET role = 'viewer' WHERE role = 'developer'"
    )
