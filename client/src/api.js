import i18n from './i18n'

const BASE_URL = import.meta.env.VITE_API_BASE_URL || '/api'

const TOKEN_KEY = 'phc_auth_token'

export function getToken() {
  return localStorage.getItem(TOKEN_KEY)
}

export function setToken(token) {
  if (token) localStorage.setItem(TOKEN_KEY, token)
  else localStorage.removeItem(TOKEN_KEY)
}

// A failed login/register attempt returns 401/409 for "wrong credentials" /
// "already registered" — not "your session expired" — so those two paths
// are excluded from the auto-logout-on-401 behavior below.
const NO_AUTO_LOGOUT_PATHS = ['/auth/login', '/auth/register']

/**
 * Shared fetch wrapper for every endpoint below: attaches the stored auth
 * token (see getToken/setToken), and on any 401 (except a login/register
 * attempt itself) clears it and fires a `phc:unauthorized` window event so
 * AuthContext can log the user out — a stale/expired token never just
 * fails silently.
 * @param {string} path  appended to BASE_URL, e.g. '/projects'
 * @param {RequestInit & {on404?: 'null'}} options
 */
async function request(path, options = {}) {
  const { on404, ...fetchOptions } = options
  const token = getToken()
  const headers = { ...(fetchOptions.headers || {}) }
  if (token) headers.Authorization = `Bearer ${token}`
  headers['X-Language'] = i18n.language

  const res = await fetch(`${BASE_URL}${path}`, { ...fetchOptions, headers })

  if (res.status === 404 && on404 === 'null') return null

  if (res.status === 401 && !NO_AUTO_LOGOUT_PATHS.includes(path)) {
    setToken(null)
    window.dispatchEvent(new Event('phc:unauthorized'))
  }

  if (!res.ok) {
    const err = await res.json().catch(() => ({}))
    throw new Error(err.detail || `Request failed (${res.status})`)
  }
  if (res.status === 204) return null
  return res.json()
}

/**
 * Register a new account. Auto-logs-in on success (the backend returns a
 * token immediately, no separate login step needed).
 * @returns {Promise<{token: string, user: {id, name, email, role}}>}
 */
export async function registerRequest(name, email, password) {
  return request('/auth/register', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ name, email, password }),
  })
}

/**
 * @returns {Promise<{token: string, user: {id, name, email, role}}>}
 */
export async function loginRequest(email, password) {
  return request('/auth/login', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ email, password }),
  })
}

/** Validate the stored token and fetch the current user, e.g. on app load. */
export async function getMe() {
  return request('/auth/me')
}

/**
 * Preview an invite by its token — what the Accept-Invite page shows
 * before the recipient has any account. Throws (caller shows an error
 * card) if the token is invalid, expired, or already used.
 * @returns {Promise<{name, email, role, group_name: string|null}>}
 */
export async function getInvitePreview(token) {
  return request(`/invites/${token}`)
}

/**
 * Accept an invite: sets the recipient's name + password and returns an
 * auth token, same shape as login/register.
 * @returns {Promise<{token: string, user: object}>}
 */
export async function acceptInvite(token, name, password) {
  return request(`/invites/${token}/accept`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ name, password }),
  })
}

/**
 * @returns {Promise<Array<{id, name, email, role, status: 'active'|'pending', groups: string[]}>>}
 */
export async function listMembers() {
  return request('/members')
}

/**
 * Invite a single member by email. Always succeeds (creates/reuses the
 * pending account); email_sent tells the caller whether a real email went
 * out or the invite_link should be shown for manual sharing.
 * @returns {Promise<{member, email_sent, invite_link, message}>}
 */
export async function inviteMember(name, email, role) {
  return request('/members/invite', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ name, email, role }),
  })
}

export async function updateMemberRole(memberId, role) {
  return request(`/members/${memberId}/role`, {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ role }),
  })
}

/**
 * @returns {Promise<Array<{id, name, members: Array}>>}
 */
export async function listGroups() {
  return request('/groups')
}

/**
 * Create a group and invite every listed email as a member.
 * @param {string} name
 * @param {string[]} memberEmails
 * @param {string} role  assigned to newly-created members
 * @returns {Promise<{group, results: Array<{email, status, invite_link}>}>}
 */
