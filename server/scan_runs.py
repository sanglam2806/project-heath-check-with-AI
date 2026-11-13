"""
Persist a completed "Scan & Evaluate" / "Re-evaluate with AI" run to
PostgreSQL: upserts the ticket rows, inserts the scan_runs rollup row, and
inserts one evaluation_results row per ticket. Backs POST /api/scan-runs,
which both Check Health Project pipelines (real upload/scan/evaluate, and
the existing-project re-run) call after a successful evaluation when a
project is selected and "Save as new snapshot" is checked.
"""
import json
from typing import Dict, List, Optional

import db
import reeval_cache

_SNAPSHOTS_SQL = """
    SELECT completed_at, health_score, late_ticket_count, mismatch_count, scope_note
    FROM scan_runs
    WHERE project_id = %s AND is_snapshot = true AND status = 'done'
    ORDER BY completed_at DESC NULLS LAST
"""

_LATEST_RUN_SQL = """
    SELECT id, total_tickets, match_count, mismatch_count, incomplete_count,
           match_percent, avg_completion, scanned_files_count
    FROM scan_runs
    WHERE project_id = %s AND is_snapshot = true AND status = 'done'
    ORDER BY completed_at DESC NULLS LAST
    LIMIT 1
"""

_RUN_TICKETS_SQL = """
    SELECT t.ticket_key, t.summary, t.description, t.issue_type, t.due_date, t.assignee,
           er.reported_status, er.completion_percent, er.assessment, er.confidence,
           er.schedule_status, er.days_diff, er.missing_parts, er.suggestions,
           er.evidence_files, er.notes, er.from_cache
    FROM evaluation_results er
    JOIN tickets t ON t.id = er.ticket_id
    WHERE er.scan_run_id = %s
    ORDER BY t.ticket_key
"""


def _upsert_tickets(cur, project_id: int, tickets: List[Dict]) -> Dict[str, int]:
    """Insert/refresh this project's ticket rows, return {ticket_key: ticket_id}.

    assignee_key (Jira accountId, see member_performance.py) is only
    overwritten when the incoming value is non-blank -- a re-scan that
    doesn't supply one (e.g. an Excel-sourced re-run of a ticket that was
    previously Jira-sourced) must not clobber a previously-known-good key
    with NULL."""
    ticket_ids: Dict[str, int] = {}
    for t in tickets:
        cur.execute(
            """
            INSERT INTO tickets (project_id, ticket_key, summary, description, issue_type, due_date, assignee, assignee_key)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (project_id, ticket_key) DO UPDATE SET
                summary = EXCLUDED.summary,
                description = EXCLUDED.description,
                issue_type = EXCLUDED.issue_type,
                due_date = EXCLUDED.due_date,
                assignee = EXCLUDED.assignee,
                assignee_key = COALESCE(NULLIF(EXCLUDED.assignee_key, ''), tickets.assignee_key),
                updated_at = now()
            RETURNING id
            """,
            (
                project_id,
                t["ticket_id"],
                t.get("summary") or "",
                t.get("description") or "",
                t.get("issue_type") or None,
                t.get("due_date") or None,
                t.get("assignee") or None,
                t.get("assignee_key") or None,
            ),
        )
        ticket_ids[t["ticket_id"]] = cur.fetchone()[0]
    return ticket_ids


def _upsert_git_connection(
    cur,
    project_id: int,
    repo_url: Optional[str],
    branch: Optional[str],
    doc_path: Optional[str] = None,
    source_path: Optional[str] = None,
) -> None:
    """Non-secret only (repo_url/branch/doc_path/source_path) -- never a
    token. Lets Connect Git/Jira's "existing project" mode pre-fill these
    fields, tell a real Git-connected project apart from an Excel-uploaded
    one, and lets Project Detail's per-ticket re-scan re-apply the same
    doc/source subfolder scoping as the original connect instead of
    silently falling back to scanning the whole repo."""
    if not repo_url:
        return
    cur.execute(
        """
        INSERT INTO project_git_connections (project_id, repo_url, branch, doc_path, source_path)
        VALUES (%s, %s, %s, %s, %s)
        ON CONFLICT (project_id) DO UPDATE SET
            repo_url = EXCLUDED.repo_url,
            branch = EXCLUDED.branch,
            doc_path = EXCLUDED.doc_path,
            source_path = EXCLUDED.source_path,
            connected_at = now()
        """,
        (project_id, repo_url, branch or "main", doc_path or None, source_path or None),
    )


