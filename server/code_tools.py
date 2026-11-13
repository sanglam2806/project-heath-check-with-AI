"""
"Code-graph-lite" tools for the Layer-4 agentic deep-dive: pure,
LLM-independent functions that operate on a local clone (see
git_workspace.clone_repo) and give the agent grep/read/symbol-search
capability over the real repo. Deliberately NOT a real AST/call-graph --
find_definition/find_references are regex heuristics, not a symbol index;
upgradeable later (tree-sitter/ctags) if accuracy proves insufficient.
Reuses the same source-file scoping as scanner.py/git_scan.py (extensions
+ excluded dirs, "docs" included) so the agent only ever sees real source
code -- documentation is handled separately via scanner.select_relevant_docs.
"""
import re
import subprocess
from pathlib import Path
from typing import Dict, List, Optional

import doc_extract
from scanner import SOURCE_EXTENSIONS

_EXCLUDED_DIRS = {
    "node_modules", ".git", "__pycache__", "venv", ".venv",
    "dist", "build", ".next", ".nuxt", "target", "bin", "obj",
    ".idea", ".vscode", "coverage", ".pytest_cache", ".mypy_cache",
    "docs",
}
# Same noise dirs as source-file scanning, EXCEPT "docs" -- unlike source
# code, documentation SHOULD be found there (and elsewhere: doc files are
# often scattered across many folders, not confined to one docs/ path,
# mirroring git_scan._select_doc_paths' approach).
_EXCLUDED_DOC_DIRS = _EXCLUDED_DIRS - {"docs"}

_MAX_LIST_FILES = 500
_MAX_SEARCH_RESULTS = 50
_MAX_READ_CHARS = 4000
_MAX_MATCHES_PER_SYMBOL = 30
_MAX_DOC_LIST = 200

# Heuristic "definition" shapes across common languages -- {sym} is
# substituted with the (escaped) symbol name before compiling. Not a real
# parser: e.g. the Java/C#-ish pattern is intentionally loose.
_DEFINITION_PATTERN_TEMPLATES = [
    r"^\s*(?:async\s+)?def\s+{sym}\b",                              # Python function/method
    r"^\s*class\s+{sym}\b",                                          # Python class
    r"^\s*(?:export\s+)?(?:default\s+)?(?:async\s+)?function\s+{sym}\b",  # JS/TS function
    r"^\s*(?:export\s+)?(?:default\s+)?class\s+{sym}\b",             # JS/TS class
    r"^\s*(?:export\s+)?(?:const|let|var)\s+{sym}\s*=",              # JS/TS const/arrow fn
    r"^\s*(?:public|private|protected|internal|static|\s)*[\w<>\[\],\s]+\s+{sym}\s*\(",  # Java/C#-style method
]


def _is_excluded(rel_path: str) -> bool:
    segments = Path(rel_path).parts[:-1]
    return any(seg.lower() in _EXCLUDED_DIRS for seg in segments)


def _iter_repo_files(repo_path: str):
    """Yield (relative_posix_path, absolute_Path) for every in-scope source
    file under `repo_path` -- same extension/exclusion rules as
    scanner._iter_source_files and git_scan._select_source_paths."""
    root = Path(repo_path)
    for path in root.rglob("*"):
        if not path.is_file():
            continue
        rel = path.relative_to(root).as_posix()
        if _is_excluded(rel):
            continue
        if path.suffix.lower() not in SOURCE_EXTENSIONS:
            continue
        yield rel, path


def list_files(repo_path: str, pattern: str = "") -> List[str]:
    """List source files in the clone (docs/node_modules/etc excluded),
    optionally filtered by a case-insensitive substring `pattern` on the
    relative path. Capped at _MAX_LIST_FILES."""
    pattern_lower = (pattern or "").lower()
    results = []
    for rel, _ in _iter_repo_files(repo_path):
        if pattern_lower and pattern_lower not in rel.lower():
            continue
        results.append(rel)
        if len(results) >= _MAX_LIST_FILES:
            break
    return sorted(results)


