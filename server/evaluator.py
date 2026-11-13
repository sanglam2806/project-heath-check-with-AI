"""
Evaluator module: builds prompts and calls an LLM (OpenAI-compatible API
or local Ollama) to compare ticket descriptions against actual source code.
"""

import base64
import json
import os
import re
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime
from typing import Dict, List, Optional, Tuple

from dotenv import load_dotenv
from openai import OpenAI

import model_config
import scan_progress
import ticket_status
from models import TicketResult
from scanner import build_scan_context

load_dotenv()

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
# API key/base URL/model name (both phases) are resolved fresh at the start
# of every evaluate_with_llm call via model_config.get_llm_settings() --
# DB-saved values (Model Configuration page) win, falling back to
# server/.env. See model_config.py for why: this lets an Owner/Admin
# change models from the UI with no backend restart needed.

# One LLM call covers at most this many tickets. Asking for too many at once
# risks the response getting cut off mid-JSON at max_tokens (which then fails
# to parse at all) - keeping batches small keeps each response comfortably
# within budget, and a truncated/bad batch only falls back to heuristics for
# its own tickets rather than the whole evaluation.
_BATCH_SIZE = int(os.getenv("EVAL_BATCH_SIZE", "3"))
# Deep-judgment batches are smaller: each may carry image attachments, and
# the point of escalating is careful review, not throughput.
_DEEP_BATCH_SIZE = int(os.getenv("EVAL_DEEP_BATCH_SIZE", "1"))
_MAX_TOKENS = int(os.getenv("EVAL_MAX_TOKENS", "4096"))
# How many batches to send to the LLM at once. Batches are independent, so
# running them concurrently (instead of one after another) cuts total wait
# time roughly by this factor. Keep it modest to avoid tripping the
# provider's own rate limits.
_CONCURRENCY = int(os.getenv("EVAL_CONCURRENCY", "4"))
_MAX_IMAGES_PER_TICKET = 3


