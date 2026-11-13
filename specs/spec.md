# Project Health Checker — Specification

| | |
|---|---|
| **Version** | 2.0 |
| **Status** | Implemented (describes current behavior) |
| **Related** | [Architecture](../document/architecture.md) |

---

## 1. Problem

Ticket status in JIRA or Excel often doesn't match reality. A ticket marked *Done* may have no code behind it, and a project that looks green on the board may be late. PMs find out too late, usually at delivery.

## 2. Goal

Automatically verify ticket status against the real source code, then show each project's health, risk and schedule so PMs can act early.

### Success criteria
- Every ticket gets a verdict (`Match`, `Incomplete`, `Mismatch` or `Skipped`) with a completion %, confidence and evidence.
- A PM can see a project's health status and its top risks without reading code.
- Re-running a scan on an unchanged project costs (almost) no LLM calls.

### Non-goals
- Not a replacement for code review or QA testing.
- Does not modify tickets in JIRA or code in Git (read-only).
- Does not judge code quality, only whether the ticket's work exists.

---

## 3. Users & roles

| Role | Can do |
|---|---|
| **Owner** | Everything, including member, model and performance management |
| **Admin** | Same as Owner |
| **Editor** | Run scans (Check Health), view all results |
| **Viewer** | View dashboards, projects, risk and solutions |

---

## 4. Functional requirements

### 4.1 Accounts & team
| ID | Requirement |
|---|---|
| FR-01 | Users can register, log in and stay logged in with a token. |
| FR-02 | Owner/Admin can invite members by email and change their role. |
| FR-03 | If email sending is not configured, the invite link is shown to copy manually. |
| FR-04 | Owner/Admin can create groups and invite a whole group. |
| FR-05 | Invited users accept via a link and set their password. |

### 4.2 Projects
| ID | Requirement |
|---|---|
| FR-10 | Users can create projects and assign members. |
| FR-11 | A project stores its Git connection and ticket source (JIRA, Excel or manual). |
| FR-12 | Each saved scan becomes a snapshot; the project shows its latest snapshot and history. |

### 4.3 Ticket & code input
| ID | Requirement |
|---|---|
| FR-20 | **Upload flow**: user uploads a source code ZIP and imports tickets from Excel (`.xlsx`, `.xlsm`). |
| FR-21 | Excel columns are auto-detected (Key, Summary, Status, Description, plus Assignee and Due Date when present); the user can preview and map columns manually. |
| FR-22 | Tickets can also be pasted as tab-separated text. |
| FR-23 | **Connect flow**: user connects to JIRA (site URL, project key, email + API token) and a Git repo (URL, branch, token). The system verifies both before scanning. |
| FR-24 | GitHub and GitLab are supported and detected from the repo URL. |
| FR-25 | The user can limit the scan to a source path and a docs path inside the repo. |

### 4.4 Evaluation
| ID | Requirement |
|---|---|
| FR-30 | For each ticket, collect evidence: files mentioning the ticket ID or keywords, and for Git also branches, commits and PR/MR titles. |
| FR-31 | Related documentation (Markdown, HTML, PPTX) and mockup images are matched per ticket and used as extra evidence. |
| FR-32 | Cancelled tickets are not evaluated and get `Skipped`. |
| FR-33 | Obvious cases are decided by rules without an LLM (e.g. *Done* with no code → `Mismatch`). |
| FR-34 | Remaining tickets are evaluated by a fast triage model; ambiguous tickets are escalated to a deep model. |
| FR-35 | If the LLM is unavailable or returns invalid output, a heuristic evaluation is used instead. The scan never fails because of the LLM. |
| FR-36 | Evidence files are checked to exist on the scanned branch. |
| FR-37 | Optionally, a deep-dive agent explores the cloned repo for `Incomplete` or low-confidence tickets. It may only improve a result. |
| FR-38 | When re-running an existing project, a ticket is reused from the last scan only if it was `Match` and its status, content and the repo commit are unchanged. |
| FR-39 | A single ticket can be re-evaluated on demand. |
| FR-40 | The UI shows live progress ("X / Y tickets") during a scan. |