def _search_with_git_grep(repo_path: str, query: str, regex: bool) -> Optional[List[Dict]]:
    args = ["git", "grep", "-n", "-I"]
    if not regex:
        args.append("-F")
    args += ["-e", query, "--"] + [f"*{ext}" for ext in SOURCE_EXTENSIONS]
    try:
        proc = subprocess.run(args, cwd=repo_path, capture_output=True, text=True, timeout=20)
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
        return None
    # git grep exit code 0 = matches found, 1 = no matches (not an error), >1 = real error
    if proc.returncode > 1:
        return None
    results = []
    for line in proc.stdout.splitlines():
        parts = line.split(":", 2)
        if len(parts) < 3:
            continue
        path, line_no, text = parts
        if _is_excluded(path):
            continue
        try:
            line_int = int(line_no)
        except ValueError:
            continue
        results.append({"path": path, "line": line_int, "text": text.strip()[:300]})
    return results


def _search_with_python(repo_path: str, query: str, regex: bool) -> List[Dict]:
    pattern = re.compile(query) if regex else None
    results: List[Dict] = []
    for rel, path in _iter_repo_files(repo_path):
        try:
            text = path.read_text(encoding="utf-8", errors="ignore")
        except Exception:
            continue
        for i, line in enumerate(text.splitlines(), start=1):
            matched = pattern.search(line) if pattern else (query in line)
            if matched:
                results.append({"path": rel, "line": i, "text": line.strip()[:300]})
                if len(results) >= _MAX_SEARCH_RESULTS:
                    return results
    return results


def search_code(repo_path: str, query: str, regex: bool = False) -> List[Dict]:
    """Search file contents for `query` (literal substring by default, or a
    regex when `regex=True`). Tries `git grep` first (fast, works from the
    clone root); falls back to a pure-Python per-file scan if git grep is
    unavailable or errors out."""
    query = (query or "").strip()
    if not query:
        return []
    results = _search_with_git_grep(repo_path, query, regex)
    if results is None:
        results = _search_with_python(repo_path, query, regex)
    return results[:_MAX_SEARCH_RESULTS]


def read_file(
    repo_path: str, path: str, start_line: Optional[int] = None, end_line: Optional[int] = None
) -> str:
    """Read a file (or a 1-indexed inclusive line range) from the clone,
    capped at _MAX_READ_CHARS. Refuses to read outside the clone root
    (path traversal)."""
    root = Path(repo_path).resolve()
    try:
        target = (root / path).resolve()
    except (OSError, ValueError):
        return "(refused: invalid path)"
    if root != target and root not in target.parents:
        return "(refused: path escapes the repository)"
    if not target.is_file():
        return "(file not found)"
    try:
        text = target.read_text(encoding="utf-8", errors="ignore")
    except Exception as exc:
        return f"(could not read file: {exc})"
    if start_line or end_line:
        lines = text.splitlines()
        start = max(1, start_line or 1) - 1
        end = min(len(lines), end_line or len(lines))
        text = "\n".join(lines[start:end])
    return text[:_MAX_READ_CHARS]


def find_definition(repo_path: str, symbol: str) -> List[Dict]:
    """Heuristic (regex, not AST) search for where `symbol` is defined.
    Returns up to _MAX_MATCHES_PER_SYMBOL {path, line, text} entries."""
    symbol = (symbol or "").strip()
    if not symbol:
        return []
    escaped = re.escape(symbol)
    patterns = [re.compile(t.format(sym=escaped)) for t in _DEFINITION_PATTERN_TEMPLATES]
    results: List[Dict] = []
    for rel, path in _iter_repo_files(repo_path):
        try:
            lines = path.read_text(encoding="utf-8", errors="ignore").splitlines()
        except Exception:
            continue
        for i, line in enumerate(lines, start=1):
            if any(p.search(line) for p in patterns):
                results.append({"path": rel, "line": i, "text": line.strip()[:300]})
                if len(results) >= _MAX_MATCHES_PER_SYMBOL:
                    return results
    return results


def find_references(repo_path: str, symbol: str) -> List[Dict]:
    """Heuristic proxy for "callers/usages" of `symbol`: a plain-text
    search for the symbol name across source files -- not scope/type-aware,
    just the closest approximation of a call graph achievable without a
    real AST index."""
    return search_code(repo_path, symbol, regex=False)


