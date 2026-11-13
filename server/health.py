"""
Rolls up per-ticket evaluation results into an overall project health
snapshot for the dashboard: an OK/Risk/Late status, the list of flagged
issues/risks, and progress on the next upcoming milestone.
"""
import re
from datetime import date, datetime
from typing import Dict, List, Optional

from models import IssueFlag, MilestoneStatus, ProjectHealth, TicketResult

_DATE_FORMATS = ("%Y-%m-%d", "%d/%b/%y", "%d/%b/%Y", "%m/%d/%Y", "%d/%m/%Y")
_TICKET_ID_SUFFIX_RE = re.compile(r"^(.*?)(\d+)$")


def _ticket_id_sort_key(ticket_id: str):
    """Natural sort for 'PREFIX-123' style ticket IDs, so ...-2 sorts before
    ...-10 instead of a plain string compare putting ...-10 first."""
    m = _TICKET_ID_SUFFIX_RE.match(ticket_id)
    if m:
        prefix, number = m.groups()
        return (prefix, int(number))
    return (ticket_id, -1)


def _parse_date(value: str) -> Optional[date]:
    if not value:
        return None
    value = value.strip()
    for fmt in _DATE_FORMATS:
        try:
            return datetime.strptime(value, fmt).date()
        except ValueError:
            continue
    return None


def _issue_reason(result: TicketResult) -> str:
    """Pick the most useful one-line explanation for a flagged ticket."""
    if result.missing_parts:
        return result.missing_parts[0]
    if result.notes:
        for line in result.notes.splitlines():
            line = line.strip()
            # Skip the machine-readable "SCHEDULE: ..." line if present.
            if line and not line.upper().startswith("SCHEDULE:"):
                return line
    return f"{result.assessment}: no additional detail from evaluation."


def _is_flagged(r: TicketResult) -> bool:
    """
    A ticket is a genuine issue/risk only if the code contradicts its
    reported status (Mismatch) or its schedule has actually slipped or is
    slipping (Late / At-Risk). Merely being "Incomplete" - i.e. still
    honest, in-progress work with no schedule problem - is not an issue.
    """
    return r.assessment == "Mismatch" or r.schedule_status in ("Late", "At-Risk")


def _severity(r: TicketResult) -> int:
    """Higher = more severe. Late and Mismatch each add independently, so a
    ticket that's both overdue AND code-mismatched ranks above either alone."""
    score = 0
    if r.schedule_status == "Late":
        score += 3
    elif r.schedule_status == "At-Risk":
        score += 1
    if r.assessment == "Mismatch":
        score += 2
    return score


def _overall_status(results: List[TicketResult]) -> str:
    """Worst-ticket-wins: Late > Risk > OK."""
    status = "OK"
    for r in results:
        if r.assessment == "Mismatch" or r.schedule_status == "Late":
            return "Late"
        if r.schedule_status == "At-Risk":
            status = "Risk"
    return status


def _flagged_issues(results: List[TicketResult]) -> List[IssueFlag]:
    flagged = [r for r in results if _is_flagged(r)]
    flagged.sort(key=lambda r: (-_severity(r), _ticket_id_sort_key(r.ticket_id)))
    return [
        IssueFlag(
            ticket_id=r.ticket_id,
            summary=r.summary,
            assessment=r.assessment,
            schedule_status=r.schedule_status,
            reason=_issue_reason(r),
        )
        for r in flagged
    ]


def _next_milestone(
    tickets_by_id: Dict[str, Dict], results: List[TicketResult], as_of: date
) -> MilestoneStatus:
    """
    Among tickets whose JIRA Issue Type is literally "Milestone" and that
    have a parseable Due Date, pick the nearest upcoming one (falling back
    to the most recently passed one if none are upcoming) and report its
    progress relative to that date.
    """
    candidates = []
    for r in results:
        t = tickets_by_id.get(r.ticket_id.upper())
        if not t or (t.get("issue_type") or "").strip().lower() != "milestone":
            continue
        due = _parse_date(t.get("due_date") or "")
        if due is None:
            continue
        candidates.append((due, t, r))

    if not candidates:
        return MilestoneStatus(
            status="None",
            days=None,
            message='No milestone tickets found (Issue Type = "Milestone" with a Due Date).',
        )

    upcoming = [c for c in candidates if c[0] >= as_of]
    due, ticket, result = min(upcoming, key=lambda c: c[0]) if upcoming else max(candidates, key=lambda c: c[0])
    days_diff = (as_of - due).days  # positive=overdue, negative=days remaining

    if result.completion_percent >= 100:
        if days_diff < 0:
            status, message = "Early", f"Done {abs(days_diff)} day(s) ahead of schedule."
        else:
            status, message = "On-time", "Completed on schedule."
    elif days_diff > 0:
        status, message = "Late", f"Overdue by {days_diff} day(s)."
    elif result.schedule_status == "At-Risk":
        status, message = "At-Risk", f"At risk of missing the deadline — {abs(days_diff)} day(s) remaining."
    else:
        status, message = "On-time", f"On track — {abs(days_diff)} day(s) remaining."

    return MilestoneStatus(
        ticket_id=ticket["ticket_id"],
        summary=ticket.get("summary", ""),
        due_date=ticket.get("due_date", ""),
        status=status,
        days=days_diff,
        message=message,
    )


def build_project_health(
    tickets: List[Dict], results: List[TicketResult], as_of: Optional[date] = None
) -> ProjectHealth:
    as_of = as_of or date.today()
    tickets_by_id = {t["ticket_id"].upper(): t for t in tickets}

    return ProjectHealth(
        status=_overall_status(results),
        issues=_flagged_issues(results),
        next_milestone=_next_milestone(tickets_by_id, results, as_of),
    )
