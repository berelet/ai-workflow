"""Git branch management for pipeline tasks.

Creates per-task branches, ensures correct branch before each stage,
merges or creates PRs after pipeline completion.
"""
import asyncio
import logging
import os
import re
import tempfile
from pathlib import Path

logger = logging.getLogger("services.git_manager")


class GitError(Exception):
    """Raised when a git operation fails."""


async def _run_git(args: list[str], cwd: str, env: dict | None = None) -> tuple[int, str, str]:
    """Run a git command async. Returns (returncode, stdout, stderr)."""
    cmd_env = os.environ.copy()
    if env:
        cmd_env.update(env)
    proc = await asyncio.create_subprocess_exec(
        "git", *args,
        cwd=cwd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        env=cmd_env,
    )
    stdout, stderr = await proc.communicate()
    return proc.returncode, stdout.decode("utf-8", errors="replace"), stderr.decode("utf-8", errors="replace")


def _slugify(text: str, max_len: int = 50) -> str:
    """Convert text to git-branch-safe slug."""
    slug = re.sub(r'[^a-zA-Z0-9\-]', '-', text.lower())
    slug = re.sub(r'-+', '-', slug).strip('-')
    return slug[:max_len]


class _SSHKeyContext:
    """Context manager that writes decrypted SSH key to a temp file and cleans up."""

    def __init__(self, encrypted_key: str | None):
        self.encrypted_key = encrypted_key
        self._tmp_path: str | None = None

    def __enter__(self) -> dict | None:
        if not self.encrypted_key:
            return None
        from dashboard.auth.crypto import decrypt_ssh_key
        key_content = decrypt_ssh_key(self.encrypted_key)
        fd, self._tmp_path = tempfile.mkstemp(suffix=".key")
        with os.fdopen(fd, "w") as f:
            f.write(key_content)
        os.chmod(self._tmp_path, 0o600)
        return {"GIT_SSH_COMMAND": f"ssh -i {self._tmp_path} -o StrictHostKeyChecking=no"}

    def __exit__(self, *exc):
        if self._tmp_path and os.path.exists(self._tmp_path):
            os.unlink(self._tmp_path)
            self._tmp_path = None