def _upsert_ticket_connection(
    cur,
    project_id: int,
    source_type: Optional[str],
    jira_site_url: Optional[str],
    jira_project_key: Optional[str],
    excel_filename: Optional[str],
    excel_mapping: Optional[Dict],
) -> None:
    """Non-secret only (site url/project key/filename/column mapping) --
    never a Jira API token. This is what Connect Git/Jira's re-run mode
    reads (project_ticket_connections.source_type) to decide whether a
    project can be re-run live (Jira) or needs a fresh Excel upload."""
    if not source_type:
        return
    cur.execute(
        """
        INSERT INTO project_ticket_connections (
            project_id, source_type, jira_site_url, jira_project_key, excel_filename, excel_mapping
        ) VALUES (%s, %s, %s, %s, %s, %s::jsonb)
        ON CONFLICT (project_id) DO UPDATE SET
            source_type = EXCLUDED.source_type,
            jira_site_url = EXCLUDED.jira_site_url,
            jira_project_key = EXCLUDED.jira_project_key,
            excel_filename = EXCLUDED.excel_filename,
            excel_mapping = EXCLUDED.excel_mapping,
            connected_at = now()
        """,
        (
            project_id,
            source_type,
            jira_site_url,
            jira_project_key,
            excel_filename,
            json.dumps(excel_mapping) if excel_mapping else None,
        ),
    )


def save_scan_run(
    project_id: int,
    run_type: str,
    scope: str,
    scope_note: Optional[str],
    upload_id: Optional[str],
    is_snapshot: bool,
    tickets: List[Dict],
    results: List[Dict],
    summary: Dict,
    health_status: str,
    checked_by: Optional[int] = None,
    repo_url: Optional[str] = None,
    branch: Optional[str] = None,
    source_type: Optional[str] = None,
    jira_site_url: Optional[str] = None,
    jira_project_key: Optional[str] = None,
    excel_filename: Optional[str] = None,
    excel_mapping: Optional[Dict] = None,
    commit_sha: Optional[str] = None,
    doc_path: Optional[str] = None,
    source_path: Optional[str] = None,
) -> Dict:
    """checked_by is the logged-in user running this check (main.py's
    current_user) — stamped onto scan_runs.triggered_by, and onto
    projects.owner_id so Project List's "Checker" column always reflects
    whoever most recently checked the project.

    commit_sha (from GitJiraScanResponse.commit_sha, Connect Git/Jira only)
    is stored on scan_runs.source_commit so a LATER re-run's reeval_cache
    can tell whether the repo has moved since this snapshot.

    doc_path/source_path (Connect Git/Jira's "restrict scan to this
    subfolder" fields) are stored on project_git_connections so Project
    Detail's per-ticket re-scan can re-apply the same scoping instead of
    silently falling back to scanning the whole repo."""
    late_ticket_count = sum(1 for r in results if r.get("schedule_status") == "Late")
    tickets_by_key = {t["ticket_id"].upper(): t for t in tickets}

    with db.get_connection() as conn:
        with conn.cursor() as cur:
            _upsert_git_connection(cur, project_id, repo_url, branch, doc_path, source_path)
            _upsert_ticket_connection(
                cur, project_id, source_type, jira_site_url, jira_project_key, excel_filename, excel_mapping
            )
            ticket_ids = _upsert_tickets(cur, project_id, tickets)

            cur.execute(
                """
                INSERT INTO scan_runs (
                    project_id, upload_id, triggered_by, run_type, scope, scope_note, status,
                    source_commit, scanned_files_count, total_tickets, match_count, mismatch_count,
                    incomplete_count, match_percent, avg_completion, health_status,
                    health_score, late_ticket_count, is_snapshot, completed_at
                ) VALUES (
                    %s, %s, %s, %s, %s, %s, 'done',
                    %s, %s, %s, %s, %s,
                    %s, %s, %s, %s,
                    %s, %s, %s, now()
                )
                RETURNING id, completed_at
                """,
                (
                    project_id,
                    upload_id,
                    checked_by,
                    run_type,
                    scope,
                    scope_note,
                    commit_sha,
                    summary.get("scanned_files", 0),
                    summary.get("total_tickets", 0),
                    summary.get("match_count", 0),
                    summary.get("mismatch_count", 0),
                    summary.get("incomplete_count", 0),
                    summary.get("match_percent", 0),
                    summary.get("avg_completion", 0),
                    health_status,
                    round(summary.get("avg_completion", 0)),
                    late_ticket_count,
                    is_snapshot,
                ),
            )
            scan_run_id, completed_at = cur.fetchone()

            for r in results:
                ticket_id = ticket_ids.get(r["ticket_id"])
                if ticket_id is None:
                    continue
                t = tickets_by_key.get(r["ticket_id"].upper(), {})
                chash = reeval_cache.content_hash({
                    "status": r.get("status") or "",
                    "summary": t.get("summary") or "",
                    "description": t.get("description") or "",
                })
                cur.execute(
                    """
                    INSERT INTO evaluation_results (
                        scan_run_id, ticket_id, reported_status, completion_percent,
                        assessment, confidence, schedule_status, days_diff,
                        missing_parts, suggestions, evidence_files, notes,
                        content_hash, from_cache
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s::jsonb, %s::jsonb, %s::jsonb, %s, %s, %s)
                    ON CONFLICT (scan_run_id, ticket_id) DO NOTHING
                    """,
                    (
                        scan_run_id,
                        ticket_id,
                        r.get("status") or "",
                        r.get("completion_percent") or 0,
                        r.get("assessment") or "Incomplete",
                        r.get("confidence") or 0,
                        r.get("schedule_status") or "",
                        r.get("days_diff"),
                        json.dumps(r.get("missing_parts") or []),
                        json.dumps(r.get("suggestions") or []),
                        json.dumps(r.get("evidence_files") or []),
                        r.get("notes") or "",
                        chash,
                        bool(r.get("from_cache")),
                    ),
                )

            if checked_by is not None:
                cur.execute(
                    "UPDATE projects SET updated_at = now(), owner_id = %s WHERE id = %s",
                    (checked_by, project_id),
                )
            else:
                cur.execute("UPDATE projects SET updated_at = now() WHERE id = %s", (project_id,))

    return {
        "scan_run_id": scan_run_id,
        "completed_at": completed_at.isoformat() if completed_at else None,
    }


