"""
Real Git evidence gathering for the Connect Git/Jira page's Scan & Evaluate:
implements Layer 1 (rule-based ticket-ID matching across branches, commit
messages, PR/MR titles) and gathers the raw material Layer 2 (LLM diff +
design-doc review, via evaluator.evaluate_with_llm) and Layer 3 (repo tree
existence check) need. Supports GitHub and GitLab, auto-detected from the
repo URL's host. Also discovers documentation files anywhere in the repo
(Markdown, HTML, PPTX) as extra evidence for Layer 2 — per-ticket relevance
ranking happens in scanner.build_scan_context, not here. HTTP/HTML/PPTX
extraction is stdlib-only except python-pptx (see doc_extract.py).

Both source-code AND documentation file CONTENT are read from a local
`git clone` (git_workspace.py) whenever possible -- one clone instead of
one HTTP request per file, immune to per-file API rate limits, and not at
the mercy of an individual fetch silently failing. Falls back to the old
per-file GitHub/GitLab Contents-API fetch (per file type) only if the
clone itself fails (git not installed, network issue, auth, ...) -- this
must never be a hard requirement for a scan to run at all. Branches/
commits/PR-MR metadata and the file tree still come from the REST APIs
regardless, since a shallow single-branch clone has none of that.
"""
import base64
import json
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple

import db
import doc_extract
import git_client
import git_files_db
import git_workspace
import ticket_status
from evaluator import _compute_schedule
from i18n import TranslatableError
from models import TicketResult
from scanner import (
    SOURCE_EXTENSIONS,
    TICKET_ID_PATTERN,
    scan_source_content_for_tickets,
    select_relevant_docs,
    select_relevant_images,
)

_TIMEOUT = 15
_MAX_COMMIT_PAGES = 3
_MAX_MR_PAGES = 2
_MAX_TREE_PAGES = 5
_PAGE_SIZE = 100
_DIFF_CHAR_CAP = 4000
_MAX_DOC_FILES = 40
_DOC_CHAR_CAP_PER_FILE = 3000

_IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg"}
_IMAGE_MIME_TYPES = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg"}
_MAX_IMAGE_FILES = 10
_MAX_IMAGE_BYTES = 1_500_000

# Noise/non-source directories to skip when walking the repo tree for source
# files -- "docs" is included so documentation (fetched separately via
# _select_doc_paths/doc_path) is never double-counted as source evidence.
_EXCLUDED_SOURCE_DIRS = {
    "node_modules", ".git", "__pycache__", "venv", ".venv",
    "dist", "build", ".next", ".nuxt", "target", "bin", "obj",
    ".idea", ".vscode", "coverage", ".pytest_cache", ".mypy_cache",
    "docs",
}
_MAX_SOURCE_FILES = 300
_SOURCE_CHAR_CAP_PER_FILE = 4000


class GitScanError(TranslatableError):
    """Translated message for any Git evidence-gathering failure."""

    def __init__(self, key: str, **kwargs):
        super().__init__(key, status_code=400, **kwargs)


def _find_ticket_ids(text: str) -> List[str]:
    if not text:
        return []
    seen: List[str] = []
    for m in TICKET_ID_PATTERN.findall(text):
        tid = m.upper()
        if tid not in seen:
            seen.append(tid)
    return seen


def _detect_provider(repo_url: str, provider_hint: str = "") -> str:
    hint = (provider_hint or "").strip().lower()
    if hint in ("github", "gitlab"):
        return hint

    url = repo_url if "://" in repo_url else f"https://{repo_url}"
    parsed = urllib.parse.urlparse(url)
    host = parsed.netloc.lower()
    if "github" in host:
        return "github"
    if "gitlab" in host:
        return "gitlab"

    # Self-hosted instance whose hostname gives no hint (e.g. an internal
    # domain like git3.company.com). GitHub only ever has an owner/repo path
    # (2 segments); nested subgroups are a GitLab-only feature, so treat a
    # deeper path as a reliable signal it's a self-hosted GitLab instance.
    path = parsed.path.strip("/")
    if path.endswith(".git"):
        path = path[:-4]
    segments = [p for p in path.split("/") if p]
    if len(segments) > 2:
        return "gitlab"

    raise GitScanError("gitscan.provider_unsupported")


