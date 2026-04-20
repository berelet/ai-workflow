"""
Structured JSON logging for pipeline telemetry.

Produces one JSON object per line with stable field names.
Sanitizes user input to prevent log injection (CR/LF stripping).
Timestamps in UTC ISO-8601 (RFC3339).
"""

import json
import logging
import re
from datetime import datetime, timezone
from pathlib import Path

_SANITIZE_RE = re.compile(r"[\r\n\x00-\x08\x0b\x0c\x0e-\x1f]")


def sanitize(value: str) -> str:
    """Strip control characters (CR, LF, etc.) to prevent log injection."""
    return _SANITIZE_RE.sub("", value) if isinstance(value, str) else str(value)


class JSONFormatter(logging.Formatter):
    """Emit each log record as a single JSON line."""

    def format(self, record: logging.LogRecord) -> str:
        entry = {
            "timestamp": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ"),
            "level": record.levelname,
            "event": sanitize(getattr(record, "event", record.getMessage())),
            "session_id": sanitize(getattr(record, "session_id", "")),
            "project": sanitize(getattr(record, "project", "")),
        }

        # Merge extra data fields if provided
        data = getattr(record, "data", None)
        if data and isinstance(data, dict):
            entry["data"] = {k: sanitize(v) if isinstance(v, str) else v for k, v in data.items()}

        return json.dumps(entry, ensure_ascii=False)


def create_pipeline_logger(log_path: Path | None = None) -> logging.Logger:
    """Create and configure the pipeline telemetry logger."""
    if log_path is None:
        log_path = Path(__file__).parent / "pipeline.log"

    logger = logging.getLogger("pipeline")
    logger.setLevel(logging.DEBUG)

    # Avoid duplicate handlers on reload
    if not logger.handlers:
        fh = logging.FileHandler(log_path, encoding="utf-8")
        fh.setFormatter(JSONFormatter())
        logger.addHandler(fh)

    return logger


def tel_log(
    logger: logging.Logger,
    event: str,
    session_id: str = "",
    project: str = "",
    level: str = "info",
    **data,
):
    """Emit a structured telemetry event."""
    extra = {
        "event": event,
        "session_id": session_id,
        "project": project,
    }
    if data:
        extra["data"] = data

    log_fn = getattr(logger, level, logger.info)
    log_fn(event, extra=extra)
