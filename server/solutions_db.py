"""
Cache for Solution Management's project-wide AI synthesis
(solutions.build_project_solutions), keyed by scan_run_id -- a scan_run_id
never changes once a scan is saved, so caching by it means a project's
solutions are only ever synthesized (one LLM call) once per scan, no
matter how many times a PM reopens the Solutions page for it. A new scan
produces a new scan_run_id, so the cache "invalidates" itself naturally
(cache miss on the new id) with no TTL or manual eviction needed.
"""
import json
from typing import Dict, List, Optional

import db


def get_cached(scan_run_id: int) -> Optional[Dict]:
    """Return the previously-synthesized {items, generated_by, message} for
    this scan_run_id, or None if it hasn't been synthesized yet."""
    with db.get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT items, generated_by, message FROM project_solutions WHERE scan_run_id = %s",
                (scan_run_id,),
            )
            row = cur.fetchone()
    if not row:
        return None
    items, generated_by, message = row
    return {"items": items, "generated_by": generated_by, "message": message}


def save_cache(scan_run_id: int, items: List[Dict], generated_by: str, message: str) -> None:
    with db.get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO project_solutions (scan_run_id, items, generated_by, message)
                VALUES (%s, %s::jsonb, %s, %s)
                ON CONFLICT (scan_run_id) DO UPDATE SET
                    items = EXCLUDED.items,
                    generated_by = EXCLUDED.generated_by,
                    message = EXCLUDED.message,
                    created_at = now()
                """,
                (scan_run_id, json.dumps(items), generated_by, message),
            )
