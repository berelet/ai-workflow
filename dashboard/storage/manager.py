import logging
import mimetypes
import os
import re
import uuid
from pathlib import Path

logger = logging.getLogger("storage.manager")

STORAGE_BACKEND = os.getenv("STORAGE_BACKEND", "s3")  # "s3" or "local"

def _get_s3():
    from dashboard.storage.s3 import s3
    return s3

# Binary types that go to S3 (or local filesystem)
BINARY_EXTENSIONS = {
    ".png", ".jpg", ".jpeg", ".gif", ".webp", ".svg", ".ico",
    ".webm", ".mp3", ".wav", ".ogg", ".mp4",
    ".pdf", ".zip", ".gz", ".tar", ".woff", ".woff2", ".ttf",
}

# Text types that go to DB (content_text column)
TEXT_EXTENSIONS = {
    ".md", ".txt", ".html", ".htm", ".json", ".css", ".js", ".ts", ".tsx", ".jsx",
    ".py", ".yaml", ".yml", ".toml", ".sh", ".sql", ".xml", ".csv", ".env",
    ".rs", ".go", ".java", ".rb", ".php", ".c", ".cpp", ".h",
}


class StorageError(Exception):
    """Raised when a storage operation fails."""


def _safe_name(filename: str) -> str:
    """Extract safe filename: strip path components, sanitize characters."""
    name = Path(filename).name  # strips all directory components
    name = re.sub(r'[^\w\-.]', '_', name)  # keep only word chars, hyphens, dots
    return name or "unnamed"


def _is_binary(filename: str) -> bool:
    ext = Path(filename).suffix.lower()
    if ext in BINARY_EXTENSIONS:
        return True
    if ext in TEXT_EXTENSIONS:
        return False
    return True


def _guess_mime(filename: str) -> str:
    mime, _ = mimetypes.guess_type(filename)
    return mime or "application/octet-stream"


def _safe_s3_key(prefix: str, *parts: str) -> str:
    """Build sanitized S3 key: projects/{prefix}/{parts}. Strips '..' from components."""
    clean = [p.replace("..", "").strip("/") for p in (prefix, *parts) if p]
    return "projects/" + "/".join(clean)


def _safe_local_path(project_dir: str, *parts: str) -> Path:
    """Build local path with containment check. Raises StorageError on traversal."""
    if not project_dir:
        raise StorageError("project_dir is required for local storage")
    base = Path(project_dir).resolve() / ".ai-workflow"
    p = base / Path(*parts)
    resolved = p.resolve()
    # Containment check: resolved path must be under base
    if not str(resolved).startswith(str(base)):
        raise StorageError(f"Path traversal detected: {parts}")
    p.parent.mkdir(parents=True, exist_ok=True)
    return p