export async function createGroup(name, memberEmails, role) {
  return request('/groups', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ name, member_emails: memberEmails, role }),
  })
}

/**
 * Test a real Git connection (smart-HTTP refs handshake) and confirm the
 * given branch exists.
 * @returns {Promise<{connected, commit_sha, message}>}
 */
export async function connectGit(repoUrl, branch, gitToken, gitUsername) {
  return request('/git/connect', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      repo_url: repoUrl,
      branch,
      git_token: gitToken || '',
      git_username: gitUsername || '',
    }),
  })
}

/**
 * Real 3-layer Git/Jira scan (Connect Git/Jira page's Scan & Evaluate):
 * fetches the real Jira ticket list, gathers Git evidence, and evaluates.
 * `enableDeepDive` opts into Layer 4 (agentic deep-dive against a local
 * clone) for whatever comes out Incomplete/low-confidence — slower/costlier,
 * off by default.
 * @returns {Promise<{tickets, results, summary, health, trend}>}
 */
export async function runGitJiraScan({
  repoUrl,
  branch,
  gitToken,
  gitProvider,
  docPath,
  sourcePath,
  enableDeepDive,
  jiraSiteUrl,
  jiraProjectKey,
  jiraEmail,
  jiraApiToken,
  jobId,
  projectId,
  forceFullReevaluate,
}) {
  return request('/git-jira-scan', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      repo_url: repoUrl,
      branch,
      git_token: gitToken || '',
      git_provider: gitProvider || '',
      doc_path: docPath || '',
      source_path: sourcePath || '',
      enable_deep_dive: !!enableDeepDive,
      jira_site_url: jiraSiteUrl,
      jira_project_key: jiraProjectKey,
      jira_email: jiraEmail,
      jira_api_token: jiraApiToken,
      job_id: jobId || null,
      // Existing-project re-run only: lets the backend skip AI re-evaluation
      // for tickets unchanged since their last check (reeval_cache.py).
      project_id: projectId || null,
      force_full_reevaluate: !!forceFullReevaluate,
    }),
  })
}

/**
 * Poll while /evaluate or /git-jira-scan is still in flight, to render a
 * real "X/Y tickets" progress bar. Returns null on 404 (job not found /
 * already swept) so callers can just keep polling instead of erroring out.
 * @param {string} jobId
 * @returns {Promise<{phase: string, current: number, total: number, done: boolean, error: string|null}|null>}
 */
export async function getScanProgress(jobId) {
  return request(`/scan-progress/${jobId}`, { on404: 'null' })
}

/**
 * Test a real Jira connection (Basic Auth) and count tickets in the given
 * project. The email/API token are sent only for this one request — the
 * backend never persists them.
 * @returns {Promise<{connected, ticket_count, message}>}
 */
export async function connectJira(siteUrl, projectKey, email, apiToken) {
  return request('/jira/connect', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ site_url: siteUrl, project_key: projectKey, email, api_token: apiToken }),
  })
}

/** Re-invite whichever members of this group are still pending. */
export async function inviteGroup(groupId) {
  return request(`/groups/${groupId}/invite`, { method: 'POST' })
}

/** "2h ago" / "3d ago" style relative time, for the small connection-status
 * labels (e.g. Git "Last commit ..."). Falls back to the raw ISO string if
 * given something unparseable. */
function relativeTime(isoString) {
  if (!isoString) return null
  const then = new Date(isoString).getTime()
  if (Number.isNaN(then)) return isoString
  const diffMs = Date.now() - then
  const minutes = Math.round(diffMs / 60000)
  if (minutes < 1) return 'just now'
  if (minutes < 60) return `${minutes}m ago`
  const hours = Math.round(minutes / 60)
  if (hours < 24) return `${hours}h ago`
  const days = Math.round(hours / 24)
  return `${days}d ago`
}

/** Map the backend's snake_case project shape to the camelCase shape
 * ProjectTable/Dashboard/CheckHealthConnectPage already expect. */
