"""
Pydantic models for Project Health Checker API
"""
from typing import Dict, List, Optional
from pydantic import BaseModel, Field


class TicketInfo(BaseModel):
    """A single ticket submitted by the client (from TSV input)."""
    ticket_id: str = Field(..., description="Unique ticket identifier, e.g. PROJ-101")
    summary: str = Field(default="", description="Short ticket title")
    status: str = Field(default="To Do", description="Reported status (Done / In Progress / To Do...)")
    description: str = Field(default="", description="Full ticket description / acceptance criteria")
    due_date: str = Field(default="", description="Due date, e.g. 2026-09-30 (blank if none)")
    issue_type: str = Field(default="", description="JIRA Issue Type, e.g. 'Milestone', 'PM Task'")
    assignee: str = Field(default="", description="Assignee name/email (blank if unassigned)")
    assignee_key: str = Field(
        default="",
        description="Stable per-person id for cross-project rollups (Jira's assignee.accountId). "
        "Blank for Excel/ZIP-sourced tickets, which have no such identifier.",
    )


class ScanRequest(BaseModel):
    """Request body for scanning an uploaded project."""
    upload_id: str = Field(..., description="Upload ID returned by /api/upload")
    tickets: List[TicketInfo] = Field(..., description="List of tickets to check")


class EvaluateRequest(BaseModel):
    """Request body for evaluating tickets against scanned code."""
    upload_id: str = Field(..., description="Upload ID returned by /api/upload")
    tickets: List[TicketInfo] = Field(..., description="List of tickets to evaluate")
    enable_deep_dive: bool = Field(
        default=False,
        description="Layer 4: agentic deep-dive (tool-calling LLM against the already-extracted ZIP) for low-confidence/Incomplete tickets. Slower and more costly than Layers 1-2, so opt-in.",
    )
    deep_dive_threshold: float = Field(
        default=0.6, ge=0, le=1, description="Confidence below which a ticket is escalated to Layer 4, in addition to any 'Incomplete' assessment."
    )
    job_id: Optional[str] = Field(
        default=None,
        description="Client-generated id (e.g. crypto.randomUUID()) this run's progress is reported under -- "
        "poll GET /api/scan-progress/{job_id} while this request is in flight. Omit for no progress tracking.",
    )


class ReEvaluateTicketRequest(BaseModel):
    """Re-run AI evaluation for a SINGLE ticket from the Ticket Evaluation
    Results table, bypassing the re-evaluation cache (reeval_cache.py) for
    this one ticket -- a targeted alternative to re-running the whole
    project. Exactly one of `upload_id` (Upload ZIP/Excel flow) or
    `repo_url` (Connect Git/Jira flow) must be given, matching whichever
    flow produced the ticket being re-checked."""
    ticket: TicketInfo
    upload_id: Optional[str] = Field(default=None, description="Upload ZIP/Excel flow: the existing extracted upload to re-scan against.")
    repo_url: Optional[str] = Field(default=None, description="Connect Git/Jira flow: re-fetches evidence from this repo.")
    branch: str = "main"
    git_token: str = ""
    git_provider: str = ""
    doc_path: str = ""
    source_path: str = ""
    enable_deep_dive: bool = False
    deep_dive_threshold: float = Field(default=0.6, ge=0, le=1)
    project_id: Optional[int] = Field(
        default=None,
        description="When given, also patches this ticket's row + recomputed rollup into the project's "
        "latest saved snapshot (see main._persist_single_ticket_result), so the change survives a reload "
        "instead of only living in the requesting browser tab. Omit for a not-yet-saved in-progress check.",
    )
    jira_site_url: Optional[str] = Field(
        default=None,
        description="When given (with jira_email/jira_api_token), re-fetches this ticket's CURRENT status/"
        "summary/description from Jira by key before evaluating, instead of using the possibly-stale "
        "`ticket` field as-is -- e.g. a status that was fixed on Jira since the last full scan. Omit for a "
        "ticket with no live Jira source (Excel/manual) to refresh from.",
    )
    jira_email: str = ""
    jira_api_token: str = ""


