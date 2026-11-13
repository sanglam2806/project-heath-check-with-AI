"""
Layer 4: agentic deep-dive for tickets that Layers 1-3 (git_scan.py +
evaluator.evaluate_with_llm) leave as low-confidence or "Incomplete".
Unlike Layer 2 (one-shot LLM call over pre-selected snippets), this gives
the LLM real tool-calling access (code_tools.py) to a locally cloned repo
(git_workspace.py) -- it can list/search/read files and follow up on its
own hypotheses instead of only judging whatever was pre-filtered for it.

Opt-in and additive: only invoked from /api/git-jira-scan when the request
asks for it, and only for tickets Layer 2/3 already flagged as uncertain.
Never replaces Layers 1-3 for the common case. If the agent fails or runs
out of budget, the prior (Layer 2/3) result is kept unchanged -- Layer 4
can only improve a result, never crash the scan.
"""
import json
import os
from typing import Dict, List, Tuple

from openai import OpenAI

import code_tools
import db
import git_files_db
import model_config
from models import TicketResult

_MAX_TOKENS = int(os.getenv("EVAL_MAX_TOKENS", "4096"))
# Tool-call rounds and total tool-output budget are capped -- this is the
# most expensive path in the whole pipeline (multiple LLM round-trips per
# ticket instead of one), so it must have a hard ceiling on both cost and
# wall-clock time.
_MAX_ROUNDS = int(os.getenv("DEEP_DIVE_MAX_ROUNDS", "6"))
_MAX_TOOL_OUTPUT_CHARS = 3000
_MAX_TOTAL_TOOL_CHARS = int(os.getenv("DEEP_DIVE_MAX_TOTAL_TOOL_CHARS", "20000"))

DEEP_DIVE_SYSTEM_PROMPT = """You are a senior software auditor with direct read access to a cloned \
Git repository via tools. Your job is to determine, with real evidence, whether a specific ticket's \
described functionality is actually implemented in the code -- this ticket was flagged by a faster \
first-pass model as low-confidence or "Incomplete", so take your time and actually investigate \
instead of judging only the snippet you were handed.

You have these tools:
- list_files(pattern): list source files in the repo, optionally filtered by a substring of the path.
- search_code(query, regex): search file contents for a literal string or (if regex=true) a regex.
- read_file(path, start_line, end_line): read a file, optionally a specific line range.
- find_definition(symbol): heuristic search for where a function/class/variable is defined.
- find_references(symbol): heuristic search for where a symbol is used/called elsewhere in the code.
- list_docs(pattern): list documentation files (README/specs/slide decks) anywhere in the repo, not \
just the excerpts already given to you below.
- search_docs(query): search documentation text (Markdown/HTML/PPTX, tags/slides already extracted \
to plain text) for a literal string, returning a surrounding snippet per match.
- read_doc(path): read the full extracted text of one documentation file.

The documentation excerpts given to you below are only the top few matches from a simple keyword-\
overlap ranking against the ticket text -- it can miss the actually-relevant doc (different wording, \
a doc that covers this feature as part of a broader topic, etc). Use list_docs/search_docs/read_doc \
whenever those excerpts seem insufficient, contradictory, or absent, instead of concluding \
"No Doc Found" just because the pre-selected excerpts didn't cover it.

Strategy: start from the ticket's summary/description and any related documentation excerpts given \
below, form a hypothesis about what file(s)/symbol(s) should exist, then use the tools to verify it \
-- e.g. search for a plausible function/endpoint/route name, read the file it's defined in, check \
who references it; if the doc side is unclear, search the docs directly rather than relying only on \
the pre-selected excerpts. Be skeptical: a similarly-named file or a TODO comment is not evidence of \
a working feature. Call tools as many times as you need (a reasonable number, not excessive), then \
call submit_result exactly once with your final, evidence-based verdict -- never guess without \
having looked at real code/docs first.

Assessment values: "Match" (feature is genuinely implemented per the acceptance criteria), \
"Mismatch" (reported Done but code is missing/wrong), "Incomplete" (partially implemented). \
doc_ticket_match: "Match" / "Doc Outdated" / "No Doc Found". doc_code_match: "Match" / "Mismatch" \
/ "Doc Drift" / "N/A". missing_parts must be concrete (cite the file/symbol you expected and didn't \
find). notes must summarize what you actually checked (files opened, symbols searched) and why you \
reached this verdict.

Language rule: ALWAYS write "notes", "missing_parts", "suggestions", and "doc_notes" in English, \
regardless of what language the ticket, source code, or documentation are written in. Never \
mirror the input's language.
"""

_TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "list_files",
            "description": (
                "List source files in the cloned repository (documentation and noise "
                "directories like node_modules/.git/docs are excluded), optionally filtered "
                "by a substring of the relative path."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "pattern": {
                        "type": "string",
                        "description": "Case-insensitive substring to filter file paths by. Leave empty to list all (capped).",
                    }
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "search_code",
            "description": "Search file contents across the repository for a literal string or regex pattern. Returns matching {path, line, text}.",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Text or regex pattern to search for."},
                    "regex": {
                        "type": "boolean",
                        "description": "True to treat `query` as a regex pattern instead of a literal string.",
                    },
                },
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "read_file",
            "description": "Read the contents of one file from the repository, optionally restricted to a 1-indexed inclusive line range.",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": "File path relative to the repository root, as returned by list_files/search_code.",
                    },
                    "start_line": {"type": "integer", "description": "1-indexed start line (optional)."},
                    "end_line": {"type": "integer", "description": "1-indexed end line, inclusive (optional)."},
                },
                "required": ["path"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "find_definition",
            "description": "Heuristic search for where a function, class, or variable is defined (pattern-based, not a true AST/call graph).",
            "parameters": {
                "type": "object",
                "properties": {
                    "symbol": {"type": "string", "description": "The exact function/class/variable name to look for."}
                },
                "required": ["symbol"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "find_references",
            "description": "Heuristic search for where a symbol name is used/called elsewhere in the code (a plain-text usage search, not scope-aware).",
            "parameters": {
                "type": "object",
                "properties": {
                    "symbol": {"type": "string", "description": "The exact function/class/variable name to look for usages of."}
                },
                "required": ["symbol"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "list_docs",
            "description": (
                "List documentation files (README/specs/slide decks -- .md/.mdx/.txt/.rst/.adoc/"
                ".html/.htm/.pptx) anywhere in the repository, not confined to a docs/ folder. "
                "Optionally filtered by a substring of the path."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "pattern": {
                        "type": "string",
                        "description": "Case-insensitive substring to filter doc file paths by. Leave empty to list all (capped).",
                    }
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "search_docs",
            "description": (
                "Search documentation text for a literal string (HTML tags and PPTX slide/notes "
                "text are already extracted to plain text before searching). Returns {path, snippet} "
                "around each match -- use this instead of assuming the pre-selected doc excerpts "
                "already covered everything relevant."
            ),
            "parameters": {
                "type": "object",
                "properties": {"query": {"type": "string", "description": "Literal text to search for."}},
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "read_doc",
            "description": "Read the full extracted text of one documentation file (Markdown as-is, HTML tag-stripped, PPTX slide/notes text).",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": "Doc file path relative to the repository root, as returned by list_docs/search_docs.",
                    }
                },
                "required": ["path"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "submit_result",
            "description": "Submit your final, evidence-based verdict for this ticket. Call this exactly once, after investigating with the other tools -- this ends the review.",
            "parameters": {
                "type": "object",
                "properties": {
                    "assessment": {"type": "string", "enum": ["Match", "Mismatch", "Incomplete"]},
                    "completion_percent": {"type": "number", "description": "0-100"},
                    "confidence": {"type": "number", "description": "0.0-1.0"},
                    "missing_parts": {"type": "array", "items": {"type": "string"}},
                    "suggestions": {"type": "array", "items": {"type": "string"}},
                    "notes": {
                        "type": "string",
                        "description": "Summarize what you checked (files/symbols) and why you reached this verdict.",
                    },
                    "doc_ticket_match": {"type": "string", "enum": ["Match", "Doc Outdated", "No Doc Found"]},
                    "doc_code_match": {"type": "string", "enum": ["Match", "Mismatch", "Doc Drift", "N/A"]},
                    "doc_notes": {"type": "string"},
                },
                "required": ["assessment", "completion_percent", "confidence", "missing_parts", "notes"],
            },
        },
    },
]

_TOOL_FUNCS = {
    "list_files": lambda repo_path, args: code_tools.list_files(repo_path, args.get("pattern", "") or ""),
    "search_code": lambda repo_path, args: code_tools.search_code(
        repo_path, args.get("query", "") or "", bool(args.get("regex", False))
    ),
    "read_file": lambda repo_path, args: code_tools.read_file(
        repo_path, args.get("path", "") or "", args.get("start_line"), args.get("end_line")
    ),
    "find_definition": lambda repo_path, args: code_tools.find_definition(repo_path, args.get("symbol", "") or ""),
    "find_references": lambda repo_path, args: code_tools.find_references(repo_path, args.get("symbol", "") or ""),
    "list_docs": lambda repo_path, args: code_tools.list_docs(repo_path, args.get("pattern", "") or ""),
    "search_docs": lambda repo_path, args: code_tools.search_docs(repo_path, args.get("query", "") or ""),
    "read_doc": lambda repo_path, args: code_tools.read_doc(repo_path, args.get("path", "") or ""),
}


def _record_file_read(path: str, file_type: str = "Source Code") -> None:
    """Best-effort audit-trail write, mirroring git_scan.py's
    _record_git_file -- never raises, silently skipped without a DB."""
    if not db.is_configured():
        return
    try:
        git_files_db.record_file(path.rsplit("/", 1)[-1], path, file_type)
    except Exception:
        pass


def _safe_list(value) -> List[str]:
    if isinstance(value, list):
        return [str(x) for x in value]
    if isinstance(value, str) and value.strip():
        return [value.strip()]
    return []


def _safe_float(value, lo: float, hi: float, default: float) -> float:
    try:
        v = float(value)
        return max(lo, min(hi, v))
    except (TypeError, ValueError):
        return default


def _apply_deep_dive_result(prior_result: TicketResult, item: Dict) -> TicketResult:
    """Merge the agent's submit_result payload onto the prior (Layer 2/3)
    result -- same TicketResult schema, only the fields the agent actually
    investigated are overridden; anything it left out/gave an invalid
    value for falls back to what was already there."""
    assessment = str(item.get("assessment", "")).strip()
    if assessment not in {"Match", "Mismatch", "Incomplete"}:
        assessment = prior_result.assessment

    doc_ticket_match = str(item.get("doc_ticket_match", "")).strip()
    if doc_ticket_match not in {"Match", "Doc Outdated", "No Doc Found"}:
        doc_ticket_match = prior_result.doc_ticket_match

    doc_code_match = str(item.get("doc_code_match", "")).strip()
    if doc_code_match not in {"Match", "Mismatch", "Doc Drift", "N/A"}:
        doc_code_match = prior_result.doc_code_match

    notes = str(item.get("notes", "") or "").strip()
    combined_notes = f"Layer 4 (agent deep-dive): {notes}" if notes else prior_result.notes

    missing_parts = _safe_list(item.get("missing_parts"))
    suggestions = _safe_list(item.get("suggestions"))

    return prior_result.model_copy(update={
        "assessment": assessment,
        "completion_percent": _safe_float(
            item.get("completion_percent"), 0.0, 100.0, prior_result.completion_percent
        ),
        "confidence": _safe_float(item.get("confidence"), 0.0, 1.0, prior_result.confidence),
        "missing_parts": missing_parts or prior_result.missing_parts,
        "suggestions": suggestions or prior_result.suggestions,
        "notes": combined_notes,
        "doc_ticket_match": doc_ticket_match,
        "doc_code_match": doc_code_match,
        "doc_notes": str(item.get("doc_notes", "") or prior_result.doc_notes),
    })


def run_deep_dive(
    ticket: Dict,
    prior_result: TicketResult,
    repo_path: str,
    docs: List[Tuple[str, str]],
) -> TicketResult:
    """Run the tool-calling loop for one ticket against the locally cloned
    repo at `repo_path`. Returns an updated copy of `prior_result` if the
    agent successfully calls submit_result within budget, otherwise returns
    `prior_result` unchanged."""
    # Resolved fresh on every call (DB-saved Model Configuration wins,
    # falling back to server/.env) -- see model_config.py.
    settings = model_config.get_llm_settings()
    client = OpenAI(api_key=settings["api_key_deep"], base_url=settings["base_url_deep"])

    # `docs` is already capped at scanner.select_relevant_docs' top_n (6) --
    # no further slicing here, so the agent's starting context matches what
    # Layer 2 saw, before it goes on to search the full doc set itself.
    doc_context = "\n\n".join(f"[{path}]\n{text[:1500]}" for path, text in docs)
    if not doc_context:
        doc_context = "(no related documentation found)"

    user_prompt = (
        f"Ticket {ticket.get('ticket_id', '')} — {ticket.get('summary', '')}\n"
        f"Reported status: {ticket.get('status', '')}\n"
        f"Description: {ticket.get('description', '')[:1500]}\n\n"
        f"Related documentation excerpts:\n{doc_context}\n\n"
        f"The prior automated pass rated this: assessment={prior_result.assessment}, "
        f"confidence={prior_result.confidence}, notes={prior_result.notes[:500]!r}. "
        "Investigate the actual repository and confirm or correct this."
    )

    messages: List[Dict] = [
        {"role": "system", "content": DEEP_DIVE_SYSTEM_PROMPT},
        {"role": "user", "content": user_prompt},
    ]

    files_read: List[str] = []
    docs_read: List[str] = []
    total_chars = 0
    ticket_id = ticket.get("ticket_id", "?")

    for _ in range(_MAX_ROUNDS):
        try:
            response = client.chat.completions.create(
                model=settings["model_deep"],
                messages=messages,
                tools=_TOOLS,
                tool_choice="auto",
                temperature=0.2,
                max_tokens=_MAX_TOKENS,
            )
        except Exception as exc:
            print(f"[deep_dive_agent] LLM call failed for {ticket_id}, keeping prior result: {exc}")
            return prior_result

        msg = response.choices[0].message
        tool_calls = msg.tool_calls or []
        if not tool_calls:
            break

        messages.append({
            "role": "assistant",
            "content": msg.content or "",
            "tool_calls": [
                {
                    "id": tc.id,
                    "type": "function",
                    "function": {"name": tc.function.name, "arguments": tc.function.arguments},
                }
                for tc in tool_calls
            ],
        })

        submitted = None
        for tc in tool_calls:
            name = tc.function.name
            try:
                args = json.loads(tc.function.arguments or "{}")
            except json.JSONDecodeError:
                args = {}

            if name == "submit_result":
                submitted = args
                output_text = "Result recorded."
            elif name in _TOOL_FUNCS:
                try:
                    output = _TOOL_FUNCS[name](repo_path, args)
                except Exception as exc:
                    output = f"(tool error: {exc})"
                if name == "read_file" and isinstance(args.get("path"), str) and args["path"]:
                    files_read.append(args["path"])
                elif name == "read_doc" and isinstance(args.get("path"), str) and args["path"]:
                    docs_read.append(args["path"])
                output_text = output if isinstance(output, str) else json.dumps(output)
                output_text = output_text[:_MAX_TOOL_OUTPUT_CHARS]
            else:
                output_text = f"(unknown tool: {name})"

            total_chars += len(output_text)
            messages.append({"role": "tool", "tool_call_id": tc.id, "content": output_text})

        if submitted is not None:
            for path in dict.fromkeys(files_read):
                _record_file_read(path, "Source Code")
            for path in dict.fromkeys(docs_read):
                _record_file_read(path, "Doc")
            return _apply_deep_dive_result(prior_result, submitted)

        if total_chars >= _MAX_TOTAL_TOOL_CHARS:
            break

    print(f"[deep_dive_agent] Deep-dive for {ticket_id} ended without submit_result, keeping prior result.")
    return prior_result
