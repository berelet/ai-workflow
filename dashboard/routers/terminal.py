"""Terminal API routes (HTTP polling + WebSocket).

POST      /api/terminal/start              - start a CLI session via HTTP
GET       /api/terminal/poll/{session_id}   - poll for new output
POST      /api/terminal/input/{session_id}  - send input to running session
POST      /api/terminal/stop/{session_id}   - stop a running session
WebSocket /ws/terminal                      - WebSocket terminal to CLI
"""
import asyncio
import json
import os
import re
import uuid

import pexpect
from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, WebSocket
from pydantic import BaseModel

from dashboard.auth.middleware import get_current_user, ws_authenticate
from dashboard.db.engine import async_session
from dashboard.db.models.user import User
from dashboard.helpers import BASE
from dashboard.structured_logger import create_pipeline_logger, tel_log

router = APIRouter(tags=["terminal"])

tel_logger = create_pipeline_logger()

# --- ANSI / spinner regexes ---

ANSI_RE = re.compile(
    r'\x1b\[[0-9;]*[a-zA-Z]'     # CSI sequences (cursor, color, erase)
    r'|\x1b\[\?[0-9;]*[a-zA-Z]'  # DEC private modes
    r'|\x1b\][^\x07]*\x07'        # OSC sequences
    r'|\x1b\([A-Z0-9]'            # Character set selection
    r'|\x1b[=>NOMDEHc78]'         # Simple escape sequences
    r'|\x1b\[[\d;]*m'             # SGR (color/style)
    r'|\x1b\[\d*[ABCDJKGHST]'    # Cursor movement, erase
    r'|\x1b\[\d*;\d*[Hf]'        # Cursor positioning
    r'|\x1b\[\?\d+[hl]'          # DEC mode set/reset
    r'|\x00'                      # Null bytes
)
KIRO_SPINNER_RE = re.compile(r'[⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏]\s*Thinking\.\.\.')
CLAUDE_SPINNER_RE = re.compile(r'[✢✶✻✽⏵●·◆◇░█▓▒❯]')  # kept for potential reuse

# --- Telemetry patterns ---

_TEL_PATTERNS = [
    (re.compile(r'📋 Skills Review \((\w+)\):\s*(.*)'), 'SKILLS_REVIEW'),
    (re.compile(r'📋 Skills applied:\s*(.*)'), 'SKILLS_APPLIED'),
    (re.compile(r'Этап \d+:\s*(\w+)'), 'STAGE_START'),
    (re.compile(r'user-stories\.md'), 'ARTIFACT_PM'),
    (re.compile(r'spec\.md'), 'ARTIFACT_BA'),
    (re.compile(r'changes\.md'), 'ARTIFACT_DEV'),
    (re.compile(r'test-result\.md|bug-report\.md'), 'ARTIFACT_QA'),
    (re.compile(r'review\.md'), 'ARTIFACT_REVIEW'),
    (re.compile(r'PASS|FAIL'), 'QA_RESULT'),
    (re.compile(r'I will run the following command:(.*)'), 'TOOL_USE'),
    (re.compile(r'I will (read|create|edit|write)'), 'FILE_OP'),
]


def _tel_detect(session_id: str, line: str, project: str = ""):
    """Detect pipeline events in output and log them."""
    stripped = line.strip()
    if not stripped:
        return
    for pattern, event in _TEL_PATTERNS:
        m = pattern.search(stripped)
        if m:
            detail = m.group(1) if m.lastindex else ""
            tel_log(tel_logger, event, session_id=session_id, project=project, detail=detail)
            return


