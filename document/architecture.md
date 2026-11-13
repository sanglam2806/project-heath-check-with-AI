# Architecture

This document describes how Project Health Checker is built: the main components, how a scan flows through the system, and where data is stored.

For *what* the system must do, see [`specs/spec.md`](../specs/spec.md).

---

## 1. System overview

```
┌──────────────────────────┐        HTTP (JSON)         ┌───────────────────────────────┐
│  client/  (React + Vite) │  ───── /api, /health ────▶ │  server/  (FastAPI, Python)   │
│  Dashboard, pages, i18n  │ ◀───────────────────────── │  Scan & evaluation pipeline   │
└──────────────────────────┘                            └──────┬──────────┬─────────┬───┘
                                                               │          │         │
                                         ┌─────────────────────┘          │         └────────────────┐
                                         ▼                                ▼                          ▼
                              ┌────────────────────┐        ┌───────────────────────┐   ┌────────────────────────┐
                              │ LLM (OpenAI-compat │        │ External sources      │   │ PostgreSQL (optional)  │
                              │ API or Ollama)     │        │ JIRA REST API v2      │   │ projects, scan runs,   │
                              │ triage + deep model│        │ GitHub / GitLab API   │   │ results, users, config │
                              └────────────────────┘        │ git clone (local)     │   └────────────────────────┘
                                                            └───────────────────────┘
```

| Component | Responsibility |
|---|---|
| **client** | Single-page app (hash routing). Collects inputs, shows progress, renders results, dashboards and admin pages. |
| **server** | REST API. Ingests tickets and code, runs the evaluation pipeline, computes roll-ups, persists results, handles auth. |
| **LLM** | Judges each ticket against code/doc evidence. Two configurable models: a fast *triage* model and a *deep* model. |
| **External sources** | JIRA (tickets), GitHub/GitLab (branches, commits, PR/MR, file tree, file contents). |
| **PostgreSQL** | Optional. Without it, the app runs on in-memory data (no history, no users/projects persistence). |

---

## 2. Client (`client/`)

- **Stack**: React 18, Vite, TailwindCSS, i18next (en / ja / vi), lucide-react icons.
- **Routing**: hash-based routes defined in `src/router.js`; some routes are restricted by role (`src/utils/permissions.js`).
- **State**: React contexts — `AuthContext` (logged-in user, JWT), `EvaluationContext` (current scan result), `ReEvalJobContext` (background re-evaluation job).
- **API access**: all calls go through `src/api.js`. In development, Vite proxies `/api` and `/health` to `http://localhost:8001`.

| Route | Page | Roles |
|---|---|---|
| `#/check-health/connect` | Connect JIRA + Git and scan | Owner, Admin, Editor |
| `#/check-health/upload` | Upload ZIP + Excel and scan | Owner, Admin, Editor |
| `#/dashboard` | Portfolio overview | all |
| `#/projects` | Project list / detail | all |
| `#/risk` | Risk ranking | all |
| `#/solutions` | Project-wide recommendations | all |
| `#/members` | Member & group management, invites | Owner, Admin |
| `#/member-performance` | Cross-project assignee stats | Owner, Admin |
| `#/model-config` | LLM connection settings | Owner, Admin |

---

## 3. Server (`server/`)

All endpoints live in `main.py`. Logic is split into focused modules:

| Area | Modules |
|---|---|
| **API & models** | `main.py`, `models.py` (Pydantic), `i18n.py` (translated error messages) |
| **Ticket input** | `excel_parser.py` (Excel → tickets, column mapping), `jira_client.py` (JIRA REST v2) |
| **Code input** | ZIP upload (in `main.py`), `git_client.py` (reachability check), `git_scan.py` (GitHub/GitLab evidence), `git_workspace.py` (local shallow clone) |
| **Evidence** | `scanner.py` (find ticket references, build per-ticket context), `doc_extract.py` (Markdown / HTML / PPTX text) |
| **Evaluation** | `evaluator.py` (LLM triage + deep review, heuristic fallback), `deep_dive_agent.py` + `code_tools.py` (Layer 4 agent), `reeval_cache.py`, `ticket_status.py` |
| **Roll-ups** | `health.py`, `trend.py`, `risk.py`, `solutions.py`, `member_performance.py`, `report.py` (Excel export) |
| **Persistence** | `db.py` (connection pool), `schema.sql`, `projects.py`, `scan_runs.py`, `uploads_db.py`, `git_files_db.py`, `solutions_db.py`, `model_config.py` |
| **Users & teams** | `auth.py` (PBKDF2 passwords, JWT), `members.py`, `groups.py`, `mailer.py` (SMTP invites) |
| **Progress** | `scan_progress.py` (in-memory job progress, polled by the client) |
| **Tooling** | `init_db.py`, `seed_db.py`, `check_*.py` diagnostics |

---

## 4. Evaluation pipeline

Both input flows feed the same pipeline:

```
 ┌──────────── INPUT ────────────┐
 │ A. Upload        B. Connect   │
 │ Excel + ZIP      JIRA + Git   │
 └──────────────┬────────────────┘
                ▼
  1. Get tickets  →  2. Collect code / doc / image evidence
                ▼
  3. Layer 1: rule-based shortcut   (e.g. Done + no code → Mismatch)
                ▼
  4. Re-eval cache                  (skip unchanged Match tickets)
                ▼
  5. Layer 2: LLM triage → deep review for escalated tickets
                │          ↘ heuristic fallback if the LLM fails
                ▼
  6. Layer 3: check changed files exist on the branch
                ▼
  7. Layer 4 (optional): deep-dive agent on Incomplete / low-confidence
                ▼
  8. Roll-ups: Summary · Health · Trend · Risk · Solutions
                ▼
  9. Save scan run (DB)  →  Dashboard / Excel report
```

### Layer details

| Step | Where | What happens |
|---|---|---|
| **Evidence** | `scanner.py`, `git_scan.py` | Find files that mention the ticket ID or its keywords; for Git, also branches, commit messages and PR/MR titles. Docs (MD/HTML/PPTX) and images are ranked per ticket. File contents come from a local `git clone` when possible, falling back to the REST API per file. |
| **Layer 1** | `git_scan.py` | Rule-based, no LLM. Cancelled tickets → `Skipped`. |
| **Re-eval cache** | `reeval_cache.py` | On a re-run of an existing project, a ticket is reused only if its last result was `Match` **and** its status, content hash and the repo commit SHA are all unchanged. |
| **Layer 2** | `evaluator.py` | *Phase 1 (triage)*: fast model evaluates every ticket in batches and may set `needs_deep_review`. *Phase 2 (deep)*: deep model re-evaluates only flagged tickets, with mockup images when relevant. If both fail → heuristic based on matched files. |
| **Layer 3** | `git_scan.py` | Verifies files referenced as evidence actually exist in the branch tree. |
| **Layer 4** | `deep_dive_agent.py` | Opt-in. A tool-calling agent can list, grep and read the cloned repo to resolve uncertain tickets. It can only improve a result; on failure the previous result is kept. |

### Two LLM models

`model_config.py` resolves settings on every scan: a value saved from the Model Configuration page wins, otherwise the server's environment defaults are used. No restart is needed after a change.

| Model | Used by |
|---|---|
| Triage (Phase 1) | Layer 2 triage, solution synthesis |
| Deep (Phase 2) | Layer 2 deep review, Layer 4 agent (requires tool-calling support) |

---

## 5. Roll-up rules

| Output | Module | Rule (summary) |
|---|---|---|
| **Schedule** | `evaluator.py` | `Late` = past due and < 100 % done; `At-Risk` = not yet due and < 50 % done; else `On-time`. |
| **Health** | `health.py` | Worst ticket wins: any Mismatch or Late → `Late`; any At-Risk → `Risk`; else `OK`. |
| **Risk score** | `risk.py` | 0–100 per ticket: Mismatch +40 / Incomplete +15, Late +35 / At-Risk +20, "Done but low completion" gap up to +30, low-confidence penalty. Severity: Critical ≥ 70, High ≥ 45, Medium ≥ 20, else Low. |
| **Trend** | `trend.py` | Days ahead/behind due date per ticket; headline estimate only from tickets already overdue. |
| **Solutions** | `solutions.py` | One aggregate LLM call over all results (heuristic keyword grouping as fallback); cached per scan run. |

`Skipped` tickets are excluded from all roll-ups.

---

## 6. Data model (PostgreSQL)

Defined in `server/schema.sql`, created by `python init_db.py`.

```
users ──< group_members >── groups
  │
  └──< project_members >── projects ──< project_git_connections
                              │    └──< project_ticket_connections (jira | excel | manual)
                              │
                              └──< scan_runs ──< evaluation_results >── tickets
                                      │    └──< risk_scores
                                      │    └──< solutions ──< solution_affected_tickets
                                      └── project_solutions (cache)

uploads, git_read_files, model_config (single row)
```

| Table | Purpose |
|---|---|
| `users` | Accounts, role (`Owner` / `Admin` / `Editor` / `Viewer`), invite token, password hash |
| `projects`, `project_*` | Projects, their Git/ticket sources and members |
| `scan_runs` | One row per saved scan (type, scope, status, health, totals, commit SHA) |
| `tickets`, `evaluation_results` | Ticket snapshot and per-ticket result for each run |
| `risk_scores`, `solutions`, `project_solutions` | Derived analyses |
| `uploads`, `git_read_files` | Audit of uploaded ZIPs and files read from Git |
| `model_config` | Saved LLM settings (overrides environment defaults) |

---

## 7. Cross-cutting concerns

- **Authentication**: PBKDF2-HMAC-SHA256 password hashes, JWT bearer tokens. Without a fixed signing secret, a random one is generated per server start (sessions reset on restart).
- **Authorization**: role checks on the server per endpoint; the client hides routes the role cannot use.
- **Graceful degradation**: no DB → in-memory mode; no LLM → heuristic evaluation; no `git` binary → REST API file fetch; no SMTP → invite link returned to copy manually.
- **Progress**: long scans are single blocking requests; the client polls `GET /api/scan-progress/{job_id}` for "X / Y tickets".
- **i18n**: UI text in `client/src/i18n/locales/*.json`; server error messages in `server/i18n.py`. LLM output is in English.
- **Temporary files**: ZIP uploads in `server/uploads/`, Git clones in `server/clones/` (removed after the scan). Both are git-ignored.
