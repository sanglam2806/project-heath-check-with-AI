"""
Scanner module: scans extracted source code for ticket references.
"""
import os
import re
from datetime import date
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import doc_extract

# Common source-code extensions we care about
SOURCE_EXTENSIONS = {
    ".py", ".js", ".jsx", ".ts", ".tsx", ".java", ".cs", ".go", ".rb",
    ".php", ".c", ".cpp", ".h", ".hpp", ".sql", ".html", ".css", ".vue",
    ".kt", ".swift", ".rs", ".sh", ".yml", ".yaml", ".json", ".xml",
}

# Keywords commonly found in ticket IDs (e.g. ABC-123, PROJ-45, TICKET-7,
# COWORKLOCAL-185). Jira Cloud caps project keys at 10 chars, but Jira
# Server/Data Center allows longer ones, so the prefix limit here must be
# generous enough to still match those (was capped at 10 total, which
# silently broke every ticket-ID match for an 11+ char project key).
TICKET_ID_PATTERN = re.compile(r"\b([A-Z][A-Z0-9]{1,19}-\d{1,6})\b", re.IGNORECASE)


_DOC_STOPWORDS = {
    "the", "a", "an", "and", "or", "for", "to", "of", "in", "on", "with", "is",
    "are", "was", "were", "this", "that", "from", "by", "as", "at", "be", "it",
    "its", "will", "should", "must", "can", "not",
}

# Hiragana, Katakana (incl. halfwidth), CJK Unified Ideographs + Extension A --
# covers Japanese (and most Chinese) text. Ticket/doc text in these scripts
# has no ASCII word boundaries, so the plain [a-zA-Z0-9]+ word regex used
# below found literally nothing in it -- every Japanese-language ticket
# scored 0 against every doc/image/source file, regardless of how relevant
# it actually was (see _cjk_bigrams for how these runs become "words").
_CJK_RANGES = "぀-ヿ㐀-䶿一-鿿ｦ-ﾝ"
_CJK_PATTERN = re.compile(f"[{_CJK_RANGES}]+")

# A handful of near-meaningless standalone Japanese particles/copulas --
# bigram overlap already dilutes noise far more than word-level stopwords
# do, so this list stays short (unlike a real tokenizer's dictionary).
_CJK_STOPWORDS = {
    "です", "ます", "した", "する", "ない", "こと", "もの", "ため", "これ",
    "それ", "あれ", "この", "その", "れる", "られ", "いる", "ある", "など",
}


def _cjk_bigrams(run: str) -> List[str]:
    """Overlapping 2-character n-grams for a run of CJK characters. This is
    the standard lightweight technique full-text search engines use to
    index Japanese/Chinese without a real morphological analyzer (MeCab,
    Sudachi, ...) -- pulling in one of those (plus its dictionary data)
    would be a heavy new dependency for a pipeline that's deliberately
    stdlib-only keyword overlap, not embeddings/NLP."""
    if len(run) < 2:
        return [run] if run else []
    return [run[i:i + 2] for i in range(len(run) - 1)]


def _significant_words(text: str) -> List[str]:
    text = text or ""
    ascii_words = [
        w for w in re.findall(r"[a-zA-Z0-9]+", text.lower())
        if len(w) > 3 and w not in _DOC_STOPWORDS
    ]
    cjk_words = [
        w for run in _CJK_PATTERN.findall(text) for w in _cjk_bigrams(run)
        if w not in _CJK_STOPWORDS
    ]
    return ascii_words + cjk_words


def _score_doc_relevance(ticket: Dict, path: str, text: str) -> int:
    """Keyword-overlap relevance score (no embeddings/vector search): counts
    how many significant words from the ticket's summary+description also
    appear in the doc's path or text, weighting a filename hit higher than a
    body hit (a doc literally named after the feature is a strong signal)."""
    words = set(_significant_words(f"{ticket.get('summary', '')} {ticket.get('description', '')}"))
    if not words:
        return 0
    path_lower = path.lower()
    text_lower = text.lower()
    score = 0
    for w in words:
        if w in path_lower:
            score += 5
        if w in text_lower:
            score += 1
    return score


