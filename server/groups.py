"""
Member Manager's "Invite group" — a real team/group of users. Inviting a
group (re-)invites whichever of its members are still pending.
"""
from typing import Dict, List, Optional

import psycopg2

import db
from i18n import TranslatableError
from members import _MEMBER_BASE_SQL, _row_to_member

_GROUP_MEMBERS_SQL = _MEMBER_BASE_SQL + " JOIN group_members gm2 ON gm2.user_id = u.id WHERE gm2.group_id = %s ORDER BY u.name"


def list_groups() -> List[Dict]:
    with db.get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT id, name FROM groups ORDER BY name")
            groups = cur.fetchall()
            result = []
            for group_id, name in groups:
                cur.execute(_GROUP_MEMBERS_SQL, (group_id,))
                members = [_row_to_member(r) for r in cur.fetchall()]
                result.append({"id": group_id, "name": name, "members": members})
    return result


def create_group(name: str, created_by: Optional[int]) -> Dict:
    name = name.strip()
    if not name:
        raise TranslatableError("groups.name_required", status_code=400)
    with db.get_connection() as conn:
        with conn.cursor() as cur:
            try:
                cur.execute(
                    "INSERT INTO groups (name, created_by) VALUES (%s, %s) RETURNING id, name",
                    (name, created_by),
                )
            except psycopg2.errors.UniqueViolation:
                raise TranslatableError("groups.name_exists", status_code=409, name=name)
            row = cur.fetchone()
    return {"id": row[0], "name": row[1]}


def add_member(group_id: int, user_id: int) -> None:
    with db.get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO group_members (group_id, user_id) VALUES (%s, %s) ON CONFLICT DO NOTHING",
                (group_id, user_id),
            )


def get_group(group_id: int) -> Optional[Dict]:
    with db.get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT id, name FROM groups WHERE id = %s", (group_id,))
            row = cur.fetchone()
            if not row:
                return None
            cur.execute(_GROUP_MEMBERS_SQL, (group_id,))
            members = [_row_to_member(r) for r in cur.fetchall()]
    return {"id": row[0], "name": row[1], "members": members}
