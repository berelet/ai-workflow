"""Server-side task queue runner.

Executes queue items sequentially — fully server-side, no JS dependency.
Each item spawns a terminal session (non-interactive -p mode).
After each session exits, a supervisor (haiku, fast) analyzes the output
and decides: task done → next, error → retry/skip, infra issue → wait+retry.
"""
import asyncio
import json as _json
import logging
import os
import re
import uuid
from datetime import datetime, timezone

import pexpect
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from dashboard.db.engine import async_session
from dashboard.db.models.backlog import BacklogItem
from dashboard.db.models.pipeline import PipelineDefinition
from dashboard.db.models.project import Project
from dashboard.db.models.task_queue import TaskQueue, TaskQueueItem

logger = logging.getLogger("services.queue_runner")

# Active queue runners: queue_id -> asyncio.Task
_active_runners: dict[str, asyncio.Task] = {}

TASK_TIMEOUT = 3600        # 60 min per task
MAX_RETRIES = 2            # retry on infra errors
RETRY_DELAY = 30           # seconds before retry
SUPERVISOR_MODEL = "haiku" # fast + cheap for analysis
OUTPUT_TAIL_SIZE = 3000    # last N chars sent to supervisor


async def start_queue(queue_id: uuid.UUID, user_id: uuid.UUID) -> None:
    """Start executing a queue. Launches a background asyncio task."""
    qid = str(queue_id)
    if qid in _active_runners and not _active_runners[qid].done():
        logger.warning("Queue %s already running", qid)
        return

    task = asyncio.create_task(_run_queue(queue_id, user_id))
    _active_runners[qid] = task
    task.add_done_callback(lambda t: _active_runners.pop(qid, None))
    logger.info("Queue runner started: %s", qid)


async def cancel_queue(queue_id: uuid.UUID) -> None:
    """Cancel a running queue."""
    qid = str(queue_id)
    task = _active_runners.get(qid)
    if task and not task.done():
        task.cancel()
        logger.info("Queue runner cancelled: %s", qid)

    async with async_session() as db:
        queue = await db.get(TaskQueue, queue_id)
        if queue and queue.status == "running":
            queue.status = "cancelled"
            queue.completed_at = datetime.now(timezone.utc)
            await db.execute(
                update(TaskQueueItem).where(
                    TaskQueueItem.queue_id == queue_id,
                    TaskQueueItem.status == "pending",
                ).values(status="skipped")
            )
            await db.commit()


# ── Main queue loop ──────────────────────────────────────────────