class ScanProgressResponse(BaseModel):
    """GET /api/scan-progress/{job_id} -- polled while /api/evaluate or
    /api/git-jira-scan is still in flight."""
    phase: str = Field(description="'scanning' / 'evaluating' / 'evaluating_deep' / 'deep_dive' / 'done'")
    current: int = 0
    total: int = 0
    done: bool = False
    error: Optional[str] = None


class UploadResponse(BaseModel):
    """Response after uploading a ZIP archive."""
    upload_id: str
    filename: str
    size: int
    extracted_path: str


class TicketResult(BaseModel):
    """Per-ticket evaluation result returned to the client."""
    ticket_id: str
    summary: str
    status: str                      # Original status from Excel (Done / In Progress / To Do...)
    completion_percent: float = Field(
        ..., ge=0, le=100, description="Estimated completion percentage 0-100"
    )
    assessment: str = Field(
        ..., description="Match / Mismatch / Incomplete / Skipped (Cancelled tickets are never evaluated)"
    )
    confidence: float = Field(
        default=0.0, ge=0, le=1, description="LLM confidence score"
    )
    missing_parts: List[str] = Field(
        default_factory=list, description="List of missing/incomplete items"
    )
    suggestions: List[str] = Field(
        default_factory=list, description="Recommended fixes"
    )
    evidence_files: List[str] = Field(
        default_factory=list, description="Source files matched to this ticket"
    )
    notes: str = Field(default="", description="Free-form notes from the LLM")
    schedule_status: str = Field(
        default="",
        description="On-time / At-Risk / Late / 'No due date provided'",
    )
    days_diff: Optional[int] = Field(
        default=None,
        description="Days vs Due Date: positive=overdue, negative=days remaining",
    )
    assignee: str = Field(default="", description="Assignee name/email (blank if unassigned)")
    doc_ticket_match: str = Field(
        default="", description="Match / Doc Outdated / No Doc Found (Ticket vs Documentation axis)"
    )
    doc_code_match: str = Field(
        default="", description="Match / Mismatch / Doc Drift / N/A (Documentation vs Code axis)"
    )
    doc_notes: str = Field(default="", description="Free-form reasoning for the doc_ticket_match/doc_code_match axes")
    matched_doc_files: List[str] = Field(
        default_factory=list, description="Doc file paths matched as relevant to this ticket"
    )
    needs_deep_review: bool = Field(
        default=False, description="Set by the triage model when this ticket's logic is ambiguous enough to escalate"
    )
    escalated: bool = Field(
        default=False, description="True only if the deep-judgment model actually ran and returned a usable result"
    )
    ui_screen_match: str = Field(
        default="", description="Match / Missing UI / No Screen Found / N/A (mockup image vs code, deep-review only)"
    )
    matched_image_files: List[str] = Field(
        default_factory=list, description="Screenshot/mockup image paths matched as relevant to this ticket"
    )
    previous_assessment: Optional[str] = Field(
        default=None,
        description="This ticket's assessment on its last real check (existing-project re-run only) -- "
        "None if it has never been checked before. See reeval_cache.py.",
    )
    from_cache: bool = Field(
        default=False,
        description="True if this result was carried forward from the last check instead of a fresh AI "
        "evaluation, because nothing relevant changed (ticket status/content, and the repo's commit) since "
        "that check found it a Match. See reeval_cache.py.",
    )


class IssueFlag(BaseModel):
    """A ticket flagged as a project risk/issue (bad code match or bad schedule)."""
    ticket_id: str
    summary: str
    assessment: str
    schedule_status: str = ""
    reason: str = ""


class MilestoneStatus(BaseModel):
    """Progress of the next upcoming ticket whose Issue Type is 'Milestone'."""
    ticket_id: Optional[str] = None
    summary: Optional[str] = None
    due_date: Optional[str] = None
    status: str = Field(..., description="Early / On-time / At-Risk / Late / None")
    days: Optional[int] = Field(
        default=None,
        description="Days vs Due Date: positive=overdue, negative=days remaining/ahead",
    )
    message: str = ""


