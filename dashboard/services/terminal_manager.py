"""Terminal session manager.

Manages pexpect child processes for AI CLI sessions (Claude Code, Kiro CLI).
Each session is identified by user_id + project_id.
"""
import asyncio
import logging
import os
import uuid
from pathlib import Path

import pexpect

logger = logging.getLogger("services.terminal_manager")

# Environment vars to strip to avoid nested Claude Code session errors
_STRIP_ENV = [
    "CLAUDECODE", "CLAUDE_CODE", "CLAUDE_CONVERSATION_ID",
    "CLAUDE_CODE_SSE_PORT", "CLAUDE_CODE_ENTRYPOINT",
]


def _build_cmd(
    provider: str,
    model: str,
    prompt: str,
    resume_id: str | None = None,
) -> tuple[str, list[str]]:
    """Build CLI command for the given provider."""
    if provider == "claude":
        args = [
            "-p",
            "--verbose",
            "--model", model,
            "--output-format", "stream-json",
            "--dangerously-skip-permissions",
        ]
        if resume_id:
            args += ["--resume", resume_id]
        args.append(prompt)
        return "claude", args
    else:
        return "kiro-cli", ["chat", "--model", model, "--trust-all-tools", prompt]


def _clean_env(extra_env: dict | None = None) -> dict:
    """Create clean environment for child process."""
    env = os.environ.copy()
    for key in _STRIP_ENV:
        env.pop(key, None)
    if extra_env:
        env.update(extra_env)
    return env


def _session_key(user_id: uuid.UUID | str, project_id: uuid.UUID | str) -> str:
    """Generate tmux-compatible session key."""
    return f"user_{user_id}_project_{project_id}"


class TerminalSession:
    """Represents an active terminal session."""

    def __init__(
        self,
        session_id: str,
        user_id: uuid.UUID,
        project_id: uuid.UUID,
        child: pexpect.spawn,
        provider: str,
        model: str,
    ):
        self.session_id = session_id
        self.user_id = user_id
        self.project_id = project_id
        self.child = child
        self.provider = provider
        self.model = model
        self.claude_session_id: str | None = None


class TerminalManager:
    """Manages pexpect child processes for AI CLI sessions."""

    def __init__(self):
        self._active: dict[str, TerminalSession] = {}  # session_key -> session

    async def spawn_session(
        self,
        user_id: uuid.UUID,
        project_id: uuid.UUID,
        prompt: str,
        cwd: str,
        provider: str = "claude",
        model: str = "claude-opus-4-6",
        claude_session_id: str | None = None,
        git_env: dict | None = None,
    ) -> TerminalSession:
        """Spawn a new CLI session for a user+project.

        Kills any existing session for the same user+project.
        """
        key = _session_key(user_id, project_id)

        # Kill existing session for this user+project
        existing = self._active.get(key)
        if existing and existing.child.isalive():
            logger.info("Killing existing session for %s", key)
            existing.child.terminate(force=True)

        session_id = str(uuid.uuid4())[:8]
        env = _clean_env(git_env)

        # Spawn in executor to avoid blocking
        loop = asyncio.get_running_loop()

        def _spawn():
            cmd, args = _build_cmd(provider, model, prompt, resume_id=claude_session_id)
            child = pexpect.spawn(
                cmd, args,
                cwd=cwd,
                encoding="utf-8",
                timeout=None,  # no read timeout — AI agents can take 30+ minutes
                env=env,
            )
            child.setwinsize(200, 500)
            return child

        child = await loop.run_in_executor(None, _spawn)

        session = TerminalSession(
            session_id=session_id,
            user_id=user_id,
            project_id=project_id,
            child=child,
            provider=provider,
            model=model,
        )
        session.claude_session_id = claude_session_id
        self._active[key] = session

        logger.info(
            "Spawned session %s for %s (%s/%s) in %s",
            session_id, key, provider, model, cwd,
        )
        return session

    def get_session(self, user_id: uuid.UUID, project_id: uuid.UUID) -> TerminalSession | None:
        """Get active session for user+project."""
        key = _session_key(user_id, project_id)
        session = self._active.get(key)
        if session and not session.child.isalive():
            del self._active[key]
            return None
        return session

    def get_active_sessions(self, project_id: uuid.UUID | None = None) -> list[TerminalSession]:
        """List active sessions, optionally filtered by project."""
        alive = []
        dead_keys = []
        for key, session in self._active.items():
            if not session.child.isalive():
                dead_keys.append(key)
                continue
            if project_id and session.project_id != project_id:
                continue
            alive.append(session)
        for key in dead_keys:
            del self._active[key]
        return alive

    async def kill_session(self, user_id: uuid.UUID, project_id: uuid.UUID) -> bool:
        """Kill a session. Returns True if session was running."""
        key = _session_key(user_id, project_id)
        session = self._active.pop(key, None)
        if session and session.child.isalive():
            session.child.terminate(force=True)
            logger.info("Killed session %s for %s", session.session_id, key)
            return True
        return False

    async def send_input(self, user_id: uuid.UUID, project_id: uuid.UUID, text: str) -> bool:
        """Send input to an active session."""
        session = self.get_session(user_id, project_id)
        if not session:
            return False
        loop = asyncio.get_running_loop()
        await loop.run_in_executor(None, lambda: session.child.send(text + "\r"))
        return True


# Singleton
terminal_manager = TerminalManager()
