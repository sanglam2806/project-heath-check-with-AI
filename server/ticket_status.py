"""
Shared ticket-status categorization, used consistently across the whole
evaluation pipeline (evaluator.py, git_scan.py, risk.py) AND the Project
List's "Complete Tickets" column (projects.py's _BASE_SQL) so "what counts
as Done" is defined in exactly one place conceptually instead of drifting
across files. Teams name their terminal statuses differently (Done,
Closed, Resolved, "Release", "Ready for Release", "Deployed to prod",
"Verified", "Shipped", ...), so DONE matching also checks for a handful of
substrings anywhere in the status.

projects.py's SQL query mirrors _DONE_SUBSTRINGS below BY HAND, since raw
SQL can't import this Python function -- if you change this list, update
that query's comment/WHERE clause to match, and vice versa.
"""

_DONE_STATUSES = {"done", "closed", "resolved"}
_DONE_SUBSTRINGS = ("release", "deploy", "complete", "verified", "shipped")
_CANCELLED_STATUSES = {"cancelled", "canceled"}
_IN_PROGRESS_STATUSES = {"in progress", "in_progress", "doing", "development"}


def normalize(status: str) -> str:
    return (status or "").strip().lower()


def is_done_status(status: str) -> bool:
    s = normalize(status)
    if s in _DONE_STATUSES:
        return True
    for sub in _DONE_SUBSTRINGS:
        if sub not in s:
            continue
        # The one known false-positive: "complete" is a substring of
        # "incomplete", which must NOT count as done.
        if sub == "complete" and "incomplete" in s:
            continue
        return True
    return False


def is_cancelled_status(status: str) -> bool:
    return normalize(status) in _CANCELLED_STATUSES


def is_in_progress_status(status: str) -> bool:
    return normalize(status) in _IN_PROGRESS_STATUSES