async def _dump_backlog_to_files(project: str, cwd: str):
    """Dump backlog from DB to .ai-workflow/backlog.json + backlog.md.
    Called before each terminal start so orchestrator can read task data."""
    import json as _json
    from pathlib import Path as _Path
    from dashboard.db.engine import async_session as _async_session
    from dashboard.db.models.project import Project
    from dashboard.db.models.backlog import BacklogItem as _BI
    from sqlalchemy import select as _sel

    async with _async_session() as db:
        proj = (await db.execute(_sel(Project).where(Project.slug == project))).scalar_one_or_none()
        if not proj:
            return
        result = await db.execute(
            _sel(_BI).where(
                _BI.project_id == proj.id,
                _BI.status.notin_(["done", "archived"]),
            ).order_by(_BI.sort_order, _BI.sequence_number)
        )
        items = []
        for bi in result.scalars().all():
            items.append({
                "id": bi.sequence_number,
                "task": bi.title,
                "title": bi.title,
                "description": bi.description or "",
                "priority": bi.priority or "medium",
                "status": bi.status or "todo",
            })

    ai_dir = _Path(cwd) / ".ai-workflow"
    ai_dir.mkdir(parents=True, exist_ok=True)

    # backlog.json
    (ai_dir / "backlog.json").write_text(_json.dumps(items, ensure_ascii=False, indent=2), encoding="utf-8")

    # backlog.md
    lines = ["# Бэклог", "", "| # | Задача | Приоритет | Статус |", "|---|--------|-----------|--------|"]
    for item in items:
        lines.append(f"| {item['id']} | {item['task']} | {item['priority']} | {item['status']} |")
    (ai_dir / "backlog.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


async def _dump_pipelines_to_files(project: str):
    """Dump pipeline definitions from DB to projects/{project}/pipelines/*.json.
    Called before each terminal start so orchestrator can read pipeline graphs."""
    import json as _json
    from pathlib import Path as _Path
    from dashboard.db.engine import async_session as _async_session
    from dashboard.db.models.project import Project
    from dashboard.db.models.pipeline import PipelineDefinition
    from sqlalchemy import select as _sel

    async with _async_session() as db:
        proj = (await db.execute(_sel(Project).where(Project.slug == project))).scalar_one_or_none()
        if not proj:
            return
        result = await db.execute(
            _sel(PipelineDefinition).where(PipelineDefinition.project_id == proj.id)
        )
        pipelines_dir = BASE / "projects" / project / "pipelines"
        pipelines_dir.mkdir(parents=True, exist_ok=True)
        for pl in result.scalars().all():
            data = {
                "id": str(pl.id),
                "name": pl.name,
                "is_default": pl.is_default,
                "graph": pl.graph_json,
                "stages_order": pl.stages_order,
            }
            (pipelines_dir / f"{pl.id}.json").write_text(
                _json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
            )


async def _dump_agents_to_files():
    """Sync global agent instructions from DB to filesystem.
    Called before each terminal start so agents have current instructions."""
    from dashboard.db.engine import async_session as _async_session
    from dashboard.db.models.agent_config import AgentConfig
    from sqlalchemy import select as _sel

    async with _async_session() as db:
        configs = (await db.execute(
            _sel(AgentConfig).where(AgentConfig.project_id == None)
        )).scalars().all()

    for cfg in configs:
        agent_dir = BASE / cfg.agent_name
        agent_dir.mkdir(exist_ok=True)
        (agent_dir / "instructions.md").write_text(
            cfg.instructions_md or "", encoding="utf-8"
        )


def _check_skills() -> str:
    """Pre-flight: verify AGENTS.md and skill files exist. Return terminal output."""
    agents_md = BASE / "docs" / "AGENTS.md"
    if not agents_md.exists():
        return "⚠️  AGENTS.md not found — skills NOT loaded\n\n"

    text = agents_md.read_text()
    lines = []
    agent_labels = {"global": "ALL", "pm": "PM", "ba": "BA", "backend": "DEV", "frontend": "DEV", "qa": "QA"}
    current = "global"
    ok = 0
    fail = 0

    for line in text.split("\n"):
        if line.startswith("## "):
            s = line[3:].strip().lower()
            if "global" in s: current = "global"
            elif "backend" in s: current = "backend"
            elif "frontend" in s: current = "frontend"
            elif "qa" in s or "test" in s: current = "qa"
            elif "product" in s: current = "pm"
            elif "business" in s: current = "ba"
        elif line.startswith("### "):
            name = line[4:].split(" — ")[0].strip()
            # find @path on next line
            idx = text.index(line) + len(line)
            path = ""
            for nl in text[idx:].split("\n"):
                nl = nl.strip()
                if nl.startswith("@"):
                    path = nl.split()[0][1:]
                    break
                if nl.startswith("##"): break
            exists = (BASE / path).exists() if path else False
            tag = agent_labels.get(current, current.upper())
            if exists:
                lines.append(f"  ✅ {name:22} → {tag}")
                ok += 1
            else:
                lines.append(f"  ❌ {name:22} → {tag}  (MISSING: {path})")
                fail += 1

    if not lines:
        return ""

    header = f"🧩 Skills: {ok} loaded"
    if fail:
        header += f", {fail} missing"
    return header + "\n" + "\n".join(lines) + "\n\n"


# Track active terminal sessions per project to kill on re-run
_active_children: dict[str, "pexpect.spawn"] = {}

# --- HTTP polling terminal (mobile-friendly fallback) ---
_poll_sessions: dict[str, dict] = {}  # session_id -> {output_chunks: [], done: bool, ...}

_CLAUDE_MODEL_MAP = {
    "claude-opus-4.6": "opus",
    "claude-sonnet-4": "sonnet",
    "claude-haiku-4-5-20251001": "haiku",
    "auto": "sonnet",
}


class TerminalStartRequest(BaseModel):
    prompt: str = ""
    project: str = "?"
    model: str | None = None
    provider: str | None = None
    claude_session_id: str | None = None


class TerminalInputRequest(BaseModel):
    data: str = ""


class TerminalCompleteTaskRequest(BaseModel):
    project: str
    task_id: str


def _build_cmd_poll(cli_name, model, prompt, resume_id=None, max_turns=None):
    if cli_name == "claude":
        cc_model = _CLAUDE_MODEL_MAP.get(model, model)
        args = ['-p', '--verbose', '--model', cc_model, '--output-format', 'stream-json', '--dangerously-skip-permissions']
        if max_turns:
            args += ['--max-turns', str(max_turns)]
        if resume_id:
            args += ['--resume', resume_id]
        args.append(prompt)
        return 'claude', args
    else:
        args = ['chat', '--trust-all-tools']
        if model and model != 'auto':
            args += ['--model', model]
        args.append(prompt)
        return 'kiro-cli', args


@router.post("/api/terminal/start")
async def terminal_start(body: TerminalStartRequest, user: User = Depends(get_current_user)):
    """Start a CLI session via HTTP. Returns session_id for SSE streaming. Requires developer+ role."""
    prompt = body.prompt
    project = body.project
    model = body.model or os.getenv("DEFAULT_MODEL", "claude-opus-4.6")
    cli = body.provider or os.getenv("DEFAULT_CLI", "claude")
    claude_session_id = body.claude_session_id
    session_id = uuid.uuid4().hex
    user_id = str(user.id)

    # Check developer+ role for the project
    if project and project != "?":
        from dashboard.db.engine import async_session as _check_session
        from dashboard.auth.permissions import _resolve_project, check_project_access
        async with _check_session() as db:
            proj = await _resolve_project(db, project)
            if proj:
                effective_role = await check_project_access(db, user, proj, "developer")
                if effective_role is None:
                    raise HTTPException(status_code=403, detail="Requires developer role")

    # Kill previous run for this project (keyed by user+project)
    child_key = f"{user_id}:{project}"
    old = _active_children.pop(child_key, None)
    if old and old.isalive():
        old.terminate(force=True)

    # Resolve project working directory
    import json as _json
    cwd = str(BASE)
    try:
        cfg_path = BASE / "projects" / project / "pipeline-config.json"
        if cfg_path.exists():
            cfg = _json.loads(cfg_path.read_text(encoding="utf-8"))
            if "project_dir" in cfg and os.path.isdir(cfg["project_dir"]):
                cwd = cfg["project_dir"]
    except Exception:
        pass

    # Dump DB data to files so orchestrator can read them
    try:
        await _dump_backlog_to_files(project, cwd)
        await _dump_pipelines_to_files(project)
        await _dump_agents_to_files()
    except Exception as e:
        tel_logger.warning(f"[{session_id}] pre-start dump failed: {e}")

    tel_logger.info(f"[{session_id}] HTTP START project={project} cli={cli} model={model} cwd={cwd}")

    _poll_sessions[session_id] = {"chunks": [], "done": False, "cursor": 0, "exitCode": None, "claude_session_id": None, "project": project, "user_id": user_id}

    # Skills pre-flight
    if not claude_session_id:
        skills_report = _check_skills()
        if skills_report:
            _poll_sessions[session_id]["chunks"].append(skills_report)

    cmd, args = _build_cmd_poll(cli, model, prompt, resume_id=claude_session_id)
    env = os.environ.copy()
    for key in ['CLAUDECODE', 'CLAUDE_CODE', 'CLAUDE_CONVERSATION_ID', 'CLAUDE_CODE_SSE_PORT', 'CLAUDE_CODE_ENTRYPOINT']:
        env.pop(key, None)

    loop = asyncio.get_event_loop()
    child = await loop.run_in_executor(None, lambda: pexpect.spawn(cmd, args, cwd=cwd, encoding='utf-8', timeout=300, env=env))
    child.setwinsize(200, 500)
    _active_children[child_key] = child

    # Background reader task
    async def _poll_reader():
        sess = _poll_sessions[session_id]
        _captured_sid = {"value": claude_session_id}

        _secret_patterns = re.compile(
            r'(?i)'
            r'(?:password|passwd|pwd|secret|token|api[_-]?key|auth|credential)s?\s*[=:]\s*\S+'
            r'|(?:PGPASSWORD|AWS_SECRET|DATABASE_URL|DB_PASS)\s*=\s*\S+'
            r'|(?<=://)[^:]+:[^@]+(?=@)'  # user:password in URLs
        )

        async def poll_send(data):
            """Append to poll chunks, masking secrets."""
            if data.get("type") == "output":
                text = _secret_patterns.sub(lambda m: m.group(0).split('=')[0] + '=***' if '=' in m.group(0) else '***:***', data["data"])
                sess["chunks"].append(text)

        if cli == "claude":
            # Reuse the stream-json parser from WS handler
            line_buf = ""
            while True:
                try:
                    chunk = await loop.run_in_executor(None, lambda: child.read_nonblocking(size=16384, timeout=0.5))
                    if chunk:
                        clean = ANSI_RE.sub('', chunk)
                        for raw_line in (line_buf + clean).split('\n'):
                            raw_line = raw_line.strip()
                            if not raw_line:
                                continue
                            if raw_line.startswith('{'):
                                try:
                                    event = json.loads(raw_line)
                                    line_buf = ""
                                    # Capture session_id
                                    if "session_id" in event and not _captured_sid["value"]:
                                        _captured_sid["value"] = event["session_id"]
                                    etype = event.get("type", "")
                                    if etype == "system":
                                        sub = event.get("subtype", "")
                                        if sub == "init" and not claude_session_id:
                                            await poll_send({"type": "output", "data": "🚀 Claude Code session started\n"})
                                    elif etype == "assistant":
                                        msg = event.get("message", {})
                                        for block in msg.get("content", []):
                                            bt = block.get("type", "")
                                            if bt == "text":
                                                text = block.get("text", "")
                                                if text.strip():
                                                    await poll_send({"type": "output", "data": text if text.endswith("\n") else text + "\n"})
                                            elif bt == "tool_use":
                                                name = block.get("name", "?")
                                                inp = block.get("input", {})
                                                summary = f"🔧 {name}"
                                                if "file_path" in inp:
                                                    summary += f" {inp['file_path']}"
                                                elif "command" in inp:
                                                    cmd_str = inp["command"][:80]
                                                    summary += f" $ {cmd_str}"
                                                await poll_send({"type": "output", "data": summary + "\n"})
                                    elif etype == "result":
                                        result_text = event.get("result", "")
                                        if result_text.strip():
                                            await poll_send({"type": "output", "data": result_text + "\n"})
                                except json.JSONDecodeError:
                                    line_buf = raw_line
                            else:
                                # Non-JSON output
                                if raw_line:
                                    await poll_send({"type": "output", "data": raw_line + "\n"})
                except pexpect.TIMEOUT:
                    if not child.isalive():
                        break
                except pexpect.EOF:
                    break
        else:
            # kiro-cli: plain text
            line_buf = ""
            while True:
                try:
                    chunk = await loop.run_in_executor(None, lambda: child.read_nonblocking(size=16384, timeout=0.5))
                    if chunk:
                        clean = ANSI_RE.sub('', chunk)
                        for ch in clean:
                            if ch == '\r': continue
                            elif ch == '\n':
                                sess["chunks"].append(line_buf + "\n")
                                line_buf = ""
                            else:
                                line_buf += ch
                        if line_buf:
                            sess["chunks"].append(line_buf)
                            line_buf = ""
                except pexpect.TIMEOUT:
                    if not child.isalive():
                        break
                except pexpect.EOF:
                    if line_buf:
                        sess["chunks"].append(line_buf + "\n")
                    break

        sess["done"] = True
        sess["exitCode"] = child.exitstatus or 0
        sess["claude_session_id"] = _captured_sid["value"]
        _active_children.pop(child_key, None)
        child.close()
        tel_logger.info(f"[{session_id}] HTTP DONE exitCode={sess['exitCode']}")

    asyncio.create_task(_poll_reader())
    return {"session_id": session_id}


@router.get("/api/terminal/stream/{session_id}")
async def terminal_stream(session_id: str, user: User = Depends(get_current_user)):
    """SSE stream for terminal output. Replaces WebSocket for reliability."""
    from fastapi.responses import StreamingResponse

    sess = _poll_sessions.get(session_id)
    if not sess:
        raise HTTPException(status_code=404, detail="Session not found")
    if sess.get("user_id") != str(user.id):
        raise HTTPException(status_code=403, detail="Access denied")

    async def _generate():
        cursor = 0
        idle = 0
        while True:
            # Send new chunks (batch into one message to avoid splitting words)
            chunks = sess["chunks"][cursor:]
            if chunks:
                text = "".join(chunks)
                yield f"data: {json.dumps({'type': 'output', 'data': text})}\n\n"
                cursor = len(sess["chunks"])
                idle = 0
            else:
                idle += 1

            # Check if done
            if sess["done"]:
                # Flush remaining chunks
                remaining = sess["chunks"][cursor:]
                if remaining:
                    yield f"data: {json.dumps({'type': 'output', 'data': ''.join(remaining)})}\n\n"
                done_data = {"type": "done", "exitCode": sess.get("exitCode", 0)}
                if sess.get("claude_session_id"):
                    done_data["claude_session_id"] = sess["claude_session_id"]
                yield f"data: {json.dumps(done_data)}\n\n"
                return

            # Timeout: if no data for 10 minutes, close stream
            if idle > 600:
                yield f"data: {json.dumps({'type': 'error', 'data': 'Stream timeout'})}\n\n"
                return

            # Keepalive every 15s, otherwise short sleep
            if idle % 15 == 0 and idle > 0:
                yield ": ping\n\n"

            await asyncio.sleep(1)

    return StreamingResponse(
        _generate(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",  # disable nginx buffering
        },
    )


@router.get("/api/terminal/active")
async def terminal_active(project: str = "", user: User = Depends(get_current_user)):
    """Find active session for user+project. Used to reconnect after page reload."""
    user_id = str(user.id)
    for sid, sess in _poll_sessions.items():
        if sess.get("user_id") == user_id and sess.get("project") == project and not sess["done"]:
            return {"session_id": sid, "chunks_count": len(sess["chunks"])}
    return {"session_id": None}


@router.get("/api/terminal/poll/{session_id}")
async def terminal_poll(session_id: str, cursor: int = 0, user: User = Depends(get_current_user)):
    """Poll for new output. Returns chunks since cursor."""
    sess = _poll_sessions.get(session_id)
    if not sess:
        raise HTTPException(status_code=404, detail="Session not found")
    if sess.get("user_id") != str(user.id):
        raise HTTPException(status_code=403, detail="Access denied")
    chunks = sess["chunks"][cursor:]
    new_cursor = len(sess["chunks"])
    result = {"chunks": chunks, "cursor": new_cursor, "done": sess["done"]}
    if sess["done"]:
        result["exitCode"] = sess["exitCode"]
        if sess.get("claude_session_id"):
            result["claude_session_id"] = sess["claude_session_id"]
    return result


@router.post("/api/terminal/input/{session_id}")
async def terminal_input(session_id: str, body: TerminalInputRequest, user: User = Depends(get_current_user)):
    """Send input to running session identified by session_id."""
    sess = _poll_sessions.get(session_id)
    if not sess:
        raise HTTPException(status_code=404, detail="Session not found")
    if sess.get("user_id") != str(user.id):
        raise HTTPException(status_code=403, detail="Access denied")
    # Find the child associated with this session's project (keyed by user+project)
    project = sess.get("project", "")
    child_key = f"{str(user.id)}:{project}"
    child = _active_children.get(child_key)
    if child and child.isalive():
        text = body.data
        child.send(text + '\r')
        return {"ok": True}
    raise HTTPException(status_code=404, detail="No active session")


# --- File upload for terminal chat ---

UPLOAD_DIR = BASE / "tmp" / "terminal-uploads"
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)