async def _run_queue(queue_id: uuid.UUID, user_id: uuid.UUID) -> None:
    """Main queue execution loop."""
    async with async_session() as db:
        queue = await db.get(TaskQueue, queue_id)
        if not queue:
            return
        project = await db.get(Project, queue.project_id)
        pipeline_def = await db.get(PipelineDefinition, queue.pipeline_def_id)
        if not project or not pipeline_def:
            queue.status = "failed"
            queue.completed_at = datetime.now(timezone.utc)
            await db.commit()
            return
        queue.status = "running"
        queue.started_at = datetime.now(timezone.utc)
        await db.commit()

    try:
        while True:
            async with async_session() as db:
                queue = await db.get(TaskQueue, queue_id)
                if not queue or queue.status != "running":
                    return

                result = await db.execute(
                    select(TaskQueueItem).where(
                        TaskQueueItem.queue_id == queue_id,
                        TaskQueueItem.status == "pending",
                    ).order_by(TaskQueueItem.sort_order).limit(1)
                )
                item = result.scalar_one_or_none()
                if not item:
                    queue.status = "completed"
                    queue.completed_at = datetime.now(timezone.utc)
                    await db.commit()
                    logger.info("Queue %s completed", queue_id)
                    return

                backlog_item = await db.get(BacklogItem, item.backlog_item_id)
                if not backlog_item:
                    item.status = "skipped"
                    item.error_message = "Task not found"
                    await db.commit()
                    continue

                item.status = "running"
                item.started_at = datetime.now(timezone.utc)
                await db.commit()

                task_id = backlog_item.sequence_number
                task_display = backlog_item.task_id_display

            # Run task with retries
            logger.info("Queue %s: task %s", queue_id, task_display)
            success = False
            error_msg = None

            for attempt in range(1, MAX_RETRIES + 1):
                try:
                    exit_code, output_tail = await asyncio.wait_for(
                        _run_single_task(project, pipeline_def, task_id, user_id, item.id),
                        timeout=TASK_TIMEOUT,
                    )
                except asyncio.TimeoutError:
                    exit_code, output_tail = -1, "Task timed out after 30 minutes"
                except asyncio.CancelledError:
                    raise
                except Exception as e:
                    exit_code, output_tail = -1, str(e)

                # Ask supervisor to analyze
                verdict = await _supervisor_analyze(
                    project_slug=project.slug,
                    task_display=task_display,
                    exit_code=exit_code,
                    output_tail=output_tail,
                    attempt=attempt,
                    user_id=user_id,
                )

                logger.info(
                    "Queue %s: task %s attempt %d → supervisor: %s",
                    queue_id, task_display, attempt, verdict,
                )

                if verdict["action"] == "done":
                    success = True
                    break
                elif verdict["action"] == "retry":
                    error_msg = verdict.get("reason", "retrying")
                    delay = verdict.get("delay", RETRY_DELAY)
                    logger.info("Queue %s: retrying task %s in %ds — %s", queue_id, task_display, delay, error_msg)
                    await asyncio.sleep(delay)
                    # Re-dump backlog before retry
                    continue
                else:  # skip / fail
                    error_msg = verdict.get("reason", f"exit code {exit_code}")
                    break

            # Update item & backlog
            async with async_session() as db:
                item = await db.get(TaskQueueItem, item.id)
                if item:
                    item.status = "completed" if success else "failed"
                    item.completed_at = datetime.now(timezone.utc)
                    if error_msg and not success:
                        item.error_message = error_msg[:1000]

                if success:
                    bi = await db.get(BacklogItem, item.backlog_item_id)
                    pd = await db.get(PipelineDefinition, queue.pipeline_def_id) if queue else None
                    final_status = pd.final_task_status if pd else "done"
                    if bi:
                        bi.status = final_status or "done"
                await db.commit()

            if not success:
                async with async_session() as db:
                    queue = await db.get(TaskQueue, queue_id)
                    if queue and queue.stop_on_error:
                        queue.status = "failed"
                        queue.completed_at = datetime.now(timezone.utc)
                        await db.execute(
                            update(TaskQueueItem).where(
                                TaskQueueItem.queue_id == queue_id,
                                TaskQueueItem.status == "pending",
                            ).values(status="skipped")
                        )
                        await db.commit()
                        return

    except asyncio.CancelledError:
        logger.info("Queue %s cancelled", queue_id)
    except Exception as e:
        logger.error("Queue %s error: %s", queue_id, e, exc_info=True)
        async with async_session() as db:
            queue = await db.get(TaskQueue, queue_id)
            if queue:
                queue.status = "failed"
                queue.completed_at = datetime.now(timezone.utc)
                await db.commit()


# ── Run single task (no auto-input) ──────────────────────────────

