"""
Real Jira REST API access: connection check (count tickets) and fetching
the real ticket list for the Connect Git/Jira page's Scan & Evaluate.
stdlib-only (urllib), no new dependency.

Uses REST API v2, not v3: v3 (with its ADF-formatted description field) is
Jira Cloud-only. v2 works on both Jira Cloud and self-hosted Jira Server/
Data Center, returning `description` as a plain string on both — so
_adf_to_text's plain-string branch covers the common case and its dict-
walking branch is just a safety net for any deployment that still hands
back ADF. Basic Auth here also covers both deployment types transparently:
Jira Cloud expects `email:API-token`, Jira Server/Data Center expects
`username:password` (or a Personal Access Token as the password) — either
way it's just `base64(user:pass)`, so the caller decides what the two
fields actually mean.
"""
import base64
import json
import urllib.error
import urllib.parse
import urllib.request

from i18n import TranslatableError


class JiraConnectionError(TranslatableError):
    """Translated message for any connect failure (bad URL, bad auth, bad
    project key, network error, timeout)."""

    def __init__(self, key: str, **kwargs):
        super().__init__(key, status_code=400, **kwargs)


def _normalize_site_url(site_url: str) -> str:
    base = (site_url or "").strip().rstrip("/")
    if not base:
        raise JiraConnectionError("jira.site_url_required")
    if not base.startswith("http://") and not base.startswith("https://"):
        base = "https://" + base
    return base


def _jira_get(url: str, email: str, api_token: str) -> dict:
    """Shared Basic-Auth GET + error mapping used by both the connection-test
    (ticket count) and the real ticket-list fetch."""
    if not email or not api_token:
        raise JiraConnectionError("jira.email_token_required")
    credentials = base64.b64encode(f"{email}:{api_token}".encode("utf-8")).decode("ascii")
    req = urllib.request.Request(
        url,
        headers={"Authorization": f"Basic {credentials}", "Accept": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            return json.loads(resp.read())
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="ignore")
        if exc.code == 401:
            raise JiraConnectionError("jira.wrong_credentials")
        messages = []
        try:
            messages = json.loads(body).get("errorMessages") or []
        except json.JSONDecodeError:
            pass
        if messages:
            # Passed through verbatim (Jira's own error text, not ours to translate).
            raise JiraConnectionError("; ".join(messages))
        if exc.code in (400, 404):
            raise JiraConnectionError("jira.project_or_url_invalid")
        raise JiraConnectionError("jira.host_error", code=exc.code)
    except urllib.error.URLError as exc:
        raise JiraConnectionError("jira.connect_failed", reason=exc.reason)
    except TimeoutError:
        raise JiraConnectionError("jira.timeout")
    except json.JSONDecodeError:
        raise JiraConnectionError("jira.invalid_json")


def test_connection_and_count(site_url: str, project_key: str, email: str, api_token: str) -> int:
    base = _normalize_site_url(site_url)
    project_key = (project_key or "").strip()
    if not project_key:
        raise JiraConnectionError("jira.project_key_required")

    query = urllib.parse.urlencode({"jql": f'project="{project_key}"', "maxResults": 0})
    data = _jira_get(f"{base}/rest/api/2/search?{query}", email, api_token)

    total = data.get("total")
    if total is None:
        raise JiraConnectionError("jira.missing_total")
    return int(total)


def _adf_to_text(node) -> str:
    """Flatten Jira Cloud's Atlassian Document Format description into
    plain text by concatenating every 'text' leaf node."""
    if not node:
        return ""
    if isinstance(node, str):
        return node
    parts = []

    def walk(n):
        if isinstance(n, dict):
            if n.get("type") == "text":
                parts.append(n.get("text", ""))
            for child in n.get("content") or []:
                walk(child)
        elif isinstance(n, list):
            for child in n:
                walk(child)

    walk(node)
    return " ".join(p for p in parts if p)


def fetch_tickets(site_url: str, project_key: str, email: str, api_token: str, max_results: int = 200) -> list:
    """Fetch the real ticket list for a Jira project, shaped like TicketInfo
    dicts (ticket_id, summary, status, description, due_date, issue_type,
    assignee) for use by the scan/evaluate pipeline."""
    base = _normalize_site_url(site_url)
    project_key = (project_key or "").strip()
    if not project_key:
        raise JiraConnectionError("jira.project_key_required")

    tickets = []
    start_at = 0
    page_size = 100
    while len(tickets) < max_results:
        query = urllib.parse.urlencode({
            "jql": f'project="{project_key}"',
            "fields": "summary,description,status,assignee,duedate,issuetype",
            "startAt": start_at,
            "maxResults": page_size,
        })
        data = _jira_get(f"{base}/rest/api/2/search?{query}", email, api_token)
        issues = data.get("issues") or []
        if not issues:
            break
        for issue in issues:
            fields = issue.get("fields") or {}
            status = fields.get("status") or {}
            assignee = fields.get("assignee") or {}
            issuetype = fields.get("issuetype") or {}
            tickets.append({
                "ticket_id": issue.get("key", ""),
                "summary": fields.get("summary") or "",
                "status": status.get("name") or "To Do",
                "description": _adf_to_text(fields.get("description")),
                "due_date": fields.get("duedate") or "",
                "issue_type": issuetype.get("name") or "",
                "assignee": assignee.get("displayName") or "",
                # Stable per-person id for cross-project rollups (Member
                # Performance page) -- unlike displayName, this never
                # changes for the same person. accountId is Jira Cloud's
                # identifier; key/name are the Server/Data Center
                # equivalents (accountId doesn't exist there).
                "assignee_key": assignee.get("accountId") or assignee.get("key") or assignee.get("name") or "",
            })
        start_at += page_size
        if start_at >= (data.get("total") or 0):
            break

    return tickets[:max_results]


def fetch_ticket(site_url: str, email: str, api_token: str, ticket_key: str) -> dict:
    """Fetch a single ticket's CURRENT data from Jira by key, via the
    single-issue endpoint (cheaper than a JQL search for one ticket). Used
    by /api/re-evaluate-ticket to refresh a ticket's status/summary/
    description before re-checking it against code -- a "re-check this
    ticket" click is often prompted by exactly this: the status was wrong
    on Jira, got fixed there, and the user wants that reflected without
    re-running the whole project's scan. Shaped like fetch_tickets' dicts."""
    base = _normalize_site_url(site_url)
    ticket_key = (ticket_key or "").strip()
    if not ticket_key:
        raise JiraConnectionError("jira.project_key_required")

    query = urllib.parse.urlencode({"fields": "summary,description,status,assignee,duedate,issuetype"})
    data = _jira_get(f"{base}/rest/api/2/issue/{urllib.parse.quote(ticket_key, safe='')}?{query}", email, api_token)

    fields = data.get("fields") or {}
    status = fields.get("status") or {}
    assignee = fields.get("assignee") or {}
    issuetype = fields.get("issuetype") or {}
    return {
        "ticket_id": data.get("key", ticket_key),
        "summary": fields.get("summary") or "",
        "status": status.get("name") or "To Do",
        "description": _adf_to_text(fields.get("description")),
        "due_date": fields.get("duedate") or "",
        "issue_type": issuetype.get("name") or "",
        "assignee": assignee.get("displayName") or "",
        "assignee_key": assignee.get("accountId") or assignee.get("key") or assignee.get("name") or "",
    }