def select_relevant_docs(
    ticket: Dict, doc_files: List[Tuple[str, str]], top_n: int = 6, max_chars: int = 1500
) -> Tuple[List[Tuple[str, str]], int]:
    """Rank the repo's discovered documentation files by relevance to this
    ticket and return the top `top_n`, each truncated to `max_chars`, plus
    the TOTAL number of candidates that scored above 0 (which may be more
    than `top_n` — the caller surfaces this to the LLM so it knows when
    doc coverage was truncated, see git_scan.build_scan_result /
    evaluator.build_scan_context's "showing top X of Y" line). Returns
    ([], 0) if nothing scores above 0 — deliberately simple keyword
    overlap, not embeddings, to stay stdlib-only and consistent with the
    rest of this pipeline."""
    if not doc_files:
        return [], 0
    scored = [(_score_doc_relevance(ticket, path, text), path, text) for path, text in doc_files]
    scored = [s for s in scored if s[0] > 0]
    scored.sort(key=lambda s: s[0], reverse=True)
    top = [(path, text[:max_chars]) for _, path, text in scored[:top_n]]
    return top, len(scored)


def _score_image_relevance(ticket: Dict, path: str) -> int:
    """Same keyword-overlap idea as _score_doc_relevance, but images have no
    extractable text — score by filename/path only (e.g. a ticket mentioning
    "cancel confirm modal" ranks screens/cancel-confirm-modal.png highest)."""
    words = set(_significant_words(f"{ticket.get('summary', '')} {ticket.get('description', '')}"))
    if not words:
        return 0
    path_lower = path.lower()
    return sum(5 for w in words if w in path_lower)


def select_relevant_images(
    ticket: Dict, image_files: List[Tuple[str, bytes, str]], top_n: int = 3
) -> List[Tuple[str, bytes, str]]:
    """Rank the repo's discovered screenshot/mockup images by filename
    relevance to this ticket and return the top `top_n`. Returns [] if
    nothing scores above 0."""
    if not image_files:
        return []
    scored = [(_score_image_relevance(ticket, path), path, raw, mime) for path, raw, mime in image_files]
    scored = [s for s in scored if s[0] > 0]
    scored.sort(key=lambda s: s[0], reverse=True)
    return [(path, raw, mime) for _, path, raw, mime in scored[:top_n]]


def _normalise_text(text: str) -> str:
    """Lowercase and strip punctuation for fuzzy matching, but keep CJK
    characters intact (unlike the old [^a-z0-9]+ regex, which erased them
    entirely) -- a Japanese keyword/bigram is a substring of a CJK run in
    this normalised text, the same way an ASCII word is a substring here."""
    return re.sub(rf"[^a-z0-9{_CJK_RANGES}]+", " ", text.lower()).strip()


def _iter_source_files(source_code_dir: str):
    """Yield all source files recursively."""
    for root, dirs, files in os.walk(source_code_dir):
        # Skip common noise directories
        dirs[:] = [
            d for d in dirs
            if d not in {
                "node_modules", ".git", "__pycache__", "venv", ".venv",
                "dist", "build", ".next", ".nuxt", "target", "bin", "obj",
                ".idea", ".vscode", "coverage", ".pytest_cache", ".mypy_cache",
            }
        ]
        for fname in files:
            ext = os.path.splitext(fname)[1].lower()
            if ext in SOURCE_EXTENSIONS:
                yield os.path.join(root, fname)


def _read_file_text(file_path: str) -> str:
    try:
        with open(file_path, "r", encoding="utf-8", errors="ignore") as f:
            return f.read()
    except Exception:
        return ""