# ---------------------------------------------------------------------------
# Prompt construction
# ---------------------------------------------------------------------------
_SHARED_INTRO = """You perform a 3-way triangular verification for each ticket, cross-checking \
three sources against each other: the JIRA/Excel ticket, the actual source code (Git diff), \
and the project's design documentation (specs, architecture docs, UI mockups, slide decks). \
You must be strict and evidence-based.

For each ticket you will receive:
- Ticket ID
- Reported status (Done / In Progress / To Do / ...)
- Due Date (may be blank)
- As-of Date (the date this audit is being run)
- Summary & Description (including acceptance criteria)
- Matched source files
- Relevant code snippets
- Related documentation: the top-matching excerpts from the repo's design docs for this \
specific ticket (found by keyword relevance — may say "NONE FOUND" if nothing matched)

PART A — Ticket vs Code (assessment): this axis checks whether the REPORTED STATUS itself is \
accurate given the real implementation state -- not just whether the described feature exists \
somewhere in the code.
1. Treat "Done", "Closed", "Resolved", and any status containing "release", "deploy", \
"verified", "shipped", or "complete" (e.g. "Release", "Ready for Release", "Deployed to prod", \
"Verified", "Shipped", "Complete") as DONE-equivalent — EXCEPT "Incomplete", which is not done.
2. If reported status is DONE-equivalent but the code is missing, incomplete, or does not \
satisfy the acceptance criteria, mark assessment = "Mismatch".
3. If reported status is "In Progress", estimate the real completion percentage based on \
evidence in the code and mark assessment = "Incomplete" — unless the evidence shows the work \
is actually already fully done, in which case evaluate it like a DONE-equivalent status (rule 2).
4. If reported status is "To Do"/"Open" (not started) but matching code ALREADY EXISTS that \
implements some/all of the acceptance criteria, mark assessment = "Mismatch" — the ticket \
status is stale/inaccurate, not the code. Still give a completion percentage reflecting the \
real progress, and explain in missing_parts that the reported status does not match the actual \
implementation state.
5. Be conservative: only count features as implemented if there is real code evidence.
6. Missing parts must be concrete (e.g. "User login endpoint POST /auth/login is missing", \
"Input validation for email field not found").
7. If reported status is DONE-equivalent but NO matching source file/content was found at all, \
mark assessment = "Mismatch" and add a missing_parts entry starting with the literal tag \
"[NO_SOURCE]" followed by what was expected, e.g. \
"[NO_SOURCE] Expected implementation of CSV export feature, no matching file found".

PART B — Ticket vs Documentation (doc_ticket_match):
Does the related documentation actually cover this ticket's acceptance criteria?
- "Match": the doc describes this feature/requirement adequately.
- "Doc Outdated": the ticket asks for something (e.g. a new field, a changed business \
rule) that the matched doc doesn't mention or contradicts — the doc hasn't caught up.
- "No Doc Found": no related documentation was found for this ticket at all.
This axis is about documentation coverage, independent of whether the code was built.

PART C — Documentation vs Code (doc_code_match):
Does the actual code conform to what the matched documentation specifies? This is the \
most important axis for catching silent business-logic bugs. Compare concrete details: \
API routes/request/response shape, numeric business rules (percentages, thresholds, \
limits), required fields/validation, and UI elements (buttons, modals, forms) mentioned \
in the doc vs what the code/diff actually does.
- "Match": code behavior/shape matches what the doc specifies.
- "Mismatch": code contradicts the doc on a concrete point — always cite BOTH the doc's \
stated value/behavior and the code's actual value/behavior in doc_notes, e.g. \
"Doc (function_list.md) states refund = 80% before 24h; code hardcodes refund = 1.0 (100%)".
- "Doc Drift": the code does something reasonable that the doc simply doesn't mention \
(code is ahead of docs, not wrong — e.g. an extra validation not documented).
- "N/A": no related documentation was found, so this axis cannot be evaluated.
Only use "Mismatch" when you can point to a specific concrete contradiction, not vague \
impressions.

Confidence discipline for truncated documentation: the "Related documentation" line tells you \
when only some candidate docs are shown (e.g. "showing top 6 of 9 candidate docs ... MORE \
CANDIDATE DOCS EXIST THAT ARE NOT SHOWN HERE"). When you see that marker and you are not fully \
confident the shown excerpts are representative enough to judge doc_ticket_match/doc_code_match \
(e.g. they seem tangential, or contradict each other, or the ticket describes something none of \
them clearly cover), cap your overall "confidence" for this ticket at 0.5 or lower. This is the \
deliberate signal that routes the ticket to deeper review — including, when the deep-dive agent \
is enabled, giving it access to search ALL documentation in the repo, not just what was shown to \
you here. Do not cap confidence this way when the shown docs already clearly settle the question.

PART D — Schedule/risk assessment (only if Due Date is provided):
1. Compare Due Date to As-of Date and to your estimated completion_percent to judge \
timeliness. Use these labels internally: "On-time", "Late", "At-Risk".
   - "Late": Due Date has passed AND completion_percent < 100.
   - "At-Risk": Due Date has NOT passed, but completion_percent is low relative to time \
remaining (e.g. <50% complete with <20% of the time-to-deadline left), based on your \
best judgment from the evidence available.
   - "On-time": everything else (completed on time, or comfortably on track).
2. If Due Date is missing, skip schedule labeling and state "No due date provided" instead.
3. Always compute days_diff = (As-of Date - Due Date) in days. Positive means overdue, \
negative means days remaining, 0 if due today. Omit if Due Date is missing.

Output formatting rule for "notes":
Always start the "notes" field with a single structured line in this exact format, \
then a blank line, then your free-text reasoning:
"SCHEDULE: <On-time|Late|At-Risk|No due date provided> | DAYS_DIFF: <integer or N/A>"

Example notes field:
"SCHEDULE: Late | DAYS_DIFF: 7\n\nThe ticket was due 2024-05-01 but code shows only the \
backend endpoint implemented; the frontend form described in the acceptance criteria is \
absent."

Put your PART B/C reasoning in "doc_notes" instead (separate field, not mixed into "notes").

Language rule: ALWAYS write every text field ("notes", "missing_parts", "suggestions", \
"doc_notes") in English, regardless of what language the ticket's summary/description, the \
source code, or the documentation are written in. Never mirror the input's language.
"""

