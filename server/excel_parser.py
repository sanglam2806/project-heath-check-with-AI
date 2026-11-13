"""
Parse JIRA/Excel ticket exports into a normalized list of tickets.

Supports .xlsx and .xlsm files. We read the following columns and map them
to fields used for comparison against the source code:

    1. Key          -> ticket_id
    2. Summary      -> summary
    3. Status       -> status
    4. Description  -> description

Column mapping is flexible: we look for these common header names
(case-insensitive). If no recognizable header is found, we assume the
fixed positional order Key, Summary, Status, Description.

Real-world JIRA "general_report" exports don't always put the header on
row 1 — they often prepend a project/title line and a "Displaying N
issues at ..." caption first. They can also be extremely wide (one column
per custom field, sometimes 400+ columns) and render each issue as a
tall block of merged cells rather than a single flat row. This parser
scans the first few rows to locate the real header (instead of assuming
row 1), and treats a non-blank ticket-id OR summary cell — not "row is
fully blank" — as the signal for where one issue's data starts, so
multi-row merged blocks collapse correctly into a single ticket per
issue. Some rows are real, tracked work items with a Summary but no Key
yet (e.g. backlog/planning notes not formally ticketed in JIRA) - those
get a synthetic ticket_id instead of being silently dropped.
"""
import io
import re
from datetime import date, datetime
from typing import Dict, List, Optional, Tuple

from i18n import TranslatableError

try:
    import openpyxl
except ImportError:  # pragma: no cover
    openpyxl = None


# Common header aliases for each logical field.
# The canonical names (Key, Summary, Status, Description) are listed first.
_FIELD_ALIASES: Dict[str, List[str]] = {
    "ticket_id": [
        "key", "issue key", "issuekey", "ticket_id", "ticket id",
        "ticket", "id", "jira id", "jiraid", "issue id", "issueid",
        "story id", "storyid", "task id", "taskid", "bug id", "bugid",
    ],
    "summary": [
        "summary", "title", "subject", "issue summary", "issuetitle",
        "ticket summary", "ticket title", "name", "headline",
    ],
    "status": [
        "status", "state", "current status", "ticket status",
        "issue status", "workflow status", "resolution",
    ],
    "description": [
        "description", "desc", "details", "detail", "body", "content",
        "issue description", "ticket description", "acceptance criteria",
        "acceptancecriteria", "notes", "note", "comment", "comments",
    ],
    "due_date": [
        "due date", "duedate", "due_date", "deadline", "target date",
        "target_date", "planned end date", "end date",
    ],
    "issue_type": [
        "issue type", "issuetype", "issue_type", "type", "ticket type",
        "work item type",
    ],
    "assignee": [
        "assignee", "assigned to", "assigned_to", "assign to", "assign_to",
        "owner", "responsible",
    ],
}

# How many leading rows to scan when searching for the real header row
# (JIRA report exports typically have 2-3 title/caption rows before it).
_HEADER_SCAN_ROWS = 30


def _normalize(value) -> str:
    """Lowercase and collapse whitespace for header matching."""
    return " ".join(str(value).strip().lower().split())


def _find_column_index(headers: List, aliases: List[str]) -> int:
    """Return the index of the first header that matches any alias, or -1."""
    norm_headers = [_normalize(h) if h is not None else "" for h in headers]
    for alias in aliases:
        norm_alias = _normalize(alias)
        for i, h in enumerate(norm_headers):
            if h == norm_alias:
                return i
    return -1


def _format_cell(field: str, value) -> str:
    """Stringify a cell value; dates are rendered as YYYY-MM-DD."""
    if value is None:
        return ""
    if field == "due_date" and isinstance(value, (datetime, date)):
        return value.strftime("%Y-%m-%d")
    return str(value).strip()


_ID_PREFIX_RE = re.compile(r"^(.*?-)\d+$")


def _derive_synthetic_prefix(first_real_id: str) -> str:
    """
    Build a prefix for auto-generated IDs from a real ticket ID seen in
    the sheet, e.g. 'COWORKLOCAL-14' -> 'COWORKLOCAL-U' (so backlog rows
    with no Key get an ID like 'COWORKLOCAL-U1' that can't collide with a
    real ticket number).
    """
    m = _ID_PREFIX_RE.match(first_real_id)
    prefix = m.group(1) if m else f"{first_real_id}-"
    return f"{prefix}U"


