-- Project Health Checker — persistence schema
-- ---------------------------------------------
-- PostgreSQL dialect. Applied via `python init_db.py` (server/db.py),
-- never automatically on server startup. Every statement uses
-- IF NOT EXISTS, so re-running this file is always safe.
--
-- On SQLite instead: GENERATED ALWAYS AS IDENTITY -> INTEGER PRIMARY KEY
-- AUTOINCREMENT; TIMESTAMPTZ/DATE -> TEXT; BOOLEAN -> INTEGER (0/1);
-- JSONB -> TEXT (store JSON-encoded strings); IF NOT EXISTS on CREATE
-- INDEX is unsupported before SQLite 3.8 but fine on anything current.
--
-- Models the full set of features already built (real + mock UI):
-- Dashboard, Project List, Check Health Project (New + Re-run Existing),
-- History/Trend snapshots, Risk, Suggested Solutions, Member Manager.

-- ---------------------------------------------------------------------
-- 1. Identity
-- ---------------------------------------------------------------------

-- Member (Role) Manager + login identity (see server/auth.py). Rows
-- created before real auth shipped (e.g. seed_db.py's project "owner"
-- placeholders) have password_hash = NULL and simply can't log in.
CREATE TABLE IF NOT EXISTS users (
  id             INTEGER GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  name           TEXT NOT NULL,
  email          TEXT NOT NULL UNIQUE,
  role           TEXT NOT NULL DEFAULT 'Viewer'
                   CHECK (role IN ('Owner', 'Admin', 'Editor', 'Viewer')),
  invited_at     TIMESTAMPTZ NOT NULL DEFAULT now()
);
ALTER TABLE users ADD COLUMN IF NOT EXISTS password_hash TEXT;
ALTER TABLE users ADD COLUMN IF NOT EXISTS last_login_at TIMESTAMPTZ;
-- Pending-invite state (Member Manager's "Invite member"/"Invite group",
-- see server/members.py). A user is "pending" when password_hash IS NULL
-- AND invite_token_hash IS NOT NULL — distinct from the seed-only "owner"
-- placeholder rows above, which have neither.
ALTER TABLE users ADD COLUMN IF NOT EXISTS invite_token_hash TEXT;
ALTER TABLE users ADD COLUMN IF NOT EXISTS invite_token_expires_at TIMESTAMPTZ;
ALTER TABLE users ADD COLUMN IF NOT EXISTS invited_by INTEGER REFERENCES users(id);