_BASE_RESULT_SCHEMA_FIELDS = """      "ticket_id": "string",
      "completion_percent": 0-100,
      "assessment": "Match|Mismatch|Incomplete",
      "confidence": 0.0-1.0,
      "missing_parts": ["string", ...],
      "suggestions": ["string", ...],
      "notes": "string",
      "doc_ticket_match": "Match|Doc Outdated|No Doc Found",
      "doc_code_match": "Match|Mismatch|Doc Drift|N/A",
      "doc_notes": "string\""""

TRIAGE_SYSTEM_PROMPT = (
    "You are the FAST first-pass triage auditor (cheap/quick model). "
    + _SHARED_INTRO
    + """
PART E — Escalation routing (needs_deep_review):
Set "needs_deep_review" = true when ANY of these apply, so a stronger model double-checks \
before this becomes the final answer:
- The ticket involves conditional/numeric business-rule logic (percentages, thresholds, \
date/time cutoffs, multi-branch conditions) where getting the exact value/condition wrong \
matters.
- You suspect doc_code_match should be "Mismatch" or "Doc Drift" but aren't fully certain \
from the evidence given.
- The ticket or documentation implies a specific UI element (button, modal, form, screen \
layout) that would need a mockup image to verify.
- Anything else where your confidence is not high.
Otherwise (obviously correct Match, or an obviously absent "ghost feature" with zero \
evidence) set "needs_deep_review" = false. Always give your best-effort answer for every \
field regardless of this flag — if escalation fails for any reason, this answer is used \
as the final result.

Return STRICT JSON only, no markdown, no extra text. Schema:
{
  "results": [
    {
"""
    + _BASE_RESULT_SCHEMA_FIELDS
    + """,
      "needs_deep_review": true|false
    }
  ]
}
"""
)

DEEP_SYSTEM_PROMPT = (
    "You are the DEEP judgment auditor. This ticket was escalated by a faster first-pass "
    "model because it looked ambiguous — take your time and be thorough. "
    + _SHARED_INTRO
    + """
PART E — Documentation image vs Code (ui_screen_match):
If one or more reference images (UI mockups/screenshots) are attached, compare them against \
the ticket and the code/diff. Set "ui_screen_match":
- "Match": the code's UI (component names, form fields, buttons visible in the diff) is \
consistent with what the image shows.
- "Missing UI": the image shows a specific element (e.g. a confirm modal, a specific field) \
that the code/diff does not contain evidence of.
- "No Screen Found": no reference image was attached for this ticket.
- "N/A": images aren't relevant to this ticket (no UI implied).
Cite concretely what the image shows vs what's missing, in doc_notes.

Return STRICT JSON only, no markdown, no extra text. Schema:
{
  "results": [
    {
"""
    + _BASE_RESULT_SCHEMA_FIELDS
    + """,
      "ui_screen_match": "Match|Missing UI|No Screen Found|N/A"
    }
  ]
}
"""
)


# ---------------------------------------------------------------------------
# Schedule/risk helpers (Due Date vs As-of Date)
# ---------------------------------------------------------------------------
_SCHEDULE_LINE_RE = re.compile(
    r"^SCHEDULE:\s*(?P<status>[^|]+?)\s*\|\s*DAYS_DIFF:\s*(?P<days>-?\d+|N/A)",
    re.IGNORECASE,
)
_DUE_DATE_FORMATS = ("%Y-%m-%d", "%d/%b/%y", "%d/%b/%Y", "%m/%d/%Y", "%d/%m/%Y")


def _parse_due_date(value: str):
    if not value:
        return None
    value = value.strip()
    for fmt in _DUE_DATE_FORMATS:
        try:
            return datetime.strptime(value, fmt).date()
        except ValueError:
            continue
    return None