async def _run_single_task(
    project: Project,
    pipeline_def: PipelineDefinition,
    task_id: int,
    user_id: uuid.UUID,
    queue_item_id: uuid.UUID,
) -> tuple[int, str]:
    """Run one task via orchestrator. Returns (exit_code, last_output_tail)."""
    from dashboard.helpers import BASE
    from dashboard.routers.terminal import (
        _poll_sessions, _active_children, _build_cmd_poll,
        _dump_backlog_to_files, _dump_pipelines_to_files, _dump_agents_to_files,
        ANSI_RE,
    )

    project_slug = project.slug
    session_id = uuid.uuid4().hex
    user_id_str = str(user_id)
    child_key = f"{user_id_str}:{project_slug}"

    # Resolve CWD
    cwd = str(BASE)
    try:
        cfg_path = BASE / "projects" / project_slug / "pipeline-config.json"
        if cfg_path.exists():
            cfg = _json.loads(cfg_path.read_text(encoding="utf-8"))
            if "project_dir" in cfg and os.path.isdir(cfg["project_dir"]):
                cwd = cfg["project_dir"]
    except Exception:
        pass

    # Dump data
    try:
        await _dump_backlog_to_files(project_slug, cwd)
        await _dump_pipelines_to_files(project_slug)
        await _dump_agents_to_files()
    except Exception:
        pass

    # Get user lang
    async with async_session() as db:
        from dashboard.db.models.user import User
        user = await db.get(User, user_id)
        lang = user.lang if user else "en"

    # Build prompt
    graph_json = _json.dumps(pipeline_def.graph_json, ensure_ascii=False)
    prompt = (
        f"read orchestrator/instructions.md, project {project_slug}, "
        f"take task {task_id}, pipeline \"{pipeline_def.name}\". "
        f"Language: {lang}\n\n"
        f"IMPORTANT: This is an automated queue run. Execute ALL pipeline stages "
        f"without stopping. Do NOT ask for confirmation between stages — "
        f"proceed automatically. Commit and push at the end.\n\n"
        f"Pipeline graph (Drawflow JSON):\n{graph_json}"
    )

    # Build command
    model = os.environ.get("DEFAULT_MODEL", "claude-opus-4-6")
    cli = os.environ.get("DEFAULT_CLI", "claude")
    cmd, args = _build_cmd_poll(cli, model, prompt, max_turns=200)

    env = os.environ.copy()
    for key in ['CLAUDECODE', 'CLAUDE_CODE', 'CLAUDE_CONVERSATION_ID',
                'CLAUDE_CODE_SSE_PORT', 'CLAUDE_CODE_ENTRYPOINT']:
        env.pop(key, None)

    # Register session for UI monitoring
    _poll_sessions[session_id] = {
        "chunks": [], "done": False, "cursor": 0, "exitCode": None,
        "claude_session_id": None, "project": project_slug,
        "user_id": user_id_str, "queue_item_id": str(queue_item_id),
    }

    async with async_session() as db:
        qi = await db.get(TaskQueueItem, queue_item_id)
        if qi:
            qi.terminal_session_id = session_id
            await db.commit()

    # Spawn process
    loop = asyncio.get_event_loop()
    child = await loop.run_in_executor(
        None, lambda: pexpect.spawn(cmd, args, cwd=cwd, encoding='utf-8', timeout=300, env=env)
    )
    child.setwinsize(200, 500)

    old = _active_children.pop(child_key, None)
    if old and old.isalive():
        old.terminate(force=True)
    _active_children[child_key] = child

    logger.info("[%s] Task started: project=%s task=%d", session_id, project_slug, task_id)

    # Read output — no auto-input, just collect
    sess = _poll_sessions[session_id]
    output_buf = []  # rolling buffer for supervisor

    _secret_re = re.compile(
        r'(?i)(?:password|passwd|pwd|secret|token|api[_-]?key|auth|credential)s?\s*[=:]\s*\S+'
        r'|(?:PGPASSWORD|AWS_SECRET|DATABASE_URL|DB_PASS)\s*=\s*\S+'
        r'|(?<=://)[^:]+:[^@]+(?=@)'
    )

    if cli == "claude":
        line_buf = ""
        while True:
            try:
                chunk = await loop.run_in_executor(
                    None, lambda: child.read_nonblocking(size=16384, timeout=0.5)
                )
                if chunk:
                    clean = ANSI_RE.sub('', chunk)
                    for raw_line in (line_buf + clean).split('\n'):
                        raw_line = raw_line.strip()
                        if not raw_line:
                            continue
                        if raw_line.startswith('{'):
                            try:
                                event = _json.loads(raw_line)
                                line_buf = ""
                                etype = event.get("type", "")
                                if etype == "assistant":
                                    msg = event.get("message", {})
                                    for block in msg.get("content", []):
                                        if block.get("type") == "text":
                                            text = block.get("text", "")
                                            if text.strip():
                                                masked = _secret_re.sub('***', text)
                                                sess["chunks"].append(masked + "\n")
                                                output_buf.append(text)
                                        elif block.get("type") == "tool_use":
                                            name = block.get("name", "?")
                                            inp = block.get("input", {})
                                            s = f"🔧 {name}"
                                            if "file_path" in inp:
                                                s += f" {inp['file_path']}"
                                            elif "command" in inp:
                                                s += f" $ {inp['command'][:80]}"
                                            sess["chunks"].append(s + "\n")
                                            output_buf.append(s)
                                elif etype == "result":
                                    rt = event.get("result", "")
                                    if rt.strip():
                                        sess["chunks"].append(rt + "\n")
                                        output_buf.append(rt)
                            except _json.JSONDecodeError:
                                line_buf = raw_line
                        else:
                            if raw_line:
                                sess["chunks"].append(raw_line + "\n")
                                output_buf.append(raw_line)
            except pexpect.TIMEOUT:
                if not child.isalive():
                    break
            except pexpect.EOF:
                break
    else:
        # kiro
        while True:
            try:
                chunk = await loop.run_in_executor(
                    None, lambda: child.read_nonblocking(size=16384, timeout=0.5)
                )
                if chunk:
                    clean = ANSI_RE.sub('', chunk)
                    sess["chunks"].append(clean)
                    output_buf.append(clean)
            except pexpect.TIMEOUT:
                if not child.isalive():
                    break
            except pexpect.EOF:
                break

    exit_code = child.exitstatus if child.exitstatus is not None else -1
    sess["done"] = True
    sess["exitCode"] = exit_code
    _active_children.pop(child_key, None)
    child.close()

    # Build output tail for supervisor
    full_output = "\n".join(output_buf)
    tail = full_output[-OUTPUT_TAIL_SIZE:] if len(full_output) > OUTPUT_TAIL_SIZE else full_output

    logger.info("[%s] Task finished: exit=%d output=%d chars", session_id, exit_code, len(full_output))
    return exit_code, tail


