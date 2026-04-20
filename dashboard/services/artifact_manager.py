"""Artifact manager for pipeline stages.

Collects artifacts from agent completion callbacks,
provides input artifacts for next stages,
stores via StorageManager.
"""
import logging
import uuid
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from dashboard.db.models.artifact import Artifact
from dashboard.db.models.pipeline import PipelineStageLog
from dashboard.storage.manager import storage, StorageError

logger = logging.getLogger("services.artifact_manager")

# Expected output artifacts per agent type
EXPECTED_ARTIFACTS = {
    "PM": ["user-stories.md"],
    "PM_REVIEW": ["user-stories-reviewed.md", "pm-review.md"],
    "BA": ["spec.md", "wireframe.html"],
    "BA_REVIEW": ["spec-reviewed.md", "ba-review.md"],
    "DESIGN": ["design-notes.md"],
    "DEV": ["changes.md"],
    "DEV_REVIEW": ["dev-review.md"],
    "QA": ["test-result.md"],  # or bug-report.md on FAIL
    "QA_REVIEW": ["qa-review.md"],
    "PERF": ["perf-review.md"],
    "COMMIT": [],
}

# Which artifacts from previous stages a given stage needs as input
INPUT_REQUIREMENTS = {
    "PM": [],
    "PM_REVIEW": ["user-stories.md"],
    "BA": ["user-stories-reviewed.md"],
    "BA_REVIEW": ["spec.md"],
    "DESIGN": ["spec-reviewed.md", "wireframe.html"],
    "DEV": ["spec-reviewed.md", "wireframe.html", "design-notes.md"],
    "DEV_REVIEW": ["changes.md"],
    "QA": ["spec-reviewed.md", "changes.md"],
    "QA_REVIEW": ["test-result.md"],
    "PERF": ["changes.md", "dev-review.md"],
    "COMMIT": [],
}


class ArtifactManager:

    async def collect_artifacts(
        self,
        db: AsyncSession,
        project_id: uuid.UUID,
        project_visibility: str,
        project_prefix: str,
        project_dir: str | None,
        backlog_item_id: uuid.UUID,
        task_id_display: str,
        stage: str,
        reported_artifacts: list[dict],
    ) -> list[Artifact]:
        """Process artifacts reported by agent callback. Store and create DB records.

        Args:
            reported_artifacts: [{filename, path}] from the agent's curl callback
        """
        created = []
        for art_info in reported_artifacts:
            filename = art_info.get("filename", "")
            file_path = art_info.get("path", "")

            if not filename:
                logger.warning("Artifact with no filename, skipping")
                continue

            # Read file content from the path the agent wrote to
            try:
                p = Path(file_path).resolve()
                # Security: only allow reading from project directory or /tmp
                if project_dir:
                    allowed_base = Path(project_dir).resolve()
                    if not (str(p).startswith(str(allowed_base)) or str(p).startswith("/tmp")):
                        logger.warning("Artifact path outside project dir, skipping: %s", file_path)
                        continue
                if not p.exists():
                    logger.warning("Artifact file not found: %s", file_path)
                    continue
                if p.stat().st_size > 50 * 1024 * 1024:  # 50MB limit
                    logger.warning("Artifact too large, skipping: %s (%d bytes)", filename, p.stat().st_size)
                    continue
                data = p.read_bytes()
            except Exception as e:
                logger.error("Cannot read artifact %s: %s", file_path, e)
                continue

            # Store via storage manager
            try:
                store_info = await storage.save_artifact(
                    visibility=project_visibility,
                    project_prefix=project_prefix,
                    project_dir=project_dir,
                    task_id_display=task_id_display,
                    stage=stage,
                    filename=filename,
                    data=data,
                )
            except StorageError as e:
                logger.error("Storage error for artifact %s: %s", filename, e)
                continue

            artifact = Artifact(
                project_id=project_id,
                backlog_item_id=backlog_item_id,
                stage=stage,
                name=store_info.get("name", filename),
                artifact_type=store_info["artifact_type"],
                content_text=store_info.get("content_text"),
                s3_key=store_info.get("s3_key"),
                local_path=store_info.get("local_path"),
                mime_type=store_info.get("mime_type"),
                size_bytes=store_info.get("size_bytes"),
            )
            db.add(artifact)
            created.append(artifact)

        if created:
            await db.commit()
            logger.info("Stored %d artifacts for %s/%s", len(created), task_id_display, stage)

        return created

    async def get_input_for_stage(
        self,
        db: AsyncSession,
        pipeline_run_id: uuid.UUID,
        stage: str,
    ) -> list[dict]:
        """Get artifacts from previous stages that this stage needs as input.

        Returns [{filename, content}] for text artifacts.
        """
        stage_upper = stage.upper()
        required_names = INPUT_REQUIREMENTS.get(stage_upper, [])
        if not required_names:
            return []

        # Also add bug-report.md if this is a DEV re-run (returned from QA)
        if stage_upper == "DEV":
            required_names = list(required_names) + ["bug-report.md", "perf-review.md"]

        # Find artifacts from this pipeline run's backlog item
        # We need to get backlog_item_id from the pipeline run
        from dashboard.db.models.pipeline import PipelineRun
        run = await db.get(PipelineRun, pipeline_run_id)
        if not run:
            return []

        result = await db.execute(
            select(Artifact).where(
                Artifact.backlog_item_id == run.backlog_item_id,
                Artifact.name.in_(required_names),
            ).order_by(Artifact.created_at.desc())
        )
        artifacts = result.scalars().all()

        # Deduplicate by name (latest version wins)
        seen = set()
        inputs = []
        for art in artifacts:
            if art.name in seen:
                continue
            seen.add(art.name)

            content = ""
            if art.content_text:
                content = art.content_text
            elif art.local_path:
                try:
                    content = Path(art.local_path).read_text(encoding="utf-8")
                except Exception:
                    continue
            elif art.s3_key:
                try:
                    from dashboard.storage.manager import _get_s3
                    data = await _get_s3().download(art.s3_key)
                    content = data.decode("utf-8", errors="replace")
                except Exception:
                    continue

            if content:
                inputs.append({"filename": art.name, "content": content})

        return inputs

    async def get_artifacts_for_task(
        self,
        db: AsyncSession,
        backlog_item_id: uuid.UUID,
    ) -> list[dict]:
        """Get all artifacts for a task (for UI display)."""
        result = await db.execute(
            select(Artifact).where(
                Artifact.backlog_item_id == backlog_item_id,
            ).order_by(Artifact.stage, Artifact.created_at)
        )
        return [
            {
                "id": str(a.id),
                "stage": a.stage,
                "name": a.name,
                "artifact_type": a.artifact_type,
                "mime_type": a.mime_type,
                "size_bytes": a.size_bytes,
                "created_at": a.created_at.isoformat() if a.created_at else None,
            }
            for a in result.scalars().all()
        ]

    async def count_artifacts(self, db: AsyncSession, backlog_item_id: uuid.UUID) -> int:
        """Count artifacts for a task (for badge display)."""
        from sqlalchemy import func
        result = await db.execute(
            select(func.count(Artifact.id)).where(Artifact.backlog_item_id == backlog_item_id)
        )
        return result.scalar() or 0


# Singleton
artifact_manager = ArtifactManager()