-- Teams for Member Manager's "Invite group" — inviting a group invites (or
-- re-invites) every member currently in it.
CREATE TABLE IF NOT EXISTS groups (
  id          INTEGER GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  name        TEXT NOT NULL UNIQUE,
  created_by  INTEGER REFERENCES users(id),
  created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE TABLE IF NOT EXISTS group_members (
  group_id  INTEGER NOT NULL REFERENCES groups(id) ON DELETE CASCADE,
  user_id   INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  added_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
  PRIMARY KEY (group_id, user_id)
);

-- ---------------------------------------------------------------------
-- 2. Projects & connections
-- ---------------------------------------------------------------------

-- One row per tracked project (Dashboard / Project List row).
CREATE TABLE IF NOT EXISTS projects (
  id              INTEGER GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  name            TEXT NOT NULL,
  owner_id        INTEGER REFERENCES users(id),
  current_sprint  TEXT,
  created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Git source, shown as the "Connected" card in Check Health Project's
-- existing-project mode. 1-to-1 with projects — a project has at most one
-- active repo connection.
CREATE TABLE IF NOT EXISTS project_git_connections (
  project_id      INTEGER PRIMARY KEY REFERENCES projects(id) ON DELETE CASCADE,
  repo_url        TEXT NOT NULL,
  branch          TEXT NOT NULL DEFAULT 'main',
  last_commit     TEXT,
  last_commit_at  TIMESTAMPTZ,
  connected_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);
-- doc_path/source_path (the "restrict scan to this subfolder" fields on
-- Connect Git/Jira's ConnectPanel) weren't persisted here originally --
-- Project Detail's per-ticket re-scan had no way to reapply them and
-- silently fell back to scanning the WHOLE repo instead of the originally
-- configured subfolder. Non-secret, same as repo_url/branch.
ALTER TABLE project_git_connections ADD COLUMN IF NOT EXISTS doc_path TEXT;
ALTER TABLE project_git_connections ADD COLUMN IF NOT EXISTS source_path TEXT;

-- Ticket source (Jira live, or an Excel template with a remembered column
-- mapping). 1-to-1 with projects.
CREATE TABLE IF NOT EXISTS project_ticket_connections (
  project_id        INTEGER PRIMARY KEY REFERENCES projects(id) ON DELETE CASCADE,
  source_type       TEXT NOT NULL CHECK (source_type IN ('jira', 'excel', 'manual')),
  jira_site_url     TEXT,
  jira_project_key  TEXT,
  excel_filename    TEXT,
  excel_mapping     JSONB,   -- {"ticket_id":0,"summary":1,"status":2,...}
  connected_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Explicit visibility grant: lets an Owner/Admin share a specific project
-- with a specific Editor/Viewer, independent of whether that person has
-- personally run a scan on it. projects.owner_id alone only ever reflects
-- whoever most recently checked a project (a single slot, overwritten on
-- every re-check) -- it was never a list of people allowed to see it, so
-- there was previously no way to hand an invited member visibility into
-- an existing project without them re-scanning it themselves (which also
-- silently took over that single owner_id slot from whoever had it).
-- NOT a per-project role -- the user's existing global Owner/Admin/Editor/
-- Viewer role still governs what they can DO; this table only governs
-- WHICH projects an Editor/Viewer can see at all (see main.py's
-- _check_project_visibility / projects.list_projects).
CREATE TABLE IF NOT EXISTS project_members (
  project_id  INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
  user_id     INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  added_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
  added_by    INTEGER REFERENCES users(id),
  PRIMARY KEY (project_id, user_id)
);

-- ---------------------------------------------------------------------
-- 3. Scan execution
-- ---------------------------------------------------------------------

-- A ZIP upload (server/main.py's existing upload_id / extracted_path).
CREATE TABLE IF NOT EXISTS uploads (
  id              TEXT PRIMARY KEY,          -- the app's hex12 upload_id
  project_id      INTEGER REFERENCES projects(id),
  filename        TEXT NOT NULL,
  size_bytes      INTEGER NOT NULL,
  extracted_path  TEXT NOT NULL,
  uploaded_by     INTEGER REFERENCES users(id),
  uploaded_at     TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- The central table: one row per "Scan & Evaluate" / "Re-evaluate with AI"
-- run. Rollup columns are denormalized on purpose so Dashboard, Project
-- List, and the Trend/History table read straight off this table with no
-- joins or recomputation.
CREATE TABLE IF NOT EXISTS scan_runs (
  id                    INTEGER GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  project_id            INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
  upload_id             TEXT REFERENCES uploads(id),   -- null for git-sourced runs
  triggered_by          INTEGER REFERENCES users(id),
  run_type              TEXT NOT NULL CHECK (run_type IN ('new_check', 'existing_rerun')),
  scope                 TEXT NOT NULL DEFAULT 'all' CHECK (scope IN ('all', 'sprint', 'custom')),
  scope_note            TEXT,                          -- "Sprint 24", "2026-09-01 -> 2026-09-15"
  source_commit         TEXT,
  status                TEXT NOT NULL DEFAULT 'running' CHECK (status IN ('running', 'done', 'error')),
  error_message         TEXT,
  scanned_files_count   INTEGER,
  -- rollup (Summary + ProjectHealth, cached per run)
  total_tickets         INTEGER,
  match_count           INTEGER,
  mismatch_count        INTEGER,
  incomplete_count      INTEGER,
  match_percent         REAL,
  avg_completion        REAL,
  health_status         TEXT CHECK (health_status IN ('OK', 'Risk', 'Late')),
  health_score          INTEGER,               -- round(avg_completion) — Trend table's Health Score
  late_ticket_count     INTEGER,
  overall_risk_score    REAL,
  is_snapshot           BOOLEAN NOT NULL DEFAULT TRUE,  -- "Lưu thành snapshot mới" checkbox
  started_at            TIMESTAMPTZ NOT NULL DEFAULT now(),
  completed_at          TIMESTAMPTZ
);
CREATE INDEX IF NOT EXISTS idx_scan_runs_project_time ON scan_runs(project_id, completed_at);

-- ---------------------------------------------------------------------
-- 4. Tickets & evaluation
-- ---------------------------------------------------------------------

-- Persistent ticket identity per project (kept in sync on each Jira/Excel
-- sync), so the same ticket is tracked across multiple runs over time.
CREATE TABLE IF NOT EXISTS tickets (
  id           INTEGER GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  project_id   INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
  ticket_key   TEXT NOT NULL,             -- "PROJ-101"
  summary      TEXT NOT NULL DEFAULT '',
  description  TEXT NOT NULL DEFAULT '',
  issue_type   TEXT,
  due_date     DATE,
  created_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
  UNIQUE (project_id, ticket_key)
);
ALTER TABLE tickets ADD COLUMN IF NOT EXISTS assignee TEXT;

-- Stable per-person identifier for cross-project rollups (Member
-- Performance page): Jira's assignee.accountId, which never changes even
-- if the person's display name or email does -- unlike `assignee` (plain
-- display-name text), which two different real people can share across
-- projects. NULL for Excel/ZIP-sourced tickets (no such identifier exists
-- there) -- those fall back to grouping by lower(trim(assignee)) instead,
-- a known/accepted limitation (see server/member_performance.py).
ALTER TABLE tickets ADD COLUMN IF NOT EXISTS assignee_key TEXT;

-- One row per ticket per run — the AI's verdict (mirrors models.TicketResult).
CREATE TABLE IF NOT EXISTS evaluation_results (
  id                  INTEGER GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  scan_run_id         INTEGER NOT NULL REFERENCES scan_runs(id) ON DELETE CASCADE,
  ticket_id           INTEGER NOT NULL REFERENCES tickets(id),
  reported_status     TEXT NOT NULL,             -- Done / In Progress / To Do, as of this run
  completion_percent  REAL NOT NULL,
  assessment          TEXT NOT NULL CHECK (assessment IN ('Match', 'Mismatch', 'Incomplete', 'Skipped')),
  confidence          REAL NOT NULL DEFAULT 0,
  schedule_status     TEXT NOT NULL DEFAULT 'No due date provided',
  days_diff           INTEGER,
  missing_parts       JSONB,   -- array of strings
  suggestions         JSONB,   -- array of strings
  evidence_files      JSONB,   -- array of file paths
  notes               TEXT,
  UNIQUE (scan_run_id, ticket_id)
);
CREATE INDEX IF NOT EXISTS idx_eval_results_run ON evaluation_results(scan_run_id);

-- 'Skipped' (Cancelled tickets, evaluator._skipped_result) was added to the
-- assessment CHECK after this table may already have been created on an
-- existing database -- CREATE TABLE IF NOT EXISTS above won't retroactively
-- widen an existing constraint, so redo it explicitly every time this file
-- runs (idempotent: DROP IF EXISTS then ADD always converges to the same
-- constraint, whether the table was just created above or already existed).
ALTER TABLE evaluation_results DROP CONSTRAINT IF EXISTS evaluation_results_assessment_check;
ALTER TABLE evaluation_results ADD CONSTRAINT evaluation_results_assessment_check
  CHECK (assessment IN ('Match', 'Mismatch', 'Incomplete', 'Skipped'));

-- Re-evaluation cache (existing-project "Re-evaluate with AI" re-runs, see
-- server/reeval_cache.py): content_hash fingerprints this ticket's
-- status+summary+description AS OF this run, so a later run can tell
-- whether anything relevant changed without keeping full history text.
-- from_cache marks a row that was carried forward unchanged instead of a
-- fresh AI call -- informational only, not read back by the skip decision
-- itself (which relies on content_hash + scan_runs.source_commit, both of
-- which a cached row still carries forward correctly).
ALTER TABLE evaluation_results ADD COLUMN IF NOT EXISTS content_hash TEXT;
ALTER TABLE evaluation_results ADD COLUMN IF NOT EXISTS from_cache BOOLEAN NOT NULL DEFAULT FALSE;

-- Cached project-wide "Solution Management" AI synthesis (solutions.py),
-- keyed by scan_run_id -- a scan_run_id never changes once a scan is saved,
-- so this means a project's solutions are only ever synthesized once per
-- scan no matter how many times a PM reopens the Solutions page for it. A
-- new scan produces a new scan_run_id, so the cache "invalidates" itself
-- naturally (cache miss on the new id) with no TTL/eviction logic needed.
CREATE TABLE IF NOT EXISTS project_solutions (
  scan_run_id   INTEGER PRIMARY KEY REFERENCES scan_runs(id) ON DELETE CASCADE,
  items         JSONB NOT NULL,
  generated_by  TEXT NOT NULL CHECK (generated_by IN ('llm', 'heuristic')),
  message       TEXT NOT NULL DEFAULT '',
  created_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- ---------------------------------------------------------------------
-- 5. Risk & suggested solutions
-- ---------------------------------------------------------------------

-- One row per ticket per run (mirrors risk.py's RiskItem).
CREATE TABLE IF NOT EXISTS risk_scores (
  id                  INTEGER GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  scan_run_id         INTEGER NOT NULL REFERENCES scan_runs(id) ON DELETE CASCADE,
  ticket_id           INTEGER NOT NULL REFERENCES tickets(id),
  risk_score          REAL NOT NULL,
  severity            TEXT NOT NULL CHECK (severity IN ('Critical', 'High', 'Medium', 'Low')),
  factors             JSONB,   -- array of strings
  recommended_action  TEXT,
  UNIQUE (scan_run_id, ticket_id)
);

-- Project-wide recommendations synthesized per run (mirrors solutions.py's
-- SolutionItem) — not per-ticket, so it's its own table, not a column on
-- evaluation_results.
CREATE TABLE IF NOT EXISTS solutions (
  id              INTEGER GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  scan_run_id     INTEGER NOT NULL REFERENCES scan_runs(id) ON DELETE CASCADE,
  title           TEXT NOT NULL,
  category        TEXT NOT NULL DEFAULT 'Other',
  recommendation  TEXT NOT NULL,
  priority        TEXT NOT NULL DEFAULT 'Medium' CHECK (priority IN ('High', 'Medium', 'Low')),
  rationale       TEXT,
  generated_by    TEXT NOT NULL DEFAULT 'heuristic' CHECK (generated_by IN ('llm', 'heuristic'))
);

-- Many-to-many: one recommendation can name several tickets.
CREATE TABLE IF NOT EXISTS solution_affected_tickets (
  solution_id  INTEGER NOT NULL REFERENCES solutions(id) ON DELETE CASCADE,
  ticket_id    INTEGER NOT NULL REFERENCES tickets(id),
  PRIMARY KEY (solution_id, ticket_id)
);

-- ---------------------------------------------------------------------
-- 6. Git evidence audit trail
-- ---------------------------------------------------------------------

-- One row per distinct (filename, path) actually read from Git during
-- Scan & Evaluate (source-code diffs + design docs/images) -- visibility
-- into what evidence the AI saw. Composite key: two files with the same
-- basename but different paths (e.g. two "index.js" in different folders)
-- get their own row; re-reading the exact same path just updates read_at.
CREATE TABLE IF NOT EXISTS git_read_files (
  filename   TEXT NOT NULL,
  path       TEXT NOT NULL,
  file_type  TEXT NOT NULL CHECK (file_type IN ('Source Code', 'Doc')),
  read_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
  PRIMARY KEY (filename, path)
);

-- ---------------------------------------------------------------------
-- 7. App settings
-- ---------------------------------------------------------------------

-- Runtime-configurable LLM connection settings (Model Configuration page,
-- Owner/Admin only), replacing the need to hand-edit server/.env and
-- restart the server. Singleton row (id always 1, enforced by the CHECK).
-- Any field left NULL falls back to its server/.env default at read time
-- (see server/model_config.py's get_llm_settings) -- an admin can override
-- just the model name, for instance, without having to also re-enter an
-- API key. api_key/api_key_deep are stored the same way server/.env
-- already stored them (plaintext) -- same trust model, just a different
-- location, and only Owner/Admin can read or write this table.
CREATE TABLE IF NOT EXISTS model_config (
  id              INTEGER PRIMARY KEY DEFAULT 1 CHECK (id = 1),
  api_key         TEXT,
  base_url        TEXT,
  model           TEXT,
  api_key_deep    TEXT,
  base_url_deep   TEXT,
  model_deep      TEXT,
  updated_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_by      INTEGER REFERENCES users(id)
);

-- ---------------------------------------------------------------------
-- Notes on things intentionally left out
-- ---------------------------------------------------------------------
-- * Next-milestone (ProjectHealthPanel) is a query, not a table:
--     SELECT * FROM tickets
--     WHERE project_id = ? AND issue_type = 'Milestone' AND due_date IS NOT NULL
--     ORDER BY due_date LIMIT 1
-- * Trend/History rows are just:
--     SELECT completed_at, health_score, late_ticket_count, mismatch_count, scope_note
--     FROM scan_runs WHERE project_id = ? AND is_snapshot = true ORDER BY completed_at
-- * Per-project roles (vs. today's single global role per user) are still
--   NOT modeled -- project_members (added above) only grants VISIBILITY
--   into a project, it carries no role of its own. The user's global
--   Owner/Admin/Editor/Viewer role still governs what they can DO.
