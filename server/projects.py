"""
Projects module: reads project rows — joined to their latest snapshot
scan_run and their Git/ticket connections — from PostgreSQL. Backs
GET /api/projects and GET /api/projects/{id}, which replace the
frontend's former MOCK_PROJECTS for Dashboard / Project List / Check
Health Project's existing-project picker.
"""
from typing import Dict, List, Optional

import db
from i18n import TranslatableError

_BASE_SQL = """
    SELECT
        p.id, p.name, p.owner_id, p.current_sprint, u.name AS owner,
        gc.repo_url, gc.branch, gc.last_commit, gc.last_commit_at, gc.doc_path, gc.source_path,
        tc.source_type, tc.jira_site_url, tc.jira_project_key,
        tc.excel_filename, tc.excel_mapping,
        sr.completed_at AS last_checked_at, sr.health_status,
        sr.total_tickets, sr.match_percent, sr.avg_completion,
        sr.match_count, sr.mismatch_count, sr.late_ticket_count, sr.health_score,
        (
            SELECT COUNT(*) FROM evaluation_results er
            WHERE er.scan_run_id = sr.id
            -- A ticket only counts as genuinely "complete" when BOTH hold:
            -- (1) its reported status means done, AND (2) the code was NOT
            -- found to contradict that (assessment <> 'Mismatch') -- a
            -- ticket reported Done whose code is missing/wrong is not
            -- actually complete, it's a Mismatch that happens to claim it
            -- is. "Incomplete" still counts here (status says done, and the
            -- code isn't flatly contradicted, just weakly evidenced) --
            -- only Mismatch is excluded, per the exact ask.
            AND er.assessment <> 'Mismatch'
            AND (
                -- Mirrors ticket_status.is_done_status() in ticket_status.py
                -- BY HAND -- raw SQL can't import that Python function, so
                -- keep this WHERE clause in sync with _DONE_SUBSTRINGS there.
                -- Exact canonical statuses, plus a substring match against
                -- other common done-equivalent workflow labels (e.g. a
                -- custom "Release it" or "Deployed to prod" column) since
                -- teams name their final status differently. A "release"
                -- or "deploy" substring match can over-count a not-yet-
                -- released "Ready for Release" ticket as complete -- an
                -- accepted trade-off for supporting custom workflow names
                -- without a per-project status-mapping UI. (%% below is a
                -- literal SQL LIKE wildcard, escaped for psycopg2.)
                lower(er.reported_status) IN ('done', 'closed', 'resolved')
                OR lower(er.reported_status) LIKE '%%release%%'
                OR lower(er.reported_status) LIKE '%%deploy%%'
                OR lower(er.reported_status) LIKE '%%verified%%'
                OR lower(er.reported_status) LIKE '%%shipped%%'
                -- "complete" substring, but not when it's really "incomplete".
                OR (
                    lower(er.reported_status) LIKE '%%complete%%'
                    AND lower(er.reported_status) NOT LIKE '%%incomplete%%'
                )
            )
        ) AS complete_count
    FROM projects p
    LEFT JOIN users u ON u.id = p.owner_id
    LEFT JOIN project_git_connections gc ON gc.project_id = p.id
    LEFT JOIN project_ticket_connections tc ON tc.project_id = p.id
    LEFT JOIN LATERAL (
        SELECT *
        FROM scan_runs sr2
        WHERE sr2.project_id = p.id AND sr2.is_snapshot = true AND sr2.status = 'done'
        ORDER BY sr2.completed_at DESC NULLS LAST
        LIMIT 1
    ) sr ON true
"""