function mapProject(p) {
  return {
    id: p.id,
    name: p.name,
    owner: p.owner,
    currentSprint: p.current_sprint,
    lastCheckedAt: p.last_checked_at ? p.last_checked_at.slice(0, 10) : null,
    lastCheckedRelative: relativeTime(p.last_checked_at),
    healthStatus: p.health_status,
    healthScore: p.health_score,
    ticketCount: p.ticket_count,
    matchPercent: p.match_percent,
    avgCompletion: p.avg_completion,
    matchCount: p.match_count,
    mismatchCount: p.mismatch_count,
    lateCount: p.late_count,
    completeCount: p.complete_count,
    source: p.git
      ? {
          repoUrl: p.git.repo_url,
          branch: p.git.branch,
          lastCommit: p.git.last_commit,
          lastCommitAt: relativeTime(p.git.last_commit_at),
          docPath: p.git.doc_path,
          sourcePath: p.git.source_path,
        }
      : null,
    ticketSource: p.ticket_source
      ? {
          type: p.ticket_source.type,
          jiraSiteUrl: p.ticket_source.jira_site_url,
          jiraProjectKey: p.ticket_source.jira_project_key,
          fileName: p.ticket_source.excel_filename,
          mapping: p.ticket_source.excel_mapping,
        }
      : null,
  }
}

/**
 * List all projects (Dashboard, Project List, Check Health Project's
 * existing-project picker) with their latest scan snapshot rolled up.
 * @returns {Promise<Array<object>>}
 */
export async function listProjects() {
  const data = await request('/projects')
  return data.map(mapProject)
}

/**
 * Users explicitly granted visibility into a project (Owner/Admin only) --
 * separate from whoever the project's current "Checker" (owner_id) is.
 * @returns {Promise<Array<{id, name, email, role}>>}
 */
export async function getProjectMembers(projectId) {
  return request(`/projects/${projectId}/members`)
}

/** Grant a user visibility into a project. Returns the updated member list. */
export async function addProjectMember(projectId, userId) {
  return request(`/projects/${projectId}/members`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ user_id: userId }),
  })
}

/** Revoke a user's explicit visibility into a project. Returns the updated member list. */
export async function removeProjectMember(projectId, userId) {
  return request(`/projects/${projectId}/members/${userId}`, { method: 'DELETE' })
}

/**
 * Fetch a single project by id.
 * @param {number} id
 * @returns {Promise<object>}
 */
export async function getProject(id) {
  return mapProject(await request(`/projects/${id}`))
}

/**
 * Upload a ZIP archive containing the project source code.
 * @param {File} zipFile
 * @returns {Promise<object>} { upload_id, filename, size, extracted_path }
 */
export async function uploadZip(zipFile) {
  const formData = new FormData()
  formData.append('file', zipFile)
  return request('/upload', { method: 'POST', body: formData })
}

/**
 * Parse an Excel file (.xlsx/.xlsm) containing ticket data.
 * @param {File} excelFile
 * @returns {Promise<object>} { filename, ticket_count, tickets, tsv }
 */
export async function parseExcelFile(excelFile) {
  const formData = new FormData()
  formData.append('file', excelFile)
  return request('/parse-excel', { method: 'POST', body: formData })
}

/**
 * Preview an Excel file's raw headers + a few data rows, plus a suggested
 * column mapping, before committing to how it should be parsed.
 * @param {File} excelFile
 * @returns {Promise<object>} { sheet_name, header_row, headers, preview_rows, suggested_mapping }
 */
export async function previewExcelFile(excelFile) {
  const formData = new FormData()
  formData.append('file', excelFile)
  return request('/excel-preview', { method: 'POST', body: formData })
}

/**
 * Parse an Excel file using an explicit column->field mapping instead of
 * relying on auto-detected column names.
 * @param {File} excelFile
 * @param {object} mapping  { ticket_id, summary, status, description, due_date, issue_type } -> column index or null
 * @param {number} headerRow  1-indexed row number where the real header lives
 * @returns {Promise<object>} { filename, ticket_count, tickets, tsv }
 */
export async function parseExcelFileMapped(excelFile, mapping, headerRow) {
  const formData = new FormData()
  formData.append('file', excelFile)
  formData.append('mapping', JSON.stringify(mapping))
  if (headerRow != null) formData.append('header_row', String(headerRow))
  return request('/parse-excel-mapped', { method: 'POST', body: formData })
}

