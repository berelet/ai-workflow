"""Sync task artifacts from filesystem to DB.

Usage:
    python -m dashboard.db.sync_artifacts <project-slug> <task-number> [--clean]

Called by orchestrator after each pipeline stage.
Without --clean: syncs files to DB but keeps originals (safe during active pipeline).
With --clean: also removes text files after successful sync (use after pipeline completes).
Idempotent: skips files that already have a matching DB record (by name + stage).
"""
import asyncio
import json
import logging
import mimetypes
import re
import shutil
import sys
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(ROOT))
load_dotenv(str(ROOT / ".env"))

from sqlalchemy import select
from dashboard.db.engine import async_session
from dashboard.db.models.artifact import Artifact
from dashboard.db.models.backlog import BacklogItem
from dashboard.db.models.project import Project
from dashboard.storage.s3 import s3 as s3_storage

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger("sync_artifacts")

TEXT_EXT = {
    ".md", ".txt", ".html", ".htm", ".json", ".css", ".js", ".ts",
    ".py", ".yaml", ".yml", ".toml", ".sh", ".sql", ".xml", ".csv",
}

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


def _resolve_artifacts_dir(project_slug: str) -> Path | None:
    """Find .ai-workflow dir for a project via pipeline-config.json."""
    cfg_path = ROOT / "projects" / project_slug / "pipeline-config.json"
    if cfg_path.exists():
        cfg = json.loads(cfg_path.read_text(encoding="utf-8"))
        if "project_dir" in cfg:
            return Path(cfg["project_dir"]) / ".ai-workflow"
    return ROOT / "projects" / project_slug


async def sync(project_slug: str, task_num: int, clean: bool = False):
    ai_dir = _resolve_artifacts_dir(project_slug)
    if not ai_dir:
        logger.error("Cannot resolve artifacts dir for %s", project_slug)
        return

    task_dir = ai_dir / "artifacts" / f"task-{task_num}"
    if not task_dir.exists():
        logger.info("No artifacts directory: %s", task_dir)
        return

    async with async_session() as db:
        proj = (await db.execute(
            select(Project).where(Project.slug == project_slug)
        )).scalar_one_or_none()
        if not proj:
            logger.error("Project '%s' not found in DB", project_slug)
            return

        bi = (await db.execute(
            select(BacklogItem).where(
                BacklogItem.project_id == proj.id,
                BacklogItem.sequence_number == task_num,
            )
        )).scalar_one_or_none()
        if not bi:
            logger.error("BacklogItem #%d not found for project '%s'", task_num, project_slug)
            return

        # Get existing artifact names to avoid duplicates
        existing = (await db.execute(
            select(Artifact.name, Artifact.stage).where(
                Artifact.backlog_item_id == bi.id,
            )
        )).all()
        existing_set = {(name, stage) for name, stage in existing}

        created = 0
        skipped = 0
        files_to_remove = []

        for f in sorted(task_dir.rglob("*")):
            if not f.is_file():
                continue

            filename = f.name
            parent_dir = f.parent.name if f.parent != task_dir else ""
            stage = _guess_stage(filename, parent_dir)
            mime = _guess_mime(filename)
            size = f.stat().st_size

            # Check for duplicate
            artifact_name = filename
            if parent_dir == "code-changes" and filename == "changes.json":
                artifact_name = "code-changes"

            if (artifact_name, stage) in existing_set:
                logger.info("SKIP (exists): %s [%s]", artifact_name, stage)
                skipped += 1
                files_to_remove.append(f)
                continue

            # Code-changes special case
            if parent_dir == "code-changes" and filename == "changes.json":
                try:
                    meta = json.loads(f.read_text(encoding="utf-8"))
                except Exception:
                    meta = {}
                artifact = Artifact(
                    project_id=proj.id,
                    backlog_item_id=bi.id,
                    stage=stage,
                    artifact_type="code_changes",
                    name="code-changes",
                    content_text=None,
                    s3_key=None,
                    local_path=None,
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
                    backlog_item_id=bi.id,
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
                # Binary — upload to S3
                s3_key = f"artifacts/{project_slug}/task-{task_num}/{parent_dir}/{filename}" if parent_dir else f"artifacts/{project_slug}/task-{task_num}/{filename}"
                try:
                    data = f.read_bytes()
                    await s3_storage.upload(s3_key, data, content_type=mime)
                    logger.info("S3 upload: %s (%d bytes)", s3_key, len(data))
                except Exception as e:
                    logger.warning("S3 upload failed for %s, falling back to local_path: %s", filename, e)
                    s3_key = None

                artifact = Artifact(
                    project_id=proj.id,
                    backlog_item_id=bi.id,
                    stage=stage,
                    artifact_type="binary",
                    name=filename,
                    content_text=None,
                    s3_key=s3_key,
                    local_path=str(f) if not s3_key else None,
                    mime_type=mime,
                    size_bytes=size,
                )
                # Binary uploaded to S3 — safe to remove local file
                if s3_key:
                    files_to_remove.append(f)

            db.add(artifact)
            created += 1
            # Text artifacts go to DB → safe to remove file
            if artifact.artifact_type in ("text", "code_changes"):
                files_to_remove.append(f)

        if created:
            await db.commit()

        # Remove synced files only if --clean flag is set
        removed = 0
        if clean:
            for f in files_to_remove:
                try:
                    f.unlink()
                    removed += 1
                except Exception as e:
                    logger.warning("Cannot remove %s: %s", f, e)

            # Remove empty directories
            for d in sorted(task_dir.rglob("*"), reverse=True):
                if d.is_dir() and not any(d.iterdir()):
                    d.rmdir()
            if task_dir.exists() and not any(task_dir.iterdir()):
                task_dir.rmdir()

        logger.info("Done: %d created, %d skipped%s", created, skipped,
                     f", {removed} files removed" if clean else " (files kept)")


def main():
    if len(sys.argv) < 3:
        print("Usage: python -m dashboard.db.sync_artifacts <project-slug> <task-number> [--clean]")
        sys.exit(1)
    project_slug = sys.argv[1]
    task_num = int(sys.argv[2])
    clean = "--clean" in sys.argv
    asyncio.run(sync(project_slug, task_num, clean=clean))


if __name__ == "__main__":
    main()