def _row_to_project(row: tuple) -> Dict:
    (
        pid, name, owner_id, current_sprint, owner,
        repo_url, branch, last_commit, last_commit_at, doc_path, source_path,
        source_type, jira_site_url, jira_project_key,
        excel_filename, excel_mapping,
        last_checked_at, health_status, total_tickets, match_percent, avg_completion,
        match_count, mismatch_count, late_ticket_count, health_score, complete_count,
    ) = row

    git = None
    if repo_url:
        git = {
            "repo_url": repo_url,
            "branch": branch,
            "last_commit": last_commit,
            "last_commit_at": last_commit_at.isoformat() if last_commit_at else None,
            "doc_path": doc_path,
            "source_path": source_path,
        }

    ticket_source = None
    if source_type:
        ticket_source = {
            "type": source_type,
            "jira_site_url": jira_site_url,
            "jira_project_key": jira_project_key,
            "excel_filename": excel_filename,
            "excel_mapping": excel_mapping,
        }

    return {
        "id": pid,
        "name": name,
        # Raw FK alongside the resolved display name, so callers (e.g.
        # main.py's visibility check) can compare against current_user["id"]
        # without a second query.
        "owner_id": owner_id,
        "owner": owner,
        "current_sprint": current_sprint,
        "last_checked_at": last_checked_at.isoformat() if last_checked_at else None,
        "health_status": health_status,
        "health_score": health_score,
        "ticket_count": total_tickets,
        "match_percent": match_percent,
        "avg_completion": avg_completion,
        "match_count": match_count,
        "mismatch_count": mismatch_count,
        "late_count": late_ticket_count,
        "complete_count": complete_count,
        "git": git,
        "ticket_source": ticket_source,
    }


def list_projects(user_id: Optional[int] = None) -> List[Dict]:
    """user_id restricts results to projects visible to that user — either
    ones they personally checked (owner_id) or ones an Owner/Admin
    explicitly shared with them (project_members) — used for Editor/Viewer
    accounts (Owner/Admin see everything, so call this with user_id=None)."""
    sql = _BASE_SQL
    params: tuple = ()
    if user_id is not None:
        sql += """
            WHERE p.owner_id = %s
               OR p.id IN (SELECT project_id FROM project_members WHERE user_id = %s)
        """
        params = (user_id, user_id)
    sql += " ORDER BY p.name"
    with db.get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(sql, params)
            rows = cur.fetchall()
    return [_row_to_project(r) for r in rows]


def get_project(project_id: int) -> Optional[Dict]:
    with db.get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(_BASE_SQL + " WHERE p.id = %s", (project_id,))
            row = cur.fetchone()
    return _row_to_project(row) if row else None


def user_has_project_access(project_id: int, user_id: int) -> bool:
    """True if `user_id` has an explicit project_members grant for
    `project_id` -- called from main.py's _check_project_visibility as the
    fallback check when the user isn't the project's owner_id."""
    with db.get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT 1 FROM project_members WHERE project_id = %s AND user_id = %s",
                (project_id, user_id),
            )
            return cur.fetchone() is not None


def list_project_members(project_id: int) -> List[Dict]:
    """Users explicitly granted visibility into this project (not
    including whoever happens to be its current owner_id -- that's a
    separate, automatic "last checked by" slot, shown elsewhere)."""
    with db.get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT u.id, u.name, u.email, u.role
                FROM project_members pm
                JOIN users u ON u.id = pm.user_id
                WHERE pm.project_id = %s
                ORDER BY u.name
                """,
                (project_id,),
            )
            rows = cur.fetchall()
    return [{"id": r[0], "name": r[1], "email": r[2], "role": r[3]} for r in rows]


def add_project_member(project_id: int, user_id: int, added_by: Optional[int]) -> None:
    with db.get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO project_members (project_id, user_id, added_by)
                VALUES (%s, %s, %s)
                ON CONFLICT (project_id, user_id) DO NOTHING
                """,
                (project_id, user_id, added_by),
            )


def remove_project_member(project_id: int, user_id: int) -> None:
    with db.get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "DELETE FROM project_members WHERE project_id = %s AND user_id = %s",
                (project_id, user_id),
            )


def find_or_create_project(name: str) -> Dict:
    """Look up a project by exact (case-insensitive) name, or create it —
    backs Check Health Project's "New project" real-scan flow, which derives
    the name from the connected Git repo or the uploaded ZIP's filename and
    has no separate "create project" UI step of its own."""
    name = name.strip()
    if not name:
        raise TranslatableError("projects.name_required", status_code=400)
    with db.get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT id, name FROM projects WHERE lower(name) = lower(%s)", (name,))
            row = cur.fetchone()
            if row:
                return {"id": row[0], "name": row[1], "created": False}
            cur.execute("INSERT INTO projects (name) VALUES (%s) RETURNING id, name", (name,))
            row = cur.fetchone()
            return {"id": row[0], "name": row[1], "created": True}
