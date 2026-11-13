"""
In-memory scan-progress tracker: lets the frontend poll
GET /api/scan-progress/{job_id} while a long-running /api/evaluate or
/api/git-jira-scan request is still in flight (these are single blocking
HTTP calls that can take minutes -- one LLM round-trip per ticket batch),
so the UI can render a real "X/Y tickets" progress bar instead of just an
indeterminate spinner.

Deliberately in-memory, no DB: a job's progress is only ever meaningful for
the lifetime of one HTTP request from one browser tab, and doesn't need to
survive a backend restart -- same rationale as main.py's _active_uploads.
Entries are swept by TTL so a client that stops polling (tab closed,
network drop) doesn't leak memory forever.
"""
import time
from threading import Lock
from typing import Dict, Optional

_LOCK = Lock()
_JOBS: Dict[str, Dict] = {}
_TTL_SECONDS = 900  # sweep jobs whose last update is older than this


def _sweep_locked() -> None:
    cutoff = time.time() - _TTL_SECONDS
    stale = [jid for jid, job in _JOBS.items() if job["updated_at"] < cutoff]
    for jid in stale:
        del _JOBS[jid]


def start(job_id: str, phase: str, total: int = 0) -> None:
    """Reset/initialize a job's progress at the start of a pipeline run.
    No-op if job_id is falsy (the frontend can omit it entirely and just
    gets no progress bar, never an error)."""
    if not job_id:
        return
    with _LOCK:
        _sweep_locked()
        _JOBS[job_id] = {
            "phase": phase,
            "current": 0,
            "total": total,
            "done": False,
            "error": None,
            "updated_at": time.time(),
        }


def update(
    job_id: str, phase: Optional[str] = None, current: Optional[int] = None, total: Optional[int] = None
) -> None:
    """Update whichever fields are given; leaves the rest as-is. Safe to
    call even if start() was never called for this job_id (creates a bare
    entry), since a caller several layers deep (e.g. deep_dive_agent) may
    not always know if the top-level pipeline already initialized it."""
    if not job_id:
        return
    with _LOCK:
        job = _JOBS.get(job_id)
        if job is None:
            job = {"phase": "", "current": 0, "total": 0, "done": False, "error": None}
            _JOBS[job_id] = job
        if phase is not None:
            job["phase"] = phase
        if current is not None:
            job["current"] = current
        if total is not None:
            job["total"] = total
        job["updated_at"] = time.time()


def finish(job_id: str, error: Optional[str] = None) -> None:
    """Mark a job done (success or failure) -- called once in a `finally`
    at the top-level endpoint, regardless of how far progress reporting
    made it through the pipeline."""
    if not job_id:
        return
    with _LOCK:
        job = _JOBS.setdefault(
            job_id, {"phase": "done", "current": 0, "total": 0, "done": False, "error": None}
        )
        job["done"] = True
        job["error"] = error
        job["updated_at"] = time.time()


def get(job_id: str) -> Optional[Dict]:
    with _LOCK:
        job = _JOBS.get(job_id)
        return dict(job) if job else None