def _http_get_json(url: str, headers: Dict[str, str]):
    req = urllib.request.Request(url, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=_TIMEOUT) as resp:
            return json.loads(resp.read())
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="ignore")
        if exc.code == 401:
            raise GitScanError("gitscan.invalid_token")
        if exc.code == 403:
            raise GitScanError("gitscan.access_denied")
        if exc.code == 404:
            raise GitScanError("gitscan.repo_or_branch_not_found")
        raise GitScanError("gitscan.host_error", code=exc.code, body=body[:200])
    except urllib.error.URLError as exc:
        raise GitScanError("gitscan.connect_failed", reason=exc.reason)
    except TimeoutError:
        raise GitScanError("gitscan.timeout")
    except json.JSONDecodeError:
        raise GitScanError("gitscan.invalid_json")


def _http_get_bytes(url: str, headers: Dict[str, str]) -> bytes:
    req = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(req, timeout=_TIMEOUT) as resp:
        return resp.read()


def _basename(path: str) -> str:
    return path.rsplit("/", 1)[-1]


def _record_git_file(path: str, file_type: str) -> None:
    """Best-effort audit-trail write (git_files_db.record_file) for a file
    actually read from Git. Never raises -- a DB hiccup here must not break
    the scan itself, and is silently skipped entirely when no database is
    configured (dev setups without DATABASE_URL)."""
    if not db.is_configured():
        return
    try:
        git_files_db.record_file(_basename(path), path, file_type)
    except Exception:
        pass


def _read_source_files_from_clone(repo_path: str, source_paths: List[str]) -> List[Tuple[str, str]]:
    """Read already-selected source file paths directly from a local clone
    (git_workspace.clone_repo) instead of fetching them one-by-one via the
    GitHub/GitLab Contents API -- a single `git clone` instead of N HTTP
    round trips, not capped by per-file API rate limits, and immune to an
    individual file fetch silently failing partway through."""
    root = Path(repo_path)
    results: List[Tuple[str, str]] = []
    for rel_path in source_paths:
        try:
            text = (root / rel_path).read_text(encoding="utf-8", errors="ignore")
        except Exception:
            continue
        text = text[:_SOURCE_CHAR_CAP_PER_FILE]
        if text.strip():
            results.append((rel_path, text))
            _record_git_file(rel_path, "Source Code")
    return results


def _read_doc_files_from_clone(repo_path: str, doc_paths: List[str]) -> List[Tuple[str, str]]:
    """Read already-selected documentation file paths directly from a local
    clone, same rationale as _read_source_files_from_clone above -- one
    clone instead of N per-file API calls. Uses doc_extract.extract_doc_text
    for the same HTML-tag-stripping/PPTX-slide-text handling the API-fetch
    path applies, just reading bytes from disk instead of over HTTP."""
    root = Path(repo_path)
    results: List[Tuple[str, str]] = []
    for rel_path in doc_paths:
        try:
            raw = (root / rel_path).read_bytes()
        except Exception:
            continue
        text = doc_extract.extract_doc_text(rel_path, raw)[:_DOC_CHAR_CAP_PER_FILE]
        if text.strip():
            results.append((rel_path, text))
            _record_git_file(rel_path, "Doc")
    return results


def _select_doc_paths(tree_paths, doc_path: str = "") -> List[str]:
    """Filter the already-fetched repo tree down to documentation-looking
    files (README/specs/slides, by extension) anywhere in the repo — doc
    files in this codebase are scattered across many folders (architecture/,
    screens/, integration/, ...), not confined to one docs/ path. `doc_path`,
    if given, narrows this to one root instead (kept for backward compat).
    Capped so a huge doc tree can't blow up fetch time; per-ticket relevance
    ranking (scanner._score_doc_relevance) picks the few that matter for
    each ticket out of this pool."""
    root = (doc_path or "").strip().strip("/")
    prefix = root + "/" if root else ""
    matches = [
        p for p in tree_paths
        if doc_extract.file_extension(p) in doc_extract.DOC_EXTENSIONS and (not root or p == root or p.startswith(prefix))
    ]
    return sorted(matches)[:_MAX_DOC_FILES]


