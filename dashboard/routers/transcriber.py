"""Transcriber API routes.

POST   /api/transcriber/upload                   - upload audio recording
GET    /api/transcriber/recordings                - list recordings
POST   /api/transcriber/transcribe/{filename}     - transcribe a recording
DELETE /api/transcriber/recordings/{filename}      - delete a recording
"""
import asyncio
import datetime
import json
import shutil
import time as _time
from pathlib import Path

from fastapi import APIRouter, Depends, File, UploadFile
from fastapi.responses import JSONResponse, StreamingResponse

from dashboard.auth.middleware import get_current_user
from dashboard.db.models.user import User
from dashboard.helpers import BASE

router = APIRouter(tags=["transcriber"])

TRANSCRIBER_DIR = BASE / "transcriber"
RECORDINGS_DIR = TRANSCRIBER_DIR / "recordings"
RECORDINGS_DIR.mkdir(parents=True, exist_ok=True)

ALLOWED_WHISPER_MODELS = {"tiny", "base", "small", "medium", "large-v3"}


def _safe_recording_path(filename: str, base: Path = RECORDINGS_DIR) -> Path | None:
    """Resolve filename within base dir; return None if path traversal detected."""
    resolved = (base / filename).resolve()
    if not str(resolved).startswith(str(base.resolve())):
        return None
    return resolved


@router.post("/api/transcriber/upload")
async def upload_recording(audio: UploadFile = File(...), user: User = Depends(get_current_user)):
    ts = datetime.datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    fname = f"{ts}.webm"
    dest = RECORDINGS_DIR / fname
    with open(dest, "wb") as f:
        shutil.copyfileobj(audio.file, f)
    return {"filename": fname, "path": str(dest)}


@router.get("/api/transcriber/recordings")
def list_recordings(user: User = Depends(get_current_user)):
    recs = []
    for f in sorted(RECORDINGS_DIR.iterdir(), reverse=True):
        if f.is_file() and f.suffix in (".webm", ".wav", ".mp3", ".m4a", ".ogg"):
            txt = TRANSCRIBER_DIR / "output" / f"{f.stem}.txt"
            recs.append({
                "filename": f.name,
                "size": f.stat().st_size,
                "has_transcript": txt.exists(),
                "transcript": txt.read_text("utf-8") if txt.exists() else None,
            })
    return recs


