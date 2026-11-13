"""
Local Git workspace management for the Layer-4 agentic deep-dive:
shallow-clones a repo to a request-scoped temp directory so
`code_tools`/`deep_dive_agent` can grep/read real files, then removes it
once the deep-dive finishes. Mirrors the ZIP-upload lifecycle in main.py
(_UPLOADS_DIR / uuid-named dirs), but request-scoped rather than
persisted, since a clone is only needed for the duration of one scan.

New host requirement: the `git` CLI must be installed and on PATH. Every
other Git integration in this codebase (git_client.py, git_scan.py) is
deliberately stdlib-only (HTTP API calls) and avoids this -- an actual
clone needs the real binary, so this shells out to it rather than add a
GitPython/dulwich dependency for no real benefit over subprocess.
"""
import logging
import shutil
import subprocess
import urllib.parse
import uuid
from pathlib import Path
from typing import Optional

from i18n import TranslatableError

logger = logging.getLogger(__name__)

_CLONES_DIR = Path(__file__).resolve().parent / "clones"
_CLONES_DIR.mkdir(parents=True, exist_ok=True)

_CLONE_TIMEOUT_SECONDS = 120


class GitWorkspaceError(TranslatableError):
    """Translated message for a clone failure (bad URL, auth, missing
    branch, git not installed, timeout)."""

    def __init__(self, key: str, **kwargs):
        super().__init__(key, status_code=400, **kwargs)


def _authenticated_url(repo_url: str, token: str, username: str = "") -> str:
    """Embed credentials in the clone URL the same way git_client.test_connection
    authenticates over HTTP: the token as the password, falling back to a
    placeholder username for PAT-only flows, or the given username for
    self-hosted servers that authenticate against a real account."""
    if not token:
        return repo_url
    parsed = urllib.parse.urlparse(repo_url)
    auth_user = urllib.parse.quote((username or "").strip() or "token", safe="")
    auth_token = urllib.parse.quote(token, safe="")
    netloc = f"{auth_user}:{auth_token}@{parsed.netloc}"
    return urllib.parse.urlunparse(parsed._replace(netloc=netloc))


def clone_repo(repo_url: str, branch: str, token: str = "", username: str = "") -> str:
    """Shallow-clone `repo_url` at `branch` into a fresh directory under
    server/clones/, and return its local path. Raises GitWorkspaceError on
    any failure (bad URL, auth, missing branch, git not installed, timeout).
    Caller is responsible for calling cleanup_workspace() when done."""
    repo_url = (repo_url or "").strip().rstrip("/")
    if not repo_url:
        raise GitWorkspaceError("gitworkspace.url_required")
    if not repo_url.startswith("http://") and not repo_url.startswith("https://"):
        raise GitWorkspaceError("gitworkspace.http_only")
    branch = (branch or "").strip() or "main"

    workspace_id = uuid.uuid4().hex[:12]
    dest_dir = _CLONES_DIR / workspace_id
    auth_url = _authenticated_url(repo_url, token, username)

    try:
        result = subprocess.run(
            [
                "git", "clone", "--depth", "1", "--branch", branch, "--single-branch",
                auth_url, str(dest_dir),
            ],
            capture_output=True,
            text=True,
            timeout=_CLONE_TIMEOUT_SECONDS,
        )
    except FileNotFoundError:
        raise GitWorkspaceError("gitworkspace.git_not_installed")
    except subprocess.TimeoutExpired:
        shutil.rmtree(dest_dir, ignore_errors=True)
        raise GitWorkspaceError("gitworkspace.timeout")

    if result.returncode != 0:
        shutil.rmtree(dest_dir, ignore_errors=True)
        stderr = (result.stderr or "")
        if token:
            stderr = stderr.replace(token, "***")
        logger.warning("git clone failed for %s (branch=%s): %s", repo_url, branch, stderr[:500])
        lowered = stderr.lower()
        if "not found" in lowered or "could not find remote branch" in lowered:
            raise GitWorkspaceError("gitworkspace.branch_not_found", branch=branch)
        if "authentication" in lowered or "403" in stderr or "401" in stderr:
            raise GitWorkspaceError("gitworkspace.auth_required")
        raise GitWorkspaceError("gitworkspace.clone_failed")

    return str(dest_dir)


def get_head_commit(workspace_path: str) -> Optional[str]:
    """Full commit SHA currently checked out in a clone (see clone_repo).
    Used by git_scan.fetch_git_evidence to populate evidence["commit_sha"]
    for the re-evaluation cache (reeval_cache.py) -- has the repo moved
    since a ticket's last evaluation? Best-effort: returns None on any
    failure rather than raising, since this is an optimization, not a
    correctness-critical path."""
    if not workspace_path:
        return None
    try:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=workspace_path,
            capture_output=True,
            text=True,
            timeout=10,
        )
    except Exception:
        return None
    if result.returncode != 0:
        return None
    return result.stdout.strip() or None


def cleanup_workspace(path: str) -> None:
    """Remove a cloned workspace directory. Never raises -- best-effort,
    called in a `finally` block right after the Layer-4 deep-dive finishes
    for that request."""
    if not path:
        return
    shutil.rmtree(path, ignore_errors=True)


def cleanup_all() -> None:
    """Safety net for any leftover clone dirs from crashed requests --
    registered alongside main.py's existing shutdown cleanup."""
    shutil.rmtree(_CLONES_DIR, ignore_errors=True)
    _CLONES_DIR.mkdir(parents=True, exist_ok=True)