class StorageManager:
    """Routes storage operations to S3 (with local fallback if S3 not configured).

    Text artifacts → DB content_text column.
    Binary artifacts/images → S3 (preferred) or local filesystem (fallback).
    """

    # --- Backlog images ---

    async def save_backlog_image(
        self,
        visibility: str,
        project_prefix: str,
        project_dir: str | None,
        item_seq: int,
        filename: str,
        data: bytes,
    ) -> dict:
        """Save a backlog item image. Returns storage info dict for BacklogItemImage row."""
        sanitized = _safe_name(filename)
        safe_fname = f"{uuid.uuid4().hex[:8]}_{sanitized}"
        mime = _guess_mime(sanitized)

        if STORAGE_BACKEND == "s3":
            try:
                key = _safe_s3_key(project_prefix, "backlog-images", str(item_seq), safe_fname)
                await _get_s3().upload(key, data, content_type=mime)
                return {
                    "storage_type": "s3",
                    "s3_key": key,
                    "local_path": None,
                    "original_filename": filename,
                    "mime_type": mime,
                    "size_bytes": len(data),
                }
            except Exception:
                logger.warning("S3 upload failed, falling back to local")

        # Local storage (primary when STORAGE_BACKEND=local, fallback when S3 fails)
        if not project_dir:
            raise StorageError("No project_dir for local storage")
        path = _safe_local_path(project_dir, "backlog-images", str(item_seq), safe_fname)
        path.write_bytes(data)
        logger.debug("Local backlog image: %s", path)
        return {
            "storage_type": "local",
            "local_path": str(path),
            "s3_key": None,
            "original_filename": filename,
            "mime_type": mime,
            "size_bytes": len(data),
        }

    async def get_backlog_image(self, storage_type: str, s3_key: str | None, local_path: str | None) -> tuple[bytes, str]:
        """Retrieve backlog image data. Returns (bytes, mime_type)."""
        try:
            if storage_type == "local" and local_path:
                p = Path(local_path)
                return p.read_bytes(), _guess_mime(p.name)
            elif s3_key:
                data = await _get_s3().download(s3_key)
                return data, _guess_mime(s3_key.split("/")[-1])
        except Exception as e:
            raise StorageError(f"Failed to get image: {e}") from e
        raise StorageError("Image not found: no storage path")

    async def delete_backlog_image(self, storage_type: str, s3_key: str | None, local_path: str | None) -> None:
        """Delete a backlog image."""
        if storage_type == "local" and local_path:
            p = Path(local_path)
            if p.exists():
                p.unlink()
        elif s3_key:
            await _get_s3().delete(s3_key)

    # --- Artifacts ---

    async def save_artifact(
        self,
        visibility: str,
        project_prefix: str,
        project_dir: str | None,
        task_id_display: str,
        stage: str,
        filename: str,
        data: bytes | str,
    ) -> dict:
        """Save an artifact. Text → DB content_text, binary → S3 (local fallback)."""
        sanitized = _safe_name(filename)
        is_binary = _is_binary(sanitized)
        mime = _guess_mime(sanitized)

        try:
            if not is_binary:
                text_content = data if isinstance(data, str) else data.decode("utf-8")
                return {
                    "artifact_type": "text",
                    "name": sanitized,
                    "content_text": text_content,
                    "s3_key": None,
                    "local_path": None,
                    "mime_type": mime,
                    "size_bytes": len(text_content.encode("utf-8")),
                }

            # Binary → S3 or local
            raw = data.encode("utf-8") if isinstance(data, str) else data
            if STORAGE_BACKEND == "s3":
                try:
                    key = _safe_s3_key(project_prefix, "artifacts", task_id_display, stage, sanitized)
                    await _get_s3().upload(key, raw, content_type=mime)
                    return {
                        "artifact_type": "binary",
                        "name": sanitized,
                        "content_text": None,
                        "s3_key": key,
                        "local_path": None,
                        "mime_type": mime,
                        "size_bytes": len(raw),
                    }
                except Exception:
                    logger.warning("S3 upload failed, falling back to local")

            if not project_dir:
                raise StorageError("No project_dir for local storage")
            path = _safe_local_path(project_dir, "artifacts", task_id_display, stage, sanitized)
            path.write_bytes(raw)
            return {
                "artifact_type": "binary",
                "name": sanitized,
                "content_text": None,
                "s3_key": None,
                "local_path": str(path),
                "mime_type": mime,
                "size_bytes": len(raw),
            }
        except StorageError:
            raise
        except Exception as e:
            raise StorageError(f"Failed to save artifact '{sanitized}': {e}") from e

    async def get_artifact(
        self,
        artifact_type: str,
        content_text: str | None,
        s3_key: str | None,
        local_path: str | None,
        mime_type: str | None = None,
    ) -> tuple[bytes | str, str]:
        """Retrieve artifact content. Returns (data, mime_type).
        Text artifacts return str, binary return bytes."""
        try:
            if content_text is not None:
                return content_text, mime_type or "text/plain"
            if local_path:
                p = Path(local_path)
                m = mime_type or _guess_mime(p.name)
                if _is_binary(p.name):
                    return p.read_bytes(), m
                return p.read_text(encoding="utf-8"), m
            if s3_key:
                data = await _get_s3().download(s3_key)
                return data, mime_type or _guess_mime(s3_key.split("/")[-1])
        except Exception as e:
            raise StorageError(f"Failed to get artifact: {e}") from e
        raise StorageError("Artifact not found: no storage path")

    async def delete_artifact(
        self,
        artifact_type: str,
        s3_key: str | None,
        local_path: str | None,
    ) -> None:
        """Delete an artifact's stored data."""
        if local_path:
            p = Path(local_path)
            if p.exists():
                p.unlink()
        if s3_key:
            await _get_s3().delete(s3_key)

    # --- Recordings (transcriber) ---

    async def save_recording(
        self,
        visibility: str,
        project_prefix: str,
        project_dir: str | None,
        filename: str,
        data: bytes,
    ) -> dict:
        """Save an audio recording. Always binary."""
        sanitized = _safe_name(filename)
        safe_fname = f"{uuid.uuid4().hex[:8]}_{sanitized}"
        mime = _guess_mime(sanitized)

        if STORAGE_BACKEND == "s3":
            try:
                key = _safe_s3_key(project_prefix, "recordings", safe_fname)
                await _get_s3().upload(key, data, content_type=mime)
                return {"storage_type": "s3", "s3_key": key, "local_path": None}
            except Exception:
                logger.warning("S3 upload failed, falling back to local")

        if not project_dir:
            raise StorageError("No project_dir for local storage")
        path = _safe_local_path(project_dir, "recordings", safe_fname)
        path.write_bytes(data)
        return {"storage_type": "local", "local_path": str(path), "s3_key": None}

    async def get_recording(self, storage_type: str, s3_key: str | None, local_path: str | None) -> tuple[bytes, str]:
        """Retrieve recording data. Returns (bytes, mime_type)."""
        try:
            if storage_type == "local" and local_path:
                p = Path(local_path)
                return p.read_bytes(), _guess_mime(p.name)
            elif s3_key:
                data = await _get_s3().download(s3_key)
                return data, _guess_mime(s3_key.split("/")[-1])
        except Exception as e:
            raise StorageError(f"Failed to get recording: {e}") from e
        raise StorageError("Recording not found: no storage path")

    async def delete_recording(self, storage_type: str, s3_key: str | None, local_path: str | None) -> None:
        """Delete a recording."""
        if storage_type == "local" and local_path:
            p = Path(local_path)
            if p.exists():
                p.unlink()
        elif s3_key:
            await _get_s3().delete(s3_key)


# Singleton instance
storage = StorageManager()
