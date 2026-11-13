"""
Track every source/doc file actually read from Git during Scan & Evaluate
(git_scan.py), so there's visibility into what evidence the AI saw.
(filename, path) is the composite primary key: re-reading the exact same
path just updates the row, but two files with the same basename in
different folders each keep their own row. Best-effort, like
uploads_db.py -- only called when DATABASE_URL is configured, and a
failure here must never break the scan itself.

clear_all() wipes the whole table at the start of every scan (main.py) --
this table has no project_id/scan_run_id column, so it's a snapshot of the
MOST RECENT scan's evidence only, not a cross-scan history.
"""
import db


def clear_all() -> None:
    """Delete every row from git_read_files. Called once at the start of
    each Git/Jira scan (main.py) so this table only ever reflects the most
    recent scan's evidence -- an audit trail of "what did the AI just look
    at", not an ever-growing history across every scan ever run."""
    with db.get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM git_read_files")


def record_file(filename: str, path: str, file_type: str) -> None:
    with db.get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO git_read_files (filename, path, file_type, read_at)
                VALUES (%s, %s, %s, now())
                ON CONFLICT (filename, path) DO UPDATE SET
                    file_type = EXCLUDED.file_type,
                    read_at = now()
                """,
                (filename, path, file_type),
            )
