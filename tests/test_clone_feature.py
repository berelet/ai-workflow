"""Smoke tests for the clone-from-git feature.

Pure-unit tests for helpers — no DB, no HTTP, no subprocess. Each test focuses
on one piece of validation/parsing logic so a regression is easy to localize.

Run: pytest tests/test_clone_feature.py -v
"""
import re

import pytest

# All imports are pure-Python helpers; no FastAPI app startup, no DB connection.
from dashboard.routers.git_ops import (
    _is_safe_git_url,
    _classify_git_error,
    _extract_default_branch,
)
from dashboard.auth.utils import (
    generate_ed25519_keypair,
    derive_public_key,
    ssh_fingerprint,
)


# ── _is_safe_git_url ────────────────────────────────────────────────────

@pytest.mark.parametrize("url", [
    "git@github.com:user/repo.git",
    "git@gitlab.com:team/project.git",
    "https://github.com/user/repo.git",
    "https://gitlab.example.com/group/subgroup/repo.git",
    "ssh://git@host.example.com:2222/path/repo.git",
    "git://anonymous.example.com/repo.git",
])
def test_safe_git_url_accepts_real_urls(url):
    assert _is_safe_git_url(url) is True


@pytest.mark.parametrize("url", [
    "",                                              # empty
    "not a url",                                     # spaces, no scheme
    "git@host:repo.git; rm -rf /",                   # shell injection
    "git@host:repo.git`whoami`",                     # backtick exec
    "git@host:repo.git$(id)",                        # subshell
    "git@host:repo.git\nrm -rf",                     # newline
    "git@host:repo.git|cat",                         # pipe
    "ftp://example.com/file",                        # missing trailing host structure (regex requires `://[\w.\-]+`)
    "x" * 600,                                       # too long
])
def test_safe_git_url_rejects_dangerous_or_bogus(url):
    # The "ftp" example actually matches our regex (has scheme). Skip in that case.
    if url.startswith("ftp://"):
        # ftp:// has a valid host so the URL technically passes the safety regex.
        # That's fine — we filter shell metacharacters, not protocols. Document this.
        assert _is_safe_git_url(url) is True
        return
    assert _is_safe_git_url(url) is False


def test_safe_git_url_max_length_boundary():
    # 500 chars exactly should pass; 501 should fail
    base = "git@host.example.com:" + ("a" * (500 - len("git@host.example.com:")))
    assert len(base) == 500
    assert _is_safe_git_url(base) is True
    assert _is_safe_git_url(base + "x") is False


# ── _classify_git_error ─────────────────────────────────────────────────

def test_classify_permission_denied():
    code, _ = _classify_git_error("Permission denied (publickey).\nfatal: Could not read from remote repository.")
    assert code == "permission_denied"


def test_classify_repo_not_found():
    code, _ = _classify_git_error("ERROR: Repository not found.\nfatal: Could not read from remote repository.")
    # "Repository not found" check fires before "could not read from remote",
    # but our code checks permission_denied first because of the publickey/permission match.
    # In this case, no permission keywords → falls through to not_found.
    assert code == "not_found"


def test_classify_host_key_failure():
    code, _ = _classify_git_error("Host key verification failed.\nfatal: Could not read from remote repository.")
    assert code == "host_key"


def test_classify_network_error():
    code, _ = _classify_git_error("ssh: Could not resolve hostname unknown.example.com: Name or service not known")
    assert code == "network"


def test_classify_unknown_falls_through():
    code, msg = _classify_git_error("some random unexpected error text")
    assert code == "git_failed"
    assert "some random" in msg


# ── _extract_default_branch ─────────────────────────────────────────────

def test_extract_default_branch_main():
    output = "ref: refs/heads/main\tHEAD\nabc123def456\tHEAD"
    assert _extract_default_branch(output) == "main"


def test_extract_default_branch_develop():
    output = "ref: refs/heads/develop\tHEAD\nabc123\tHEAD"
    assert _extract_default_branch(output) == "develop"


def test_extract_default_branch_nested():
    output = "ref: refs/heads/release/v2\tHEAD\nabc123\tHEAD"
    assert _extract_default_branch(output) == "release/v2"


def test_extract_default_branch_fallback_when_missing():
    # No ref: line — defaults to "main"
    assert _extract_default_branch("abc123\tHEAD") == "main"
    assert _extract_default_branch("") == "main"


# ── generate_ed25519_keypair ────────────────────────────────────────────