**Per-ticket result** contains: assessment, completion % (0–100), confidence (0–1), evidence files, missing parts, suggestions, notes, schedule status and days vs. due date, assignee, doc ↔ ticket and doc ↔ code match, UI mockup match, and whether it was escalated or reused from cache.

### 4.5 Analysis & reporting
| ID | Requirement |
|---|---|
| FR-50 | **Summary**: total tickets and counts per assessment, average completion. |
| FR-51 | **Schedule**: `Late` (past due, not finished), `At-Risk` (not due yet, < 50 % done), `On-time`, or no due date. |
| FR-52 | **Health**: `Late` if any Mismatch or Late ticket, `Risk` if any At-Risk ticket, else `OK`; plus the flagged issues and next milestone. |
| FR-53 | **Risk**: a 0–100 score and severity (Critical / High / Medium / Low) per ticket with reasons and a recommended action. |
| FR-54 | **Trend**: days ahead/behind schedule per ticket and an overall delay estimate from overdue tickets. |
| FR-55 | **Solutions**: project-wide recommendations generated once per scan (LLM, with heuristic fallback). |
| FR-56 | **Member performance**: per-assignee totals (complete, in progress, late) across all projects. |
| FR-57 | **Excel report**: a Summary sheet and a Tickets sheet including the recommended action for each ticket. |
| FR-58 | `Skipped` tickets are excluded from all statistics. |

### 4.6 Configuration
| ID | Requirement |
|---|---|
| FR-60 | Owner/Admin can set the triage and deep model (API URL, model name, key) from the UI and test the connection. |
| FR-61 | Saved settings take effect on the next scan without restarting the server; unset fields fall back to server defaults. |
| FR-62 | The UI is available in English, Japanese and Vietnamese. |

---

## 5. Non-functional requirements

| ID | Requirement |
|---|---|
| NFR-01 | **Works without optional services**: runs without a database (in-memory), without an LLM (heuristics), without `git` installed (REST API) and without SMTP. |
| NFR-02 | **Security**: passwords are hashed (PBKDF2-HMAC-SHA256); API keys are never shown in full after saving; secrets are never committed to the repository. |
| NFR-03 | **Read-only on sources**: never writes to JIRA or Git. |
| NFR-04 | **Cost control**: LLM calls are batched, run with limited concurrency, escalated only when needed, and skipped via the re-eval cache. |
| NFR-05 | **Resilience**: failure of any optional step (deep review, Layer 4, file tracking, DB logging) must not fail the scan. |
| NFR-06 | **Cleanup**: temporary Git clones are removed after the scan. |

---

## 6. Acceptance scenarios

| # | Given | When | Then |
|---|---|---|---|
| AC-1 | Ticket `PROJ-1` is *Done* and no code mentions it | Scan runs | Result is `Mismatch`; project health is `Late` |
| AC-2 | Ticket is *In Progress*, partial code exists, not overdue | Scan runs | Result is `Incomplete`; it is not flagged as an issue |
| AC-3 | Ticket is *Cancelled* | Scan runs | Result is `Skipped` and not counted in stats |
| AC-4 | LLM endpoint is down | Scan runs | Scan completes using heuristic results |
| AC-5 | Previous result `Match`, nothing changed | Project is re-run | Ticket is marked as reused from cache; no LLM call for it |
| AC-6 | Repo has a new commit since last scan | Project is re-run | All tickets are evaluated again |
| AC-7 | User is a Viewer | Opens Check Health or Model Config | Access is denied / route hidden |
| AC-8 | Scan finished | User exports report | An `.xlsx` with Summary and Tickets sheets is downloaded |

---

## 7. Future ideas

- Real code index (tree-sitter / ctags) for the deep-dive agent instead of regex search.
- Scheduled automatic scans and alerts when health changes.
- More ticket sources (Linear, GitHub Issues, Azure DevOps).
- Read acceptance criteria from JIRA to sharpen the LLM's judgment.