def _extract_ticket_refs(content: str) -> List[str]:
    refs: List[str] = []
    for match in TICKET_ID_PATTERN.findall(content):
        normalized = match.upper()
        if normalized not in refs:
            refs.append(normalized)
    return refs


def _match_tickets_against_files(tickets: List[Dict], files_iter_factory) -> Dict[str, Dict]:
    """
    Core two-pass matching, shared by the disk-based scan (ZIP-upload flow,
    `scan_source_for_tickets`) and the in-memory scan (Git-connect flow,
    `scan_source_content_for_tickets`).

    Matching strategy:
      1. Direct ticket-id reference in file content (strongest signal).
      2. Fuzzy keyword overlap between ticket summary/description and file
         content — runs for every ticket, not just ones with no direct hit,
         so the actual implementation files still surface as evidence even
         when a ticket is also (separately) mentioned in documentation.

    `files_iter_factory` is called once per pass and must yield fresh
    (path, content) pairs each time, so a disk-backed caller can re-walk
    instead of holding every file's content in memory at once.

    Returns mapping: ticket_id -> {"files": [...], "snippets": [...]}
    """
    # Precompute ticket keywords. Uses the same tokenizer as doc/image
    # relevance scoring (_significant_words: ASCII words + CJK bigrams) so a
    # ticket written in Japanese generates real keywords here too, instead
    # of _normalise_text(combined).split() reducing an entire untranslated
    # CJK sentence to one giant "word" that would never match anything.
    ticket_keywords: Dict[str, List[str]] = {}
    for t in tickets:
        tid = t["ticket_id"].upper()
        combined = f"{t['summary']} {t['description']}"
        ticket_keywords[tid] = _significant_words(combined)[:12]

    # Pass 1: direct ticket-id references
    direct_hits: Dict[str, List[str]] = {t["ticket_id"].upper(): [] for t in tickets}
    snippets_by_ticket: Dict[str, List[str]] = {}

    for path, content in files_iter_factory():
        if not content:
            continue
        refs = _extract_ticket_refs(content)
        if not refs:
            continue
        snippet = content[:4000]  # Limit context size sent to LLM
        for ref in refs:
            if ref in direct_hits:
                direct_hits[ref].append(path)
                snippets_by_ticket.setdefault(ref, []).append(snippet)

    # Pass 2: fuzzy keyword matching against source code, for ALL tickets.
    # Note: this must run even for tickets that already have a direct hit
    # (e.g. a ticket ID mentioned in a doc/changelog) - otherwise the actual
    # implementation files never get surfaced as evidence, and the ticket
    # ends up "matched" against documentation alone.
    fuzzy_hits: Dict[str, List[str]] = {tid: [] for tid in ticket_keywords}
    for path, content in files_iter_factory():
        if not content:
            continue
        snippet = content[:4000]
        norm_snippet = _normalise_text(snippet)
        for tid, kw in ticket_keywords.items():
            if not kw:
                continue
            score = sum(1 for word in kw if word in norm_snippet)
            # Require at least 2 keyword matches OR 30% of keywords
            threshold = max(2, int(len(kw) * 0.3))
            if score >= threshold:
                fuzzy_hits[tid].append(path)
                snippets_by_ticket.setdefault(tid, []).append(snippet)

    # Merge results
    result: Dict[str, Dict] = {}
    for t in tickets:
        tid = t["ticket_id"].upper()
        files = list(dict.fromkeys(direct_hits.get(tid, []) + fuzzy_hits.get(tid, [])))
        snippets = snippets_by_ticket.get(tid, [])
        result[tid] = {
            "files": files[:20],           # Cap evidence files
            "snippets": snippets[:5],      # Cap snippets sent to LLM
        }
    return result