class ProjectHealth(BaseModel):
    """Overall project health rollup for the dashboard header."""
    status: str = Field(..., description="OK / Risk / Late")
    issues: List[IssueFlag] = Field(default_factory=list)
    next_milestone: MilestoneStatus


class TicketVariance(BaseModel):
    """One ticket's schedule position for the trend chart: how many days
    ahead of (negative) or behind (positive) its Due Date it is today."""
    ticket_id: str
    summary: str
    due_date: str = ""
    variance_days: int = Field(..., description="positive=overdue, negative=days remaining")
    schedule_status: str = Field(..., description="On-time / At-Risk / Late")


class ProjectTrend(BaseModel):
    """Single-run schedule trend: a bar per due-dated ticket plus a
    headline estimate of overall project slip, computed from the tickets
    that are already overdue (no history across runs required)."""
    tickets: List[TicketVariance] = Field(default_factory=list)
    trend_min_days: Optional[int] = Field(
        default=None, description="Smallest overdue count among Late tickets"
    )
    trend_max_days: Optional[int] = Field(
        default=None, description="Largest overdue count among Late tickets"
    )
    message: str = ""


class Summary(BaseModel):
    """Aggregate statistics for the dashboard."""
    total_tickets: int
    match_count: int
    mismatch_count: int
    incomplete_count: int
    match_percent: float
    avg_completion: float
    scanned_files: int


class EvaluateResponse(BaseModel):
    """Response after evaluation."""
    results: List[TicketResult]
    summary: Summary
    health: ProjectHealth
    trend: ProjectTrend
    scan_run_id: Optional[int] = Field(
        default=None, description="Set on /api/projects/{id}/latest-scan -- lets callers key a solutions cache."
    )
    tickets: List[TicketInfo] = Field(
        default_factory=list,
        description="Set on /api/projects/{id}/latest-scan -- lets the client re-evaluate a single ticket "
        "(POST /api/re-evaluate-ticket needs the ticket's full data, not just its prior result).",
    )


class ErrorResponse(BaseModel):
    detail: str


class ExcelPreviewResponse(BaseModel):
    """Raw preview of an uploaded Excel file, for manual column mapping."""
    sheet_name: str
    header_row: Optional[int] = None
    headers: List[str]
    preview_rows: List[List[str]]
    suggested_mapping: dict = Field(
        default_factory=dict,
        description="field -> column index (0-based) guessed via the existing alias matcher, or null",
    )


class AnalysisRequest(BaseModel):
    """Request body shared by /api/risk and /api/solutions: the tickets and
    their already-computed evaluation results, so no re-scan is needed.
    scan_run_id is /api/solutions-only: when given, its AI synthesis is
    cached (project_solutions table) keyed by this id, so re-opening the
    Solutions page for the same saved scan reuses the cached result instead
    of paying for a fresh LLM call every time. Left None for the in-memory/
    mock-detail case, where there's no real scan_run_id to key on."""
    tickets: List[TicketInfo]
    results: List[TicketResult]
    scan_run_id: Optional[int] = None
    scanned_files: int = Field(
        default=0,
        description="/api/recompute-summary only -- the last known scanned-files count, carried through "
        "unchanged since a single-ticket re-evaluation doesn't rescan the whole source tree.",
    )


class RecomputeSummaryResponse(BaseModel):
    """Pure recomputation of summary/health/trend from an already-evaluated
    ticket+result set -- no AI call. Used after a single-ticket
    re-evaluation (POST /api/re-evaluate-ticket) patches one result in
    place, so the aggregate rollup (StatCards/ProjectHealthPanel/
    ProjectTrendChart) reflects the change instead of showing stale totals
    from the last full scan."""
    summary: Summary
    health: ProjectHealth
    trend: ProjectTrend