def _select_source_paths(tree_paths, source_path: str = "") -> List[str]:
    """Filter the already-fetched repo tree down to source-code files (by
    extension) under `source_path` (or the whole repo if empty). Excludes any
    path passing through a folder literally named "docs" (case-insensitive)
    or other known noise dirs (node_modules, .git, ...) -- documentation is
    fetched separately via `_select_doc_paths`/`doc_path`, so it must never
    be double-counted here as source evidence. Capped so a huge repo can't
    blow up fetch time; direct-ticket-ID and fuzzy-keyword matching (Layer 1,
    scanner.scan_source_content_for_tickets) then narrows this pool per ticket."""
    root = (source_path or "").strip().strip("/")
    prefix = root + "/" if root else ""
    matches = []
    for p in tree_paths:
        if root and not (p == root or p.startswith(prefix)):
            continue
        if doc_extract.file_extension(p) not in SOURCE_EXTENSIONS:
            continue
        segments = p.split("/")[:-1]
        if any(seg.lower() in _EXCLUDED_SOURCE_DIRS for seg in segments):
            continue
        matches.append(p)
    return sorted(matches)[:_MAX_SOURCE_FILES]


def _select_image_paths(tree_paths) -> List[str]:
    """Screenshots/mockups (screens/, ui-audit assets, ...) anywhere in the
    repo, by extension. Repo-wide cap keeps this cheap regardless of ticket
    count — per-ticket relevance ranking (scanner.select_relevant_images)
    happens later, and images are only attached to the LLM call for tickets
    that actually get escalated to deep judgment."""
    matches = [p for p in tree_paths if doc_extract.file_extension(p) in _IMAGE_EXTENSIONS]
    return sorted(matches)[:_MAX_IMAGE_FILES]


# ---------------------------------------------------------------------------
# GitHub
# ---------------------------------------------------------------------------
def _github_headers(token: str) -> Dict[str, str]:
    headers = {"Accept": "application/vnd.github+json", "User-Agent": "project-health-checker"}
    if token:
        headers["Authorization"] = f"token {token}"
    return headers


def _github_owner_repo(repo_url: str) -> Tuple[str, str]:
    path = urllib.parse.urlparse(repo_url).path.strip("/")
    if path.endswith(".git"):
        path = path[:-4]
    parts = [p for p in path.split("/") if p]
    if len(parts) < 2:
        raise GitScanError("gitscan.invalid_github_url")
    return parts[0], parts[1]


def _github_fetch_doc_files(
    owner: str, repo: str, branch: str, token: str, doc_paths: List[str]
) -> List[Tuple[str, str]]:
    if not doc_paths:
        return []
    headers = _github_headers(token)
    api = f"https://api.github.com/repos/{owner}/{repo}"
    results: List[Tuple[str, str]] = []
    for path in doc_paths:
        url = f"{api}/contents/{urllib.parse.quote(path)}?ref={urllib.parse.quote(branch)}"
        try:
            data = _http_get_json(url, headers)
        except GitScanError:
            continue
        content_b64 = data.get("content", "") if isinstance(data, dict) else ""
        if not content_b64:
            continue
        try:
            raw = base64.b64decode(content_b64)
        except (ValueError, TypeError):
            continue
        text = doc_extract.extract_doc_text(path, raw)[:_DOC_CHAR_CAP_PER_FILE]
        if text.strip():
            results.append((path, text))
            _record_git_file(path, "Doc")
    return results


