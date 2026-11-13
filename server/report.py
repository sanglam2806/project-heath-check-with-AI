"""
Excel report export: turns a completed evaluation (tickets + per-ticket
TicketResult + Summary + optional ProjectHealth) into a downloadable
.xlsx workbook a PM can open directly -- a Summary sheet (project-level
health/counts) and a Tickets sheet (one row per ticket). The per-ticket
`suggestions` field (already computed by evaluator.py -- LLM or heuristic,
"Recommended fixes") is included as its own "Recommended Action" column so
a PM can see exactly what to do about each ticket without digging through
free-form `notes`.
"""
from datetime import date
from io import BytesIO
from typing import Dict, List, Optional

import openpyxl
from openpyxl.styles import Alignment, Font
from openpyxl.utils import get_column_letter

from models import ProjectHealth, Summary, TicketResult

_TICKET_HEADERS = [
    "Ticket ID", "Summary", "Reported Status", "Assessment", "Completion %",
    "Confidence", "Schedule Status", "Assignee", "Missing Parts",
    "Recommended Action", "Doc vs Ticket", "Doc vs Code", "Evidence Files", "Notes",
]


def _autosize_columns(ws, max_width: int = 60) -> None:
    for col_cells in ws.columns:
        length = max((len(str(c.value)) if c.value is not None else 0) for c in col_cells)
        ws.column_dimensions[get_column_letter(col_cells[0].column)].width = min(length + 4, max_width)


def _write_summary_sheet(
    wb, project_name: str, summary: Summary, health: Optional[ProjectHealth]
) -> None:
    ws = wb.active
    ws.title = "Summary"
    ws.append(["Project Health Report"])
    ws["A1"].font = Font(bold=True, size=14)
    ws.append(["Project", project_name or "(unnamed)"])
    ws.append(["Generated", date.today().isoformat()])
    ws.append([])
    if health:
        ws.append(["Health Status", health.status])
    ws.append(["Total Tickets", summary.total_tickets])
    ws.append(["Match", summary.match_count])
    ws.append(["Mismatch", summary.mismatch_count])
    ws.append(["Incomplete", summary.incomplete_count])
    ws.append(["Match %", f"{summary.match_percent}%"])
    ws.append(["Avg Completion", f"{summary.avg_completion}%"])
    ws.append(["Scanned Files", summary.scanned_files])

    for row in ws.iter_rows(min_row=2, min_col=1, max_col=1):
        for cell in row:
            cell.font = Font(bold=True)
    _autosize_columns(ws)


def _write_tickets_sheet(wb, tickets: List[Dict], results: List[TicketResult]) -> None:
    ws = wb.create_sheet("Tickets")
    ws.append(_TICKET_HEADERS)
    for cell in ws[1]:
        cell.font = Font(bold=True)

    tickets_by_id = {t["ticket_id"].upper(): t for t in tickets}
    for r in results:
        t = tickets_by_id.get(r.ticket_id.upper(), {})
        ws.append([
            r.ticket_id,
            r.summary,
            r.status,
            r.assessment,
            r.completion_percent,
            round(r.confidence, 2),
            r.schedule_status,
            r.assignee or t.get("assignee", ""),
            "\n".join(r.missing_parts),
            "\n".join(r.suggestions),
            r.doc_ticket_match,
            r.doc_code_match,
            "\n".join(r.evidence_files),
            r.notes,
        ])

    for row in ws.iter_rows(min_row=2):
        for cell in row:
            cell.alignment = Alignment(wrap_text=True, vertical="top")
    ws.freeze_panes = "A2"
    _autosize_columns(ws)


def build_report_workbook(
    project_name: str,
    tickets: List[Dict],
    results: List[TicketResult],
    summary: Summary,
    health: Optional[ProjectHealth] = None,
) -> BytesIO:
    """Build the .xlsx report and return it as an in-memory buffer, ready
    to stream back as a download."""
    wb = openpyxl.Workbook()
    _write_summary_sheet(wb, project_name, summary, health)
    _write_tickets_sheet(wb, tickets, results)

    buffer = BytesIO()
    wb.save(buffer)
    buffer.seek(0)
    return buffer