UPLOAD_MAX_SIZE = 10 * 1024 * 1024  # 10 MB


@router.post("/api/terminal/upload")
async def terminal_upload(file: UploadFile = File(...), user: User = Depends(get_current_user)):
    """Upload a file for use in terminal chat. Saved to tmp/, auto-cleaned after 1 day."""
    data = await file.read()
    if len(data) > UPLOAD_MAX_SIZE:
        raise HTTPException(status_code=413, detail=f"File too large (max {UPLOAD_MAX_SIZE // 1024 // 1024} MB)")

    safe_name = re.sub(r'[^\w\-.]', '_', file.filename or "file")
    unique_name = f"{uuid.uuid4().hex[:8]}_{safe_name}"
    dest = UPLOAD_DIR / unique_name
    dest.write_bytes(data)
    return {"ok": True, "path": str(dest), "name": file.filename, "size": len(data)}


@router.post("/api/terminal/stop/{session_id}")
async def terminal_stop(session_id: str, user: User = Depends(get_current_user)):
    """Stop a specific running session."""
    sess = _poll_sessions.get(session_id)
    if not sess:
        raise HTTPException(status_code=404, detail="Session not found")
    if sess.get("user_id") != str(user.id):
        raise HTTPException(status_code=403, detail="Access denied")
    sess["done"] = True
    # Kill only the child for this session's project (keyed by user+project)
    project = sess.get("project", "")
    child_key = f"{str(user.id)}:{project}"
    child = _active_children.pop(child_key, None)
    if child and child.isalive():
        child.terminate(force=True)
    return {"ok": True}