def _github_fetch_source_files(
    owner: str, repo: str, branch: str, token: str, source_paths: List[str]
) -> List[Tuple[str, str]]:
    if not source_paths:
        return []
    headers = _github_headers(token)
    api = f"https://api.github.com/repos/{owner}/{repo}"
    results: List[Tuple[str, str]] = []
    for path in source_paths:
        url = f"{api}/contents/{urllib.parse.quote(path)}?ref={urllib.parse.quote(branch)}"
        try:
            data = _http_get_json(url, headers)
        except GitScanError:
            continue
        content_b64 = data.get("content", "") if isinstance(data, dict) else ""
        if not content_b64:
            continue
        try:
            raw = base64.b64decode(content_b64)
        except (ValueError, TypeError):
            continue
        text = raw.decode("utf-8", errors="ignore")[:_SOURCE_CHAR_CAP_PER_FILE]
        if text.strip():
            results.append((path, text))
            _record_git_file(path, "Source Code")
    return results


def _github_fetch_image_files(
    owner: str, repo: str, branch: str, token: str, image_paths: List[str]
) -> List[Tuple[str, bytes, str]]:
    if not image_paths:
        return []
    headers = _github_headers(token)
    api = f"https://api.github.com/repos/{owner}/{repo}"
    results: List[Tuple[str, bytes, str]] = []
    for path in image_paths:
        url = f"{api}/contents/{urllib.parse.quote(path)}?ref={urllib.parse.quote(branch)}"
        try:
            data = _http_get_json(url, headers)
        except GitScanError:
            continue
        content_b64 = data.get("content", "") if isinstance(data, dict) else ""
        if not content_b64:
            continue
        try:
            raw = base64.b64decode(content_b64)
        except (ValueError, TypeError):
            continue
        if len(raw) > _MAX_IMAGE_BYTES:
            continue
        results.append((path, raw, _IMAGE_MIME_TYPES.get(doc_extract.file_extension(path), "image/png")))
        _record_git_file(path, "Doc")
    return results


def _github_evidence(
    owner: str,
    repo: str,
    branch: str,
    token: str,
    doc_path: str = "",
    source_path: str = "",
    workspace_path: Optional[str] = None,
) -> Dict:
    headers = _github_headers(token)
    api = f"https://api.github.com/repos/{owner}/{repo}"

    branches = _http_get_json(f"{api}/branches?per_page={_PAGE_SIZE}", headers)
    branch_names = [b.get("name", "") for b in branches]

    commits: List[Dict] = []
    for page in range(1, _MAX_COMMIT_PAGES + 1):
        batch = _http_get_json(
            f"{api}/commits?sha={urllib.parse.quote(branch)}&per_page={_PAGE_SIZE}&page={page}", headers
        )
        if not batch:
            break
        commits.extend(batch)
        if len(batch) < _PAGE_SIZE:
            break

    prs: List[Dict] = []
    for page in range(1, _MAX_MR_PAGES + 1):
        batch = _http_get_json(f"{api}/pulls?state=all&per_page={_PAGE_SIZE}&page={page}", headers)
        if not batch:
            break
        prs.extend(batch)
        if len(batch) < _PAGE_SIZE:
            break

    tree_data = _http_get_json(f"{api}/git/trees/{urllib.parse.quote(branch)}?recursive=1", headers)
    tree_paths = {n.get("path", "") for n in (tree_data.get("tree") or []) if n.get("type") == "blob"}
    selected_doc_paths = _select_doc_paths(tree_paths, doc_path)
    doc_files = (
        _read_doc_files_from_clone(workspace_path, selected_doc_paths)
        if workspace_path
        else _github_fetch_doc_files(owner, repo, branch, token, selected_doc_paths)
    )
    image_files = _github_fetch_image_files(owner, repo, branch, token, _select_image_paths(tree_paths))
    selected_source_paths = _select_source_paths(tree_paths, source_path)
    source_files = (
        _read_source_files_from_clone(workspace_path, selected_source_paths)
        if workspace_path
        else _github_fetch_source_files(owner, repo, branch, token, selected_source_paths)
    )

    ticket_refs: Dict[str, List[str]] = {}
    for name in branch_names:
        for tid in _find_ticket_ids(name):
            ticket_refs.setdefault(tid, []).append(f"branch: {name}")

    for c in commits:
        msg = (c.get("commit") or {}).get("message", "")
        first_line = msg.splitlines()[0] if msg else ""
        sha = c.get("sha", "")[:7]
        for tid in _find_ticket_ids(msg):
            ticket_refs.setdefault(tid, []).append(f"commit {sha}: {first_line}")

    ticket_diffs: Dict[str, str] = {}
    ticket_files: Dict[str, List[str]] = {}
    for pr in prs:
        title = pr.get("title", "")
        number = pr.get("number")
        for tid in _find_ticket_ids(title):
            ticket_refs.setdefault(tid, []).append(f"PR #{number}: {title}")
            if tid in ticket_diffs or number is None:
                continue
            try:
                files = _http_get_json(f"{api}/pulls/{number}/files?per_page=100", headers)
            except GitScanError:
                files = []
            diff_parts, paths = [], []
            for f in files:
                fname = f.get("filename", "")
                paths.append(fname)
                patch = f.get("patch", "")
                if patch:
                    diff_parts.append(f"--- {fname} ---\n{patch}")
                    _record_git_file(fname, "Source Code")
            diff_text = "\n\n".join(diff_parts)[:_DIFF_CHAR_CAP]
            if diff_text:
                ticket_diffs[tid] = diff_text
            if paths:
                ticket_files[tid] = paths

    return {
        "ticket_refs": ticket_refs,
        "ticket_diffs": ticket_diffs,
        "ticket_files": ticket_files,
        "tree_paths": tree_paths,
        "doc_files": doc_files,
        "image_files": image_files,
        "source_files": source_files,
    }