def update_ticket_result_in_run(scan_run_id: int, ticket: Dict, result: Dict, rollup: Dict) -> None:
    """Best-effort persistence for a single-ticket re-evaluation (Project
    Detail's per-row re-scan button, main.py's _persist_single_ticket_result):
    updates that one evaluation_results row plus the scan_run's cached
    rollup counters in place -- does NOT insert a new scan_runs snapshot
    row, since a targeted one-ticket correction isn't a new full "Check"
    event for Trend History purposes.

    `ticket` is the TicketInfo used to compute this result (status/summary/
    description, for content_hash -- see reeval_cache.py). `result` mirrors
    models.TicketResult as a dict. `rollup` carries the freshly recomputed
    scan_runs columns: total_tickets, match_count, mismatch_count,
    incomplete_count, match_percent, avg_completion, health_status,
    health_score, late_ticket_count."""
    chash = reeval_cache.content_hash(ticket)
    with db.get_connection() as conn:
        with conn.cursor() as cur:
            # Keep the tickets table's own summary/description in sync too
            # (e.g. a Jira refresh -- see jira_client.fetch_ticket -- pulled
            # in a corrected summary/description) -- otherwise a later page
            # reload would show these fields as they were BEFORE this
            # re-evaluation, even though the fresh assessment/notes above
            # were computed against the corrected text.
            cur.execute(
                """
                UPDATE tickets SET
                    summary = %s, description = %s, issue_type = %s, due_date = %s, assignee = %s,
                    updated_at = now()
                WHERE project_id = (SELECT project_id FROM scan_runs WHERE id = %s) AND ticket_key = %s
                """,
                (
                    ticket.get("summary") or "",
                    ticket.get("description") or "",
                    ticket.get("issue_type") or None,
                    ticket.get("due_date") or None,
                    ticket.get("assignee") or None,
                    scan_run_id,
                    ticket["ticket_id"],
                ),
            )
            cur.execute(
                """
                UPDATE evaluation_results er SET
                    reported_status = %s, completion_percent = %s, assessment = %s, confidence = %s,
                    schedule_status = %s, days_diff = %s, missing_parts = %s::jsonb, suggestions = %s::jsonb,
                    evidence_files = %s::jsonb, notes = %s, content_hash = %s, from_cache = false
                FROM tickets t
                WHERE er.ticket_id = t.id AND er.scan_run_id = %s AND t.ticket_key = %s
                """,
                (
                    result.get("status") or "",
                    result.get("completion_percent") or 0,
                    result.get("assessment") or "Incomplete",
                    result.get("confidence") or 0,
                    result.get("schedule_status") or "",
                    result.get("days_diff"),
                    json.dumps(result.get("missing_parts") or []),
                    json.dumps(result.get("suggestions") or []),
                    json.dumps(result.get("evidence_files") or []),
                    result.get("notes") or "",
                    chash,
                    scan_run_id,
                    ticket["ticket_id"],
                ),
            )
            cur.execute(
                """
                UPDATE scan_runs SET
                    total_tickets = %s, match_count = %s, mismatch_count = %s, incomplete_count = %s,
                    match_percent = %s, avg_completion = %s, health_status = %s, health_score = %s,
                    late_ticket_count = %s
                WHERE id = %s
                """,
                (
                    rollup["total_tickets"],
                    rollup["match_count"],
                    rollup["mismatch_count"],
                    rollup["incomplete_count"],
                    rollup["match_percent"],
                    rollup["avg_completion"],
                    rollup["health_status"],
                    rollup["health_score"],
                    rollup["late_ticket_count"],
                    scan_run_id,
                ),
            )
            conn.commit()