@router.post("/api/terminal/complete-task")
async def terminal_complete_task(body: TerminalCompleteTaskRequest, user: User = Depends(get_current_user)):
    """Complete a task: sync artifacts to DB + set status to done."""
    project = body.project
    task_id = body.task_id
    if not project or not task_id:
        raise HTTPException(status_code=400, detail="project and task_id required")

    from dashboard.db.engine import async_session as _async_session
    from dashboard.db.models.project import Project
    from dashboard.db.models.backlog import BacklogItem

    async with _async_session() as db:
        from sqlalchemy import select as _select
        proj = (await db.execute(_select(Project).where(Project.slug == project))).scalar_one_or_none()
        if not proj:
            raise HTTPException(status_code=404, detail="Project not found")
        bi = (await db.execute(_select(BacklogItem).where(
            BacklogItem.project_id == proj.id,
            BacklogItem.sequence_number == int(task_id),
        ))).scalar_one_or_none()
        if not bi:
            raise HTTPException(status_code=404, detail="Task not found")
        if bi.status == "done":
            return {"ok": True, "already_done": True}

        # Sync artifacts
        try:
            from dashboard.db.sync_artifacts import sync
            await sync(project, int(task_id), clean=True)
        except Exception as e:
            tel_logger.error(f"complete-task sync error: {e}")

        # Update status
        bi.status = "done"
        await db.commit()

    # Re-dump backlog files (removes done task from active list)
    try:
        import json as _json
        cwd = str(BASE)
        cfg_path = BASE / "projects" / project / "pipeline-config.json"
        if cfg_path.exists():
            cfg = _json.loads(cfg_path.read_text(encoding="utf-8"))
            if "project_dir" in cfg and os.path.isdir(cfg["project_dir"]):
                cwd = cfg["project_dir"]
        await _dump_backlog_to_files(project, cwd)
    except Exception as e:
        tel_logger.warning(f"complete-task backlog dump: {e}")

    tel_logger.info(f"Task #{task_id} completed for {project} by {user.email}")
    return {"ok": True}


