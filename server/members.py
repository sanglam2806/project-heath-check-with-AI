"""
Member Manager: real member listing/role updates, plus the invite lifecycle
(create/reuse a pending user + token, preview a token, accept it). Mirrors
the plain-tuple sync-DB-module style of projects.py/scan_runs.py.
"""
import secrets
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional, Tuple

import auth
import db

_MEMBER_BASE_SQL = """
    SELECT u.id, u.name, u.email, u.role,
           CASE WHEN u.password_hash IS NOT NULL THEN 'active' ELSE 'pending' END AS status,
           COALESCE(
             (SELECT array_agg(g.name ORDER BY g.name)
              FROM group_members gm JOIN groups g ON g.id = gm.group_id
              WHERE gm.user_id = u.id),
             '{}'
           ) AS groups
    FROM users u
"""


def _row_to_member(row) -> Dict:
    user_id, name, email, role, status, groups = row
    return {
        "id": user_id,
        "name": name,
        "email": email,
        "role": role,
        "status": status,
        "groups": list(groups or []),
    }


def _get_member_by_id(cur, user_id: int) -> Dict:
    cur.execute(_MEMBER_BASE_SQL + " WHERE u.id = %s", (user_id,))
    return _row_to_member(cur.fetchone())


def list_members() -> List[Dict]:
    """Real accounts (active) + outstanding invites (pending) — excludes the
    seed-only "owner" placeholder rows, which have neither a password nor an
    invite token."""
    with db.get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                _MEMBER_BASE_SQL
                + " WHERE u.invite_token_hash IS NOT NULL OR u.password_hash IS NOT NULL"
                + " ORDER BY u.name"
            )
            rows = cur.fetchall()
    return [_row_to_member(r) for r in rows]


def update_member_role(user_id: int, role: str) -> Dict:
    with db.get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("UPDATE users SET role = %s WHERE id = %s", (role, user_id))
            return _get_member_by_id(cur, user_id)


def create_or_reuse_invite(
    name: str, email: str, role: str, invited_by: Optional[int]
) -> Tuple[Dict, Optional[str]]:
    """Returns (member, token). token is None if the email already belongs
    to an active account — nothing to invite in that case."""
    email = email.strip().lower()
    name = name.strip() or email
    token = secrets.token_urlsafe(32)
    token_hash = auth.hash_invite_token(token)
    expires_at = datetime.now(timezone.utc) + timedelta(seconds=auth.INVITE_EXPIRES_SECONDS)

    with db.get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT id, password_hash FROM users WHERE email = %s", (email,))
            row = cur.fetchone()

            if row and row[1] is not None:
                return _get_member_by_id(cur, row[0]), None

            if row:
                user_id = row[0]
                cur.execute(
                    """
                    UPDATE users
                    SET name = %s, role = %s, invite_token_hash = %s,
                        invite_token_expires_at = %s, invited_by = %s
                    WHERE id = %s
                    """,
                    (name, role, token_hash, expires_at, invited_by, user_id),
                )
            else:
                cur.execute(
                    """
                    INSERT INTO users (name, email, role, invite_token_hash, invite_token_expires_at, invited_by)
                    VALUES (%s, %s, %s, %s, %s, %s)
                    RETURNING id
                    """,
                    (name, email, role, token_hash, expires_at, invited_by),
                )
                user_id = cur.fetchone()[0]

            member = _get_member_by_id(cur, user_id)

    return member, token


def get_invite_preview(token: str) -> Optional[Dict]:
    token_hash = auth.hash_invite_token(token)
    with db.get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT u.name, u.email, u.role, u.invite_token_expires_at, u.password_hash,
                       (SELECT g.name FROM group_members gm JOIN groups g ON g.id = gm.group_id
                        WHERE gm.user_id = u.id ORDER BY gm.added_at LIMIT 1)
                FROM users u
                WHERE u.invite_token_hash = %s
                """,
                (token_hash,),
            )
            row = cur.fetchone()

    if not row:
        return None
    name, email, role, expires_at, password_hash, group_name = row
    if password_hash is not None:
        return None  # already activated
    if expires_at and expires_at < datetime.now(timezone.utc):
        return None  # expired

    return {"name": name, "email": email, "role": role, "group_name": group_name}


def accept_invite(token: str, name: str, password: str) -> Optional[Dict]:
    token_hash = auth.hash_invite_token(token)
    password_hash = auth.hash_password(password)

    with db.get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT id, password_hash, invite_token_expires_at FROM users WHERE invite_token_hash = %s",
                (token_hash,),
            )
            row = cur.fetchone()
            if not row:
                return None
            user_id, existing_hash, expires_at = row
            if existing_hash is not None:
                return None  # already activated
            if expires_at and expires_at < datetime.now(timezone.utc):
                return None  # expired

            cur.execute(
                """
                UPDATE users
                SET name = COALESCE(NULLIF(%s, ''), name),
                    password_hash = %s,
                    invite_token_hash = NULL,
                    invite_token_expires_at = NULL
                WHERE id = %s
                RETURNING id, name, email, role
                """,
                (name.strip(), password_hash, user_id),
            )
            urow = cur.fetchone()

    if not urow:
        return None
    uid, uname, uemail, urole = urow
    return {"id": uid, "name": uname, "email": uemail, "role": urole}
