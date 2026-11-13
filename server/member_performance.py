"""
Cross-project member performance rollup: aggregates each assignee's ticket
counts (Total/Complete/In Process/Late) across every project's latest
snapshot scan -- the org-wide equivalent of AssigneeStatsPanel.jsx (which
is scoped to a single project's currently-displayed result).

Grouped by tickets.assignee_key (Jira's accountId, immutable per person)
when available, else a normalized assignee display name. This matters
because two different real people can share a display name across
projects -- accountId tells them apart, but Excel/ZIP-sourced tickets have
no such identifier at all, so those fall back to name-matching. A known,
accepted limitation (see schema.sql's tickets.assignee_key comment), not a
bug: there is no reliable identifier to use instead for that source.
"""
from typing import Dict, List

import db
import ticket_status

_ROWS_SQL = """
    WITH latest_runs AS (
        SELECT DISTINCT ON (project_id) id AS scan_run_id, project_id
        FROM scan_runs
        WHERE is_snapshot = true AND status = 'done'
        ORDER BY project_id, completed_at DESC NULLS LAST
    )
    SELECT
        COALESCE(NULLIF(t.assignee_key, ''), lower(trim(t.assignee))) AS group_key,
        t.assignee,
        p.id,
        p.name,
        er.reported_status,
        er.assessment,
        er.schedule_status
    FROM latest_runs lr
    JOIN evaluation_results er ON er.scan_run_id = lr.scan_run_id
    JOIN tickets t ON t.id = er.ticket_id
    JOIN projects p ON p.id = lr.project_id
    WHERE t.assignee IS NOT NULL AND trim(t.assignee) <> ''
      AND er.assessment <> 'Skipped'
"""


def build_member_performance() -> List[Dict]:
    """One row per (assignee, project) evaluated ticket, rolled up into one
    entry per assignee (keyed by group_key) with a per-project breakdown.
    "Complete"/"In Process" mirror ticket_status.is_done_status/
    is_in_progress_status on the reported status -- the same definition
    used everywhere else in this app (evaluator prompts, Risk score,
    Project List's Complete Tickets column, AssigneeStatsPanel.jsx)."""
    with db.get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(_ROWS_SQL)
            rows = cur.fetchall()

    members: Dict[str, Dict] = {}
    for group_key, assignee, project_id, project_name, reported_status, assessment, schedule_status in rows:
        member = members.setdefault(group_key, {
            "assignee_key": group_key,
            "display_name": assignee,
            "total": 0,
            "complete": 0,
            "in_process": 0,
            "late": 0,
            "match_count": 0,
            "mismatch_count": 0,
            "incomplete_count": 0,
            "projects": {},
        })
        is_complete = ticket_status.is_done_status(reported_status)
        is_in_process = ticket_status.is_in_progress_status(reported_status)
        is_late = schedule_status == "Late"

        member["total"] += 1
        if is_complete:
            member["complete"] += 1
        if is_in_process:
            member["in_process"] += 1
        if is_late:
            member["late"] += 1
        if assessment == "Match":
            member["match_count"] += 1
        elif assessment == "Mismatch":
            member["mismatch_count"] += 1
        elif assessment == "Incomplete":
            member["incomplete_count"] += 1

        proj = member["projects"].setdefault(
            project_id, {"project_id": project_id, "project_name": project_name, "total": 0, "complete": 0, "late": 0}
        )
        proj["total"] += 1
        if is_complete:
            proj["complete"] += 1
        if is_late:
            proj["late"] += 1

    result: List[Dict] = []
    for member in members.values():
        member["projects"] = sorted(member["projects"].values(), key=lambda p: -p["total"])
        result.append(member)
    result.sort(key=lambda m: -m["total"])
    return result
