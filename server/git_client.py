"""
Real Git connection check: given an HTTP(S) repo URL + branch name, verifies
the repo is reachable and the branch exists, using Git's smart-HTTP refs
handshake directly (the same request `git ls-remote` makes under the hood)
via stdlib urllib — no git binary required on the host.
"""
import base64
import urllib.error
import urllib.request

from i18n import TranslatableError


class GitConnectionError(TranslatableError):
    """Translated message for any connect failure (bad URL, unreachable
    host, missing branch, auth required, network error, timeout)."""

    def __init__(self, key: str, **kwargs):
        super().__init__(key, status_code=400, **kwargs)


def _parse_pkt_lines(data: bytes):
    i = 0
    n = len(data)
    lines = []
    while i + 4 <= n:
        try:
            length = int(data[i:i + 4], 16)
        except ValueError:
            break
        if length == 0:
            i += 4
            continue
        if i + length > n:
            break
        lines.append(data[i + 4:i + length])
        i += length
    return lines


def _parse_heads(data: bytes) -> dict:
    heads = {}
    for line in _parse_pkt_lines(data):
        text = line.decode("utf-8", errors="ignore").rstrip("\n")
        if text.startswith("#"):
            continue
        if "\x00" in text:
            text = text.split("\x00", 1)[0]
        parts = text.split(" ", 1)
        if len(parts) != 2:
            continue
        sha, ref = parts
        if ref.startswith("refs/heads/"):
            heads[ref[len("refs/heads/"):]] = sha
    return heads


def test_connection(repo_url: str, branch: str, token: str = "", username: str = "") -> dict:
    repo_url = (repo_url or "").strip().rstrip("/")
    if not repo_url:
        raise GitConnectionError("git.url_required")
    if not repo_url.startswith("http://") and not repo_url.startswith("https://"):
        raise GitConnectionError("git.http_only")
    branch = (branch or "").strip() or "main"

    url = f"{repo_url}/info/refs?service=git-upload-pack"
    headers = {"User-Agent": "git/2.40.0"}
    if token:
        # Git's smart-HTTP protocol authenticates the same way regardless of
        # host: HTTP Basic Auth with the credential as the password. Hosted
        # providers (GitHub/GitLab/Bitbucket) ignore the username when a
        # valid PAT is given as the password, but some self-hosted Git
        # servers authenticate against a real account (e.g. LDAP/AD) and
        # need the actual username too -- so use it when the caller
        # provided one, falling back to a placeholder for PAT-only flows.
        auth_user = username.strip() or "token"
        credentials = base64.b64encode(f"{auth_user}:{token}".encode("utf-8")).decode("ascii")
        headers["Authorization"] = f"Basic {credentials}"
    req = urllib.request.Request(url, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            body = resp.read()
    except urllib.error.HTTPError as exc:
        if exc.code in (401, 403):
            raise GitConnectionError("git.auth_required")
        if exc.code == 404:
            raise GitConnectionError("git.repo_not_found")
        raise GitConnectionError("git.server_error", code=exc.code)
    except urllib.error.URLError as exc:
        raise GitConnectionError("git.connect_failed", url=repo_url, reason=exc.reason)
    except TimeoutError:
        raise GitConnectionError("git.timeout")

    heads = _parse_heads(body)
    if not heads:
        raise GitConnectionError("git.invalid_repo")
    if branch not in heads:
        available = ", ".join(sorted(heads)[:5])
        raise GitConnectionError("git.branch_not_found", branch=branch, available=available)

    return {"branch": branch, "commit_sha": heads[branch][:7]}


def get_branch_head_sha(repo_url: str, branch: str, token: str = "", username: str = "") -> str:
    """Best-effort full commit SHA for a branch, via the same ls-remote-
    style handshake as test_connection, but returns "" on any failure
    instead of raising. Used by git_scan.fetch_git_evidence as a fallback
    when no local clone is available (git_workspace.get_head_commit) --
    purely for the re-evaluation cache (reeval_cache.py), never for auth/
    repo validation, so failures here must never block a scan."""
    repo_url = (repo_url or "").strip().rstrip("/")
    branch = (branch or "").strip() or "main"
    if not repo_url.startswith("http://") and not repo_url.startswith("https://"):
        return ""

    url = f"{repo_url}/info/refs?service=git-upload-pack"
    headers = {"User-Agent": "git/2.40.0"}
    if token:
        auth_user = username.strip() or "token"
        credentials = base64.b64encode(f"{auth_user}:{token}".encode("utf-8")).decode("ascii")
        headers["Authorization"] = f"Basic {credentials}"
    req = urllib.request.Request(url, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            body = resp.read()
    except Exception:
        return ""
    return _parse_heads(body).get(branch, "")