def _compute_schedule(due_date_str: str, completion_percent: float) -> Tuple[str, Optional[int]]:
    """
    Pure date-math fallback for when there's no LLM to ask (heuristics),
    or the LLM didn't follow the "SCHEDULE: ..." notes format.
    """
    due = _parse_due_date(due_date_str or "")
    if due is None:
        return "No due date provided", None

    days_diff = (date.today() - due).days  # positive=overdue, negative=days remaining
    if days_diff > 0 and completion_percent < 100:
        return "Late", days_diff
    if days_diff <= 0 and completion_percent < 50:
        return "At-Risk", days_diff
    return "On-time", days_diff


def _extract_schedule_from_notes(notes: str) -> Tuple[str, Optional[int]]:
    """Parse the 'SCHEDULE: <status> | DAYS_DIFF: <n>' line the LLM is
    instructed to put at the top of `notes`. Returns ("", None) if the
    line isn't present/parseable."""
    if not notes:
        return "", None
    first_line = notes.strip().splitlines()[0]
    m = _SCHEDULE_LINE_RE.match(first_line.strip())
    if not m:
        return "", None
    status = m.group("status").strip()
    days_raw = m.group("days")
    days = None if days_raw.upper() == "N/A" else int(days_raw)
    return status, days


def _build_user_prompt(context: str) -> str:
    return (
        "Evaluate the following tickets against their source code evidence and related "
        "documentation.\n\n"
        f"{context}\n\n"
        "Return the JSON result for every ticket listed above."
    )


def _parse_json_response(raw: str, list_key: str = "results") -> List[Dict]:
    """Robustly parse JSON from LLM output (strips markdown fences if any).

    `list_key` is the wrapper key expected around the list (e.g. "results"
    for evaluator prompts, "items" for solutions prompts) — callers with a
    different schema pass their own key rather than duplicating this parser.
    """
    cleaned = raw.strip()
    # Remove markdown code fences if present
    fence_match = re.search(r"```(?:json)?\s*(.*?)```", cleaned, re.DOTALL)
    if fence_match:
        cleaned = fence_match.group(1).strip()

    # Try to find the outermost JSON object/array
    try:
        data = json.loads(cleaned)
    except json.JSONDecodeError:
        # Fallback: locate first '{' and last '}'
        start = cleaned.find("{")
        end = cleaned.rfind("}")
        if start != -1 and end != -1 and end > start:
            try:
                data = json.loads(cleaned[start:end + 1])
            except json.JSONDecodeError:
                raise ValueError(f"Could not parse LLM JSON output: {raw[:500]}")
        else:
            raise ValueError(f"Could not parse LLM JSON output: {raw[:500]}")

    if isinstance(data, dict) and list_key in data:
        return data[list_key]
    if isinstance(data, list):
        return data
    raise ValueError(f"Unexpected LLM response shape: {data}")


def _triage_batch(
    client: OpenAI, batch: List[Dict], scan_result: Dict[str, Dict], as_of_date: str, model: str
) -> Dict[str, Dict]:
    """Phase 1: fast/cheap triage call. Returns {ticket_id: raw_item} —
    each item is already a full best-effort result plus a needs_deep_review
    flag, or {} (falling back to heuristics) if the call fails."""
    batch_context = build_scan_context(batch, scan_result, as_of_date)
    try:
        response = client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": TRIAGE_SYSTEM_PROMPT},
                {"role": "user", "content": _build_user_prompt(batch_context)},
            ],
            temperature=0.2,
            max_tokens=_MAX_TOKENS,
        )
        raw = response.choices[0].message.content or ""
        parsed = _parse_json_response(raw)
        return {
            str(item.get("ticket_id", "")).upper(): item
            for item in parsed
            if item.get("ticket_id")
        }
    except Exception as exc:
        # Log warning but fall through to heuristic evaluation for this batch
        batch_ids = ", ".join(t["ticket_id"] for t in batch)
        print(f"[evaluator] Triage LLM call failed for batch [{batch_ids}], using heuristics: {exc}")
        return {}