# ---------------------------------------------------------------------------
# GitLab
# ---------------------------------------------------------------------------
def _gitlab_headers(token: str) -> Dict[str, str]:
    return {"PRIVATE-TOKEN": token} if token else {}


def _gitlab_api_base_and_path(repo_url: str) -> Tuple[str, str]:
    parsed = urllib.parse.urlparse(repo_url)
    path = parsed.path.strip("/")
    if path.endswith(".git"):
        path = path[:-4]
    if not path:
        raise GitScanError("gitscan.invalid_gitlab_url")
    return f"{parsed.scheme}://{parsed.netloc}/api/v4", urllib.parse.quote(path, safe="")


def _gitlab_fetch_doc_files(
    proj_api: str, branch: str, token: str, doc_paths: List[str]
) -> List[Tuple[str, str]]:
    if not doc_paths:
        return []
    headers = _gitlab_headers(token)
    results: List[Tuple[str, str]] = []
    for path in doc_paths:
        encoded_path = urllib.parse.quote(path, safe="")
        url = f"{proj_api}/repository/files/{encoded_path}/raw?ref={urllib.parse.quote(branch)}"
        try:
            raw = _http_get_bytes(url, headers)
        except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError):
            continue
        text = doc_extract.extract_doc_text(path, raw)[:_DOC_CHAR_CAP_PER_FILE]
        if text.strip():
            results.append((path, text))
            _record_git_file(path, "Doc")
    return results


def _gitlab_fetch_source_files(
    proj_api: str, branch: str, token: str, source_paths: List[str]
) -> List[Tuple[str, str]]:
    if not source_paths:
        return []
    headers = _gitlab_headers(token)
    results: List[Tuple[str, str]] = []
    for path in source_paths:
        encoded_path = urllib.parse.quote(path, safe="")
        url = f"{proj_api}/repository/files/{encoded_path}/raw?ref={urllib.parse.quote(branch)}"
        try:
            raw = _http_get_bytes(url, headers)
        except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError):
            continue
        text = raw.decode("utf-8", errors="ignore")[:_SOURCE_CHAR_CAP_PER_FILE]
        if text.strip():
            results.append((path, text))
            _record_git_file(path, "Source Code")
    return results