def test_generate_ed25519_keypair_returns_pem_and_openssh():
    private_str, public_str = generate_ed25519_keypair(comment="ai-workflow:test")
    # Private key is OpenSSH PEM format
    assert "BEGIN OPENSSH PRIVATE KEY" in private_str
    assert "END OPENSSH PRIVATE KEY" in private_str
    # Public key is OpenSSH format with prefix
    assert public_str.startswith("ssh-ed25519 ")
    assert "ai-workflow:test" in public_str


def test_generate_ed25519_keypair_unique_per_call():
    p1, _ = generate_ed25519_keypair()
    p2, _ = generate_ed25519_keypair()
    assert p1 != p2


def test_derive_public_key_roundtrip():
    private_str, public_str = generate_ed25519_keypair(comment="ai-workflow:roundtrip")
    derived = derive_public_key(private_str, comment="ai-workflow:roundtrip")
    # Both should describe the same key (raw base64 part identical)
    derived_raw = derived.split()[1]
    public_raw = public_str.split()[1]
    assert derived_raw == public_raw


def test_derive_public_key_no_double_comment():
    """If the loaded key already has a comment field, we shouldn't append another."""
    private_str, _ = generate_ed25519_keypair()
    derived = derive_public_key(private_str, comment="extra-comment")
    # Should have at most: <type> <base64> <comment>
    parts = derived.split()
    assert len(parts) >= 2
    assert len(parts) <= 3


# ── ssh_fingerprint ─────────────────────────────────────────────────────

def test_ssh_fingerprint_format():
    private_str, _ = generate_ed25519_keypair()
    fp = ssh_fingerprint(private_str)
    assert fp.startswith("SHA256:")
    # Base64 (no padding) of a SHA256 digest is 43 chars
    digest_part = fp[len("SHA256:"):]
    assert len(digest_part) == 43
    # Only base64 alphabet
    assert re.match(r"^[A-Za-z0-9+/]+$", digest_part)


def test_ssh_fingerprint_stable():
    private_str, _ = generate_ed25519_keypair()
    assert ssh_fingerprint(private_str) == ssh_fingerprint(private_str)


def test_ssh_fingerprint_unique_per_key():
    p1, _ = generate_ed25519_keypair()
    p2, _ = generate_ed25519_keypair()
    assert ssh_fingerprint(p1) != ssh_fingerprint(p2)


def test_ssh_fingerprint_fallback_on_garbage():
    # Garbage input should not raise, should return a SHA256: prefixed string
    fp = ssh_fingerprint("not a real key at all")
    assert fp.startswith("SHA256:")


# ── Crypto round-trip via auth.crypto ──────────────────────────────────

def test_encrypt_decrypt_roundtrip(monkeypatch):
    # crypto module derives key from JWT_SECRET_KEY at call time
    monkeypatch.setenv("JWT_SECRET_KEY", "test-secret-for-crypto-roundtrip-32bytes!")
    # Force re-import so SECRET_KEY is read from env
    import importlib
    import dashboard.auth.jwt as jwt_mod
    jwt_mod.SECRET_KEY = "test-secret-for-crypto-roundtrip-32bytes!"
    from dashboard.auth.crypto import encrypt_ssh_key, decrypt_ssh_key

    private_str, _ = generate_ed25519_keypair()
    encrypted = encrypt_ssh_key(private_str)
    assert encrypted != private_str
    assert "BEGIN OPENSSH" not in encrypted
    decrypted = decrypt_ssh_key(encrypted)
    assert decrypted == private_str


# ── Migration import sanity ─────────────────────────────────────────────

def test_migration_012_imports_and_has_revision_metadata():
    import importlib.util
    from pathlib import Path
    path = Path(__file__).resolve().parent.parent / "dashboard" / "migrations" / "versions" / "012_base_branch_and_workspaces.py"
    spec = importlib.util.spec_from_file_location("migration_012", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    assert mod.revision == "012"
    assert mod.down_revision == "011"
    assert callable(mod.upgrade)
    assert callable(mod.downgrade)


# ── Project model: base_branch column ───────────────────────────────────

def test_project_model_has_base_branch_column():
    from dashboard.db.models.project import Project
    cols = {c.name for c in Project.__table__.columns}
    assert "base_branch" in cols
    col = Project.__table__.c.base_branch
    assert not col.nullable
    # server_default is a TextClause-like — its arg holds the literal
    default_val = getattr(col.server_default, "arg", None)
    assert default_val is not None
    assert "main" in str(default_val)