# ---------------------------------------------------------------------------
# Documentation tools -- deliberately separate from the source-code tools
# above: these read the SAME clone but are not capped to the top-3 doc
# excerpts pre-selected by scanner.select_relevant_docs for Layers 2/4's
# initial context. The agent can use these to look for more/different
# documentation on its own instead of being limited to what was pre-ranked
# by keyword-overlap (see doc_extract.py for the shared extraction logic
# also used by git_scan.py's HTTP-fetched doc evidence).
# ---------------------------------------------------------------------------
def _is_excluded_doc(rel_path: str) -> bool:
    segments = Path(rel_path).parts[:-1]
    return any(seg.lower() in _EXCLUDED_DOC_DIRS for seg in segments)


def _iter_doc_files(repo_path: str):
    """Yield (relative_posix_path, absolute_Path) for every documentation-
    looking file (by extension) under `repo_path` -- NOT confined to a
    `docs/` folder, since real repos scatter docs across many folders."""
    root = Path(repo_path)
    for path in root.rglob("*"):
        if not path.is_file():
            continue
        rel = path.relative_to(root).as_posix()
        if _is_excluded_doc(rel):
            continue
        if doc_extract.file_extension(rel) not in doc_extract.DOC_EXTENSIONS:
            continue
        yield rel, path


def list_docs(repo_path: str, pattern: str = "") -> List[str]:
    """List documentation-looking files (README/specs/slides -- .md/.mdx/
    .txt/.rst/.adoc/.html/.htm/.pptx) anywhere in the clone, optionally
    filtered by a case-insensitive substring `pattern` on the relative
    path. Capped at _MAX_DOC_LIST."""
    pattern_lower = (pattern or "").lower()
    results = []
    for rel, _ in _iter_doc_files(repo_path):
        if pattern_lower and pattern_lower not in rel.lower():
            continue
        results.append(rel)
        if len(results) >= _MAX_DOC_LIST:
            break
    return sorted(results)


def search_docs(repo_path: str, query: str) -> List[Dict]:
    """Search EXTRACTED documentation text (HTML tags stripped, PPTX slide/
    notes text pulled out -- see doc_extract.py) for a case-insensitive
    literal substring. Returns {path, snippet} around each match -- a
    surrounding-text snippet rather than a line number, since text
    extraction from HTML/PPTX doesn't preserve original line numbers the
    way plain source files do."""
    query_stripped = (query or "").strip()
    query_lower = query_stripped.lower()
    if not query_lower:
        return []
    results: List[Dict] = []
    for rel, path in _iter_doc_files(repo_path):
        try:
            raw = path.read_bytes()
        except Exception:
            continue
        text = doc_extract.extract_doc_text(rel, raw)
        if not text:
            continue
        idx = text.lower().find(query_lower)
        if idx == -1:
            continue
        start = max(0, idx - 100)
        end = min(len(text), idx + len(query_stripped) + 100)
        results.append({"path": rel, "snippet": text[start:end].strip()})
        if len(results) >= _MAX_SEARCH_RESULTS:
            break
    return results


def read_doc(repo_path: str, path: str) -> str:
    """Read and extract plain text from one documentation file (Markdown/
    txt/rst/adoc as-is, HTML tag-stripped, PPTX slide/notes text), capped
    at _MAX_READ_CHARS. Refuses to read outside the clone root or a file
    whose extension isn't a recognized documentation type."""
    root = Path(repo_path).resolve()
    try:
        target = (root / path).resolve()
    except (OSError, ValueError):
        return "(refused: invalid path)"
    if root != target and root not in target.parents:
        return "(refused: path escapes the repository)"
    if doc_extract.file_extension(path) not in doc_extract.DOC_EXTENSIONS:
        return "(refused: not a recognized documentation file type)"
    if not target.is_file():
        return "(file not found)"
    try:
        raw = target.read_bytes()
    except Exception as exc:
        return f"(could not read file: {exc})"
    return doc_extract.extract_doc_text(path, raw)[:_MAX_READ_CHARS]