def _gitlab_fetch_image_files(
    proj_api: str, branch: str, token: str, image_paths: List[str]
) -> List[Tuple[str, bytes, str]]:
    if not image_paths:
        return []
    headers = _gitlab_headers(token)
    results: List[Tuple[str, bytes, str]] = []
    for path in image_paths:
        encoded_path = urllib.parse.quote(path, safe="")
        url = f"{proj_api}/repository/files/{encoded_path}/raw?ref={urllib.parse.quote(branch)}"
        try:
            raw = _http_get_bytes(url, headers)
        except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError):
            continue
        if len(raw) > _MAX_IMAGE_BYTES:
            continue
        results.append((path, raw, _IMAGE_MIME_TYPES.get(doc_extract.file_extension(path), "image/png")))
        _record_git_file(path, "Doc")
    return results


def _gitlab_evidence(
    repo_url: str,
    branch: str,
    token: str,
    doc_path: str = "",
    source_path: str = "",
    workspace_path: Optional[str] = None,
) -> Dict:
    api_base, project = _gitlab_api_base_and_path(repo_url)
    headers = _gitlab_headers(token)
    proj_api = f"{api_base}/projects/{project}"

    branches = _http_get_json(f"{proj_api}/repository/branches?per_page={_PAGE_SIZE}", headers)
    branch_names = [b.get("name", "") for b in branches]

    commits: List[Dict] = []
    for page in range(1, _MAX_COMMIT_PAGES + 1):
        batch = _http_get_json(
            f"{proj_api}/repository/commits?ref_name={urllib.parse.quote(branch)}&per_page={_PAGE_SIZE}&page={page}",
            headers,
        )
        if not batch:
            break
        commits.extend(batch)
        if len(batch) < _PAGE_SIZE:
            break

    mrs: List[Dict] = []
    for page in range(1, _MAX_MR_PAGES + 1):
        batch = _http_get_json(f"{proj_api}/merge_requests?state=all&per_page={_PAGE_SIZE}&page={page}", headers)
        if not batch:
            break
        mrs.extend(batch)
        if len(batch) < _PAGE_SIZE:
            break

    tree_paths: Set[str] = set()
    for page in range(1, _MAX_TREE_PAGES + 1):
        batch = _http_get_json(
            f"{proj_api}/repository/tree?ref={urllib.parse.quote(branch)}&recursive=true"
            f"&per_page={_PAGE_SIZE}&page={page}",
            headers,
        )
        if not batch:
            break
        tree_paths.update(n.get("path", "") for n in batch if n.get("type") == "blob")
        if len(batch) < _PAGE_SIZE:
            break

    selected_doc_paths = _select_doc_paths(tree_paths, doc_path)
    doc_files = (
        _read_doc_files_from_clone(workspace_path, selected_doc_paths)
        if workspace_path
        else _gitlab_fetch_doc_files(proj_api, branch, token, selected_doc_paths)
    )
    image_files = _gitlab_fetch_image_files(proj_api, branch, token, _select_image_paths(tree_paths))
    selected_source_paths = _select_source_paths(tree_paths, source_path)
    source_files = (
        _read_source_files_from_clone(workspace_path, selected_source_paths)
        if workspace_path
        else _gitlab_fetch_source_files(proj_api, branch, token, selected_source_paths)
    )

    ticket_refs: Dict[str, List[str]] = {}
    for name in branch_names:
        for tid in _find_ticket_ids(name):
            ticket_refs.setdefault(tid, []).append(f"branch: {name}")

    for c in commits:
        msg = c.get("message") or c.get("title") or ""
        first_line = msg.splitlines()[0] if msg else ""
        sha = (c.get("short_id") or c.get("id") or "")[:7]
        for tid in _find_ticket_ids(msg):
            ticket_refs.setdefault(tid, []).append(f"commit {sha}: {first_line}")

    ticket_diffs: Dict[str, str] = {}
    ticket_files: Dict[str, List[str]] = {}
    for mr in mrs:
        title = mr.get("title", "")
        iid = mr.get("iid")
        for tid in _find_ticket_ids(title):
            ticket_refs.setdefault(tid, []).append(f"MR !{iid}: {title}")
            if tid in ticket_diffs or iid is None:
                continue
            try:
                changes = _http_get_json(f"{proj_api}/merge_requests/{iid}/changes", headers)
            except GitScanError:
                changes = {}
            diff_parts, paths = [], []
            for ch in changes.get("changes") or []:
                path = ch.get("new_path") or ch.get("old_path", "")
                paths.append(path)
                diff = ch.get("diff", "")
                if diff:
                    diff_parts.append(f"--- {path} ---\n{diff}")
                    _record_git_file(path, "Source Code")
            diff_text = "\n\n".join(diff_parts)[:_DIFF_CHAR_CAP]
            if diff_text:
                ticket_diffs[tid] = diff_text
            if paths:
                ticket_files[tid] = paths

    return {
        "ticket_refs": ticket_refs,
        "ticket_diffs": ticket_diffs,
        "ticket_files": ticket_files,
        "tree_paths": tree_paths,
        "doc_files": doc_files,
        "image_files": image_files,
        "source_files": source_files,
    }