def list_snapshots(project_id: int) -> List[Dict]:
    """Trend History rows for a project: every snapshot scan_runs row,
    newest first, straight off the table — no joins or recomputation."""
    with db.get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(_SNAPSHOTS_SQL, (project_id,))
            rows = cur.fetchall()
    return [
        {
            "completed_at": completed_at.isoformat() if completed_at else None,
            "health_score": health_score,
            "late_ticket_count": late_ticket_count,
            "mismatch_count": mismatch_count,
            "scope_note": scope_note,
        }
        for completed_at, health_score, late_ticket_count, mismatch_count, scope_note in rows
    ]


def get_latest_scan_detail(project_id: int) -> Optional[Dict]:
    """The most recent snapshot run's full per-ticket detail for a project —
    None if the project has never been scanned, or its latest run predates
    per-ticket persistence (e.g. the seed_db.py rollup-only demo rows), so
    the caller can fall back to synthesized detail instead of rendering an
    empty ticket table under real-looking summary numbers."""
    with db.get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(_LATEST_RUN_SQL, (project_id,))
            run = cur.fetchone()
            if not run:
                return None
            (
                scan_run_id, total_tickets, match_count, mismatch_count, incomplete_count,
                match_percent, avg_completion, scanned_files_count,
            ) = run

            cur.execute(_RUN_TICKETS_SQL, (scan_run_id,))
            rows = cur.fetchall()

    if not rows:
        return None

    tickets = []
    results = []
    for (
        ticket_key, t_summary, description, issue_type, due_date, assignee,
        reported_status, completion_percent, assessment, confidence,
        schedule_status, days_diff, missing_parts, suggestions, evidence_files, notes,
        from_cache,
    ) in rows:
        tickets.append(
            {
                "ticket_id": ticket_key,
                "summary": t_summary or "",
                "status": reported_status or "",
                "description": description or "",
                "due_date": due_date.isoformat() if due_date else "",
                "issue_type": issue_type or "",
                "assignee": assignee or "",
            }
        )
        results.append(
            {
                "ticket_id": ticket_key,
                "summary": t_summary or "",
                "status": reported_status or "",
                "completion_percent": completion_percent or 0,
                "assessment": assessment or "Incomplete",
                "confidence": confidence or 0,
                "missing_parts": missing_parts or [],
                "suggestions": suggestions or [],
                "evidence_files": evidence_files or [],
                "notes": notes or "",
                "schedule_status": schedule_status or "",
                "days_diff": days_diff,
                "assignee": assignee or "",
                "from_cache": bool(from_cache),
            }
        )

    return {
        "scan_run_id": scan_run_id,
        "tickets": tickets,
        "results": results,
        "summary": {
            "total_tickets": total_tickets if total_tickets is not None else len(results),
            "match_count": match_count or 0,
            "mismatch_count": mismatch_count or 0,
            "incomplete_count": incomplete_count or 0,
            "match_percent": match_percent or 0,
            "avg_completion": avg_completion or 0,
            "scanned_files": scanned_files_count or 0,
        },
    }