def scan_source_for_tickets(
    source_code_dir: str, tickets: List[Dict]
) -> Dict[str, Dict]:
    """
    Disk-based scan (ZIP-upload flow): for each ticket, find related source
    files under `source_code_dir`. See `_match_tickets_against_files` for the
    matching strategy. Returns mapping: ticket_id -> {"files": [...], "snippets": [...]}
    """
    if not os.path.isdir(source_code_dir):
        raise FileNotFoundError(f"Source code directory not found: {source_code_dir}")

    def _walk_with_content():
        for file_path in _iter_source_files(source_code_dir):
            yield file_path, _read_file_text(file_path)

    return _match_tickets_against_files(tickets, _walk_with_content)


def scan_source_content_for_tickets(
    tickets: List[Dict], source_files: List[Tuple[str, str]]
) -> Dict[str, Dict]:
    """
    In-memory scan (Git-connect flow): same two-pass matching as
    `scan_source_for_tickets`, but against already-fetched (path, content)
    pairs instead of walking a local directory.
    """
    return _match_tickets_against_files(tickets, lambda: iter(source_files))


def count_scanned_files(source_code_dir: str) -> int:
    """Return total number of source files found (for reporting)."""
    return sum(1 for _ in _iter_source_files(source_code_dir))


# ---------------------------------------------------------------------------
# Documentation/image discovery for the Upload ZIP/Excel flow -- this
# extracted ZIP's equivalent of git_scan.py's _select_doc_paths/
# _select_image_paths + fetch, reading straight off disk instead of over the
# GitHub/GitLab API, so Layer 2's PART B/C (doc_ticket_match/doc_code_match)
# and Layer 4's image attachment work for ZIP uploads exactly like they
# already do for the Connect Git/Jira flow, instead of always seeing "NONE
# FOUND" / no images at all.
# ---------------------------------------------------------------------------
# Same noise dirs as _iter_source_files's exclusion set, EXCEPT "docs" is
# NOT excluded here -- unlike source code, documentation is expected there
# (and, like git_scan._select_doc_paths, is looked for repo-wide, not
# confined to a docs/ folder, since real projects scatter docs across many
# folders).
_EXCLUDED_DOC_DIRS = {
    "node_modules", ".git", "__pycache__", "venv", ".venv",
    "dist", "build", ".next", ".nuxt", "target", "bin", "obj",
    ".idea", ".vscode", "coverage", ".pytest_cache", ".mypy_cache",
}
_MAX_DOC_FILES = 40
_DOC_CHAR_CAP_PER_FILE = 3000
_IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg"}
_IMAGE_MIME_TYPES = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg"}
_MAX_IMAGE_FILES = 10
_MAX_IMAGE_BYTES = 1_500_000


def scan_source_for_docs_and_images(
    source_code_dir: str,
) -> Tuple[List[Tuple[str, str]], List[Tuple[str, bytes, str]]]:
    """Walk `source_code_dir` for documentation files (README/specs/slide
    decks -- doc_extract.DOC_EXTENSIONS) and screenshot/mockup images
    (.png/.jpg/.jpeg), extracting doc text the same way git_scan.py does for
    HTTP-fetched docs (doc_extract.extract_doc_text: HTML tag-stripped, PPTX
    slide/notes text, else decoded as-is). Capped the same way as the
    Git-connect flow (_MAX_DOC_FILES/_MAX_IMAGE_FILES, sorted alphabetically
    before capping) so a huge ZIP can't blow up scan time. Returns
    (doc_files, image_files) in the exact shape
    select_relevant_docs/select_relevant_images and evaluator.py expect."""
    root_dir = Path(source_code_dir)
    doc_paths: List[str] = []
    image_paths: List[str] = []

    for root, dirs, files in os.walk(source_code_dir):
        dirs[:] = [d for d in dirs if d not in _EXCLUDED_DOC_DIRS]
        for fname in files:
            rel_path = (Path(root) / fname).relative_to(root_dir).as_posix()
            ext = doc_extract.file_extension(fname)
            if ext in doc_extract.DOC_EXTENSIONS:
                doc_paths.append(rel_path)
            elif ext in _IMAGE_EXTENSIONS:
                image_paths.append(rel_path)

    doc_files: List[Tuple[str, str]] = []
    for rel_path in sorted(doc_paths)[:_MAX_DOC_FILES]:
        try:
            raw = (root_dir / rel_path).read_bytes()
        except Exception:
            continue
        text = doc_extract.extract_doc_text(rel_path, raw)[:_DOC_CHAR_CAP_PER_FILE]
        if text.strip():
            doc_files.append((rel_path, text))

    image_files: List[Tuple[str, bytes, str]] = []
    for rel_path in sorted(image_paths)[:_MAX_IMAGE_FILES]:
        try:
            raw = (root_dir / rel_path).read_bytes()
        except Exception:
            continue
        if len(raw) <= _MAX_IMAGE_BYTES:
            ext = doc_extract.file_extension(rel_path)
            image_files.append((rel_path, raw, _IMAGE_MIME_TYPES.get(ext, "image/png")))

    return doc_files, image_files


