"""
Seed the database with example projects (mirroring the frontend's former
MOCK_PROJECTS), so switching Dashboard / Project List over to the real
GET /api/projects doesn't just show an empty list. Idempotent — skips any
project whose name already exists.

Usage:
    cd server
    python seed_db.py
"""
import json
import sys
from datetime import datetime, timedelta, timezone

import db

_EXCEL_MAPPING = {"ticket_id": 0, "summary": 1, "status": 2, "description": 3, "due_date": 4, "issue_type": None}

SEED_PROJECTS = [
    {
        "name": "Coworklocal Platform",
        "owner": "Nguyen Van A",
        "current_sprint": "Sprint 24",
        "health_status": "Late",
        "ticket_count": 42,
        "match_percent": 61.9,
        "avg_completion": 68.4,
        "checked_days_ago": 5,
        "git": {"repo_url": "github.com/org/cowork-local.git", "branch": "main", "last_commit": "a3f91c", "commit_hours_ago": 2},
        "ticket_source": {"type": "jira", "jira_site_url": "cowork.atlassian.net", "jira_project_key": "PROJ"},
    },
    {
        "name": "FNS Toki Mobile App",
        "owner": "Tran Thi B",
        "current_sprint": "Sprint 11",
        "health_status": "Risk",
        "ticket_count": 27,
        "match_percent": 74.1,
        "avg_completion": 79.0,
        "checked_days_ago": 3,
        "git": {"repo_url": "github.com/org/fns-toki-mobile.git", "branch": "develop", "last_commit": "c17be2", "commit_hours_ago": 6},
        "ticket_source": {"type": "excel", "excel_filename": "fns_toki_jira_export.xlsx", "excel_mapping": _EXCEL_MAPPING},
    },
    {
        "name": "Internal HR Portal",
        "owner": "Le Van C",
        "current_sprint": "Sprint 6",
        "health_status": "OK",
        "ticket_count": 15,
        "match_percent": 93.3,
        "avg_completion": 95.2,
        "checked_days_ago": 7,
        "git": {"repo_url": "github.com/org/internal-hr-portal.git", "branch": "main", "last_commit": "f00d21", "commit_hours_ago": 24},
        "ticket_source": {"type": "jira", "jira_site_url": "internal.atlassian.net", "jira_project_key": "HRP"},
    },
    {
        "name": "Payment Gateway Revamp",
        "owner": "Pham Thi D",
        "current_sprint": "Sprint 9",
        "health_status": "Late",
        "ticket_count": 33,
        "match_percent": 51.5,
        "avg_completion": 58.7,
        "checked_days_ago": 10,
        "git": {"repo_url": "github.com/org/payment-gateway.git", "branch": "main", "last_commit": "9b2e77", "commit_hours_ago": 72},
        "ticket_source": {"type": "excel", "excel_filename": "payment_gateway_tickets.xlsx", "excel_mapping": _EXCEL_MAPPING},
    },
    {
        "name": "Customer Support Bot",
        "owner": "Hoang Van E",
        "current_sprint": "Sprint 14",
        "health_status": "OK",
        "ticket_count": 19,
        "match_percent": 89.5,
        "avg_completion": 91.0,
        "checked_days_ago": 2,
        "git": {"repo_url": "github.com/org/support-bot.git", "branch": "main", "last_commit": "55d0aa", "commit_hours_ago": 0.33},
        "ticket_source": {"type": "jira", "jira_site_url": "cowork.atlassian.net", "jira_project_key": "SUP"},
    },
    {
        "name": "Data Warehouse Migration",
        "owner": "Do Thi F",
        "current_sprint": "Sprint 3",
        "health_status": "Risk",
        "ticket_count": 24,
        "match_percent": 70.8,
        "avg_completion": 73.5,
        "checked_days_ago": 14,
        "git": {"repo_url": "github.com/org/data-warehouse.git", "branch": "main", "last_commit": "2ac410", "commit_hours_ago": 120},
        "ticket_source": {"type": "excel", "excel_filename": "dwh_migration_backlog.xlsx", "excel_mapping": _EXCEL_MAPPING},
    },
]


def _slugify_email(name: str) -> str:
    return name.lower().replace(" ", ".") + "@example.com"


def _get_or_create_user(cur, name: str) -> int:
    cur.execute("SELECT id FROM users WHERE name = %s", (name,))
    row = cur.fetchone()
    if row:
        return row[0]
    cur.execute(
        "INSERT INTO users (name, email, role) VALUES (%s, %s, 'Owner') RETURNING id",
        (name, _slugify_email(name)),
    )
    return cur.fetchone()[0]


def seed() -> None:
    now = datetime.now(timezone.utc)

    with db.get_connection() as conn:
        with conn.cursor() as cur:
            for p in SEED_PROJECTS:
                cur.execute("SELECT id FROM projects WHERE name = %s", (p["name"],))
                if cur.fetchone():
                    print(f"  skip (exists): {p['name']}")
                    continue

                owner_id = _get_or_create_user(cur, p["owner"])

                cur.execute(
                    """INSERT INTO projects (name, owner_id, current_sprint)
                       VALUES (%s, %s, %s) RETURNING id""",
                    (p["name"], owner_id, p["current_sprint"]),
                )
                project_id = cur.fetchone()[0]

                git = p["git"]
                last_commit_at = now - timedelta(hours=git["commit_hours_ago"])
                cur.execute(
                    """INSERT INTO project_git_connections
                       (project_id, repo_url, branch, last_commit, last_commit_at)
                       VALUES (%s, %s, %s, %s, %s)""",
                    (project_id, git["repo_url"], git["branch"], git["last_commit"], last_commit_at),
                )

                ts = p["ticket_source"]
                cur.execute(
                    """INSERT INTO project_ticket_connections
                       (project_id, source_type, jira_site_url, jira_project_key, excel_filename, excel_mapping)
                       VALUES (%s, %s, %s, %s, %s, %s::jsonb)""",
                    (
                        project_id, ts["type"], ts.get("jira_site_url"), ts.get("jira_project_key"),
                        ts.get("excel_filename"),
                        json.dumps(ts["excel_mapping"]) if ts.get("excel_mapping") else None,
                    ),
                )

                match_count = round(p["ticket_count"] * p["match_percent"] / 100)
                remaining = p["ticket_count"] - match_count
                mismatch_count = remaining // 2
                incomplete_count = remaining - mismatch_count
                completed_at = now - timedelta(days=p["checked_days_ago"])
                cur.execute(
                    """INSERT INTO scan_runs
                       (project_id, run_type, scope, status, scanned_files_count,
                        total_tickets, match_count, mismatch_count, incomplete_count,
                        match_percent, avg_completion, health_status, health_score,
                        late_ticket_count, overall_risk_score, is_snapshot, started_at, completed_at)
                       VALUES (%s, 'new_check', 'all', 'done', %s,
                               %s, %s, %s, %s,
                               %s, %s, %s, %s,
                               %s, %s, true, %s, %s)""",
                    (
                        project_id, p["ticket_count"] * 3,
                        p["ticket_count"], match_count, mismatch_count, incomplete_count,
                        p["match_percent"], p["avg_completion"], p["health_status"], round(p["avg_completion"]),
                        mismatch_count, round(100 - p["avg_completion"], 1),
                        completed_at, completed_at,
                    ),
                )
                print(f"  created: {p['name']}")


def main() -> int:
    if not db.is_configured():
        print("DATABASE_URL is not set. Add it to server/.env first.")
        return 1
    if not db.check_connection():
        print("Could not connect to the database.")
        return 1
    print("Seeding...")
    seed()
    print("Done.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