def _locate_header_row(ws) -> Optional[Tuple[int, List]]:
    """
    Scan the first `_HEADER_SCAN_ROWS` rows for the real header row: the
    first row that has a recognizable ticket-id column AND at least one
    other recognizable column (summary/status/description). Requiring two
    matches avoids mistaking a stray title/caption cell for the header.

    Returns (row_number, header_values) or None if no such row is found.
    """
    max_row = min(ws.max_row, _HEADER_SCAN_ROWS)
    if max_row < 1:
        return None

    for offset, row in enumerate(
        ws.iter_rows(min_row=1, max_row=max_row, values_only=True)
    ):
        headers = list(row)
        id_idx = _find_column_index(headers, _FIELD_ALIASES["ticket_id"])
        if id_idx == -1:
            continue
        other_hit = any(
            _find_column_index(headers, _FIELD_ALIASES[field]) != -1
            for field in ("summary", "status", "description")
        )
        if other_hit:
            return offset + 1, headers
    return None


def _extract_tickets_from_rows(
    ws, data_start_row: int, idx: Dict[str, int]
) -> List[Dict]:
    """
    Walk worksheet rows starting at `data_start_row` (1-indexed), pull out
    fields using the given field->column-index map (-1/missing means "no
    such column"), and return deduped ticket dicts. Shared by both the
    alias-auto-detected path and the user-mapped path so the row-walk,
    synthetic-ID minting, and dedup logic only live in one place.
    """
    tickets: List[Dict] = []
    seen_ids = set()
    synthetic_prefix: Optional[str] = None
    synthetic_counter = 0

    present_cols = [i for i in idx.values() if i is not None and i != -1]
    max_needed_col = (max(present_cols) + 1) if present_cols else 1

    for row in ws.iter_rows(
        min_row=data_start_row,
        max_row=ws.max_row,
        min_col=1,
        max_col=max_needed_col,
        values_only=True,
    ):
        def get(field: str) -> str:
            i = idx.get(field)
            if i is None or i == -1 or i >= len(row):
                return ""
            return _format_cell(field, row[i])

        ticket_id = get("ticket_id")
        summary = get("summary")
        # A row counts as real data - not a blank continuation row left
        # behind by a tall, per-issue merged-cell block - if it has a
        # ticket ID *or* a summary.
        if not ticket_id and not summary:
            continue

        if ticket_id:
            if synthetic_prefix is None:
                synthetic_prefix = _derive_synthetic_prefix(ticket_id)
        else:
            # Real, tracked work item with no JIRA Key yet (e.g. a
            # backlog/planning row) - synthesize a stable ID instead of
            # dropping it.
            if synthetic_prefix is None:
                synthetic_prefix = "TASK-U"
            synthetic_counter += 1
            ticket_id = f"{synthetic_prefix}{synthetic_counter}"

        key = ticket_id.upper()
        if key in seen_ids:
            continue
        seen_ids.add(key)

        tickets.append({
            "ticket_id": ticket_id,
            "summary": summary or "(untitled)",
            "status": get("status") or "To Do",
            "description": get("description"),
            "due_date": get("due_date"),
            "issue_type": get("issue_type"),
            "assignee": get("assignee"),
        })

    return tickets


def _load_workbook_sheet(file_bytes: bytes, filename: str = ""):
    """Shared open-and-pick-sheet logic. Returns (workbook, worksheet)."""
    if openpyxl is None:
        raise TranslatableError("excel.openpyxl_missing", status_code=400)

    name_lower = (filename or "").lower()
    if not (name_lower.endswith(".xlsx") or name_lower.endswith(".xlsm")):
        raise TranslatableError("excel.unsupported_format", status_code=400)

    try:
        wb = openpyxl.load_workbook(io.BytesIO(file_bytes), read_only=True, data_only=True)
    except Exception as exc:
        raise TranslatableError("excel.read_failed", status_code=400, reason=str(exc))

    # Prefer a sheet named like a JIRA export; otherwise use the active sheet.
    ws = None
    for candidate in wb.sheetnames:
        if "report" in candidate.lower() or "issue" in candidate.lower():
            ws = wb[candidate]
            break
    if ws is None:
        ws = wb.active
    if ws is None:
        wb.close()
        raise TranslatableError("excel.no_worksheets", status_code=400)

    return wb, ws


def parse_tickets_from_excel(file_bytes: bytes, filename: str = "") -> List[Dict]:
    """
    Read an Excel workbook and return a list of ticket dicts.

    Each dict has keys: ticket_id, summary, status, description.
    Raises ValueError on unsupported formats or empty data.
    """
    wb, ws = _load_workbook_sheet(file_bytes, filename)
    header_hit = _locate_header_row(ws)

    if header_hit is not None:
        header_row_num, headers = header_hit
        idx = {
            field: _find_column_index(headers, aliases)
            for field, aliases in _FIELD_ALIASES.items()
        }
        tickets = _extract_tickets_from_rows(ws, header_row_num + 1, idx)
    else:
        # No recognizable header found in the scanned range: fall back to
        # the fixed positional order Key, Summary, Status, Description,
        # starting from the first non-empty row.
        idx = {"ticket_id": 0, "summary": 1, "status": 2, "description": 3}
        tickets = []
        seen_ids = set()
        for row in ws.iter_rows(values_only=True):
            if all(cell is None or str(cell).strip() == "" for cell in row):
                continue

            def get(field: str) -> str:
                i = idx[field]
                if i >= len(row):
                    return ""
                v = row[i]
                return "" if v is None else str(v).strip()

            ticket_id = get("ticket_id")
            if not ticket_id:
                continue

            key = ticket_id.upper()
            if key in seen_ids:
                continue
            seen_ids.add(key)

            tickets.append({
                "ticket_id": ticket_id,
                "summary": get("summary") or "(untitled)",
                "status": get("status") or "To Do",
                "description": get("description"),
                "due_date": "",
                "issue_type": "",
                "assignee": "",
            })

    wb.close()

    if not tickets:
        raise TranslatableError("excel.no_tickets_found", status_code=400)

    return tickets


