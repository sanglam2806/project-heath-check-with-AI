"""
Shared documentation-file helpers: the doc-extension set + byte->text
extraction (HTML tag-stripping, PPTX slide/notes text). Used by both
git_scan.py (fetching doc files from GitHub/GitLab over HTTP, as bytes)
and code_tools.py (reading doc files from a local clone on disk, for the
Layer-4 agent's doc tools). stdlib-only except python-pptx for .pptx
slide text.
"""
import io
from html.parser import HTMLParser
from typing import List

DOC_EXTENSIONS = {".md", ".mdx", ".txt", ".rst", ".adoc", ".html", ".htm", ".pptx"}


def file_extension(path: str) -> str:
    idx = path.rfind(".")
    return path[idx:].lower() if idx != -1 else ""


def _text_extracting_html_parser():
    parts: List[str] = []

    class _Parser(HTMLParser):
        def __init__(self):
            super().__init__()
            self._skip_depth = 0

        def handle_starttag(self, tag, attrs):
            if tag in ("script", "style"):
                self._skip_depth += 1

        def handle_endtag(self, tag):
            if tag in ("script", "style") and self._skip_depth > 0:
                self._skip_depth -= 1

        def handle_data(self, data):
            if self._skip_depth == 0:
                text = data.strip()
                if text:
                    parts.append(text)

    return _Parser(), parts


def html_to_text(raw: bytes) -> str:
    """Strip tags/scripts/styles from an HTML doc (architecture.html,
    ui-audit.html, ...) down to readable text, stdlib-only (no BeautifulSoup)."""
    parser, parts = _text_extracting_html_parser()
    try:
        parser.feed(raw.decode("utf-8", errors="ignore"))
    except Exception:
        return ""
    return " ".join(parts)


def pptx_to_text(raw: bytes) -> str:
    """Extract slide text + speaker notes from a .pptx (e.g. a design deck
    with UX/business-rule slides). Slide images are not compared — text only."""
    try:
        from pptx import Presentation
    except ImportError:
        return ""
    try:
        prs = Presentation(io.BytesIO(raw))
    except Exception:
        return ""
    lines: List[str] = []
    for i, slide in enumerate(prs.slides, 1):
        slide_lines = []
        for shape in slide.shapes:
            if getattr(shape, "has_text_frame", False) and shape.text_frame.text.strip():
                slide_lines.append(shape.text_frame.text.strip())
        if getattr(slide, "has_notes_slide", False) and slide.notes_slide.notes_text_frame:
            notes = slide.notes_slide.notes_text_frame.text.strip()
            if notes:
                slide_lines.append(f"[Notes] {notes}")
        if slide_lines:
            lines.append(f"[Slide {i}] " + " | ".join(slide_lines))
    return "\n".join(lines)


def extract_doc_text(path: str, raw: bytes) -> str:
    """Convert raw file bytes to plain text based on `path`'s extension --
    HTML gets tag-stripped, PPTX gets slide/notes text, everything else
    (Markdown/txt/rst/adoc) is decoded as UTF-8 as-is."""
    ext = file_extension(path)
    if ext in (".html", ".htm"):
        return html_to_text(raw)
    if ext == ".pptx":
        return pptx_to_text(raw)
    return raw.decode("utf-8", errors="ignore")