class ReportRequest(AnalysisRequest):
    """Request body for /api/report: same tickets + already-computed
    results as AnalysisRequest, plus the project name to put on the
    Summary sheet (no re-scan needed -- summary/health are recomputed
    server-side from `results`, same as /api/risk and /api/solutions do)."""
    project_name: str = ""


class RiskItem(BaseModel):
    """Per-ticket risk score derived from its evaluation result."""
    ticket_id: str
    summary: str
    risk_score: float = Field(..., ge=0, le=100)
    severity: str = Field(..., description="Critical / High / Medium / Low")
    factors: List[str] = Field(default_factory=list)
    recommended_action: str = ""
    assessment: str
    schedule_status: str = ""
    completion_percent: float
    confidence: float


class ProjectRisk(BaseModel):
    """Project-wide risk rollup."""
    items: List[RiskItem] = Field(default_factory=list)
    overall_risk_score: float = 0.0
    distribution: dict = Field(
        default_factory=dict, description="severity -> count, e.g. {'Critical':1,'High':2,...}"
    )
    message: str = ""


class SolutionItem(BaseModel):
    """One project-wide (not per-ticket) recommendation synthesized across
    all evaluated tickets."""
    title: str
    category: str = "Other"
    recommendation: str
    affected_tickets: List[str] = Field(default_factory=list)
    priority: str = Field(default="Medium", description="High / Medium / Low")
    rationale: str = ""


class ProjectSolutions(BaseModel):
    """Project-wide suggested-solutions rollup."""
    items: List[SolutionItem] = Field(default_factory=list)
    generated_by: str = Field(default="heuristic", description="'llm' or 'heuristic'")
    message: str = ""


class ModelConfigResponse(BaseModel):
    """Current LLM connection settings for the Model Configuration page.
    API keys are always masked (e.g. "sk-...a1b2") -- the full secret, once
    saved, is never sent back to the browser."""
    base_url: str
    model: str
    api_key_set: bool
    api_key_masked: str
    base_url_deep: str
    model_deep: str
    api_key_deep_set: bool
    api_key_deep_masked: str
    is_customized: bool = Field(description="True if any field is overridden in the database, else using server/.env defaults")
    updated_at: Optional[str] = None
    updated_by_name: Optional[str] = None
    db_configured: bool = Field(description="False when DATABASE_URL isn't set -- changes here can't be saved")


class ModelConfigUpdateRequest(BaseModel):
    """Save the Model Configuration page. base_url/model/base_url_deep/
    model_deep are stored exactly as submitted (empty string clears back to
    the .env default). api_key/api_key_deep are write-only and optional:
    omit (or send blank) to leave the currently-saved key untouched -- the
    page never pre-fills a real secret into the field, so blank must not be
    read as "clear it". Use clear_api_key/clear_api_key_deep to explicitly
    reset one back to its .env default."""
    base_url: Optional[str] = None
    model: Optional[str] = None
    base_url_deep: Optional[str] = None
    model_deep: Optional[str] = None
    api_key: Optional[str] = None
    clear_api_key: bool = False
    api_key_deep: Optional[str] = None
    clear_api_key_deep: bool = False


class ModelConfigTestRequest(BaseModel):
    """Test a candidate base_url/model/api_key combo BEFORE saving it --
    the Model Configuration page's "Test Connection" button sends whatever
    is currently typed in the form, not what's saved. api_key blank means
    "use the currently-saved key for this phase" (same convention as
    ModelConfigUpdateRequest), since the page never has the real saved
    secret to resend itself."""
    phase: str = Field(..., description="'phase1' or 'phase2' -- which saved API key to fall back to when api_key is blank")
    base_url: str
    model: str
    api_key: Optional[str] = None


class ModelConfigTestResponse(BaseModel):
    success: bool
    message: str
    latency_ms: Optional[int] = None


class MemberPerformanceProject(BaseModel):
    """One assignee's rollup within a single project, for the Member
    Performance page's per-project drill-down."""
    project_id: int
    project_name: str
    total: int
    complete: int
    late: int


