"""Backfill membership for superadmins on projects they created.

For each superadmin user, insert a membership (role=owner) for every project
where the superadmin is the creator (created_by) but has no existing membership.
This ensures superadmins have explicit membership after the superadmin bypass
was removed from RequireProjectRole.

Revision ID: 010
Revises: 009
"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "010"
down_revision = "009"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Insert owner membership for each superadmin in projects they created,
    # where no membership exists yet.
    op.execute(
        """
        INSERT INTO project_memberships (id, user_id, project_id, role, created_at)
        SELECT gen_random_uuid(), u.id, p.id, 'owner', NOW()
        FROM users u
        JOIN projects p ON p.created_by = u.id
        WHERE u.is_superadmin = true
          AND NOT EXISTS (
            SELECT 1 FROM project_memberships pm
            WHERE pm.user_id = u.id AND pm.project_id = p.id
          )
        """
    )


def downgrade() -> None:
    # We cannot reliably identify which memberships were inserted by this
    # migration vs. manually created, so downgrade is a no-op.
    # If needed, the admin can manually remove extra memberships.
    pass