# ── Supervisor ───────────────────────────────────────────────────

SUPERVISOR_PROMPT = """\
You are a pipeline supervisor. A CI/CD-like pipeline just finished running a task.
Analyze the output and respond with ONLY a JSON object (no markdown, no explanation):

{{
  "action": "done" | "retry" | "skip",
  "reason": "brief explanation",
  "delay": <seconds before retry, only if action=retry, default 30>,
  "completed_stages": ["PM", "BA", "DEV", ...],
  "committed": true/false,
  "infra_error": true/false
}}

Rules:
- "done": all pipeline stages completed successfully
- "retry": transient error (VPN drop, DB connection, timeout) — worth retrying
- "skip": permanent error (code bug, missing files, auth issue) — move to next task
- Set infra_error=true if you see connection errors, timeouts, VPN, DNS, or DB issues
- Set committed=true if you see evidence of git commit/push in the output

Task: {task_display}
Exit code: {exit_code}
Attempt: {attempt}/{max_retries}

=== LAST OUTPUT ===
{output_tail}
"""


async def _supervisor_analyze(
    project_slug: str,
    task_display: str,
    exit_code: int,
    output_tail: str,
    attempt: int,
    user_id: uuid.UUID,
) -> dict:
    """Call supervisor (haiku) to analyze task output and decide next action."""

    # Fast path: exit 0 with no obvious errors
    if exit_code == 0 and output_tail and "error" not in output_tail.lower()[-500:]:
        return {"action": "done", "reason": "exit code 0"}

    prompt = SUPERVISOR_PROMPT.format(
        task_display=task_display,
        exit_code=exit_code,
        attempt=attempt,
        max_retries=MAX_RETRIES,
        output_tail=output_tail[-OUTPUT_TAIL_SIZE:] if output_tail else "(no output)",
    )

    try:
        loop = asyncio.get_event_loop()
        cmd = "claude"
        args = ["-p", "--model", SUPERVISOR_MODEL, "--output-format", "text",
                "--max-turns", "1", "--dangerously-skip-permissions", prompt]

        child = await loop.run_in_executor(
            None, lambda: pexpect.spawn(cmd, args, encoding='utf-8', timeout=60)
        )

        output = ""
        while True:
            try:
                chunk = await loop.run_in_executor(
                    None, lambda: child.read_nonblocking(size=8192, timeout=0.5)
                )
                if chunk:
                    output += chunk
            except pexpect.TIMEOUT:
                if not child.isalive():
                    break
            except pexpect.EOF:
                break
        child.close()

        # Parse JSON from output
        # Strip ANSI and find JSON
        clean = re.sub(r'\x1b\[[0-9;]*[a-zA-Z]', '', output).strip()
        # Find JSON object in the output
        match = re.search(r'\{[^{}]*\}', clean, re.DOTALL)
        if match:
            result = _json.loads(match.group())
            if "action" in result:
                return result

        logger.warning("Supervisor returned unparseable: %s", clean[:200])
    except Exception as e:
        logger.error("Supervisor error: %s", e)

    # Fallback: simple heuristic
    if exit_code == 0:
        return {"action": "done", "reason": "exit code 0 (supervisor unavailable)"}
    if attempt < MAX_RETRIES:
        return {"action": "retry", "reason": f"exit code {exit_code}, retrying", "delay": RETRY_DELAY}
    return {"action": "skip", "reason": f"exit code {exit_code} after {attempt} attempts"}


def get_active_runners() -> list[str]:
    """Return list of active queue IDs."""
    return [qid for qid, t in _active_runners.items() if not t.done()]
