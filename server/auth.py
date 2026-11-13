"""
Real authentication: password hashing, JWT issuance, and user lookups
against the `users` table's password_hash/last_login_at columns.

Password hashing uses stdlib-only PBKDF2-HMAC-SHA256 (no bcrypt dependency
needed). Tokens are JWTs signed with JWT_SECRET (server/.env) — if unset, a
random per-process secret is generated instead, so a fixed secret is only
needed to keep sessions valid across backend restarts, never a hardcoded
default checked into code.
"""
import hashlib
import hmac
import logging
import os
import secrets
import time
from typing import Dict, Optional

import jwt
import psycopg2

import db
from i18n import TranslatableError

logger = logging.getLogger(__name__)

_PBKDF2_ITERATIONS = 260_000
JWT_ALGORITHM = "HS256"
JWT_EXPIRES_SECONDS = 7 * 24 * 3600  # 7 days
INVITE_EXPIRES_SECONDS = 7 * 24 * 3600  # 7 days

JWT_SECRET = os.getenv("JWT_SECRET", "").strip()
if not JWT_SECRET:
    JWT_SECRET = secrets.token_hex(32)
    logger.warning(
        "JWT_SECRET not set in server/.env — using a random per-process secret. "
        "Existing sessions will be invalidated on every backend restart. "
        "Set JWT_SECRET to keep sessions persistent."
    )


def hash_password(password: str) -> str:
    salt = secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), bytes.fromhex(salt), _PBKDF2_ITERATIONS)
    return f"pbkdf2_sha256${_PBKDF2_ITERATIONS}${salt}${digest.hex()}"


def hash_invite_token(token: str) -> str:
    """Plain SHA-256 of the token — the token itself (secrets.token_urlsafe)
    already has 256 bits of entropy, so no salt is needed; this just keeps
    the DB from holding a directly-usable bearer credential."""
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def verify_password(password: str, stored: str) -> bool:
    try:
        algo, iterations_str, salt, hash_hex = stored.split("$")
        if algo != "pbkdf2_sha256":
            return False
        iterations = int(iterations_str)
    except (ValueError, AttributeError):
        return False
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), bytes.fromhex(salt), iterations)
    return hmac.compare_digest(digest.hex(), hash_hex)


def create_access_token(user_id: int) -> str:
    now = int(time.time())
    payload = {"sub": str(user_id), "iat": now, "exp": now + JWT_EXPIRES_SECONDS}
    return jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGORITHM)


def decode_access_token(token: str) -> Optional[dict]:
    try:
        return jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])
    except jwt.PyJWTError:
        return None


def _row_to_user(row) -> Dict:
    user_id, name, email, role = row
    return {"id": user_id, "name": name, "email": email, "role": role}


def get_user_by_id(user_id: int) -> Optional[Dict]:
    with db.get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT id, name, email, role FROM users WHERE id = %s", (user_id,))
            row = cur.fetchone()
    return _row_to_user(row) if row else None


def register_user(name: str, email: str, password: str) -> Dict:
    name = name.strip()
    email = email.strip().lower()
    if not name or not email or not password:
        raise TranslatableError("auth.fields_required", status_code=400)

    password_hash = hash_password(password)
    with db.get_connection() as conn:
        with conn.cursor() as cur:
            try:
                cur.execute(
                    """
                    INSERT INTO users (name, email, role, password_hash)
                    VALUES (%s, %s, 'Viewer', %s)
                    RETURNING id, name, email, role
                    """,
                    (name, email, password_hash),
                )
            except psycopg2.errors.UniqueViolation:
                raise TranslatableError("auth.email_already_registered", status_code=409)
            row = cur.fetchone()
    return _row_to_user(row)


def authenticate_user(email: str, password: str) -> Optional[Dict]:
    email = email.strip().lower()
    with db.get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT id, name, email, role, password_hash FROM users WHERE email = %s",
                (email,),
            )
            row = cur.fetchone()
            if not row:
                return None
            user_id, name, user_email, role, password_hash = row
            if not password_hash or not verify_password(password, password_hash):
                return None
            cur.execute("UPDATE users SET last_login_at = now() WHERE id = %s", (user_id,))
    return {"id": user_id, "name": name, "email": user_email, "role": role}
