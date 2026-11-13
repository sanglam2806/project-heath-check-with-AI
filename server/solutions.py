"""
Solutions module: synthesizes project-wide (not per-ticket) recommendations
from already-evaluated tickets, via one aggregate LLM call over the results
digest, with a heuristic keyword-bucketing fallback. Mirrors the
LLM-with-heuristic-fallback pattern used in evaluator.py.
"""
import os
import re
from typing import Dict, List

from openai import OpenAI

import model_config
from models import ProjectSolutions, TicketResult

# API key/base URL/model name are resolved fresh at call time via
# model_config.get_llm_settings() (Model Configuration page's DB-saved
# value wins, falling back to server/.env) -- see model_config.py. This
# reuses the Phase 1 ("model"/"api_key"/"base_url") settings, the same
# model Layer 2's triage phase uses.
_MAX_TOKENS = int(os.getenv("SOLUTIONS_MAX_TOKENS", "2048"))

SYSTEM_PROMPT_SOLUTIONS = """You are a senior engineering manager reviewing a project health audit. \
You will receive a compact digest of every ticket's assessment (Match/Mismatch/Incomplete), \
schedule status, missing parts, and per-ticket suggestions.

Your job is NOT to repeat per-ticket suggestions. Instead, find PROJECT-WIDE PATTERNS across \
tickets (e.g. "several tickets are missing input validation", "multiple Done tickets have no \
tests", "schedule slippage is concentrated in the auth module") and propose a small number of \
concrete, actionable, higher-level recommendations that address the root causes.

Return STRICT JSON only, no markdown, no extra text. Schema:
{
  "items": [
    {
      "title": "short recommendation title",
      "category": "one of: Process, Testing, Documentation, Technical Debt, Schedule, Other",
      "recommendation": "concrete action to take",
      "affected_tickets": ["TICKET-1", "TICKET-2"],
      "priority": "High|Medium|Low",
      "rationale": "why this matters, referencing the pattern observed"
    }
  ]
}
Return at most 8 items, ordered by priority (High first). If there is truly nothing notable, \
return {"items": []}.

Language rule: ALWAYS write "title", "recommendation", and "rationale" in English, regardless \
of what language the ticket digest below is written in. Never mirror the input's language.
"""

_CATEGORY_KEYWORDS = {
    "Testing": ["test", "tests", "unit test", "coverage"],
    "Documentation": ["document", "docs", "readme", "comment"],
    "Technical Debt": ["refactor", "duplicate", "hardcod", "cleanup", "no_source", "[no_source]"],
    "Schedule": ["overdue", "late", "deadline", "at risk", "at-risk"],
}


def _build_digest(tickets: List[Dict], results: List[TicketResult]) -> str:
    tickets_by_id = {t["ticket_id"].upper(): t for t in tickets}
    lines: List[str] = []
    for r in results:
        t = tickets_by_id.get(r.ticket_id.upper(), {})
        lines.append(f"--- {r.ticket_id} ---")
        lines.append(f"Reported status: {t.get('status', r.status)}")
        lines.append(f"Assessment: {r.assessment} | Schedule: {r.schedule_status}")
        lines.append(f"Completion: {r.completion_percent:.0f}%")
        if r.missing_parts:
            lines.append("Missing parts: " + "; ".join(r.missing_parts))
        if r.suggestions:
            lines.append("Suggestions: " + "; ".join(r.suggestions))
        lines.append("")
    return "\n".join(lines)


def synthesize_solutions_with_llm(
    tickets: List[Dict], results: List[TicketResult]
) -> List[Dict]:
    """One aggregate call over the digest of all results. Raises on any
    failure (bad connection, unparseable JSON, etc.) — caller falls back to
    heuristics."""
    from evaluator import _parse_json_response  # reuse existing robust parser

    settings = model_config.get_llm_settings()
    client = OpenAI(api_key=settings["api_key"], base_url=settings["base_url"])
    digest = _build_digest(tickets, results)
    response = client.chat.completions.create(
        model=settings["model"],
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT_SOLUTIONS},
            {"role": "user", "content": f"Ticket digest:\n\n{digest}\n\nReturn the JSON result."},
        ],
        temperature=0.2,
        max_tokens=_MAX_TOKENS,
    )
    raw = response.choices[0].message.content or ""
    parsed = _parse_json_response(raw, list_key="items")
    return parsed


def build_heuristic_solutions(
    tickets: List[Dict], results: List[TicketResult]
) -> List[Dict]:
    """Fallback: bucket missing_parts/suggestions text by keyword into fixed
    categories when the LLM is unavailable or fails."""
    buckets: Dict[str, List[str]] = {}

    for r in results:
        text_blob = " ".join(r.missing_parts + r.suggestions).lower()
        if not text_blob:
            continue
        matched_category = "Other"
        for category, keywords in _CATEGORY_KEYWORDS.items():
            if any(kw in text_blob for kw in keywords):
                matched_category = category
                break
        if r.assessment == "Mismatch" and matched_category == "Other":
            matched_category = "Technical Debt"
        buckets.setdefault(matched_category, []).append(r.ticket_id)

    items: List[Dict] = []
    for category, ticket_ids in buckets.items():
        priority = "High" if category in ("Technical Debt", "Schedule") and len(ticket_ids) > 1 else "Medium"
        items.append({
            "title": f"{category} gaps found across {len(ticket_ids)} ticket(s)",
            "category": category,
            "recommendation": f"Review the {category.lower()}-related gaps flagged on: "
                               + ", ".join(ticket_ids[:10]),
            "affected_tickets": ticket_ids,
            "priority": priority,
            "rationale": f"{len(ticket_ids)} ticket(s) had evaluation notes matching {category} keywords.",
        })

    items.sort(key=lambda it: {"High": 0, "Medium": 1, "Low": 2}.get(it["priority"], 1))
    return items


def build_project_solutions(
    tickets: List[Dict], results: List[TicketResult]
) -> ProjectSolutions:
    if not results:
        return ProjectSolutions(items=[], generated_by="heuristic", message="No tickets evaluated yet.")

    try:
        raw_items = synthesize_solutions_with_llm(tickets, results)
        if not raw_items:
            raise ValueError("LLM returned no items")
        items = [
            {
                "title": str(it.get("title", "")).strip() or "Untitled recommendation",
                "category": str(it.get("category", "Other")).strip() or "Other",
                "recommendation": str(it.get("recommendation", "")).strip(),
                "affected_tickets": [str(x) for x in it.get("affected_tickets", []) if x],
                "priority": it.get("priority") if it.get("priority") in ("High", "Medium", "Low") else "Medium",
                "rationale": str(it.get("rationale", "")).strip(),
            }
            for it in raw_items
        ]
        generated_by = "llm"
    except Exception as exc:  # pragma: no cover
        print(f"[solutions] LLM synthesis failed, using heuristics: {exc}")
        items = build_heuristic_solutions(tickets, results)
        generated_by = "heuristic"

    message = (
        f"{len(items)} recommendation(s) synthesized from {len(results)} evaluated ticket(s)."
        if items
        else "No notable patterns found across evaluated tickets."
    )

    return ProjectSolutions(
        items=[
            {
                "title": it["title"],
                "category": it["category"],
                "recommendation": it["recommendation"],
                "affected_tickets": it["affected_tickets"],
                "priority": it["priority"],
                "rationale": it["rationale"],
            }
            for it in items
        ],
        generated_by=generated_by,
        message=message,
    )