def _image_content_blocks(images: List[Tuple[str, bytes, str]]) -> List[Dict]:
    blocks = []
    for _path, raw, mime in images[:_MAX_IMAGES_PER_TICKET]:
        b64 = base64.b64encode(raw).decode("ascii")
        blocks.append({"type": "image_url", "image_url": {"url": f"data:{mime};base64,{b64}"}})
    return blocks


def _deep_evaluate_batch(
    client: OpenAI, batch: List[Dict], scan_result: Dict[str, Dict], as_of_date: str, model: str
) -> Dict[str, Dict]:
    """Phase 2: deep-judgment call for tickets the triage phase flagged as
    needing review. Attaches up to
    _MAX_IMAGES_PER_TICKET reference images per ticket as multimodal
    content when any were matched (scanner.select_relevant_images). If the
    gateway/model rejects a multimodal call (vision not supported, wrong
    model name, ...), retries once as text-only before giving up on this
    batch — callers then keep the Phase 1 result for these tickets, never
    crash the whole scan."""
    batch_context = build_scan_context(batch, scan_result, as_of_date)
    image_blocks: List[Dict] = []
    for t in batch:
        tid = t["ticket_id"].upper()
        images = scan_result.get(tid, {}).get("images") or []
        image_blocks.extend(_image_content_blocks(images))

    def _call(with_images: bool):
        use_images = with_images and bool(image_blocks)
        content = (
            [{"type": "text", "text": _build_user_prompt(batch_context)}] + image_blocks
            if use_images
            else _build_user_prompt(batch_context)
        )
        return client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": DEEP_SYSTEM_PROMPT},
                {"role": "user", "content": content},
            ],
            temperature=0.2,
            max_tokens=_MAX_TOKENS,
        )

    batch_ids = ", ".join(t["ticket_id"] for t in batch)
    try:
        response = _call(with_images=True)
    except Exception as exc:
        print(f"[evaluator] Deep LLM call with images failed for batch [{batch_ids}], retrying text-only: {exc}")
        try:
            response = _call(with_images=False)
        except Exception as exc2:
            print(f"[evaluator] Deep LLM call failed for batch [{batch_ids}], keeping triage result: {exc2}")
            return {}

    try:
        raw = response.choices[0].message.content or ""
        parsed = _parse_json_response(raw)
        return {
            str(item.get("ticket_id", "")).upper(): item
            for item in parsed
            if item.get("ticket_id")
        }
    except Exception as exc:
        print(f"[evaluator] Deep LLM response parse failed for batch [{batch_ids}], keeping triage result: {exc}")
        return {}


