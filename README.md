# Project Health Checker

Compare what your **tickets say is done** with what your **source code actually contains**.

Project Health Checker reads tickets (from JIRA or an Excel export), collects evidence from the codebase (a ZIP upload or a Git repository), and uses an LLM to judge each ticket:

| Result | Meaning |
|---|---|
| ✅ **Match** | The ticket's status agrees with the code |
| ⚠️ **Incomplete** | Work is started but parts are missing |
| ❌ **Mismatch** | The ticket is marked done, but the code isn't there |

On top of per-ticket results it builds project-level views: health score, trend over time, risk, suggested solutions, and per-member performance. Results can be exported to Excel.

---

## Features

- **Two input flows**
  - *Upload*: Excel tickets (`.xlsx` / `.xlsm`, with column mapping) + source code ZIP
  - *Connect*: JIRA API + Git repository (GitHub / GitLab)
- **Layered evaluation pipeline**
  1. Rule-based shortcut (e.g. ticket *Done* + no code → Mismatch)
  2. Re-evaluation cache (unchanged tickets are skipped)
  3. LLM triage → deep LLM review for escalated tickets (heuristic fallback if the LLM fails)
  4. Branch check that changed files really exist
  5. Optional deep-dive agent (tool-calling) for incomplete / low-confidence tickets
- **Dashboard**: projects, scan history, trend charts, risk & solutions pages
- **Team features**: login/register, roles, groups, invite links, project members
- **Model configuration page** to switch LLM provider/model from the UI
- **Multi-language UI**: English, 日本語, Tiếng Việt
- **Excel report export**

---

## Tech stack

| Part | Stack |
|---|---|
| Backend | Python 3.10+, FastAPI, Pydantic, OpenAI-compatible client (works with Ollama or any OpenAI-style API), pandas / openpyxl |
| Database | PostgreSQL (optional — runs on in-memory data without it) |
| Frontend | React 18, Vite, TailwindCSS, i18next, lucide-react |

---

## Documentation

- [Architecture](document/architecture.md) — components, evaluation pipeline, data model
- [Specification](specs/spec.md) — requirements, roles, acceptance scenarios

---

## Project structure

```
.
├── document/
│   └── architecture.md
├── specs/
│   └── spec.md
├── server/
│   ├── main.py                # FastAPI app & all API endpoints
│   ├── models.py              # Pydantic models
│   ├── scanner.py             # Find ticket references in source code
│   ├── evaluator.py           # LLM evaluation (triage + deep review)
│   ├── deep_dive_agent.py     # Layer 4 tool-calling agent
│   ├── excel_parser.py        # Read tickets from Excel
│   ├── jira_client.py         # JIRA integration
│   ├── git_client.py, git_scan.py, git_workspace.py   # Git integration
│   ├── health.py, trend.py, risk.py, solutions.py     # Project roll-ups
│   ├── report.py              # Excel report export
│   ├── auth.py, members.py, groups.py, mailer.py      # Users & teams
│   ├── db.py, schema.sql, init_db.py, seed_db.py      # PostgreSQL (optional)
│   ├── check_*.py             # Standalone diagnostic scripts
│   ├── .env.example
│   └── requirements.txt
└── client/
    ├── src/
    │   ├── pages/             # Dashboard, projects, risk, solutions, settings…
    │   ├── components/        # Tables, charts, modals, panels
    │   ├── context/           # Auth / evaluation state
    │   ├── i18n/              # en / ja / vi translations
    │   └── api.js             # API client
    ├── package.json
    └── vite.config.js         # Dev server + proxy to backend
```

---

## Getting started

### Requirements

- Python 3.10+
- Node.js 18+
- An LLM endpoint — e.g. [Ollama](https://ollama.com/) running locally, or any OpenAI-compatible API
- Git (only for the Git-connect flow)
- PostgreSQL (optional)

### 1. Backend

```bash
cd server
python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env             # then edit values as needed
uvicorn main:app --reload --port 8001
```

All configuration options are documented in [`server/.env.example`](server/.env.example).
If you use PostgreSQL, run `python init_db.py` once from `server/` to create the tables.

### 2. Frontend

```bash
cd client
npm install
npm run dev
```

Open **http://localhost:5173**. The Vite dev server proxies `/api` and `/health` to the backend on port `8001`.

---

## How to use

1. Register / log in, then create a project.
2. Choose an input flow:
   - **Upload** — upload the source code ZIP and import tickets from Excel (map the columns such as *Issue Key*, *Summary*, *Status*, *Description*).
   - **Connect** — connect to JIRA and a Git repository/branch.
3. Run **Scan & Evaluate** and watch the progress bar.
4. Review results:
   - Summary cards (total, match / mismatch / incomplete, average completion)
   - Ticket table — click a ticket for evidence files, missing parts and suggestions
   - Project health, trend history, risk and solutions pages
5. Export the report to Excel.

---

## Main API endpoints

| Method | Path | Description |
|---|---|---|
| `GET` | `/health` | Server health check |
| `POST` | `/api/auth/register`, `/api/auth/login` | Authentication |
| `POST` | `/api/parse-excel`, `/api/excel-preview`, `/api/parse-excel-mapped` | Read tickets from Excel |
| `POST` | `/api/upload` | Upload source code ZIP |
| `POST` | `/api/scan`, `/api/evaluate` | Scan code & evaluate tickets (upload flow) |
| `POST` | `/api/jira/connect`, `/api/git/connect`, `/api/git-jira-scan` | Connect flow |
| `GET` | `/api/scan-progress/{job_id}` | Scan progress |
| `POST` | `/api/re-evaluate-ticket` | Re-evaluate one ticket |
| `POST` | `/api/risk`, `/api/solutions` | Risk analysis & solution suggestions |
| `GET/POST` | `/api/projects…` | Projects, members, scan runs, latest scan, report |
| `GET/PUT` | `/api/model-config` | LLM model configuration |

Full interactive docs are available at **http://localhost:8001/docs** while the backend is running.

---

## Diagnostics

Standalone scripts in `server/` to debug integrations without touching app data:

```bash
python check_git_clone.py <repo_url> [branch]           # Why does a clone fail?
python check_source_evidence.py <repo_url> <branch> ... # What evidence files are found?
python check_tool_calling_support.py                    # Does the deep model support tool calling?
```

---

## Troubleshooting

- **LLM not reachable** — make sure Ollama is running (`ollama serve`) or your API settings in `.env` are correct. Use the *Model Configuration* page's test button.
- **No code found for a ticket** — the scanner matches ticket IDs (case-insensitive) and keywords from the summary/description. Put ticket IDs in branch names, commit messages or comments (e.g. `PROJ-123: add refund calculation`).
- **Port already in use** — change the backend port and update the proxy target in `client/vite.config.js`.