@router.post("/api/transcriber/transcribe/{filename}")
async def transcribe_recording(filename: str, model: str = "base", stream: str = "", user: User = Depends(get_current_user)):
    # Validate model against allowlist (prevent command injection)
    if model not in ALLOWED_WHISPER_MODELS:
        error_msg = f"Invalid model. Allowed: {', '.join(sorted(ALLOWED_WHISPER_MODELS))}"
        if stream.lower() == "true":
            async def _invalid_model_sse():
                yield f"data: {json.dumps({'type': 'phase', 'phase': 'error', 'message': error_msg})}\n\n"
            return StreamingResponse(
                _invalid_model_sse(),
                media_type="text/event-stream",
                headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
            )
        return {"ok": False, "log": error_msg}

    # Validate filename against path traversal
    src = _safe_recording_path(filename)
    if src is None or not src.exists():
        return JSONResponse(status_code=404, content={"ok": False, "log": "File not found"})
    script = TRANSCRIBER_DIR / "transcribe.sh"
    output_dir = TRANSCRIBER_DIR / "output"

    if stream.lower() == "true":
        return StreamingResponse(
            _transcribe_sse(script, src, output_dir, model),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    # Fallback: synchronous (no stream)
    proc = await asyncio.create_subprocess_exec(
        str(script), str(src), "-o", str(output_dir), "-m", model,
        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT,
    )
    stdout, _ = await proc.communicate()
    txt = output_dir / f"{src.stem}.txt"
    return {
        "ok": proc.returncode == 0,
        "log": stdout.decode(errors="replace"),
        "transcript": txt.read_text("utf-8") if txt.exists() else None,
    }


async def _transcribe_sse(script, src, output_dir, model):
    """Generator that yields SSE events for transcription progress."""
    import re as _re

    def sse(data):
        return f"data: {json.dumps(data)}\n\n"

    yield sse({"type": "phase", "phase": "loading_model", "model": model})

    proc = await asyncio.create_subprocess_exec(
        str(script), str(src), "-o", str(output_dir), "-m", model,
        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT,
    )

    timeout = 600  # 10 minutes
    start = _time.monotonic()
    last_progress_time = 0.0
    segments_done = 0
    duration = None
    last_segment_end = 0.0
    phase_sent = False

    try:
        while True:
            elapsed = _time.monotonic() - start
            if elapsed > timeout:
                proc.kill()
                await proc.wait()
                yield sse({"type": "phase", "phase": "error", "message": "Timeout: process killed after 10 minutes"})
                return

            try:
                line_bytes = await asyncio.wait_for(proc.stdout.readline(), timeout=max(1, timeout - elapsed))
            except asyncio.TimeoutError:
                proc.kill()
                await proc.wait()
                yield sse({"type": "phase", "phase": "error", "message": "Timeout: process killed after 10 minutes"})
                return

            if not line_bytes:
                break

            line = line_bytes.decode(errors="replace").strip()
            if not line:
                continue

            # Parse "Duration: 125.3s"
            dur_match = _re.match(r"Duration:\s*([\d.]+)s", line)
            if dur_match:
                duration = float(dur_match.group(1))
                if not phase_sent:
                    phase_sent = True
                    yield sse({"type": "phase", "phase": "transcribing", "duration": duration})
                continue

            # Parse "Language: ..." line -- skip
            if line.startswith("Language:"):
                continue

            # Parse "[0.0s - 3.2s] text"
            seg_match = _re.match(r"\[([\d.]+)s\s*-\s*([\d.]+)s\]", line)
            if seg_match:
                if not phase_sent:
                    phase_sent = True
                    yield sse({"type": "phase", "phase": "transcribing", "duration": 0})

                segments_done += 1
                last_segment_end = float(seg_match.group(2))

                now = _time.monotonic()
                if now - last_progress_time >= 2.0:
                    last_progress_time = now
                    percent = 0
                    eta = 0
                    if duration and duration > 0:
                        percent = min(99, int(last_segment_end / duration * 100))
                        transcribe_elapsed = now - start
                        if percent > 0:
                            eta = max(0, int(transcribe_elapsed / percent * (100 - percent)))
                    yield sse({"type": "progress", "percent": percent, "segments_done": segments_done, "eta_seconds": eta})
                continue

            # "Done: ..." line
            if line.startswith("Done:"):
                continue

        await proc.wait()

        txt = output_dir / f"{src.stem}.txt"
        if proc.returncode == 0 and txt.exists():
            transcript = await asyncio.to_thread(txt.read_text, "utf-8")
            yield sse({"type": "progress", "percent": 100, "segments_done": segments_done, "eta_seconds": 0})
            yield sse({"type": "phase", "phase": "completed", "transcript": transcript})
        else:
            yield sse({"type": "phase", "phase": "error", "message": f"Process exited with code {proc.returncode}"})

    except Exception as exc:
        try:
            proc.kill()
            await proc.wait()
        except ProcessLookupError:
            pass
        yield sse({"type": "phase", "phase": "error", "message": str(exc)})


@router.delete("/api/transcriber/recordings/{filename}")
def delete_recording(filename: str, user: User = Depends(get_current_user)):
    # Validate filename against path traversal
    f = _safe_recording_path(filename)
    if f is None:
        return {"error": "Invalid filename"}
    if f.exists():
        f.unlink()
    txt_path = _safe_recording_path(f"{Path(filename).stem}.txt", TRANSCRIBER_DIR / "output")
    if txt_path and txt_path.exists():
        txt_path.unlink()
    return {"ok": True}