def evaluate_with_llm(
    tickets: List[Dict],
    scan_result: Dict[str, Dict],
    job_id: str = "",
) -> List[TicketResult]:
    """
    Two-phase cascade. Phase 1 (triage) runs every ticket through a fast/
    cheap model that already produces a full best-effort result plus a
    needs_deep_review flag. Phase 2 (deep judgment) only re-evaluates
    tickets flagged needs_deep_review, with reference images attached when
    relevant — resolving the obvious
    majority of tickets in Phase 1 alone. Phase 2's result replaces Phase
    1's provisional one where it succeeds; where Phase 2 fails/is skipped,
    the Phase 1 result stands. Falls back to heuristic evaluation for any
    ticket neither phase could parse. Each ticket's related documentation/
    image excerpts (if any) are already embedded per-ticket in
    `scan_result` (see scanner.build_scan_context / git_scan.build_scan_result).

    Tickets with a Cancelled status are never sent to the LLM (or the
    heuristic fallback) at all -- they get an immediate "Skipped" result
    (see _skipped_result), since there is nothing meaningful to verify for
    work that was never going to happen. Callers that roll results up into
    summary/health/risk stats should exclude "Skipped" from those, the same
    way _build_summary in main.py does.
    """
    skip_ids = {
        t["ticket_id"].upper() for t in tickets if ticket_status.is_cancelled_status(t.get("status"))
    }
    active_tickets = [t for t in tickets if t["ticket_id"].upper() not in skip_ids]

    # Resolved fresh on every call (DB-saved Model Configuration wins,
    # falling back to server/.env) -- so a change saved from the app takes
    # effect on the very next scan, no backend restart needed.
    settings = model_config.get_llm_settings()
    client = OpenAI(
        api_key=settings["api_key"],
        base_url=settings["base_url"],
    )
    # Separate client for Phase 2: some gateways issue a distinct API key
    # per model, so the Phase 1 key/base URL isn't guaranteed to work here.
    deep_client = (
        client
        if (settings["api_key_deep"], settings["base_url_deep"]) == (settings["api_key"], settings["base_url"])
        else OpenAI(api_key=settings["api_key_deep"], base_url=settings["base_url_deep"])
    )
    as_of_date = date.today().isoformat()

    batches = [active_tickets[i:i + _BATCH_SIZE] for i in range(0, len(active_tickets), _BATCH_SIZE)]

    triage_results: Dict[str, Dict] = {}
    if batches:
        scan_progress.update(job_id, phase="evaluating", current=0, total=len(active_tickets))
        done_count = 0
        with ThreadPoolExecutor(max_workers=min(_CONCURRENCY, len(batches))) as pool:
            for batch, batch_result in zip(
                batches,
                pool.map(
                    lambda b: _triage_batch(client, b, scan_result, as_of_date, settings["model"]), batches
                ),
            ):
                triage_results.update(batch_result)
                done_count += len(batch)
                scan_progress.update(job_id, current=done_count)

    escalate_ids = {
        tid for tid, item in triage_results.items()
        if str(item.get("needs_deep_review", "")).strip().lower() in ("true", "1", "yes")
    }
    escalate_tickets = [t for t in active_tickets if t["ticket_id"].upper() in escalate_ids]

    deep_results: Dict[str, Dict] = {}
    if escalate_tickets:
        deep_batches = [
            escalate_tickets[i:i + _DEEP_BATCH_SIZE]
            for i in range(0, len(escalate_tickets), _DEEP_BATCH_SIZE)
        ]
        scan_progress.update(job_id, phase="evaluating_deep", current=0, total=len(escalate_tickets))
        done_count = 0
        with ThreadPoolExecutor(max_workers=min(_CONCURRENCY, len(deep_batches))) as pool:
            for batch, batch_result in zip(
                deep_batches,
                pool.map(
                    lambda b: _deep_evaluate_batch(deep_client, b, scan_result, as_of_date, settings["model_deep"]),
                    deep_batches,
                ),
            ):
                deep_results.update(batch_result)
                done_count += len(batch)
                scan_progress.update(job_id, current=done_count)

    results: List[TicketResult] = []
    for t in tickets:
        tid = t["ticket_id"].upper()
        if tid in skip_ids:
            results.append(_skipped_result(t))
            continue

        info = scan_result.get(tid, {"files": [], "snippets": []})
        evidence_count = len(info["files"])
        has_snippets = bool(info["snippets"])

        deep_item = deep_results.get(tid)
        triage_item = triage_results.get(tid)
        if deep_item:
            results.append(_map_llm_result(t, deep_item, info, escalated=True))
        elif triage_item:
            results.append(_map_llm_result(t, triage_item, info, escalated=False))
        else:
            results.append(_heuristic_evaluate(t, evidence_count, has_snippets, info))

    return results


def _skipped_result(ticket: Dict) -> TicketResult:
    """Immediate result for a Cancelled ticket -- never sent to the LLM or
    the heuristic fallback, since there's nothing meaningful to verify for
    work that was never going to happen. `assessment="Skipped"` is
    deliberately outside the Match/Mismatch/Incomplete set so it never gets
    counted as any of those in summary/health/risk rollups (all of which
    compare with `==` against the specific known strings)."""
    return TicketResult(
        ticket_id=ticket["ticket_id"],
        summary=ticket.get("summary", ""),
        status=ticket.get("status", ""),
        completion_percent=0.0,
        assessment="Skipped",
        confidence=1.0,
        missing_parts=[],
        suggestions=[],
        evidence_files=[],
        notes="Ticket status is Cancelled -- excluded from evaluation.",
        assignee=ticket.get("assignee", ""),
        doc_ticket_match="N/A",
        doc_code_match="N/A",
    )