class MemberPerformanceItem(BaseModel):
    """One assignee's rollup across every project's latest snapshot scan --
    see server/member_performance.py for how `assignee_key` is resolved
    (Jira accountId when available, else a normalized display name)."""
    assignee_key: str
    display_name: str
    total: int
    complete: int
    in_process: int
    late: int
    match_count: int
    mismatch_count: int
    incomplete_count: int
    projects: List[MemberPerformanceProject] = Field(default_factory=list)


class RegisterRequest(BaseModel):
    name: str = Field(..., min_length=1)
    email: str = Field(..., min_length=3)
    password: str = Field(..., min_length=6)


class LoginRequest(BaseModel):
    email: str
    password: str


class UserOut(BaseModel):
    id: int
    name: str
    email: str
    role: str


class ProjectMemberRequest(BaseModel):
    """Grant/revoke a specific user's visibility into a specific project
    (project_members) -- not a role, purely a visibility grant. Owner/Admin
    only (see main.py's require_member_management)."""
    user_id: int


class AuthResponse(BaseModel):
    token: str
    user: UserOut


class InviteMemberRequest(BaseModel):
    name: str = Field(..., min_length=1)
    email: str = Field(..., min_length=3)
    role: str = Field(default="Viewer")


class MemberOut(BaseModel):
    id: int
    name: str
    email: str
    role: str
    status: str = Field(..., description="'active' or 'pending'")
    groups: List[str] = Field(default_factory=list)


class InviteMemberResponse(BaseModel):
    member: MemberOut
    email_sent: bool
    invite_link: Optional[str] = None
    message: str = ""


class UpdateRoleRequest(BaseModel):
    role: str


class CreateGroupRequest(BaseModel):
    name: str = Field(..., min_length=1)
    member_emails: List[str] = Field(default_factory=list)
    role: str = Field(default="Viewer")


class InviteOutcome(BaseModel):
    email: str
    status: str = Field(..., description="'email_sent' / 'link_only' / 'already_active' / 'failed'")
    invite_link: Optional[str] = None


class GroupOut(BaseModel):
    id: int
    name: str
    members: List[MemberOut] = Field(default_factory=list)


class CreateGroupResponse(BaseModel):
    group: GroupOut
    results: List[InviteOutcome] = Field(default_factory=list)


class InvitePreview(BaseModel):
    name: str
    email: str
    role: str
    group_name: Optional[str] = None


class AcceptInviteRequest(BaseModel):
    name: str = Field(..., min_length=1)
    password: str = Field(..., min_length=6)


class JiraConnectRequest(BaseModel):
    site_url: str
    project_key: str
    email: str
    api_token: str


class JiraConnectResponse(BaseModel):
    connected: bool
    ticket_count: int
    message: str = ""


class GitConnectRequest(BaseModel):
    repo_url: str
    branch: str = "main"
    git_token: str = ""
    git_username: str = ""


class GitConnectResponse(BaseModel):
    connected: bool
    commit_sha: str
    message: str = ""


class GitJiraScanRequest(BaseModel):
    repo_url: str
    branch: str = "main"
    git_token: str = ""
    git_provider: str = ""
    doc_path: str = ""
    source_path: str = ""
    enable_deep_dive: bool = Field(
        default=False,
        description="Layer 4: agentic deep-dive (local clone + tool-calling LLM) for low-confidence/Incomplete tickets. Slower and more costly than Layers 1-3, so opt-in.",
    )
    deep_dive_threshold: float = Field(
        default=0.6, ge=0, le=1, description="Confidence below which a ticket is escalated to Layer 4, in addition to any 'Incomplete' assessment."
    )
    jira_site_url: str
    jira_project_key: str
    jira_email: str
    jira_api_token: str
    project_id: Optional[int] = Field(
        default=None,
        description="Existing-project re-run only -- lets the backend look up each ticket's last real "
        "evaluation to skip re-running AI on ones that haven't changed (see reeval_cache.py). Omit for a "
        "brand-new project (nothing to compare against yet).",
    )
    force_full_reevaluate: bool = Field(
        default=False,
        description="Bypass the re-evaluation cache above and run every ticket through AI fresh, even if "
        "reeval_cache would otherwise skip it.",
    )
    job_id: Optional[str] = Field(
        default=None,
        description="Client-generated id (e.g. crypto.randomUUID()) this run's progress is reported under -- "
        "poll GET /api/scan-progress/{job_id} while this request is in flight. Omit for no progress tracking.",
    )


