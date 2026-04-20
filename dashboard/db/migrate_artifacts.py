"""One-time migration: filesystem artifacts → DB artifacts table.

Scans .ai-workflow/artifacts/task-{N}/ directories,
matches to BacklogItem by sequence_number,
creates Artifact records with text in content_text and binary as local_path.

Usage:
    python -m dashboard.db.migrate_artifacts [--dry-run]
"""
import asyncio
import json
import logging
import mimetypes
import re
import sys
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(ROOT))
load_dotenv(str(ROOT / ".env"))

from sqlalchemy import select, func
from dashboard.db.engine import async_session
from dashboard.db.models.artifact import Artifact
from dashboard.db.models.backlog import BacklogItem
from dashboard.db.models.project import Project

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger("migrate_artifacts")

ARTIFACTS_DIR = ROOT / ".ai-workflow" / "artifacts"

# Text extensions (content stored in DB)
TEXT_EXT = {
    ".md", ".txt", ".html", ".htm", ".json", ".css", ".js", ".ts",
    ".py", ".yaml", ".yml", ".toml", ".sh", ".sql", ".xml", ".csv",
}

# Map filename → pipeline stage
FILENAME_TO_STAGE = {
    "user-stories.md": "PM",
    "pm-review.md": "PM_REVIEW",
    "user-stories-reviewed.md": "PM_REVIEW",
    "spec.md": "BA",
    "ba-review.md": "BA_REVIEW",
    "spec-reviewed.md": "BA_REVIEW",
    "wireframe.html": "BA",
    "design-notes.md": "DESIGN",
    "changes.md": "DEV",
    "dev-review.md": "DEV_REVIEW",
    "test-result.md": "QA",
    "bug-report.md": "QA",
    "qa-review.md": "QA_REVIEW",
    "perf-review.md": "PERF",
}


def _guess_stage(filename: str, parent_dir: str) -> str:
    """Infer pipeline stage from filename or parent directory."""
    if filename in FILENAME_TO_STAGE:
        return FILENAME_TO_STAGE[filename]
    if parent_dir == "code-changes":
        return "DEV"
    if parent_dir == "screenshots":
        return "QA"
    if "design" in filename.lower():
        return "DESIGN"
    if "review" in filename.lower():
        return "DEV_REVIEW"
    return "DEV"


def _is_text(filename: str) -> bool:
    return Path(filename).suffix.lower() in TEXT_EXT


def _guess_mime(filename: str) -> str:
    mime, _ = mimetypes.guess_type(filename)
    return mime or "application/octet-stream"


async def migrate(dry_run: bool = False):
    if not ARTIFACTS_DIR.exists():
        logger.info("No artifacts directory found at %s", ARTIFACTS_DIR)
        return

    async with async_session() as db:
        # Find the project
        proj = (await db.execute(
            select(Project).where(Project.slug == "ai-workflow")
        )).scalar_one_or_none()

        if not proj:
            logger.error("Project 'ai-workflow' not found in DB")
            return

        # Check if artifacts already migrated
        existing_count = (await db.execute(
            select(func.count(Artifact.id)).where(Artifact.project_id == proj.id)
        )).scalar() or 0

        if existing_count > 0:
            logger.info("Already have %d artifacts in DB for ai-workflow, skipping", existing_count)
            return

        # Load backlog item mapping: sequence_number → BacklogItem
        bi_result = await db.execute(
            select(BacklogItem).where(BacklogItem.project_id == proj.id)
        )
        bi_map = {bi.sequence_number: bi for bi in bi_result.scalars().all()}
        logger.info("Found %d backlog items in DB", len(bi_map))

        created = 0
        skipped = 0

        for task_dir in sorted(ARTIFACTS_DIR.iterdir()):
            if not task_dir.is_dir():
                continue

            dir_name = task_dir.name  # "task-1", "task-15", "discovery"

            # Extract task number
            m = re.match(r"task-(\d+)", dir_name)
            if m:
                task_num = int(m.group(1))
                bi = bi_map.get(task_num)
                if not bi:
                    logger.warning("No BacklogItem for sequence_number=%d, skipping %s", task_num, dir_name)
                    skipped += 1
                    continue
                backlog_item_id = bi.id
            elif dir_name == "discovery":
                backlog_item_id = None
            else:
                logger.warning("Unknown artifact directory: %s, skipping", dir_name)
                skipped += 1
                continue

            # Walk all files in this task directory
            for f in sorted(task_dir.rglob("*")):
                if not f.is_file():
                    continue

                filename = f.name
                parent_dir = f.parent.name if f.parent != task_dir else ""
                stage = _guess_stage(filename, parent_dir)
                mime = _guess_mime(filename)
                size = f.stat().st_size

                # Special handling for code-changes/changes.json
                if parent_dir == "code-changes" and filename == "changes.json":
                    try:
                        meta = json.loads(f.read_text(encoding="utf-8"))
                    except Exception:
                        meta = {}
                    artifact = Artifact(
                        project_id=proj.id,
                        backlog_item_id=backlog_item_id,
                        stage=stage,
                        artifact_type="code_changes",
                        name="code-changes",
                        content_text=None,
                        s3_key=None,
                        local_path=str(f),
                        metadata_json=meta,
                        mime_type="application/json",
                        size_bytes=size,
                    )
                elif _is_text(filename):
                    try:
                        content = f.read_text(encoding="utf-8")
                    except Exception as e:
                        logger.warning("Cannot read %s: %s", f, e)
                        continue

                    artifact = Artifact(
                        project_id=proj.id,
                        backlog_item_id=backlog_item_id,
                        stage=stage,
                        artifact_type="text",
                        name=filename,
                        content_text=content,
                        s3_key=None,
                        local_path=None,
                        mime_type=mime,
                        size_bytes=size,
                    )
                else:
                    # Binary — store local_path reference
                    artifact = Artifact(
                        project_id=proj.id,
                        backlog_item_id=backlog_item_id,
                        stage=stage,
                        artifact_type="binary",
                        name=filename,
                        content_text=None,
                        s3_key=None,
                        local_path=str(f),
                        mime_type=mime,
                        size_bytes=size,
                    )

                if dry_run:
                    logger.info("[DRY] %s/%s → stage=%s type=%s size=%d",
                                dir_name, filename, stage, artifact.artifact_type, size)
                else:
                    db.add(artifact)

                created += 1

        if not dry_run:
            await db.commit()

        logger.info("%s %d artifacts (%d dirs skipped)",
                    "Would create" if dry_run else "Created", created, skipped)


def main():
    dry_run = "--dry-run" in sys.argv
    if dry_run:
        logger.info("=== DRY RUN MODE ===")
    asyncio.run(migrate(dry_run=dry_run))


if __name__ == "__main__":
    main()