def _map_llm_result(
    ticket: Dict, llm_item: Dict, info: Dict, escalated: bool = False
) -> TicketResult:
    """Convert an LLM dict item into a validated TicketResult. `escalated`
    indicates this item came from the Phase 2 deep-judgment model rather
    than the Phase 1 triage model."""

    def _safe_list(value, default=None):
        if isinstance(value, list):
            return [str(x) for x in value]
        if isinstance(value, str) and value.strip():
            return [value.strip()]
        return default or []

    def _safe_float(value, lo=0.0, hi=100.0, default=0.0):
        try:
            v = float(value)
            return max(lo, min(hi, v))
        except (TypeError, ValueError):
            return default

    assessment_raw = str(llm_item.get("assessment", "")).strip()
    assessment = (
        assessment_raw
        if assessment_raw in {"Match", "Mismatch", "Incomplete"}
        else "Incomplete"
    )
    completion_percent = _safe_float(llm_item.get("completion_percent"))
    notes = str(llm_item.get("notes", "") or "")

    docs = info.get("docs") or []
    doc_ticket_match_raw = str(llm_item.get("doc_ticket_match", "")).strip()
    doc_ticket_match = (
        doc_ticket_match_raw
        if doc_ticket_match_raw in {"Match", "Doc Outdated", "No Doc Found"}
        else ("No Doc Found" if not docs else "Doc Outdated")
    )
    doc_code_match_raw = str(llm_item.get("doc_code_match", "")).strip()
    doc_code_match = (
        doc_code_match_raw
        if doc_code_match_raw in {"Match", "Mismatch", "Doc Drift", "N/A"}
        else "N/A"
    )

    needs_deep_review = str(llm_item.get("needs_deep_review", "")).strip().lower() in ("true", "1", "yes")

    images = info.get("images") or []
    ui_screen_match_raw = str(llm_item.get("ui_screen_match", "")).strip()
    ui_screen_match = (
        ui_screen_match_raw
        if ui_screen_match_raw in {"Match", "Missing UI", "No Screen Found", "N/A"}
        else ("No Screen Found" if not images else "")
    )

    schedule_status, days_diff = _extract_schedule_from_notes(notes)
    if not schedule_status:
        # LLM didn't follow the "SCHEDULE: ..." notes format; fall back
        # to computing it directly from the ticket's Due Date.
        schedule_status, days_diff = _compute_schedule(
            ticket.get("due_date", ""), completion_percent
        )

    return TicketResult(
        ticket_id=ticket["ticket_id"],
        summary=ticket["summary"],
        status=ticket["status"],
        completion_percent=completion_percent,
        assessment=assessment,
        confidence=_safe_float(llm_item.get("confidence"), 0.0, 1.0, 0.0),
        missing_parts=_safe_list(llm_item.get("missing_parts")),
        suggestions=_safe_list(llm_item.get("suggestions")),
        evidence_files=info["files"],
        notes=notes,
        schedule_status=schedule_status,
        days_diff=days_diff,
        assignee=ticket.get("assignee", ""),
        doc_ticket_match=doc_ticket_match,
        doc_code_match=doc_code_match,
        doc_notes=str(llm_item.get("doc_notes", "") or ""),
        matched_doc_files=[p for p, _ in docs],
        needs_deep_review=needs_deep_review,
        escalated=escalated,
        ui_screen_match=ui_screen_match,
        matched_image_files=[p for p, _, _ in images],
    )


def _heuristic_evaluate(
    ticket: Dict, evidence_count: int, has_snippets: bool, info: Dict
) -> TicketResult:
    """
    Fallback rule-based evaluation when the LLM is unavailable. Also fills
    in schedule_status/days_diff from the ticket's Due Date, since there's
    no LLM here to produce the "SCHEDULE: ..." notes line.
    """
    result = _heuristic_evaluate_core(ticket, evidence_count, has_snippets, info)
    result.schedule_status, result.days_diff = _compute_schedule(
        ticket.get("due_date", ""), result.completion_percent
    )
    result.assignee = ticket.get("assignee", "")

    docs = info.get("docs") or []
    result.matched_doc_files = [p for p, _ in docs]
    result.doc_ticket_match = "No Doc Found" if not docs else "Not evaluated (LLM unavailable)"
    result.doc_code_match = "N/A"
    if docs:
        result.doc_notes = "Doc-vs-code comparison requires the LLM; heuristic fallback was used."

    images = info.get("images") or []
    result.matched_image_files = [p for p, _, _ in images]
    result.ui_screen_match = "No Screen Found" if not images else "N/A"
    return result


