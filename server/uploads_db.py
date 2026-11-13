"""
Track ZIP uploads (server/main.py's upload_id / extracted_path) in
PostgreSQL, so scan_runs.upload_id has a real row to reference — mirrors
main.py's in-memory _active_uploads map. Best-effort: only called when
DATABASE_URL is configured, and a failure here must never break the upload
itself (the in-memory map is what actually drives scan/evaluate).
"""
import db


def record_upload(upload_id: str, filename: str, size_bytes: int, extracted_path: str) -> None:
    with db.get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO uploads (id, filename, size_bytes, extracted_path)
                VALUES (%s, %s, %s, %s)
                ON CONFLICT (id) DO NOTHING
                """,
                (upload_id, filename, size_bytes, extracted_path),
            )
