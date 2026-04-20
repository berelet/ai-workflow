"""backfill instance_project_bindings from existing projects.repo_path

Revision ID: 013
Revises: 012
Create Date: 2026-04-10

For each project with a non-null repo_path, create a binding row pointing
to the SOLE existing dashboard_instance (typically the local dev instance).
The repo_path column is kept as a fallback for not-yet-migrated rows.

If multiple dashboard instances exist at migration time, the binding is
created for the OLDEST one (first_seen_at ASC). New instances coming online
will have empty bindings until they create projects themselves — that's the
intended multi-instance behavior.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "013"
down_revision: Union[str, None] = "012"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()

    # Find oldest dashboard instance (the existing local dev)
    instance_row = bind.execute(sa.text(
        "SELECT id FROM dashboard_instances ORDER BY first_seen_at ASC LIMIT 1"
    )).fetchone()
    if not instance_row:
        # No dashboard instance yet — nothing to backfill
        return

    instance_id = instance_row[0]

    # For each project with a non-null repo_path, insert binding (skip if exists)
    bind.execute(sa.text("""
        INSERT INTO instance_project_bindings (id, instance_id, project_id, local_path, created_at)
        SELECT
            gen_random_uuid(),
            :instance_id,
            p.id,
            p.repo_path,
            now()
        FROM projects p
        WHERE p.repo_path IS NOT NULL
          AND p.repo_path <> ''
          AND NOT EXISTS (
              SELECT 1 FROM instance_project_bindings b
              WHERE b.instance_id = :instance_id AND b.project_id = p.id
          )
    """), {"instance_id": instance_id})


def downgrade() -> None:
    # Best-effort: delete bindings whose local_path equals the project's repo_path
    # for the oldest instance. Safe because the data is duplicated in repo_path column.
    bind = op.get_bind()
    instance_row = bind.execute(sa.text(
        "SELECT id FROM dashboard_instances ORDER BY first_seen_at ASC LIMIT 1"
    )).fetchone()
    if not instance_row:
        return
    instance_id = instance_row[0]
    bind.execute(sa.text("""
        DELETE FROM instance_project_bindings b
        USING projects p
        WHERE b.project_id = p.id
          AND b.instance_id = :instance_id
          AND b.local_path = p.repo_path
    """), {"instance_id": instance_id})