def _heuristic_evaluate_core(
    ticket: Dict, evidence_count: int, has_snippets: bool, info: Dict
) -> TicketResult:
    """
    Fallback rule-based evaluation when the LLM is unavailable.
    """
    status = ticket["status"]
    tid = ticket["ticket_id"]
    files = info["files"]

    if ticket_status.is_done_status(status):
        if evidence_count == 0:
            return TicketResult(
                ticket_id=tid,
                summary=ticket["summary"],
                status=ticket["status"],
                completion_percent=10.0,
                assessment="Mismatch",
                confidence=0.5,
                missing_parts=["No source files found referencing this ticket."],
                suggestions=[
                    "Search the codebase for the ticket ID or related feature keywords.",
                    "Confirm whether the work was actually merged/deployed.",
                ],
                evidence_files=files,
                notes="Heuristic: status Done but zero code evidence found.",
            )
        if evidence_count > 0 and has_snippets:
            return TicketResult(
                ticket_id=tid,
                summary=ticket["summary"],
                status=ticket["status"],
                completion_percent=80.0,
                assessment="Match",
                confidence=0.55,
                missing_parts=[],
                suggestions=["Verify acceptance criteria manually."],
                evidence_files=files,
                notes="Heuristic: status Done and code evidence found.",
            )
        return TicketResult(
            ticket_id=tid,
            summary=ticket["summary"],
            status=ticket["status"],
            completion_percent=60.0,
            assessment="Incomplete",
            confidence=0.5,
            missing_parts=["Code evidence is weak; review manually."],
            suggestions=["Run LLM evaluation for a detailed breakdown."],
            evidence_files=files,
            notes="Heuristic: status Done, partial evidence.",
        )

    if ticket_status.is_in_progress_status(status):
        if evidence_count == 0:
            return TicketResult(
                ticket_id=tid,
                summary=ticket["summary"],
                status=ticket["status"],
                completion_percent=5.0,
                assessment="Incomplete",
                confidence=0.5,
                missing_parts=["No code evidence yet."],
                suggestions=["Start implementing the ticket."],
                evidence_files=files,
                notes="Heuristic: In Progress, no code found.",
            )
        return TicketResult(
            ticket_id=tid,
            summary=ticket["summary"],
            status=ticket["status"],
            completion_percent=45.0,
            assessment="Incomplete",
            confidence=0.5,
            missing_parts=[
                "Partial implementation; verify remaining acceptance criteria."
            ],
            suggestions=["Continue implementation and add tests."],
            evidence_files=files,
            notes="Heuristic: In Progress with partial code evidence.",
        )

    # To Do / Open / Unknown
    if evidence_count > 0:
        return TicketResult(
            ticket_id=tid,
            summary=ticket["summary"],
            status=ticket["status"],
            completion_percent=70.0,
            assessment="Mismatch",
            confidence=0.6,
            missing_parts=[
                "Ticket status is still 'To Do'/'Open' but matching source code already exists "
                "-- the reported status appears stale/inaccurate."
            ],
            suggestions=["Update the ticket status to reflect the actual implementation progress."],
            evidence_files=files,
            notes="Heuristic: status not started, but code evidence already exists -- status looks stale.",
        )
    return TicketResult(
        ticket_id=tid,
        summary=ticket["summary"],
        status=ticket["status"],
        completion_percent=0.0,
        assessment="Incomplete",
        confidence=0.5,
        missing_parts=["Ticket not started."],
        suggestions=["Plan and implement the ticket."],
        evidence_files=files,
        notes="Heuristic: no code evidence.",
    )