class GitManager:

    async def create_task_branch(
        self,
        repo_path: str,
        prefix: str,
        task_id: int | str,
        task_title: str,
        base_branch: str,
        ssh_key_encrypted: str | None = None,
    ) -> str:
        """Create a branch for a task. Returns branch name.

        base_branch is now required — pass Project.base_branch from the caller.
        """
        if not base_branch:
            raise GitError("base_branch is required (set Project.base_branch)")
        slug = _slugify(task_title)
        branch_name = f"{prefix}-{task_id}/{slug}" if slug else f"{prefix}-{task_id}"

        with _SSHKeyContext(ssh_key_encrypted) as env:
            # Fetch latest
            rc, _, err = await _run_git(["fetch", "origin"], cwd=repo_path, env=env)
            if rc != 0:
                logger.warning("git fetch failed (may be offline): %s", err.strip())

            # Ensure base branch is up to date
            rc, _, _ = await _run_git(["checkout", base_branch], cwd=repo_path, env=env)
            if rc != 0:
                rc, _, err = await _run_git(
                    ["checkout", "-b", base_branch, f"origin/{base_branch}"],
                    cwd=repo_path, env=env,
                )
                if rc != 0:
                    raise GitError(f"Cannot checkout {base_branch}: {err.strip()}")

            await _run_git(["pull", "origin", base_branch], cwd=repo_path, env=env)

            # Create task branch (or checkout if exists)
            rc, _, err = await _run_git(["checkout", "-b", branch_name], cwd=repo_path, env=env)
            if rc != 0:
                rc, _, err = await _run_git(["checkout", branch_name], cwd=repo_path, env=env)
                if rc != 0:
                    raise GitError(f"Cannot create/checkout branch {branch_name}: {err.strip()}")
                await _run_git(["pull", "origin", branch_name], cwd=repo_path, env=env)

        logger.info("Task branch ready: %s in %s", branch_name, repo_path)
        return branch_name

    async def ensure_branch(
        self,
        repo_path: str,
        branch_name: str,
        ssh_key_encrypted: str | None = None,
    ) -> bool:
        """Ensure we're on the correct branch, switch + pull if needed."""
        with _SSHKeyContext(ssh_key_encrypted) as env:
            # Check current branch
            rc, current, _ = await _run_git(["branch", "--show-current"], cwd=repo_path)
            current = current.strip()

            if current != branch_name:
                # Check for uncommitted changes
                rc, status, _ = await _run_git(["status", "--porcelain"], cwd=repo_path)
                if status.strip():
                    raise GitError(
                        f"Cannot switch to {branch_name}: uncommitted changes on {current}. "
                        f"Files: {status.strip()[:200]}"
                    )
                rc, _, err = await _run_git(["checkout", branch_name], cwd=repo_path, env=env)
                if rc != 0:
                    raise GitError(f"Cannot checkout {branch_name}: {err.strip()}")

            # Pull latest
            rc, out, err = await _run_git(["pull", "origin", branch_name], cwd=repo_path, env=env)
            if rc != 0:
                combined = out + err
                if "CONFLICT" in combined:
                    await _run_git(["merge", "--abort"], cwd=repo_path)
                    conflicts = await self.detect_conflicts(repo_path)
                    raise GitError(f"Merge conflicts on pull: {', '.join(conflicts)}")
                logger.debug("Pull failed (no remote?): %s", err.strip())

        return True

    async def merge_to_base(
        self,
        repo_path: str,
        branch_name: str,
        base_branch: str,
        strategy: str = "merge",
        ssh_key_encrypted: str | None = None,
    ) -> dict:
        """Merge task branch to base or create PR.

        base_branch is now required — pass Project.base_branch from the caller.
        """
        if not base_branch:
            raise GitError("base_branch is required (set Project.base_branch)")
        with _SSHKeyContext(ssh_key_encrypted) as env:
            # Push task branch first
            rc, _, err = await _run_git(["push", "origin", branch_name], cwd=repo_path, env=env)
            if rc != 0:
                raise GitError(f"Cannot push {branch_name}: {err.strip()}")

            if strategy == "pr":
                proc = await asyncio.create_subprocess_exec(
                    "gh", "pr", "create",
                    "--title", f"Merge {branch_name}",
                    "--body", "Auto-generated PR from pipeline",
                    "--base", base_branch,
                    "--head", branch_name,
                    cwd=repo_path,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                )
                stdout_b, stderr_b = await proc.communicate()
                if proc.returncode != 0:
                    raise GitError(f"Cannot create PR: {stderr_b.decode().strip()}")
                pr_url = stdout_b.decode().strip()
                logger.info("PR created: %s", pr_url)
                return {"strategy": "pr", "pr_url": pr_url}

            else:
                # Auto-merge
                rc, _, err = await _run_git(["checkout", base_branch], cwd=repo_path, env=env)
                if rc != 0:
                    raise GitError(f"Cannot checkout {base_branch}: {err.strip()}")

                await _run_git(["pull", "origin", base_branch], cwd=repo_path, env=env)

                rc, out, err = await _run_git(["merge", branch_name, "--no-ff"], cwd=repo_path, env=env)
                if rc != 0:
                    combined = out + err
                    if "CONFLICT" in combined:
                        await _run_git(["merge", "--abort"], cwd=repo_path)
                        await _run_git(["checkout", branch_name], cwd=repo_path)
                        conflicts = await self.detect_conflicts(repo_path)
                        raise GitError(f"Merge conflicts: {', '.join(conflicts)}")
                    raise GitError(f"Merge failed: {err.strip()}")

                rc, _, err = await _run_git(["push", "origin", base_branch], cwd=repo_path, env=env)
                if rc != 0:
                    raise GitError(f"Cannot push {base_branch}: {err.strip()}")

                logger.info("Merged %s into %s", branch_name, base_branch)
                return {"strategy": "merge", "merged": True}

    async def detect_conflicts(self, repo_path: str) -> list[str]:
        """Return list of conflicted files."""
        rc, stdout, _ = await _run_git(["diff", "--name-only", "--diff-filter=U"], cwd=repo_path)
        return [f.strip() for f in stdout.splitlines() if f.strip()]

    async def get_current_branch(self, repo_path: str) -> str:
        """Get current branch name."""
        rc, stdout, _ = await _run_git(["branch", "--show-current"], cwd=repo_path)
        return stdout.strip()

    async def get_dirty_state(self, repo_path: str) -> dict:
        """Return dirty/unpushed status for a repo: {dirty: [...], unpushed: [...]}."""
        result = {"dirty": [], "unpushed": []}
        rc, stdout, _ = await _run_git(["status", "--porcelain"], cwd=repo_path)
        if rc == 0 and stdout.strip():
            result["dirty"] = [line.strip() for line in stdout.splitlines() if line.strip()]
        rc, stdout, _ = await _run_git(["log", "@{u}..HEAD", "--oneline"], cwd=repo_path)
        if rc == 0 and stdout.strip():
            result["unpushed"] = [line.strip() for line in stdout.splitlines() if line.strip()]
        return result

    async def checkout_branch(
        self,
        repo_path: str,
        branch: str,
        force: bool = False,
        ssh_key_encrypted: str | None = None,
    ) -> dict:
        """Checkout an existing branch (local or origin/<branch>).

        Returns {ok, branch, dirty, unpushed} on success.
        Raises GitError with structured info on failure.
        """
        branch = self.validate_branch_name(branch)

        # Refuse to switch if working tree is dirty unless force=True
        if not force:
            state = await self.get_dirty_state(repo_path)
            if state["dirty"] or state["unpushed"]:
                err = GitError("dirty_or_unpushed")
                err.dirty = state["dirty"]
                err.unpushed = state["unpushed"]
                raise err

        with _SSHKeyContext(ssh_key_encrypted) as env:
            # Try local checkout first
            rc, _, err_text = await _run_git(["checkout", branch], cwd=repo_path, env=env)
            if rc != 0:
                # Try fetching from origin and checking out as a tracking branch
                await _run_git(["fetch", "origin", branch], cwd=repo_path, env=env)
                rc2, _, err_text2 = await _run_git(
                    ["checkout", "-B", branch, f"origin/{branch}"],
                    cwd=repo_path, env=env,
                )
                if rc2 != 0:
                    raise GitError(f"Cannot checkout '{branch}': {err_text2.strip() or err_text.strip()}")

            # Best-effort pull (silent on no-upstream / network failure)
            await _run_git(["pull", "--ff-only", "origin", branch], cwd=repo_path, env=env)

        return {"ok": True, "branch": branch}

    async def get_branch_info(self, repo_path: str | None, prefix: str | None) -> dict:
        """Get branch info for the Run Pipeline modal.

        Returns dict with: branch (str|None), prefix (str|None), has_repo (bool)
        """
        if not repo_path:
            return {"branch": None, "prefix": None, "has_repo": False}

        repo = Path(repo_path)
        if not repo.exists() or not (repo / ".git").exists():
            return {"branch": None, "prefix": None, "has_repo": False}

        branch = await self.get_current_branch(repo_path)
        return {
            "branch": branch or None,
            "prefix": prefix.lower() if prefix else None,
            "has_repo": True,
        }

    @staticmethod
    def validate_branch_name(name: str) -> str:
        """Validate and sanitize a git branch name.

        Rejects names that could cause command injection or are invalid
        per git-check-ref-format rules.
        Raises GitError if invalid. Returns the validated name.
        """
        if not name or len(name) > 200:
            raise GitError("Branch name must be 1-200 characters")

        # Must match safe pattern: alphanumeric, hyphens, slashes, dots, underscores
        # No: spaces, ~, ^, :, ?, *, [, \, .., @{, leading/trailing dots/slashes
        if not re.match(r'^[a-zA-Z0-9][a-zA-Z0-9._/\-]*$', name):
            raise GitError("Branch name contains invalid characters")

        # Reject git ref-format violations and dangerous patterns
        forbidden = ['..', '~', '^', ':', '?', '*', '[', '\\', '@{', ' ']
        for pat in forbidden:
            if pat in name:
                raise GitError(f"Branch name must not contain '{pat}'")

        # Reject names starting with dash (could be interpreted as git flags)
        if name.startswith('-') or name.startswith('/'):
            raise GitError("Branch name must not start with '-' or '/'")

        # Reject trailing dot or .lock suffix
        if name.endswith('.') or name.endswith('.lock') or name.endswith('/'):
            raise GitError("Branch name must not end with '.', '.lock', or '/'")

        return name

    async def create_named_branch(self, repo_path: str, branch_name: str) -> str:
        """Create and checkout a new branch with the given name. Returns branch name."""
        branch_name = self.validate_branch_name(branch_name)

        rc, _, err = await _run_git(["checkout", "-b", branch_name], cwd=repo_path)
        if rc != 0:
            if "already exists" in err:
                raise GitError("Branch already exists")
            raise GitError("Cannot create branch")
        logger.info("Created branch: %s in %s", branch_name, repo_path)
        return branch_name


# Singleton
git_manager = GitManager()