def read_excel_preview(
    file_bytes: bytes, filename: str = "", max_rows: int = 15
) -> Dict:
    """
    Return the first few raw rows of the uploaded workbook (regardless of
    where the real header is), plus a best-effort guess of which row is the
    header and a suggested column mapping for it. The frontend lets the
    user override the header row (for templates with caption rows before
    the real header, or non-English headers the alias matcher can't
    recognize) as well as the column->field mapping.
    """
    wb, ws = _load_workbook_sheet(file_bytes, filename)
    header_hit = _locate_header_row(ws)
    guessed_header_row = header_hit[0] if header_hit is not None else 1

    max_col = 1
    all_rows: List[List[str]] = []
    for row in ws.iter_rows(min_row=1, max_row=max_rows, values_only=True):
        cells = [_format_cell("preview", v)[:200] for v in row]
        # Trim fully-blank trailing cells but keep at least 1 column.
        while len(cells) > 1 and cells[-1] == "":
            cells.pop()
        max_col = max(max_col, len(cells))
        all_rows.append(cells)
    # Pad every row to the same width so the frontend can render a rectangular grid.
    all_rows = [row + [""] * (max_col - len(row)) for row in all_rows]

    suggested_mapping: Dict[str, Optional[int]] = {}
    if header_hit is not None:
        _, raw_headers = header_hit
        for field, aliases in _FIELD_ALIASES.items():
            idx = _find_column_index(raw_headers, aliases)
            suggested_mapping[field] = idx if idx != -1 else None
    else:
        suggested_mapping = {field: None for field in _FIELD_ALIASES.keys()}

    sheet_name = ws.title
    wb.close()

    header_idx = guessed_header_row - 1
    headers = (
        [c or f"Column {chr(65 + i)}" for i, c in enumerate(all_rows[header_idx])]
        if 0 <= header_idx < len(all_rows)
        else []
    )

    return {
        "sheet_name": sheet_name,
        "header_row": guessed_header_row,
        "headers": headers,  # best guess only; frontend recomputes labels if the user picks a different header row
        "preview_rows": all_rows,
        "suggested_mapping": suggested_mapping,
    }


def parse_tickets_from_excel_with_mapping(
    file_bytes: bytes,
    filename: str,
    mapping: Dict[str, Optional[int]],
    header_row: Optional[int] = None,
) -> List[Dict]:
    """
    Parse tickets using the caller's explicit column->field mapping
    (field -> 0-based column index, or None/missing for "not mapped")
    instead of alias auto-detection.
    """
    wb, ws = _load_workbook_sheet(file_bytes, filename)

    if header_row is None:
        header_hit = _locate_header_row(ws)
        header_row = header_hit[0] if header_hit is not None else 1

    idx = {
        field: (mapping.get(field) if mapping.get(field) is not None else -1)
        for field in _FIELD_ALIASES.keys()
    }

    if idx.get("ticket_id", -1) == -1 and idx.get("summary", -1) == -1:
        wb.close()
        raise TranslatableError("excel.no_usable_mapping", status_code=400)

    tickets = _extract_tickets_from_rows(ws, header_row + 1, idx)
    wb.close()

    if not tickets:
        raise TranslatableError("excel.no_tickets_with_mapping", status_code=400)

    return tickets


def tickets_to_tsv(tickets: List[Dict]) -> str:
    """Render tickets as tab-separated text for the frontend textarea."""
    lines = ["ticket_id\tsummary\tstatus\tdescription\tdue_date\tissue_type\tassignee"]
    for t in tickets:
        def clean(v: str) -> str:
            return (v or "").replace("\t", " ").replace("\n", " ")

        lines.append(
            "\t".join([
                clean(t["ticket_id"]),
                clean(t["summary"]),
                clean(t["status"]),
                clean(t["description"]),
                clean(t.get("due_date", "")),
                clean(t.get("issue_type", "")),
                clean(t.get("assignee", "")),
            ])
        )
    return "\n".join(lines)