def fetch_git_evidence(
    repo_url: str,
    branch: str,
    token: str = "",
    provider_hint: str = "",
    doc_path: str = "",
    source_path: str = "",
) -> Dict:
    """Layer 1 data-gathering: ticket refs from branches/commits/PR-MR
    titles, plus PR/MR diffs (Layer 2 input), the target branch's file tree
    (Layer 3 input), documentation files anywhere in the repo (or under
    `doc_path` if given) as Layer 2 design-doc evidence — returned as
    `doc_files: List[(path, text)]` — and actual source-code files under
    `source_path` (or the whole repo if empty), excluding any `docs` folder,
    as real implementation evidence — returned as `source_files: List[(path,
    text)]`; per-ticket relevance ranking happens in scanner.build_scan_context
    (docs) and scanner.scan_source_content_for_tickets (source files).

    Clones the repo locally first (git_workspace.clone_repo) so source_files
    can be read directly from disk instead of one-by-one over the GitHub/
    GitLab Contents API — falls back to the old per-file API fetch if the
    clone fails (git not installed, network issue, auth, ...), so a scan
    never hard-depends on a local `git` binary being available. The clone's
    local path is returned as `workspace_path` (None if cloning failed) so
    callers (main.py) can reuse the SAME clone for the Layer-4 deep-dive
    instead of cloning twice, and are responsible for cleaning it up
    (git_workspace.cleanup_workspace) once the whole scan is done."""
    repo_url = (repo_url or "").strip()
    branch = (branch or "").strip() or "main"
    doc_path = (doc_path or "").strip()
    source_path = (source_path or "").strip()
    provider = _detect_provider(repo_url, provider_hint)

    workspace_path: Optional[str] = None
    try:
        workspace_path = git_workspace.clone_repo(repo_url, branch, token)
    except TranslatableError as exc:
        print(f"[git_scan] Local clone unavailable, falling back to per-file API fetch for source code: {exc}")

    if provider == "github":
        owner, repo = _github_owner_repo(repo_url)
        evidence = _github_evidence(owner, repo, branch, token, doc_path, source_path, workspace_path)
    else:
        evidence = _gitlab_evidence(repo_url, branch, token, doc_path, source_path, workspace_path)

    # Current HEAD commit of the scanned branch, for the re-evaluation
    # cache (reeval_cache.py) to tell whether the repo has moved since a
    # ticket's last check. Prefer reading it straight out of the clone
    # (free, already have it); fall back to a lightweight ls-remote when
    # the clone itself failed, so the cache still works via the old
    # per-file API path.
    commit_sha = git_workspace.get_head_commit(workspace_path) if workspace_path else None
    if not commit_sha:
        commit_sha = git_client.get_branch_head_sha(repo_url, branch, token) or None

    evidence["workspace_path"] = workspace_path
    evidence["commit_sha"] = commit_sha
    return evidence