def enrich_scan_result_with_docs(
    scan_result: Dict[str, Dict], tickets: List[Dict], source_code_dir: str
) -> Dict[str, Dict]:
    """Mutates and returns `scan_result` (from scan_source_for_tickets) by
    adding each ticket's top-ranked doc/image matches under the "docs"/
    "docs_total_candidates"/"images" keys -- the Upload ZIP/Excel flow's
    equivalent of git_scan.build_scan_result's doc/image handling. Safe to
    call even when the ZIP has no doc/image files at all (a no-op in that
    case, same as an empty "Related documentation: NONE FOUND" today)."""
    doc_files, image_files = scan_source_for_docs_and_images(source_code_dir)
    if not doc_files and not image_files:
        return scan_result
    for t in tickets:
        tid = t["ticket_id"].upper()
        info = scan_result.setdefault(tid, {"files": [], "snippets": []})
        docs, docs_total_candidates = select_relevant_docs(t, doc_files)
        info["docs"] = docs
        info["docs_total_candidates"] = docs_total_candidates
        info["images"] = select_relevant_images(t, image_files)
    return scan_result


def build_scan_context(
    tickets: List[Dict],
    scan_result: Dict[str, Dict],
    as_of_date: Optional[str] = None,
) -> str:
    """
    Build a compact textual context for the LLM prompt.
    """
    as_of_date = as_of_date or date.today().isoformat()
    lines: List[str] = [f"As of Date: {as_of_date}", ""]
    for t in tickets:
        tid = t["ticket_id"].upper()
        info = scan_result.get(tid, {"files": [], "snippets": []})
        lines.append(f"--- TICKET {tid} ---")
        lines.append(f"Status: {t['status']}")
        lines.append(f"Due Date: {t.get('due_date') or '(none)'}")
        lines.append(f"Summary: {t['summary']}")
        lines.append(f"Description: {t['description'][:1500]}")
        if info["files"]:
            lines.append("Matched source files:")
            for fp in info["files"]:
                lines.append(f"  - {fp}")
        else:
            lines.append("Matched source files: NONE")
        if info["snippets"]:
            lines.append("Relevant code snippets (truncated):")
            for snip in info["snippets"]:
                lines.append(snip[:1200])
        docs = info.get("docs") or []
        docs_total = info.get("docs_total_candidates", len(docs))
        if docs:
            if docs_total > len(docs):
                lines.append(
                    f"Related documentation (showing top {len(docs)} of {docs_total} candidate docs "
                    "ranked by keyword relevance, may be outdated -- MORE CANDIDATE DOCS EXIST THAT ARE "
                    "NOT SHOWN HERE):"
                )
            else:
                lines.append("Related documentation (top match by keyword relevance, may be outdated):")
            for doc_path, doc_text in docs:
                lines.append(f"  [{doc_path}]")
                lines.append(doc_text)
        else:
            lines.append("Related documentation: NONE FOUND")
        lines.append("")
    return "\n".join(lines)