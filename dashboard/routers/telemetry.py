"""Pipeline telemetry API routes.

GET    /api/telemetry   - return last N lines of pipeline.log as parsed JSON
DELETE /api/telemetry   - clear pipeline.log
"""
import json
from pathlib import Path

from fastapi import APIRouter, Depends

from dashboard.auth.middleware import get_current_user
from dashboard.db.models.user import User

router = APIRouter(tags=["telemetry"])


@router.get("/api/telemetry")
def get_telemetry(lines: int = 100, user: User = Depends(get_current_user)):
    """Return last N lines of pipeline.log as parsed JSON objects."""
    log_path = Path(__file__).parent.parent / "pipeline.log"
    if not log_path.exists():
        return {"lines": [], "total": 0}
    all_lines = log_path.read_text(encoding="utf-8").strip().split("\n")
    parsed = []
    for raw in all_lines[-lines:]:
        raw = raw.strip()
        if not raw:
            continue
        try:
            parsed.append(json.loads(raw))
        except json.JSONDecodeError:
            # Legacy pipe-delimited line -- wrap for backward compatibility
            parsed.append({"timestamp": "", "level": "INFO", "event": raw, "session_id": "", "project": ""})
    return {"lines": parsed, "total": len(all_lines)}


@router.delete("/api/telemetry")
def clear_telemetry(user: User = Depends(get_current_user)):
    log_path = Path(__file__).parent.parent / "pipeline.log"
    if log_path.exists():
        log_path.write_text("", encoding="utf-8")
    return {"ok": True}
