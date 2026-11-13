"""
Re-evaluation cache for the Connect Git/Jira page's "Re-evaluate with AI"
on an EXISTING project: skips a full AI re-run for a ticket whose relevant
state hasn't changed since the last time it was actually checked, saving
the LLM calls (time + tokens) that dominate the cost of a re-run.

A ticket is only ever skipped when ALL of the following hold against its
last known evaluation:
  1. that evaluation's assessment was 'Match' (Incomplete/Mismatch always
     deserve a fresh look -- there's nothing to "confirm unchanged" there)
  2. the ticket's reported status hasn't changed
  3. the ticket's summary/description haven't changed (content_hash)
  4. the repo's commit SHA hasn't changed since that evaluation

If the repo hasn't moved and the ticket itself hasn't changed, an
identical LLM call would almost certainly reach the same verdict, so
skipping is safe. Any drift in ANY of these re-queues the ticket for a
real evaluation -- this is deliberately NOT "skip anything marked Done",
which would blindly miss a regression a later unrelated commit introduced.

content_hash/source_commit are carried forward unchanged on a cached row
too (see scan_runs.save_scan_run), so comparing against the immediately
preceding run (real or cached) is always equivalent to comparing against
the last REAL evaluation -- no special-casing needed to "see through" a
run of consecutive cache hits.
"""
import hashlib
from typing import Dict, List, Optional, Tuple

import db
from models import TicketResult

_LATEST_BY_TICKET_SQL = """
    SELECT DISTINCT ON (t.ticket_key)
        t.ticket_key, er.assessment, er.reported_status, er.content_hash,
        er.completion_percent, er.confidence, er.schedule_status, er.days_diff,
        er.missing_parts, er.suggestions, er.evidence_files, er.notes,
        sr.source_commit
    FROM evaluation_results er
    JOIN tickets t ON t.id = er.ticket_id
    JOIN scan_runs sr ON sr.id = er.scan_run_id
    WHERE t.project_id = %s AND sr.status = 'done'
    ORDER BY t.ticket_key, sr.completed_at DESC
"""


def content_hash(ticket: Dict) -> str:
    """Fingerprint of the fields that would change what the AI sees for
    this ticket -- status, summary, description. Anything else (assignee,
    due date, ...) doesn't affect the Match/Mismatch/Incomplete verdict."""
    raw = "".join([
        (ticket.get("status") or "").strip(),
        (ticket.get("summary") or "").strip(),
        (ticket.get("description") or "").strip(),
    ])
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def get_latest_by_ticket(project_id: int) -> Dict[str, Dict]:
    """Each ticket's most recent evaluation_results row for this project
    (real or cached -- see module docstring for why that distinction
    doesn't matter here), keyed by upper-cased ticket_key. Empty dict if
    the DB isn't configured or the project has never been evaluated."""
    if not db.is_configured():
        return {}
    with db.get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(_LATEST_BY_TICKET_SQL, (project_id,))
            rows = cur.fetchall()

    result: Dict[str, Dict] = {}
    for (
        ticket_key, assessment, reported_status, chash, completion_percent, confidence,
        schedule_status, days_diff, missing_parts, suggestions, evidence_files, notes,
        source_commit,
    ) in rows:
        result[ticket_key.upper()] = {
            "assessment": assessment,
            "reported_status": reported_status,
            "content_hash": chash,
            "completion_percent": completion_percent,
            "confidence": confidence,
            "schedule_status": schedule_status,
            "days_diff": days_diff,
            "missing_parts": missing_parts or [],
            "suggestions": suggestions or [],
            "evidence_files": evidence_files or [],
            "notes": notes or "",
            "source_commit": source_commit,
        }
    return result


def _cached_result(ticket: Dict, prior: Dict) -> TicketResult:
    """Re-emit the prior evaluation as this run's result, unchanged except
    for the from_cache/previous_assessment bookkeeping the UI needs."""
    return TicketResult(
        ticket_id=ticket["ticket_id"],
        summary=ticket.get("summary") or "",
        status=ticket.get("status") or "",
        completion_percent=prior["completion_percent"] or 0,
        assessment=prior["assessment"],
        confidence=prior["confidence"] or 0,
        missing_parts=prior["missing_parts"],
        suggestions=prior["suggestions"],
        evidence_files=prior["evidence_files"],
        notes=prior["notes"],
        schedule_status=prior["schedule_status"] or "",
        days_diff=prior["days_diff"],
        assignee=ticket.get("assignee") or "",
        previous_assessment=prior["assessment"],
        from_cache=True,
    )


def partition(
    tickets: List[Dict],
    project_id: Optional[int],
    current_commit: Optional[str],
    force: bool = False,
) -> Tuple[List[Dict], List[TicketResult], Dict[str, Optional[str]]]:
    """Split `tickets` into (needs_real_evaluation, cached_results), plus a
    ticket_id -> previous_assessment map covering EVERY ticket (including
    ones that still need real evaluation) so the caller can attach it to
    those results too, for the "Previous Assessment" UI column.

    Returns (tickets, [], {}) unchanged -- i.e. nothing skipped -- when
    project_id is None (brand-new project, nothing to compare against),
    `force` is True, or current_commit couldn't be determined (safer to
    evaluate for real than to trust a comparison against an unknown
    baseline)."""
    previous_by_id: Dict[str, Optional[str]] = {}
    latest = get_latest_by_ticket(project_id) if (project_id and not force) else {}

    to_evaluate: List[Dict] = []
    cached: List[TicketResult] = []
    for t in tickets:
        tid = t["ticket_id"].upper()
        prior = latest.get(tid)
        previous_by_id[tid] = prior["assessment"] if prior else None

        if force or not prior:
            to_evaluate.append(t)
            continue

        unchanged = (
            prior["assessment"] == "Match"
            and (t.get("status") or "") == (prior["reported_status"] or "")
            and content_hash(t) == prior["content_hash"]
            and current_commit is not None
            and current_commit == prior["source_commit"]
        )
        if unchanged:
            cached.append(_cached_result(t, prior))
        else:
            to_evaluate.append(t)

    return to_evaluate, cached, previous_by_id