/**
 * Scan the uploaded project for references to the given tickets.
 * @param {string} uploadId
 * @param {Array<object>} tickets  [{ticket_id, summary, description, status}]
 * @returns {Promise<object>} { scan_result, scanned_files }
 */
export async function scanProject(uploadId, tickets) {
  return request('/scan', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ upload_id: uploadId, tickets }),
  })
}

/**
 * Evaluate tickets against the scanned code. `enableDeepDive` opts into
 * Layer 4 (agentic deep-dive against the already-extracted ZIP) for
 * whatever comes out Incomplete/low-confidence — slower/costlier, off by
 * default.
 * @param {string} uploadId
 * @param {Array<object>} tickets
 * @param {boolean} [enableDeepDive]
 * @param {string} [jobId]
 * @returns {Promise<object>} { results, summary }
 */
export async function evaluateProject(uploadId, tickets, enableDeepDive, jobId) {
  return request('/evaluate', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      upload_id: uploadId,
      tickets,
      enable_deep_dive: !!enableDeepDive,
      job_id: jobId || null,
    }),
  })
}

/**
 * Re-run AI evaluation for a SINGLE ticket from the Ticket Evaluation
 * Results table -- a fast, targeted alternative to re-running the whole
 * project. Always evaluates for real (bypasses the re-evaluation cache for
 * this one ticket). Pass exactly one of `uploadId` (Upload ZIP/Excel flow)
 * or the `repoUrl`/... git fields (Connect Git/Jira flow), matching
 * whichever flow produced this ticket.
 * @param {object} params
 * @param {object} params.ticket - the TicketInfo being re-checked
 * @param {string} [params.uploadId]
 * @param {string} [params.repoUrl]
 * @param {string} [params.branch]
 * @param {string} [params.gitToken]
 * @param {string} [params.gitProvider]
 * @param {string} [params.docPath]
 * @param {string} [params.sourcePath]
 * @param {boolean} [params.enableDeepDive]
 * @param {number} [params.projectId] - when given, also persists this ticket's row + rollup into the
 *   project's latest saved snapshot (so the change survives a reload) -- omit for a not-yet-saved check.
 * @param {string} [params.jiraSiteUrl] - when given (with jiraEmail/jiraApiToken), re-fetches this
 *   ticket's CURRENT status/summary/description from Jira before evaluating -- omit for a ticket with no
 *   live Jira source (Excel/manual) to refresh from.
 * @param {string} [params.jiraEmail]
 * @param {string} [params.jiraApiToken]
 * @returns {Promise<object>} the updated TicketResult
 */
export async function reEvaluateTicket({
  ticket,
  uploadId,
  repoUrl,
  branch,
  gitToken,
  gitProvider,
  docPath,
  sourcePath,
  enableDeepDive,
  projectId,
  jiraSiteUrl,
  jiraEmail,
  jiraApiToken,
}) {
  return request('/re-evaluate-ticket', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      ticket,
      upload_id: uploadId || null,
      repo_url: repoUrl || null,
      branch: branch || 'main',
      git_token: gitToken || '',
      git_provider: gitProvider || '',
      doc_path: docPath || '',
      source_path: sourcePath || '',
      enable_deep_dive: !!enableDeepDive,
      project_id: projectId || null,
      jira_site_url: jiraSiteUrl || null,
      jira_email: jiraEmail || '',
      jira_api_token: jiraApiToken || '',
    }),
  })
}

/**
 * Pure recomputation of summary/health/trend from an already-evaluated
 * ticket+result set -- no AI call, cheap arithmetic (like getRisk). Call
 * this right after patching a single ticket's result in place (see
 * reEvaluateTicket) so StatCards/ProjectHealthPanel/ProjectTrendChart
 * reflect the change instead of showing stale totals from the last full
 * scan.
 * @param {object} params
 * @param {Array<object>} params.tickets
 * @param {Array<object>} params.results
 * @param {number} [params.scannedFiles]
 * @returns {Promise<{summary: object, health: object, trend: object}>}
 */
export async function recomputeSummary({ tickets, results, scannedFiles }) {
  return request('/recompute-summary', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ tickets, results, scanned_files: scannedFiles || 0 }),
  })
}