@router.websocket("/ws/terminal")
async def terminal_ws(ws: WebSocket):
    await ws.accept()

    # Authenticate via cookie
    async with async_session() as db:
        user = await ws_authenticate(ws, db)

    await ws.send_json({"type": "ping"})
    child = None
    project = None
    ws_child_key = None
    session_id = uuid.uuid4().hex
    tel_log(tel_logger, "WS_CONNECTED", session_id=session_id)
    try:
        # Config via query params (mobile-friendly) or via WS message
        qp = dict(ws.query_params)
        if qp.get("project"):
            config = qp
            tel_logger.info(f"[{session_id}] got config from query params: {json.dumps(config)[:200]}")
        else:
            tel_logger.info(f"[{session_id}] waiting for config JSON...")
            config = await asyncio.wait_for(ws.receive_json(), timeout=10)
            tel_logger.info(f"[{session_id}] got config: {json.dumps(config)[:200]}")
        prompt = config.get("prompt", "")
        project = config.get("project", "?")
        model = config.get("model") or os.getenv("DEFAULT_MODEL", "sonnet")
        cli = config.get("provider") or os.getenv("DEFAULT_CLI", "claude")
        claude_session_id = config.get("claude_session_id")  # for --resume

        # Check developer+ role for the project
        if project and project != "?":
            from dashboard.auth.permissions import _resolve_project, check_project_access
            async with async_session() as _db:
                _proj = await _resolve_project(_db, project)
                if _proj:
                    _effective_role = await check_project_access(_db, user, _proj, "developer")
                    if _effective_role is None:
                        await ws.send_json({"type": "error", "data": "Requires developer role"})
                        await ws.close(code=4003)
                        return

        # Resolve project working directory
        from dashboard.helpers import get_ai_workflow_dir, PROJECTS
        import json as _json
        cwd = str(BASE)
        try:
            cfg_path = PROJECTS / project / "pipeline-config.json"
            if cfg_path.exists():
                cfg = _json.loads(cfg_path.read_text(encoding="utf-8"))
                if "project_dir" in cfg:
                    pdir = cfg["project_dir"]
                    if os.path.isdir(pdir):
                        cwd = pdir
        except Exception:
            pass

        # Kill previous run for this project (keyed by user+project)
        ws_child_key = f"{str(user.id)}:{project}"
        old = _active_children.pop(ws_child_key, None)
        if old and old.isalive():
            tel_log(tel_logger, "KILL_PREVIOUS", session_id=session_id, project=project)
            old.terminate(force=True)

        tel_log(tel_logger, "START", session_id=session_id, project=project,
                cli=cli, model=model, resume=claude_session_id or "NEW",
                prompt_preview=prompt[:120])

        # --- Skills pre-flight check (only for new sessions) ---
        if not claude_session_id:
            skills_report = _check_skills()
            if skills_report:
                await ws.send_json({"type": "output", "data": skills_report})
                tel_log(tel_logger, "SKILLS_CHECK", session_id=session_id, project=project)

        loop = asyncio.get_event_loop()

        def _build_cmd(cli_name, model, prompt, resume_id=None):
            if cli_name == "claude":
                args = [
                    '-p',
                    '--verbose',
                    '--model', model,
                    '--output-format', 'stream-json',
                    '--dangerously-skip-permissions',
                ]
                if resume_id:
                    args += ['--resume', resume_id]
                args.append(prompt)
                return 'claude', args
            else:
                args = ['chat', '--trust-all-tools']
                if model and model != 'auto':
                    args += ['--model', model]
                args.append(prompt)
                return 'kiro-cli', args

        def run_child():
            cmd, args = _build_cmd(cli, model, prompt, resume_id=claude_session_id)
            # Clean env to avoid "nested session" errors in Claude Code
            env = os.environ.copy()
            for key in ['CLAUDECODE', 'CLAUDE_CODE', 'CLAUDE_CONVERSATION_ID',
                        'CLAUDE_CODE_SSE_PORT', 'CLAUDE_CODE_ENTRYPOINT']:
                env.pop(key, None)
            return pexpect.spawn(
                cmd, args,
                cwd=cwd, encoding='utf-8', timeout=300, env=env
            )

        child = await loop.run_in_executor(None, run_child)
        child.setwinsize(200, 500)

        _active_children[ws_child_key] = child

        thinking_sent = False
        line_buf = ""
        last_send_time = 0
        ws_closed = False

        _ws_secret_patterns = re.compile(
            r'(?i)'
            r'(?:password|passwd|pwd|secret|token|api[_-]?key|auth|credential)s?\s*[=:]\s*\S+'
            r'|(?:PGPASSWORD|AWS_SECRET|DATABASE_URL|DB_PASS)\s*=\s*\S+'
            r'|(?<=://)[^:]+:[^@]+(?=@)'
        )

        async def safe_send(data):
            nonlocal ws_closed
            if ws_closed:
                return
            try:
                if data.get("type") == "output" and data.get("data"):
                    data = dict(data)
                    data["data"] = _ws_secret_patterns.sub(
                        lambda m: m.group(0).split('=')[0] + '=***' if '=' in m.group(0) else '***:***',
                        data["data"]
                    )
                await ws.send_json(data)
            except Exception:
                ws_closed = True

        async def read_output():
            nonlocal thinking_sent, line_buf, last_send_time
            import time

            if cli == "claude":
                await _read_claude_output(session_id, child, loop, safe_send)
            else:
                await _read_kiro_output(session_id, child, loop, safe_send)

        _captured_claude_session_id = {"value": None}

        async def _read_claude_output(session_id, child, loop, safe_send):
            """Read Claude Code stream-json output (-p mode, no TUI)."""
            line_buf = ""

            async def _handle_event(event):
                etype = event.get("type", "")

                # Capture Claude session_id for --resume
                if "session_id" in event and not _captured_claude_session_id["value"]:
                    _captured_claude_session_id["value"] = event["session_id"]

                if etype == "system":
                    sub = event.get("subtype", "")
                    if sub == "init" and not claude_session_id:
                        await safe_send({"type": "output", "data": "🚀 Claude Code session started\n"})

                elif etype == "assistant":
                    msg = event.get("message", {})
                    for block in msg.get("content", []):
                        bt = block.get("type", "")
                        if bt == "text":
                            text = block.get("text", "")
                            if text.strip():
                                _tel_detect(session_id, text, project)
                                await safe_send({"type": "output", "data": text if text.endswith("\n") else text + "\n"})
                        elif bt == "tool_use":
                            name = block.get("name", "?")
                            inp = block.get("input", {})
                            summary = f"🔧 {name}"
                            if "file_path" in inp:
                                summary += f" → {inp['file_path']}"
                            elif "command" in inp:
                                summary += f" → {inp['command'][:80]}"
                            elif "pattern" in inp:
                                summary += f" → {inp['pattern']}"
                            elif "query" in inp:
                                summary += f" → {inp['query'][:80]}"
                            await safe_send({"type": "output", "data": summary + "\n"})
                        elif bt == "thinking":
                            # Extended thinking -- show brief indicator
                            await safe_send({"type": "output", "data": "💭 Thinking...\n"})

                elif etype == "result":
                    sub = event.get("subtype", "")
                    cost = event.get("cost_usd", 0)
                    dur_s = event.get("duration_ms", 0) / 1000
                    if sub == "success":
                        await safe_send({"type": "output", "data": f"\n✅ Completed (${cost:.4f}, {dur_s:.1f}s)\n"})
                    else:
                        err = event.get("error", "Unknown error")
                        await safe_send({"type": "output", "data": f"\n❌ Error: {err}\n"})
                    _tel_detect(session_id, f"RESULT: {sub}", project)

            while True:
                try:
                    chunk = await loop.run_in_executor(
                        None, lambda: child.read_nonblocking(size=32768, timeout=1.0)
                    )
                    if chunk:
                        # Normalize pty line endings
                        chunk = chunk.replace('\r\n', '\n').replace('\r', '\n')
                        line_buf += chunk

                        # Process complete JSON lines
                        while '\n' in line_buf:
                            line, line_buf = line_buf.split('\n', 1)
                            line = line.strip()
                            if not line:
                                continue
                            try:
                                event = json.loads(line)
                                await _handle_event(event)
                            except json.JSONDecodeError:
                                # Not JSON -- raw text fallback
                                if line:
                                    await safe_send({"type": "output", "data": line + "\n"})

                except pexpect.TIMEOUT:
                    if not child.isalive():
                        # Flush remaining buffer
                        if line_buf.strip():
                            for part in line_buf.strip().split('\n'):
                                part = part.strip()
                                if not part:
                                    continue
                                try:
                                    event = json.loads(part)
                                    await _handle_event(event)
                                except json.JSONDecodeError:
                                    await safe_send({"type": "output", "data": part + "\n"})
                        break
                    continue
                except pexpect.EOF:
                    if line_buf.strip():
                        for part in line_buf.strip().split('\n'):
                            part = part.strip()
                            if not part:
                                continue
                            try:
                                event = json.loads(part)
                                await _handle_event(event)
                            except json.JSONDecodeError:
                                await safe_send({"type": "output", "data": part + "\n"})
                    break

        async def _read_kiro_output(session_id, child, loop, safe_send):
            """Read Kiro CLI line-based output."""
            thinking_sent = False
            line_buf = ""
            last_send_time = 0
            import time

            while True:
                try:
                    chunk = await loop.run_in_executor(None, lambda: child.read_nonblocking(size=16384, timeout=0.5))
                    if chunk:
                        clean = ANSI_RE.sub('', chunk)
                        # Kiro CLI: detect "Thinking..." spinner
                        if KIRO_SPINNER_RE.search(clean):
                            if not thinking_sent:
                                if line_buf:
                                    await safe_send({"type": "output", "data": line_buf + "\n"})
                                    line_buf = ""
                                await safe_send({"type": "output", "data": "⏳ Thinking...\n"})
                                thinking_sent = True
                            continue

                        # Handle \r -- kiro streams char by char with \r to redraw
                        for ch in clean:
                            if ch == '\r':
                                continue
                            elif ch == '\n':
                                thinking_sent = False
                                _tel_detect(session_id, line_buf, project)
                                await safe_send({"type": "output", "data": line_buf + "\n"})
                                line_buf = ""
                            else:
                                line_buf += ch

                        now = time.time()
                        if line_buf and (now - last_send_time > 0.5):
                            thinking_sent = False
                            await safe_send({"type": "output", "data": line_buf})
                            line_buf = ""
                            last_send_time = now

                except pexpect.TIMEOUT:
                    if line_buf:
                        thinking_sent = False
                        await safe_send({"type": "output", "data": line_buf + "\n"})
                        line_buf = ""
                    if not child.isalive():
                        break
                    continue
                except pexpect.EOF:
                    if line_buf.strip():
                        await safe_send({"type": "output", "data": line_buf + "\n"})
                    break

        reader = asyncio.create_task(read_output())

        # Server-side keepalive — prevents proxy/browser idle timeouts
        async def _keepalive():
            while child.isalive():
                await asyncio.sleep(15)
                await safe_send({"type": "ping"})

        keepalive = asyncio.create_task(_keepalive())

        try:
            while child.isalive():
                try:
                    msg = await asyncio.wait_for(ws.receive_json(), timeout=1)
                    if msg.get("type") == "ping":
                        await safe_send({"type": "pong"})
                    elif msg.get("type") == "input":
                        text = msg.get("data", "")
                        child.send(text + '\r')
                except asyncio.TimeoutError:
                    continue
                except Exception:
                    break
        except Exception:
            pass

        keepalive.cancel()

        await reader

        child.close()
        done_msg = {"type": "done", "exitCode": child.exitstatus or 0}
        if _captured_claude_session_id["value"]:
            done_msg["claude_session_id"] = _captured_claude_session_id["value"]
        tel_log(tel_logger, "DONE", session_id=session_id, project=project,
                exit_code=child.exitstatus or 0,
                claude_sid=_captured_claude_session_id["value"] or "")
        await safe_send(done_msg)
    except Exception as e:
        tel_log(tel_logger, "ERROR", session_id=session_id, project=project,
                level="error", error=str(e))
        try:
            await ws.send_json({"type": "error", "data": str(e)})
        except:
            pass
    finally:
        if ws_child_key:
            _active_children.pop(ws_child_key, None)
        if child and child.isalive():
            child.terminate(force=True)
        tel_log(tel_logger, "WS_CLOSED", session_id=session_id, project=project)