class GitJiraScanResponse(BaseModel):
    tickets: List[TicketInfo]
    results: List[TicketResult]
    summary: Summary
    health: ProjectHealth
    trend: ProjectTrend
    commit_sha: Optional[str] = Field(
        default=None,
        description="Full commit SHA of the scanned branch's HEAD at scan time, if it could be determined. "
        "Round-tripped back through SaveScanRunRequest.commit_sha so the NEXT re-run's reeval_cache can tell "
        "whether the repo has moved since.",
    )


class SaveScanRunRequest(BaseModel):
    """Persist a completed evaluate run (Check Health Project) as a
    scan_runs row + its per-ticket evaluation_results, for Trend/History.

    The connection fields below (repo_url/branch/jira_*/excel_*) are
    optional and, when given, get upserted into project_git_connections /
    project_ticket_connections so the Project List / "existing project"
    picker knows this project's real source (e.g. so Connect Git/Jira's
    re-run mode can tell a Jira-sourced project from an Excel-sourced one
    instead of always assuming Excel). Deliberately NEVER includes any
    token/password -- only non-secret identifiers, per the same
    never-persist-credentials rule the rest of this app follows."""
    project_id: int
    run_type: str = Field(..., description="'new_check' or 'existing_rerun'")
    scope: str = Field(default="all", description="'all' / 'sprint' / 'custom'")
    scope_note: Optional[str] = None
    upload_id: Optional[str] = None
    is_snapshot: bool = Field(default=True, description="'Save as new snapshot' checkbox")
    tickets: List[TicketInfo]
    results: List[TicketResult]
    summary: Summary
    health_status: str = Field(..., description="OK / Risk / Late")
    repo_url: Optional[str] = None
    branch: Optional[str] = None
    doc_path: Optional[str] = Field(
        default=None,
        description="Connect Git/Jira's 'restrict doc scan to this subfolder' field -- stored on "
        "project_git_connections so Project Detail's per-ticket re-scan can reapply the same scoping.",
    )
    source_path: Optional[str] = Field(
        default=None,
        description="Connect Git/Jira's 'restrict source scan to this subfolder' field -- stored on "
        "project_git_connections so Project Detail's per-ticket re-scan can reapply the same scoping.",
    )
    source_type: Optional[str] = Field(
        default=None, description="'jira' / 'excel' / 'manual' -- which ticket source produced this run's tickets"
    )
    jira_site_url: Optional[str] = None
    jira_project_key: Optional[str] = None
    excel_filename: Optional[str] = None
    excel_mapping: Optional[Dict] = None
    commit_sha: Optional[str] = Field(
        default=None,
        description="From GitJiraScanResponse.commit_sha -- stored on scan_runs.source_commit so a later "
        "re-run's reeval_cache can tell whether the repo has moved since this snapshot.",
    )


class SaveScanRunResponse(BaseModel):
    scan_run_id: int
    completed_at: Optional[str] = None


class CreateProjectRequest(BaseModel):
    """Auto-create a project for Check Health Project's "New project" real-
    scan flow, named from the connected Git repo or the uploaded ZIP."""
    name: str = Field(..., min_length=1)


class CreateProjectResponse(BaseModel):
    id: int
    name: str
    created: bool = Field(..., description="False if a project with this name already existed and was reused")


class ScanRunSnapshot(BaseModel):
    """One Trend History row: a past snapshot scan_runs row for a project."""
    completed_at: Optional[str] = None
    health_score: Optional[int] = None
    late_ticket_count: Optional[int] = None
    mismatch_count: Optional[int] = None
    scope_note: Optional[str] = None