/**
 * Persist a completed Check Health Project run (real evaluate, or an
 * existing-project re-run) as a scan_runs row + its per-ticket
 * evaluation_results, so Trend History is backed by real data instead of
 * only localStorage.
 * @param {object} payload { project_id, run_type, scope, scope_note, upload_id, is_snapshot, tickets, results, summary, health_status }
 * @returns {Promise<object>} { scan_run_id, completed_at }
 */
export async function saveScanRun(payload) {
  return request('/scan-runs', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  })
}

/**
 * Find-or-create a project by name — used by Check Health Project's "New
 * project" real-scan flow to auto-create a project row (named from the
 * connected Git repo or the uploaded ZIP's filename) before saving its
 * first scan run.
 * @param {string} name
 * @returns {Promise<{id: number, name: string, created: boolean}>}
 */
export async function createProject(name) {
  return request('/projects', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ name }),
  })
}

/** ISO timestamp -> "yyyy/MM/dd HH:mm", the History Check table's Check Date format. */
function formatCheckDate(isoString) {
  if (!isoString) return ''
  const d = new Date(isoString)
  if (Number.isNaN(d.getTime())) return isoString
  const pad = (n) => String(n).padStart(2, '0')
  return `${d.getFullYear()}/${pad(d.getMonth() + 1)}/${pad(d.getDate())} ${pad(d.getHours())}:${pad(d.getMinutes())}`
}

/**
 * "History Check" rows for a project — every past snapshot scan_runs row,
 * oldest first, straight from the database.
 * @param {number} projectId
 * @returns {Promise<Array<{date: string, healthScore: number|null, lateCount: number|null, mismatchCount: number|null, note: string|null}>>}
 */
export async function getProjectSnapshots(projectId) {
  const data = await request(`/projects/${projectId}/scan-runs`)
  return data.map((s) => ({
    date: formatCheckDate(s.completed_at),
    healthScore: s.health_score,
    lateCount: s.late_ticket_count,
    mismatchCount: s.mismatch_count,
    note: s.scope_note,
  }))
}

/**
 * Real per-ticket detail from a project's most recent snapshot scan run —
 * same shape as evaluateProject()'s response. Returns null (not a thrown
 * error) when the project has never been scanned with per-ticket data
 * saved, so callers can fall back to synthesized detail.
 * @param {number} projectId
 * @returns {Promise<{results: Array, summary: object, health: object, trend: object} | null>}
 */
export async function getLatestScan(projectId) {
  return request(`/projects/${projectId}/latest-scan`, { on404: 'null' })
}

/**
 * Score project risk from already-computed evaluation results.
 * @param {Array<object>} tickets
 * @param {Array<object>} results
 * @returns {Promise<object>} { items, overall_risk_score, distribution, message }
 */
export async function getRisk(tickets, results) {
  return request('/risk', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ tickets, results }),
  })
}

/**
 * Synthesize project-wide recommendations (patterns across tickets, not
 * per-ticket) from already-computed evaluation results — one aggregate LLM
 * call server-side, heuristic fallback if unavailable.
 *
 * Pass `scanRunId` (from getLatestScan's response) whenever this is for a
 * real saved project scan: the backend caches the synthesis by that id
 * (project_solutions table), so re-opening Solution Management for the
 * same scan is instant and doesn't re-call the AI — only a genuinely new
 * scan (a new scan_run_id) triggers a fresh call. Omit it for the in-memory/
 * mock-detail case, which always synthesizes fresh.
 * @param {Array<object>} tickets
 * @param {Array<object>} results
 * @param {number|null} [scanRunId]
 * @returns {Promise<{items: Array, generated_by: string, message: string}>}
 */
export async function getSolutions(tickets, results, scanRunId = null) {
  return request('/solutions', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ tickets, results, scan_run_id: scanRunId }),
  })
}

/**
 * Model Configuration page's current LLM connection settings (Owner/Admin
 * only). API keys always come back masked, never in full.
 * @returns {Promise<object>} { base_url, model, api_key_set, api_key_masked,
 *   base_url_deep, model_deep, api_key_deep_set, api_key_deep_masked,
 *   is_customized, updated_at, updated_by_name, db_configured }
 */