def build_scan_result(
    tickets: List[Dict], evidence: Dict
) -> Tuple[Dict[str, Dict], Dict[str, TicketResult], Dict[str, List[str]]]:
    """Layer 1 short-circuit: a ticket reported Done/Closed/Resolved with no
    Git evidence anywhere (no branch/commit/PR-MR mention AND no match in the
    fetched source files) is an immediate, confident Mismatch — no LLM call.
    Everything else is handed to evaluate_with_llm (Layer 2) via the same
    scan_result shape scanner.scan_source_for_tickets produces — "files"/
    "snippets" combine branch/commit/PR-MR refs + diffs with real source-code
    matches from scanner.scan_source_content_for_tickets (direct ticket-ID +
    fuzzy keyword matching against the files fetched under `source_path`) —
    plus each ticket's top-ranked design-doc excerpts (scanner.select_relevant_docs)
    under scan_result[tid]["docs"] for the Doc-vs-Ticket/Doc-vs-Code axes."""
    ticket_refs = evidence.get("ticket_refs", {})
    ticket_diffs = evidence.get("ticket_diffs", {})
    ticket_files = evidence.get("ticket_files", {})
    doc_files = evidence.get("doc_files", [])
    image_files = evidence.get("image_files", [])
    source_files = evidence.get("source_files", [])

    source_scan = scan_source_content_for_tickets(tickets, source_files) if source_files else {}

    scan_result: Dict[str, Dict] = {}
    certain_mismatches: Dict[str, TicketResult] = {}

    for t in tickets:
        tid = t["ticket_id"].upper()
        refs = ticket_refs.get(tid, [])
        diff = ticket_diffs.get(tid, "")
        files = ticket_files.get(tid, [])
        docs, docs_total_candidates = select_relevant_docs(t, doc_files)
        images = select_relevant_images(t, image_files)
        src = source_scan.get(tid, {"files": [], "snippets": []})

        if ticket_status.is_done_status(t.get("status")) and not refs and not src["files"]:
            schedule_status, days_diff = _compute_schedule(t.get("due_date", ""), 0.0)
            certain_mismatches[tid] = TicketResult(
                ticket_id=t["ticket_id"],
                summary=t.get("summary", ""),
                status=t.get("status", ""),
                completion_percent=0.0,
                assessment="Mismatch",
                confidence=0.9,
                missing_parts=[
                    "Ticket ID not found in any branch name, commit message, or PR/MR title on Git."
                ],
                suggestions=["Check whether the code was actually pushed/merged to the repo."],
                evidence_files=[],
                notes="Layer 1 (rule-based): no code evidence references this ticket.",
                schedule_status=schedule_status,
                days_diff=days_diff,
                assignee=t.get("assignee", ""),
                doc_ticket_match="No Doc Found" if not docs else "Not evaluated (Layer 1 short-circuit)",
                doc_code_match="N/A",
                matched_doc_files=[p for p, _ in docs],
            )
            continue

        scan_result[tid] = {
            "files": list(refs)[:8] + [f"changed: {fp}" for fp in files[:10]] + src["files"][:10],
            "snippets": ([diff] if diff else []) + src["snippets"][:3],
            "docs": docs,
            "docs_total_candidates": docs_total_candidates,
            "images": images,
        }

    return scan_result, certain_mismatches, ticket_files


def apply_repo_tree_check(
    results: List[TicketResult], ticket_files: Dict[str, List[str]], tree_paths: Set[str], branch: str
) -> List[TicketResult]:
    """Layer 3: an LLM "Match" is only as good as the code actually being on
    the target branch — downgrade to Incomplete if none of the ticket's
    changed files are present there (MR may be unmerged/reverted)."""
    checked: List[TicketResult] = []
    for r in results:
        files = ticket_files.get(r.ticket_id.upper())
        if r.assessment == "Match" and files and not any(fp in tree_paths for fp in files):
            r = r.model_copy(update={
                "assessment": "Incomplete",
                "missing_parts": r.missing_parts + [
                    f'Changed file(s) do not exist on branch "{branch}" — '
                    "the MR may not have been merged, or was reverted."
                ],
                "notes": (r.notes + "\n\nLayer 3 (repo tree check): FAILED — files not found on target branch.").strip(),
            })
        checked.append(r)
    return checked
