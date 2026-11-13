"""
Runtime-configurable LLM connection settings: API key / base URL / model
name for both the Phase 1 model (Triage evaluation + Solution Management's
synthesis) and the Phase 2 "deep" model (Deep judgment evaluation +
Layer 4's agent), editable from the app's Model Configuration page instead
of only via server/.env + a restart.

A saved DB value wins per-field; any field left unset falls back to the
matching server/.env variable, so an existing .env-only setup keeps
working with zero migration -- the model_config row is entirely optional.
get_llm_settings() is called fresh (a single indexed row lookup, no
caching) at the start of every evaluate/solutions/deep-dive run, so a
saved change takes effect on the very next run, no backend restart needed.
"""
import os
import time
from typing import Dict, Optional

from dotenv import load_dotenv
from openai import OpenAI

import db

load_dotenv()

_FIELDS = ("api_key", "base_url", "model", "api_key_deep", "base_url_deep", "model_deep")

_ENV_DEFAULTS: Dict[str, str] = {}
_ENV_DEFAULTS["api_key"] = os.getenv("OPENAI_API_KEY", "ollama")
_ENV_DEFAULTS["base_url"] = os.getenv("OPENAI_BASE_URL", "http://localhost:11434/v1")
_ENV_DEFAULTS["model"] = os.getenv("OPENAI_MODEL", "llama3.1:latest")
# Phase 2 falls back to the Phase 1 value when unset, same convention the
# .env-only setup already used (some gateways grant model access per key,
# so Phase 2 usually needs its own, but a single-model setup only needs to
# configure the Phase 1 fields).
_ENV_DEFAULTS["api_key_deep"] = os.getenv("OPENAI_API_KEY_DEEP", _ENV_DEFAULTS["api_key"])
_ENV_DEFAULTS["base_url_deep"] = os.getenv("OPENAI_BASE_URL_DEEP", _ENV_DEFAULTS["base_url"])
_ENV_DEFAULTS["model_deep"] = os.getenv("OPENAI_MODEL_DEEP", _ENV_DEFAULTS["model"])


def mask_secret(value: Optional[str]) -> str:
    """Never send a saved API key back in full -- just enough to recognize
    it (e.g. confirm "yes that's the FPT.AI key") without re-exposing the
    whole secret to every admin who opens the Model Configuration page."""
    if not value:
        return ""
    if len(value) <= 8:
        return "*" * len(value)
    return f"{value[:3]}...{value[-4:]}"


def get_db_row() -> Optional[Dict]:
    """Raw model_config row (None if never saved via the UI, or no DB
    configured at all)."""
    if not db.is_configured():
        return None
    with db.get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT api_key, base_url, model, api_key_deep, base_url_deep, model_deep,
                       updated_at, updated_by
                FROM model_config WHERE id = 1
                """
            )
            row = cur.fetchone()
    if not row:
        return None
    keys = ["api_key", "base_url", "model", "api_key_deep", "base_url_deep", "model_deep", "updated_at", "updated_by"]
    return dict(zip(keys, row))


def get_llm_settings() -> Dict[str, str]:
    """Resolved settings: a non-empty DB value wins per-field, else the
    .env default. Always returns all 6 fields populated (never empty),
    since _ENV_DEFAULTS guarantees a fallback for every one."""
    db_row = get_db_row() or {}
    resolved = dict(_ENV_DEFAULTS)
    for key in _FIELDS:
        value = db_row.get(key)
        if value and value.strip():
            resolved[key] = value.strip()
    return resolved


def save_config(
    updated_by: Optional[int],
    base_url: Optional[str] = None,
    model: Optional[str] = None,
    base_url_deep: Optional[str] = None,
    model_deep: Optional[str] = None,
    api_key: Optional[str] = None,
    clear_api_key: bool = False,
    api_key_deep: Optional[str] = None,
    clear_api_key_deep: bool = False,
) -> None:
    """Upsert the singleton config row.

    base_url/model/base_url_deep/model_deep: whatever is passed is stored
    as-is (empty string -> NULL -> falls back to .env), matching a plain
    "save this form" UX since these aren't secret and the UI always shows
    their current resolved value pre-filled.

    api_key/api_key_deep: None means "leave the existing saved value
    untouched" (the UI never pre-fills a real secret into the field, so
    "user typed nothing" must not be read as "clear it"); a non-empty
    string overwrites it; clear_api_key/clear_api_key_deep explicitly
    resets that one field back to NULL (its .env default) and takes
    precedence over a same-request api_key value.
    """
    existing = get_db_row() or {}

    def _plain(new_value: Optional[str], current: Optional[str]) -> Optional[str]:
        if new_value is None:
            return current
        stripped = new_value.strip()
        return stripped or None

    def _secret(new_value: Optional[str], clear: bool, current: Optional[str]) -> Optional[str]:
        if clear:
            return None
        if new_value is None or not new_value.strip():
            return current
        return new_value.strip()

    values = {
        "base_url": _plain(base_url, existing.get("base_url")),
        "model": _plain(model, existing.get("model")),
        "base_url_deep": _plain(base_url_deep, existing.get("base_url_deep")),
        "model_deep": _plain(model_deep, existing.get("model_deep")),
        "api_key": _secret(api_key, clear_api_key, existing.get("api_key")),
        "api_key_deep": _secret(api_key_deep, clear_api_key_deep, existing.get("api_key_deep")),
    }

    with db.get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO model_config (
                    id, api_key, base_url, model, api_key_deep, base_url_deep, model_deep, updated_by, updated_at
                ) VALUES (1, %s, %s, %s, %s, %s, %s, %s, now())
                ON CONFLICT (id) DO UPDATE SET
                    api_key = EXCLUDED.api_key,
                    base_url = EXCLUDED.base_url,
                    model = EXCLUDED.model,
                    api_key_deep = EXCLUDED.api_key_deep,
                    base_url_deep = EXCLUDED.base_url_deep,
                    model_deep = EXCLUDED.model_deep,
                    updated_by = EXCLUDED.updated_by,
                    updated_at = now()
                """,
                (
                    values["api_key"], values["base_url"], values["model"],
                    values["api_key_deep"], values["base_url_deep"], values["model_deep"],
                    updated_by,
                ),
            )


_TEST_TIMEOUT_SECONDS = 15


def test_connection(api_key: str, base_url: str, model: str) -> Dict:
    """Send one minimal chat completion to verify a candidate api_key/
    base_url/model combo actually works together -- used by the Model
    Configuration page's "Test Connection" button, BEFORE the admin saves
    anything. Never raises; always returns {success, message, latency_ms}
    so the caller can show a clear pass/fail instead of a 500."""
    client = OpenAI(api_key=api_key or "ollama", base_url=base_url, timeout=_TEST_TIMEOUT_SECONDS)
    start = time.monotonic()
    try:
        response = client.chat.completions.create(
            model=model,
            messages=[{"role": "user", "content": "Reply with exactly one word: OK"}],
            max_tokens=5,
            temperature=0,
        )
        latency_ms = int((time.monotonic() - start) * 1000)
        content = (response.choices[0].message.content or "").strip()
        return {
            "success": True,
            "message": f"Connected successfully in {latency_ms}ms — model replied: {content[:80]!r}",
            "latency_ms": latency_ms,
        }
    except Exception as exc:
        latency_ms = int((time.monotonic() - start) * 1000)
        return {
            "success": False,
            "message": str(exc)[:300],
            "latency_ms": latency_ms,
        }