export async function getModelConfig() {
  return request('/model-config')
}

/**
 * Save the Model Configuration page. Any field omitted/undefined is left
 * untouched server-side; pass an empty string for base_url/model/
 * base_url_deep/model_deep to reset that one back to its server/.env
 * default. api_key/api_key_deep are write-only: omit them to keep the
 * currently-saved key, or pass clearApiKey/clearApiKeyDeep=true to reset
 * just the key back to its .env default.
 * @param {object} fields
 * @returns {Promise<object>} same shape as getModelConfig()
 */
export async function updateModelConfig({
  baseUrl,
  model,
  baseUrlDeep,
  modelDeep,
  apiKey,
  clearApiKey,
  apiKeyDeep,
  clearApiKeyDeep,
} = {}) {
  return request('/model-config', {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      base_url: baseUrl,
      model,
      base_url_deep: baseUrlDeep,
      model_deep: modelDeep,
      api_key: apiKey,
      clear_api_key: !!clearApiKey,
      api_key_deep: apiKeyDeep,
      clear_api_key_deep: !!clearApiKeyDeep,
    }),
  })
}

/**
 * Test a candidate base_url/model/api_key combo BEFORE saving it (one real
 * minimal chat completion server-side). Pass apiKey='' (or omit) to test
 * against the currently-saved key for this phase instead of retyping it.
 * @param {{phase: 'phase1'|'phase2', baseUrl: string, model: string, apiKey?: string}} fields
 * @returns {Promise<{success: boolean, message: string, latency_ms: number|null}>}
 */
export async function testModelConfig({ phase, baseUrl, model, apiKey }) {
  return request('/model-config/test', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ phase, base_url: baseUrl, model, api_key: apiKey || null }),
  })
}

/**
 * Cross-project member performance rollup (Total/Complete/In Process/Late
 * per assignee, across every project's latest snapshot scan). Owner/Admin
 * only.
 * @returns {Promise<Array<object>>} [{ assignee_key, display_name, total,
 *   complete, in_process, late, match_count, mismatch_count,
 *   incomplete_count, projects: [{project_id, project_name, total,
 *   complete, late}] }]
 */
export async function getMemberPerformance() {
  return request('/member-performance')
}

/**
 * Fetch a file (rather than JSON) and trigger a browser download for it —
 * shared by downloadEvaluationReport/downloadProjectReport below. Reuses
 * the same auth-token/401-handling as `request()`, but reads a Blob body
 * and pulls the filename off Content-Disposition instead of parsing JSON.
 */
async function downloadFile(path, options = {}) {
  const token = getToken()
  const headers = { ...(options.headers || {}) }
  if (token) headers.Authorization = `Bearer ${token}`
  headers['X-Language'] = i18n.language

  const res = await fetch(`${BASE_URL}${path}`, { ...options, headers })

  if (res.status === 401) {
    setToken(null)
    window.dispatchEvent(new Event('phc:unauthorized'))
  }
  if (!res.ok) {
    const err = await res.json().catch(() => ({}))
    throw new Error(err.detail || `Request failed (${res.status})`)
  }

  const blob = await res.blob()
  const disposition = res.headers.get('Content-Disposition') || ''
  const match = disposition.match(/filename="?([^"]+)"?/)
  const filename = match ? match[1] : 'report.xlsx'

  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = filename
  document.body.appendChild(a)
  a.click()
  a.remove()
  URL.revokeObjectURL(url)
}

/**
 * Download an Excel health report (Summary + Tickets sheets, including
 * each ticket's recommended action) from an already-computed evaluation —
 * no re-scan needed.
 * @param {string} projectName
 * @param {Array<object>} tickets
 * @param {Array<object>} results
 */
export async function downloadEvaluationReport(projectName, tickets, results) {
  return downloadFile('/report', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ project_name: projectName, tickets, results }),
  })
}

/**
 * Download the same Excel health report, but for a project's latest saved
 * snapshot instead of an in-memory scan result.
 * @param {number} projectId
 */
export async function downloadProjectReport(projectId) {
  return downloadFile(`/projects/${projectId}/report`)
}
