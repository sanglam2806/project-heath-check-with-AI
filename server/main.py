"""
FastAPI application for Project Health Checker.
Exposes endpoints for uploading a project ZIP, scanning source code
against tickets, and evaluating with LLM.
"""
import asyncio
import json
import logging
import os
import shutil
import time
import uuid
import zipfile
from concurrent.futures import ThreadPoolExecutor
from datetime import date
from pathlib import Path
from typing import Dict, List, Optional

from fastapi import Depends, FastAPI, File, Form, Header, HTTPException, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, StreamingResponse
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from models import (
    AcceptInviteRequest,
    AnalysisRequest,
    AuthResponse,
    CreateGroupRequest,
    CreateGroupResponse,
    CreateProjectRequest,
    CreateProjectResponse,
    EvaluateRequest,
    EvaluateResponse,
    ExcelPreviewResponse,
    GitConnectRequest,
    GitConnectResponse,
    GitJiraScanRequest,
    GitJiraScanResponse,
    GroupOut,
    InviteMemberRequest,
    InviteMemberResponse,
    InviteOutcome,
    InvitePreview,
    JiraConnectRequest,
    JiraConnectResponse,
    LoginRequest,
    MemberOut,
    MemberPerformanceItem,
    ModelConfigResponse,
    ModelConfigTestRequest,
    ModelConfigTestResponse,
    ModelConfigUpdateRequest,
    ProjectMemberRequest,
    ProjectRisk,
    ProjectSolutions,
    ReEvaluateTicketRequest,
    RecomputeSummaryResponse,
    RegisterRequest,
    ReportRequest,
    SaveScanRunRequest,
    SaveScanRunResponse,
    ScanProgressResponse,
    ScanRequest,
    ScanRunSnapshot,
    Summary,
    TicketInfo,
    TicketResult,
    UpdateRoleRequest,
    UploadResponse,
    UserOut,
)
from scanner import (
    count_scanned_files,
    enrich_scan_result_with_docs,
    scan_source_for_tickets,
)
from evaluator import evaluate_with_llm
from excel_parser import (
    parse_tickets_from_excel,
    parse_tickets_from_excel_with_mapping,
    read_excel_preview,
    tickets_to_tsv,
)
from health import build_project_health
from risk import build_project_risk
from solutions import build_project_solutions
from trend import build_project_trend
import auth
import db
import deep_dive_agent
import git_client
import git_files_db
import git_scan
import git_workspace
import groups as groups_db
import i18n
import jira_client
import mailer
import members as members_db
import member_performance
import model_config
import projects as projects_db
import reeval_cache
import report
import scan_progress
import scan_runs as scan_runs_db
import solutions_db
import uploads_db

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI(
    title="Project Health Checker",
    description="Compare ticket progress against actual source code.",
    version="1.0.0",
)

# Allow the Vite dev server (and any local frontend) to call the API
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173",
        "http://127.0.0.1:5173",
        "http://localhost:4173",
        "http://127.0.0.1:4173",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.exception_handler(i18n.TranslatableError)
async def translatable_error_handler(request: Request, exc: i18n.TranslatableError):
    """Every user-facing backend error is a TranslatableError raised from
    anywhere (endpoints, jira_client, git_client, git_scan, auth, groups,
    projects, excel_parser) — this single handler is what actually
    translates it, based on the request's X-Language header, so individual
    endpoints never need to thread a language parameter through."""
    lang = i18n.language_from_header(request.headers.get("x-language"))
    return JSONResponse(
        status_code=exc.status_code,
        content={"detail": i18n.translate(exc.key, lang, **exc.kwargs)},
    )


def get_language(x_language: Optional[str] = Header(default=None)) -> str:
    """Dependency for the handful of endpoints that need the language to
    build a translated *success* message (translatable errors don't need
    this — see translatable_error_handler above)."""
    return i18n.language_from_header(x_language)


# Thread pool for CPU/IO-bound scanning work
_executor = ThreadPoolExecutor(max_workers=4)

# Storage for uploaded archives (in-memory map: upload_id -> extracted dir)
_UPLOADS_DIR = Path(__file__).resolve().parent / "uploads"
_UPLOADS_DIR.mkdir(parents=True, exist_ok=True)
_active_uploads: Dict[str, str] = {}  # upload_id -> extracted directory


@app.get("/health")
async def health_check():
    """Simple liveness probe. Also reports PostgreSQL connectivity when
    DATABASE_URL is configured — the app runs fine without it (mock data) —
    and whether THIS running process can see the `git` binary on PATH
    (required for git_workspace.clone_repo -- Layer-4 deep-dive and the
    local-clone source/doc reading in git_scan.py). Checking this via the
    running process itself (shutil.which), rather than a separate terminal,
    matters because a process started before `git` was installed keeps its
    PATH as of startup — installing Git afterward doesn't retroactively fix
    it, only a genuine restart of this backend process does."""
    if not db.is_configured():
        database_status = "not_configured"
    else:
        connected = await asyncio.get_event_loop().run_in_executor(_executor, db.check_connection)
        database_status = "connected" if connected else "unavailable"
    git_path = shutil.which("git")
    return {
        "status": "ok",
        "timestamp": time.time(),
        "database": database_status,
        "git": {"available": bool(git_path), "path": git_path},
    }


def _require_db():
    if not db.is_configured():
        raise HTTPException(status_code=503, detail="Database not configured. Set DATABASE_URL in server/.env.")


# Project visibility: Owner/Admin see every project. Editor/Viewer only see
# projects they themselves have checked (projects.owner_id, stamped by
# save_scan_run onto whoever is logged in when a scan is saved).
_CAN_VIEW_ALL_PROJECTS_ROLES = {"Owner", "Admin"}


async def _check_project_visibility(project: Dict, current_user: Dict) -> None:
    if current_user["role"] in _CAN_VIEW_ALL_PROJECTS_ROLES:
        return
    if project.get("owner_id") == current_user["id"]:
        return
    has_access = await asyncio.get_event_loop().run_in_executor(
        _executor, projects_db.user_has_project_access, project["id"], current_user["id"]
    )
    if not has_access:
        raise i18n.TranslatableError("main.project_forbidden", status_code=403)


_bearer_scheme = HTTPBearer(auto_error=False)


async def get_current_user(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(_bearer_scheme),
) -> Dict:
    """Auth dependency for every protected endpoint. Raises 401 uniformly
    for a missing, invalid, or expired token, so the frontend can treat any
    401 response as "log the user out" without distinguishing the cause."""
    if credentials is None:
        raise i18n.TranslatableError("auth.not_authenticated", status_code=401)
    payload = auth.decode_access_token(credentials.credentials)
    if not payload:
        raise i18n.TranslatableError("auth.invalid_or_expired_token", status_code=401)
    _require_db()
    user = await asyncio.get_event_loop().run_in_executor(_executor, auth.get_user_by_id, int(payload["sub"]))
    if not user:
        raise i18n.TranslatableError("auth.user_not_found", status_code=401)
    return user


# Member Management (invite/change role/groups) and the Check Health Project
# flows (Connect Git/Jira, Upload ZIP/Excel, and Project List's Re-check
# button, which all end up hitting these same trigger endpoints) are each
# gated to one role set, defined once here rather than repeated per endpoint.
_MEMBER_MANAGEMENT_ROLES = {"Owner", "Admin"}
_CHECK_HEALTH_ROLES = {"Owner", "Admin", "Editor"}


async def require_member_management(current_user: Dict = Depends(get_current_user)) -> Dict:
    if current_user["role"] not in _MEMBER_MANAGEMENT_ROLES:
        raise i18n.TranslatableError("main.member_management_forbidden", status_code=403)
    return current_user


async def require_check_health_role(current_user: Dict = Depends(get_current_user)) -> Dict:
    if current_user["role"] not in _CHECK_HEALTH_ROLES:
        raise i18n.TranslatableError("main.check_health_forbidden", status_code=403)
    return current_user


@app.post("/api/auth/register", response_model=AuthResponse)
async def register_endpoint(request: RegisterRequest):
    _require_db()
    try:
        user = await asyncio.get_event_loop().run_in_executor(
            _executor, auth.register_user, request.name, request.email, request.password
        )
    except i18n.TranslatableError:
        raise
    except Exception as exc:  # pragma: no cover
        logger.exception("Registration failed")
        raise HTTPException(status_code=500, detail=f"Registration failed: {exc}")
    token = auth.create_access_token(user["id"])
    return AuthResponse(token=token, user=user)


@app.post("/api/auth/login", response_model=AuthResponse)
async def login_endpoint(request: LoginRequest):
    _require_db()
    try:
        user = await asyncio.get_event_loop().run_in_executor(
            _executor, auth.authenticate_user, request.email, request.password
        )
    except i18n.TranslatableError:
        raise
    except Exception as exc:  # pragma: no cover
        logger.exception("Login failed")
        raise HTTPException(status_code=500, detail=f"Login failed: {exc}")
    if not user:
        raise i18n.TranslatableError("auth.invalid_credentials", status_code=401)
    token = auth.create_access_token(user["id"])
    return AuthResponse(token=token, user=user)


@app.get("/api/auth/me", response_model=UserOut)
async def me_endpoint(current_user: Dict = Depends(get_current_user)):
    return current_user


def _send_invite_or_link(member: Dict, token: Optional[str], inviter_name: str, group_name: Optional[str] = None) -> Dict:
    """token is None when the member is already active — nothing to send.
    Otherwise tries a real email (when SMTP is configured) and always
    returns the link too, so the caller can fall back to "copy this link"."""
    if token is None:
        return {"email_sent": False, "invite_link": None}
    link = mailer.build_invite_link(token)
    email_sent = False
    if mailer.is_configured():
        try:
            mailer.send_invite_email(member["email"], member["name"], link, inviter_name, group_name)
            email_sent = True
        except Exception:  # pragma: no cover
            logger.exception("Failed to send invite email to %s", member["email"])
    return {"email_sent": email_sent, "invite_link": link}


@app.get("/api/members", response_model=List[MemberOut])
async def list_members_endpoint(current_user: Dict = Depends(require_member_management)):
    _require_db()
    try:
        return await asyncio.get_event_loop().run_in_executor(_executor, members_db.list_members)
    except Exception as exc:  # pragma: no cover
        logger.exception("Failed to list members")
        raise HTTPException(status_code=500, detail=f"Failed to list members: {exc}")


@app.get("/api/member-performance", response_model=List[MemberPerformanceItem])
async def member_performance_endpoint(current_user: Dict = Depends(require_member_management)):
    """Cross-project rollup (Total/Complete/In Process/Late per assignee,
    across every project's latest snapshot scan) -- see
    member_performance.py for how assignees are matched across projects."""
    _require_db()
    try:
        return await asyncio.get_event_loop().run_in_executor(_executor, member_performance.build_member_performance)
    except Exception as exc:  # pragma: no cover
        logger.exception("Failed to build member performance")
        raise HTTPException(status_code=500, detail=f"Failed to build member performance: {exc}")


@app.patch("/api/members/{member_id}/role", response_model=MemberOut)
async def update_member_role_endpoint(
    member_id: int, request: UpdateRoleRequest, current_user: Dict = Depends(require_member_management)
):
    _require_db()
    try:
        return await asyncio.get_event_loop().run_in_executor(
            _executor, members_db.update_member_role, member_id, request.role
        )
    except Exception as exc:  # pragma: no cover
        logger.exception("Failed to update member role")
        raise HTTPException(status_code=500, detail=f"Failed to update role: {exc}")


@app.post("/api/members/invite", response_model=InviteMemberResponse)
async def invite_member_endpoint(
    request: InviteMemberRequest,
    current_user: Dict = Depends(require_member_management),
    lang: str = Depends(get_language),
):
    _require_db()
    try:
        member, token = await asyncio.get_event_loop().run_in_executor(
            _executor, members_db.create_or_reuse_invite, request.name, request.email, request.role, current_user["id"]
        )
    except Exception as exc:  # pragma: no cover
        logger.exception("Failed to create invite")
        raise HTTPException(status_code=500, detail=f"Failed to create invite: {exc}")

    if token is None:
        return InviteMemberResponse(
            member=member, email_sent=False, invite_link=None, message=i18n.translate("main.email_already_active", lang)
        )

    send_result = await asyncio.get_event_loop().run_in_executor(
        _executor, _send_invite_or_link, member, token, current_user["name"], None
    )
    message = i18n.translate(
        "main.invite_email_sent" if send_result["email_sent"] else "main.invite_smtp_not_configured", lang
    )
    return InviteMemberResponse(
        member=member, email_sent=send_result["email_sent"], invite_link=send_result["invite_link"], message=message
    )


@app.get("/api/groups", response_model=List[GroupOut])
async def list_groups_endpoint(current_user: Dict = Depends(require_member_management)):
    _require_db()
    try:
        return await asyncio.get_event_loop().run_in_executor(_executor, groups_db.list_groups)
    except Exception as exc:  # pragma: no cover
        logger.exception("Failed to list groups")
        raise HTTPException(status_code=500, detail=f"Failed to list groups: {exc}")


@app.post("/api/groups", response_model=CreateGroupResponse)
async def create_group_endpoint(request: CreateGroupRequest, current_user: Dict = Depends(require_member_management)):
    _require_db()
    try:
        group = await asyncio.get_event_loop().run_in_executor(
            _executor, groups_db.create_group, request.name, current_user["id"]
        )
    except i18n.TranslatableError:
        raise
    except Exception as exc:  # pragma: no cover
        logger.exception("Failed to create group")
        raise HTTPException(status_code=500, detail=f"Failed to create group: {exc}")

    results: List[InviteOutcome] = []
    for raw_email in request.member_emails:
        email = raw_email.strip()
        if not email:
            continue
        try:
            member, token = await asyncio.get_event_loop().run_in_executor(
                _executor, members_db.create_or_reuse_invite, "", email, request.role, current_user["id"]
            )
            await asyncio.get_event_loop().run_in_executor(_executor, groups_db.add_member, group["id"], member["id"])
            if token is None:
                results.append(InviteOutcome(email=email, status="already_active"))
            else:
                send_result = await asyncio.get_event_loop().run_in_executor(
                    _executor, _send_invite_or_link, member, token, current_user["name"], group["name"]
                )
                results.append(
                    InviteOutcome(
                        email=email,
                        status="email_sent" if send_result["email_sent"] else "link_only",
                        invite_link=None if send_result["email_sent"] else send_result["invite_link"],
                    )
                )
        except Exception:  # pragma: no cover
            logger.exception("Failed to invite %s to group %s", email, group["id"])
            results.append(InviteOutcome(email=email, status="failed"))

    full_group = await asyncio.get_event_loop().run_in_executor(_executor, groups_db.get_group, group["id"])
    return CreateGroupResponse(group=full_group, results=results)


@app.post("/api/groups/{group_id}/invite", response_model=List[InviteOutcome])
async def invite_group_endpoint(group_id: int, current_user: Dict = Depends(require_member_management)):
    """Re-invite whichever members of this group are still pending."""
    _require_db()
    group = await asyncio.get_event_loop().run_in_executor(_executor, groups_db.get_group, group_id)
    if not group:
        raise i18n.TranslatableError("groups.not_found", status_code=404, group_id=group_id)

    results: List[InviteOutcome] = []
    for member in group["members"]:
        if member["status"] == "active":
            results.append(InviteOutcome(email=member["email"], status="already_active"))
            continue
        try:
            refreshed, token = await asyncio.get_event_loop().run_in_executor(
                _executor,
                members_db.create_or_reuse_invite,
                member["name"],
                member["email"],
                member["role"],
                current_user["id"],
            )
            send_result = await asyncio.get_event_loop().run_in_executor(
                _executor, _send_invite_or_link, refreshed, token, current_user["name"], group["name"]
            )
            results.append(
                InviteOutcome(
                    email=member["email"],
                    status="email_sent" if send_result["email_sent"] else "link_only",
                    invite_link=None if send_result["email_sent"] else send_result["invite_link"],
                )
            )
        except Exception:  # pragma: no cover
            logger.exception("Failed to re-invite %s", member["email"])
            results.append(InviteOutcome(email=member["email"], status="failed"))
    return results


@app.get("/api/model-config", response_model=ModelConfigResponse)
async def get_model_config_endpoint(current_user: Dict = Depends(require_member_management)):
    """Model Configuration page's current settings (Owner/Admin only) --
    API keys are always masked, never sent back in full. Works even without
    DATABASE_URL configured (shows the server/.env defaults read-only;
    db_configured=False tells the frontend Save will fail)."""
    loop = asyncio.get_event_loop()
    settings = await loop.run_in_executor(_executor, model_config.get_llm_settings)
    db_row = await loop.run_in_executor(_executor, model_config.get_db_row) if db.is_configured() else None

    updated_by_name = None
    updated_at = None
    is_customized = False
    if db_row:
        is_customized = any(db_row.get(f) for f in ("api_key", "base_url", "model", "api_key_deep", "base_url_deep", "model_deep"))
        updated_at = db_row["updated_at"].isoformat() if db_row.get("updated_at") else None
        if db_row.get("updated_by"):
            user = await loop.run_in_executor(_executor, auth.get_user_by_id, db_row["updated_by"])
            updated_by_name = user["name"] if user else None

    return ModelConfigResponse(
        base_url=settings["base_url"],
        model=settings["model"],
        api_key_set=bool(db_row and db_row.get("api_key")),
        api_key_masked=model_config.mask_secret(db_row.get("api_key") if db_row else None),
        base_url_deep=settings["base_url_deep"],
        model_deep=settings["model_deep"],
        api_key_deep_set=bool(db_row and db_row.get("api_key_deep")),
        api_key_deep_masked=model_config.mask_secret(db_row.get("api_key_deep") if db_row else None),
        is_customized=is_customized,
        updated_at=updated_at,
        updated_by_name=updated_by_name,
        db_configured=db.is_configured(),
    )


@app.put("/api/model-config", response_model=ModelConfigResponse)
async def update_model_config_endpoint(
    request: ModelConfigUpdateRequest, current_user: Dict = Depends(require_member_management)
):
    """Save the Model Configuration page. Requires DATABASE_URL (there's
    nowhere to persist this otherwise) -- see ModelConfigUpdateRequest for
    the "leave blank to keep the saved API key" convention."""
    _require_db()
    await asyncio.get_event_loop().run_in_executor(
        _executor,
        model_config.save_config,
        current_user["id"],
        request.base_url,
        request.model,
        request.base_url_deep,
        request.model_deep,
        request.api_key,
        request.clear_api_key,
        request.api_key_deep,
        request.clear_api_key_deep,
    )
    return await get_model_config_endpoint(current_user)


@app.post("/api/model-config/test", response_model=ModelConfigTestResponse)
async def test_model_config_endpoint(
    request: ModelConfigTestRequest, current_user: Dict = Depends(require_member_management)
):
    """Test a candidate base_url/model/api_key combo BEFORE saving it --
    sends one minimal real chat completion. api_key blank falls back to
    the currently-saved key for `phase` (the page never has the real saved
    secret to resend), which also lets an admin test just a new model name
    against the already-saved key without retyping it."""
    if request.phase not in ("phase1", "phase2"):
        raise HTTPException(status_code=400, detail="phase must be 'phase1' or 'phase2'.")

    base_url = (request.base_url or "").strip()
    model = (request.model or "").strip()
    if not base_url or not model:
        raise HTTPException(status_code=400, detail="Base URL and model name are required.")

    api_key = (request.api_key or "").strip()
    if not api_key:
        settings = model_config.get_llm_settings()
        api_key = settings["api_key"] if request.phase == "phase1" else settings["api_key_deep"]

    result = await asyncio.get_event_loop().run_in_executor(
        _executor, model_config.test_connection, api_key, base_url, model
    )
    return ModelConfigTestResponse(**result)


@app.get("/api/invites/{token}", response_model=InvitePreview)
async def get_invite_preview_endpoint(token: str):
    """Public — no login required, this is what the Accept-Invite page
    calls before the recipient has any account at all."""
    _require_db()
    preview = await asyncio.get_event_loop().run_in_executor(_executor, members_db.get_invite_preview, token)
    if not preview:
        raise i18n.TranslatableError("main.invite_not_found", status_code=404)
    return preview


@app.post("/api/invites/{token}/accept", response_model=AuthResponse)
async def accept_invite_endpoint(token: str, request: AcceptInviteRequest):
    """Public — sets the invited user's password and auto-logs them in,
    same shape as register/login."""
    _require_db()
    user = await asyncio.get_event_loop().run_in_executor(
        _executor, members_db.accept_invite, token, request.name, request.password
    )
    if not user:
        raise i18n.TranslatableError("main.invite_not_found", status_code=404)
    access_token = auth.create_access_token(user["id"])
    return AuthResponse(token=access_token, user=user)


@app.post("/api/jira/connect", response_model=JiraConnectResponse)
async def jira_connect_endpoint(
    request: JiraConnectRequest,
    current_user: Dict = Depends(require_check_health_role),
    lang: str = Depends(get_language),
):
    """Tests a real Jira connection (Basic Auth) and counts the tickets in
    the given project. The email/API token are used only for this one
    outbound request and are never persisted."""
    try:
        ticket_count = await asyncio.get_event_loop().run_in_executor(
            _executor,
            jira_client.test_connection_and_count,
            request.site_url,
            request.project_key,
            request.email,
            request.api_token,
        )
    except i18n.TranslatableError:
        raise
    except Exception as exc:  # pragma: no cover
        logger.exception("Jira connect failed")
        raise HTTPException(status_code=500, detail=f"Jira connect failed: {exc}")
    return JiraConnectResponse(
        connected=True,
        ticket_count=ticket_count,
        message=i18n.translate("main.jira_connected", lang, count=ticket_count, project_key=request.project_key),
    )


@app.post("/api/git/connect", response_model=GitConnectResponse)
async def git_connect_endpoint(
    request: GitConnectRequest,
    current_user: Dict = Depends(require_check_health_role),
    lang: str = Depends(get_language),
):
    """Tests a real Git connection using the smart-HTTP refs handshake and
    confirms the given branch exists."""
    try:
        result = await asyncio.get_event_loop().run_in_executor(
            _executor, git_client.test_connection, request.repo_url, request.branch, request.git_token, request.git_username
        )
    except i18n.TranslatableError:
        raise
    except Exception as exc:  # pragma: no cover
        logger.exception("Git connect failed")
        raise HTTPException(status_code=500, detail=f"Git connect failed: {exc}")
    return GitConnectResponse(
        connected=True,
        commit_sha=result["commit_sha"],
        message=i18n.translate("main.git_connected", lang, branch=result["branch"], commit_sha=result["commit_sha"]),
    )


async def _apply_deep_dive(
    loop,
    repo_path: str,
    tickets: List[Dict],
    results: List[TicketResult],
    scan_result: Dict[str, Dict],
    threshold: float,
    job_id: str = "",
) -> List[TicketResult]:
    """Layer 4 core: for tickets Layers 1-3 left as "Incomplete" or below
    `threshold` confidence, run deep_dive_agent.run_deep_dive against
    `repo_path` (an already-available local directory -- a git clone for
    the Connect Git/Jira flow, or the already-extracted ZIP for the Upload
    flow; this function doesn't know or care which), with a small
    concurrency cap since the LLM round-trips (not local grep/read) are the
    bottleneck. Best-effort: any failure here (agent errored, LLM call
    failed) just logs a warning and leaves `results` exactly as Layers 1-3
    produced them -- Layer 4 can only improve on that, never break the scan.
    Does not touch `repo_path`'s lifecycle (clone/cleanup, or the ZIP
    upload's own extracted-dir bookkeeping) -- that's the caller's job."""
    flagged_ids = {
        r.ticket_id.upper() for r in results
        if not r.from_cache and (r.assessment == "Incomplete" or r.confidence < threshold)
    }
    if not flagged_ids:
        return results

    tickets_by_id = {t["ticket_id"].upper(): t for t in tickets}
    results_by_id = {r.ticket_id.upper(): r for r in results}

    scan_progress.update(job_id, phase="deep_dive", current=0, total=len(flagged_ids))
    completed = 0

    try:
        semaphore = asyncio.Semaphore(2)

        async def _deep_dive_one(tid: str):
            nonlocal completed
            async with semaphore:
                ticket = tickets_by_id.get(tid)
                prior = results_by_id.get(tid)
                if not ticket or not prior:
                    return tid, None
                docs = (scan_result.get(tid) or {}).get("docs") or []
                updated = await loop.run_in_executor(
                    _executor, deep_dive_agent.run_deep_dive, ticket, prior, repo_path, docs
                )
                completed += 1
                scan_progress.update(job_id, current=completed)
                return tid, updated

        for tid, updated in await asyncio.gather(*[_deep_dive_one(tid) for tid in flagged_ids]):
            if updated is not None:
                results_by_id[tid] = updated
    except Exception:  # pragma: no cover
        logger.exception("Layer 4 deep-dive failed")

    return [results_by_id.get(r.ticket_id.upper(), r) for r in results]


async def _run_deep_dive_layer(
    request: GitJiraScanRequest,
    loop,
    tickets: List[Dict],
    results: List[TicketResult],
    scan_result: Dict[str, Dict],
    workspace_path: Optional[str],
    job_id: str = "",
) -> List[TicketResult]:
    """Connect Git/Jira flow's Layer 4 entry point: resolves a local repo
    path (reusing `workspace_path` -- the same clone git_scan.fetch_git_evidence
    already made for source-code evidence -- or cloning its own copy if that
    one is None, e.g. fetch_git_evidence's clone attempt failed but
    deep-dive was still requested), then delegates to _apply_deep_dive.
    Does NOT clean up `workspace_path` if it didn't create it itself --
    that's the caller's (git_jira_scan_endpoint's) responsibility, since
    it's shared evidence."""
    owns_workspace = False
    try:
        if not workspace_path:
            workspace_path = await loop.run_in_executor(
                _executor, git_workspace.clone_repo, request.repo_url, request.branch, request.git_token
            )
            owns_workspace = True
        return await _apply_deep_dive(
            loop, workspace_path, tickets, results, scan_result, request.deep_dive_threshold, job_id
        )
    except i18n.TranslatableError as exc:
        logger.warning("Layer 4 deep-dive skipped (could not set up local clone): %s", exc)
        return results
    finally:
        if owns_workspace and workspace_path:
            await loop.run_in_executor(_executor, git_workspace.cleanup_workspace, workspace_path)


@app.post("/api/git-jira-scan", response_model=GitJiraScanResponse)
async def git_jira_scan_endpoint(request: GitJiraScanRequest, current_user: Dict = Depends(require_check_health_role)):
    """Real 3-layer scan for the Connect Git/Jira page: fetches the real
    ticket list from Jira, gathers Git evidence (branches/commits/PR-MR
    titles + diffs + repo tree), rule-based short-circuits obvious
    Done-but-no-code Mismatches (Layer 1), sends the rest to the LLM with
    real diffs as evidence (Layer 2 — reuses evaluate_with_llm unchanged),
    then verifies changed files actually exist on the target branch
    (Layer 3). If `enable_deep_dive`, an optional Layer 4 then re-examines
    whatever came out Incomplete/low-confidence with a tool-calling agent
    against a local clone of the repo (deep_dive_agent.py) — see
    _run_deep_dive_layer below."""
    loop = asyncio.get_event_loop()
    job_id = request.job_id or ""
    scan_progress.start(job_id, phase="scanning")

    try:
        tickets = await loop.run_in_executor(
            _executor,
            jira_client.fetch_tickets,
            request.jira_site_url,
            request.jira_project_key,
            request.jira_email,
            request.jira_api_token,
        )
    except i18n.TranslatableError as exc:
        scan_progress.finish(job_id, error=str(exc))
        raise
    if not tickets:
        scan_progress.finish(job_id, error="no_jira_tickets")
        raise i18n.TranslatableError("main.no_jira_tickets", status_code=400)

    # git_read_files has no project_id/scan_run_id column -- it's a
    # snapshot of the most recent scan's evidence only, so wipe it before
    # this scan starts writing new rows. Best-effort: a failure here must
    # never block the scan itself.
    if db.is_configured():
        try:
            await loop.run_in_executor(_executor, git_files_db.clear_all)
        except Exception:  # pragma: no cover
            logger.exception("Failed to clear git_read_files before scan")

    try:
        evidence = await loop.run_in_executor(
            _executor,
            git_scan.fetch_git_evidence,
            request.repo_url,
            request.branch,
            request.git_token,
            request.git_provider,
            request.doc_path,
            request.source_path,
        )
    except i18n.TranslatableError as exc:
        scan_progress.finish(job_id, error=str(exc))
        raise

    # fetch_git_evidence already cloned the repo locally (for reading full
    # source-code content -- see git_scan.py) when it could; reuse that same
    # clone for the Layer-4 deep-dive below instead of cloning again, and
    # clean it up here once everything that might touch it is done.
    workspace_path = evidence.get("workspace_path")
    try:
        scan_result, certain_mismatches, ticket_files = git_scan.build_scan_result(tickets, evidence)
        remaining = [t for t in tickets if t["ticket_id"].upper() not in certain_mismatches]

        # Re-evaluation cache (existing-project re-run only, reeval_cache.py):
        # skip an AI call for tickets whose status/content and the repo's
        # commit haven't changed since they were last found a Match --
        # this is where the actual time/token savings happen, since the
        # LLM calls (not evidence-gathering above, which is O(1) per run
        # regardless of ticket count) dominate the cost of a re-run.
        to_evaluate, cached_results, previous_by_id = await loop.run_in_executor(
            _executor,
            reeval_cache.partition,
            remaining,
            request.project_id,
            evidence.get("commit_sha"),
            request.force_full_reevaluate,
        )

        try:
            llm_results: List[TicketResult] = (
                await loop.run_in_executor(_executor, evaluate_with_llm, to_evaluate, scan_result, job_id)
                if to_evaluate
                else []
            )
        except Exception as exc:  # pragma: no cover
            logger.exception("Git/Jira evaluation failed")
            scan_progress.finish(job_id, error=str(exc))
            raise HTTPException(status_code=500, detail=f"Evaluation failed: {exc}")

        results = list(certain_mismatches.values()) + llm_results + cached_results
        results = [
            r if r.from_cache else r.model_copy(update={"previous_assessment": previous_by_id.get(r.ticket_id.upper())})
            for r in results
        ]
        results = git_scan.apply_repo_tree_check(results, ticket_files, evidence["tree_paths"], request.branch)

        if request.enable_deep_dive:
            results = await _run_deep_dive_layer(request, loop, tickets, results, scan_result, workspace_path, job_id)

        order = {t["ticket_id"].upper(): i for i, t in enumerate(tickets)}
        results.sort(key=lambda r: order.get(r.ticket_id.upper(), len(order)))

        scanned_files = len(evidence["tree_paths"])
        summary = _build_summary(results, scanned_files)
        health = build_project_health(tickets, results, date.today())
        trend = build_project_trend(tickets, results)
        scan_progress.finish(job_id)
        return GitJiraScanResponse(
            tickets=[TicketInfo(**t) for t in tickets],
            results=results,
            summary=summary,
            health=health,
            trend=trend,
            commit_sha=evidence.get("commit_sha"),
        )
    finally:
        if workspace_path:
            await loop.run_in_executor(_executor, git_workspace.cleanup_workspace, workspace_path)


@app.get("/api/projects")
async def list_projects_endpoint(current_user: Dict = Depends(get_current_user)):
    """Real project list (Dashboard, Project List, Check Health Project's
    existing-project picker) — replaces the frontend's former mock data.
    Editor/Viewer only get back projects they themselves have checked, or
    that an Owner/Admin explicitly shared with them (project_members)."""
    _require_db()
    user_id = None if current_user["role"] in _CAN_VIEW_ALL_PROJECTS_ROLES else current_user["id"]
    try:
        return await asyncio.get_event_loop().run_in_executor(_executor, projects_db.list_projects, user_id)
    except Exception as exc:  # pragma: no cover
        logger.exception("Failed to list projects")
        raise HTTPException(status_code=500, detail=f"Failed to list projects: {exc}")


@app.post("/api/projects", response_model=CreateProjectResponse)
async def create_project_endpoint(request: CreateProjectRequest, current_user: Dict = Depends(require_check_health_role)):
    """Find-or-create a project by name — backs Check Health Project's "New
    project" real-scan flow, which has no separate "create project" step and
    instead derives the name from the connected Git repo or ZIP filename."""
    _require_db()
    try:
        return await asyncio.get_event_loop().run_in_executor(
            _executor, projects_db.find_or_create_project, request.name
        )
    except i18n.TranslatableError:
        raise
    except Exception as exc:  # pragma: no cover
        logger.exception("Failed to create project")
        raise HTTPException(status_code=500, detail=f"Failed to create project: {exc}")


@app.get("/api/projects/{project_id}")
async def get_project_endpoint(project_id: int, current_user: Dict = Depends(get_current_user)):
    _require_db()
    try:
        project = await asyncio.get_event_loop().run_in_executor(_executor, projects_db.get_project, project_id)
    except Exception as exc:  # pragma: no cover
        logger.exception("Failed to get project")
        raise HTTPException(status_code=500, detail=f"Failed to get project: {exc}")
    if not project:
        raise HTTPException(status_code=404, detail=f"Project not found: {project_id}")
    await _check_project_visibility(project, current_user)
    return project


@app.get("/api/projects/{project_id}/members", response_model=List[UserOut])
async def list_project_members_endpoint(
    project_id: int, current_user: Dict = Depends(require_member_management)
):
    """Users explicitly granted visibility into this project (Owner/Admin
    only — same access level as the rest of Member Management). Does not
    include whoever the project's current owner_id happens to be (that's
    the separate, automatic "last checked by" slot)."""
    _require_db()
    loop = asyncio.get_event_loop()
    project = await loop.run_in_executor(_executor, projects_db.get_project, project_id)
    if not project:
        raise HTTPException(status_code=404, detail=f"Project not found: {project_id}")
    return await loop.run_in_executor(_executor, projects_db.list_project_members, project_id)


@app.post("/api/projects/{project_id}/members", response_model=List[UserOut])
async def add_project_member_endpoint(
    project_id: int, request: ProjectMemberRequest, current_user: Dict = Depends(require_member_management)
):
    """Grant `request.user_id` visibility into this project — purely a
    visibility grant, not a role change (their existing global role still
    governs what they can DO once they can see it)."""
    _require_db()
    loop = asyncio.get_event_loop()
    project = await loop.run_in_executor(_executor, projects_db.get_project, project_id)
    if not project:
        raise HTTPException(status_code=404, detail=f"Project not found: {project_id}")
    user = await loop.run_in_executor(_executor, auth.get_user_by_id, request.user_id)
    if not user:
        raise HTTPException(status_code=404, detail=f"User not found: {request.user_id}")
    await loop.run_in_executor(
        _executor, projects_db.add_project_member, project_id, request.user_id, current_user["id"]
    )
    return await loop.run_in_executor(_executor, projects_db.list_project_members, project_id)


@app.delete("/api/projects/{project_id}/members/{user_id}", response_model=List[UserOut])
async def remove_project_member_endpoint(
    project_id: int, user_id: int, current_user: Dict = Depends(require_member_management)
):
    _require_db()
    loop = asyncio.get_event_loop()
    await loop.run_in_executor(_executor, projects_db.remove_project_member, project_id, user_id)
    return await loop.run_in_executor(_executor, projects_db.list_project_members, project_id)


@app.post("/api/scan-runs", response_model=SaveScanRunResponse)
async def save_scan_run_endpoint(request: SaveScanRunRequest, current_user: Dict = Depends(require_check_health_role)):
    """Persist a completed Check Health Project run (real or existing-project
    re-run) as a scan_runs row + its per-ticket evaluation_results, so Trend
    History and future Dashboard reads can be backed by real data."""
    _require_db()
    project = await asyncio.get_event_loop().run_in_executor(
        _executor, projects_db.get_project, request.project_id
    )
    if not project:
        raise HTTPException(status_code=404, detail=f"Project not found: {request.project_id}")

    tickets = _tickets_to_dicts(request.tickets)
    results = [r.model_dump() for r in request.results]
    summary = request.summary.model_dump()
    try:
        result = await asyncio.get_event_loop().run_in_executor(
            _executor,
            scan_runs_db.save_scan_run,
            request.project_id,
            request.run_type,
            request.scope,
            request.scope_note,
            request.upload_id,
            request.is_snapshot,
            tickets,
            results,
            summary,
            request.health_status,
            current_user["id"],
            request.repo_url,
            request.branch,
            request.source_type,
            request.jira_site_url,
            request.jira_project_key,
            request.excel_filename,
            request.excel_mapping,
            request.commit_sha,
            request.doc_path,
            request.source_path,
        )
    except Exception as exc:  # pragma: no cover
        logger.exception("Failed to save scan run")
        raise HTTPException(status_code=500, detail=f"Failed to save scan run: {exc}")
    return result


@app.get("/api/projects/{project_id}/scan-runs", response_model=List[ScanRunSnapshot])
async def list_project_snapshots(project_id: int, current_user: Dict = Depends(get_current_user)):
    """Trend History rows for a project (Check Health Project's existing-
    project re-run view) — replaces the frontend's former localStorage-only
    snapshot store."""
    _require_db()
    project = await asyncio.get_event_loop().run_in_executor(_executor, projects_db.get_project, project_id)
    if not project:
        raise HTTPException(status_code=404, detail=f"Project not found: {project_id}")
    await _check_project_visibility(project, current_user)
    try:
        return await asyncio.get_event_loop().run_in_executor(
            _executor, scan_runs_db.list_snapshots, project_id
        )
    except Exception as exc:  # pragma: no cover
        logger.exception("Failed to list scan run snapshots")
        raise HTTPException(status_code=500, detail=f"Failed to list snapshots: {exc}")


@app.get("/api/projects/{project_id}/latest-scan", response_model=EvaluateResponse)
async def get_latest_scan_endpoint(project_id: int, current_user: Dict = Depends(get_current_user)):
    """Real per-ticket detail from the project's most recent snapshot scan
    run — backs Project Detail's ticket table. 404 when the project has
    never been scanned with per-ticket data saved (the frontend falls back
    to synthesized detail in that case, e.g. the seed_db.py demo rows)."""
    _require_db()
    project = await asyncio.get_event_loop().run_in_executor(_executor, projects_db.get_project, project_id)
    if not project:
        raise HTTPException(status_code=404, detail=f"Project not found: {project_id}")
    await _check_project_visibility(project, current_user)

    data = await asyncio.get_event_loop().run_in_executor(
        _executor, scan_runs_db.get_latest_scan_detail, project_id
    )
    if not data:
        raise HTTPException(status_code=404, detail="No saved per-ticket scan data for this project yet.")

    results = [TicketResult(**r) for r in data["results"]]
    summary = Summary(**data["summary"])
    health = build_project_health(data["tickets"], results, date.today())
    trend = build_project_trend(data["tickets"], results)
    tickets = [TicketInfo(**t) for t in data["tickets"]]
    return EvaluateResponse(
        results=results, summary=summary, health=health, trend=trend,
        scan_run_id=data.get("scan_run_id"), tickets=tickets,
    )


@app.post("/api/parse-excel")
async def parse_excel(file: UploadFile = File(...), current_user: Dict = Depends(require_check_health_role)):
    """
    Read an uploaded Excel file (.xlsx/.xlsm) containing ticket data and
    return the parsed tickets plus a TSV representation for the frontend.
    """
    if not file.filename:
        raise i18n.TranslatableError("main.no_file_provided", status_code=400)

    content = await file.read()
    try:
        tickets = parse_tickets_from_excel(content, file.filename)
    except i18n.TranslatableError:
        raise
    except Exception as exc:  # pragma: no cover
        logger.exception("Excel parse failed")
        raise HTTPException(status_code=500, detail=f"Failed to parse Excel: {exc}")

    return {
        "filename": file.filename,
        "ticket_count": len(tickets),
        "tickets": tickets,
        "tsv": tickets_to_tsv(tickets),
    }


@app.post("/api/excel-preview", response_model=ExcelPreviewResponse)
async def excel_preview(file: UploadFile = File(...), current_user: Dict = Depends(require_check_health_role)):
    """
    Return raw headers + a preview of the first few data rows from an
    uploaded Excel file, plus a best-effort suggested column mapping, so the
    frontend can render a manual column-mapping UI before parsing tickets.
    """
    if not file.filename:
        raise i18n.TranslatableError("main.no_file_provided", status_code=400)

    content = await file.read()
    try:
        preview = read_excel_preview(content, file.filename)
    except i18n.TranslatableError:
        raise
    except Exception as exc:  # pragma: no cover
        logger.exception("Excel preview failed")
        raise HTTPException(status_code=500, detail=f"Failed to preview Excel: {exc}")

    return preview


@app.post("/api/parse-excel-mapped")
async def parse_excel_mapped(
    file: UploadFile = File(...),
    mapping: str = Form(...),
    header_row: Optional[int] = Form(None),
    current_user: Dict = Depends(require_check_health_role),
):
    """
    Parse tickets from an uploaded Excel file using the caller's explicit
    column->field mapping (JSON-encoded) and header row, instead of alias
    auto-detection.
    """
    if not file.filename:
        raise i18n.TranslatableError("main.no_file_provided", status_code=400)

    try:
        mapping_dict = json.loads(mapping)
    except json.JSONDecodeError:
        raise i18n.TranslatableError("main.invalid_mapping_json", status_code=400)

    content = await file.read()
    try:
        tickets = parse_tickets_from_excel_with_mapping(
            content, file.filename, mapping_dict, header_row=header_row
        )
    except i18n.TranslatableError:
        raise
    except Exception as exc:  # pragma: no cover
        logger.exception("Mapped excel parse failed")
        raise HTTPException(status_code=500, detail=f"Failed to parse Excel: {exc}")

    return {
        "filename": file.filename,
        "ticket_count": len(tickets),
        "tickets": tickets,
        "tsv": tickets_to_tsv(tickets),
    }


@app.post("/api/upload", response_model=UploadResponse)
async def upload_archive(file: UploadFile = File(...), current_user: Dict = Depends(require_check_health_role)):
    """
    Accept a ZIP archive of the project source code, extract it, and
    return an upload_id for subsequent scan/evaluate calls.
    """
    if not file.filename or not file.filename.lower().endswith(".zip"):
        raise HTTPException(
            status_code=400,
            detail="Only .zip archives are accepted.",
        )

    upload_id = uuid.uuid4().hex[:12]
    dest_dir = _UPLOADS_DIR / upload_id
    dest_dir.mkdir(parents=True, exist_ok=False)

    zip_path = dest_dir / file.filename
    try:
        content = await file.read()
        zip_path.write_bytes(content)

        with zipfile.ZipFile(zip_path, "r") as zf:
            # Protect against Zip Slip: ensure all members stay inside dest_dir
            for member in zf.namelist():
                target = (dest_dir / member).resolve()
                if not str(target).startswith(str(dest_dir.resolve())):
                    raise HTTPException(
                        status_code=400,
                        detail=f"Unsafe path in archive: {member}",
                    )
            zf.extractall(dest_dir)

        # Remove the zip itself from the extracted tree
        zip_path.unlink(missing_ok=True)

        _active_uploads[upload_id] = str(dest_dir)
        logger.info("Uploaded %s -> %s (%d bytes)", file.filename, dest_dir, len(content))

        if db.is_configured():
            try:
                await asyncio.get_event_loop().run_in_executor(
                    _executor, uploads_db.record_upload, upload_id, file.filename, len(content), str(dest_dir)
                )
            except Exception:  # pragma: no cover
                # Non-fatal: the in-memory map above is what actually drives
                # scan/evaluate. Only scan_runs.upload_id linkage is lost.
                logger.exception("Failed to record upload in database")

        return UploadResponse(
            upload_id=upload_id,
            filename=file.filename,
            size=len(content),
            extracted_path=str(dest_dir),
        )
    except zipfile.BadZipFile:
        shutil.rmtree(dest_dir, ignore_errors=True)
        raise HTTPException(status_code=400, detail="Invalid ZIP file.")
    except Exception as exc:  # pragma: no cover
        shutil.rmtree(dest_dir, ignore_errors=True)
        logger.exception("Upload failed")
        raise HTTPException(status_code=500, detail=f"Upload failed: {exc}")


def _get_extracted_dir(upload_id: str) -> str:
    """Look up the extracted directory for an upload_id."""
    path = _active_uploads.get(upload_id)
    if not path or not os.path.isdir(path):
        raise HTTPException(status_code=404, detail=f"Upload not found: {upload_id}")
    return path


def _tickets_to_dicts(tickets: List[TicketInfo]) -> List[Dict]:
    return [
        {
            "ticket_id": t.ticket_id,
            "summary": t.summary,
            "status": t.status,
            "description": t.description,
            "due_date": t.due_date,
            "issue_type": t.issue_type,
            "assignee": t.assignee,
            "assignee_key": t.assignee_key,
        }
        for t in tickets
    ]


@app.post("/api/scan")
async def scan_project(request: ScanRequest, current_user: Dict = Depends(require_check_health_role)):
    """
    Scan the extracted source code for references to the given tickets.
    Returns per-ticket matched files plus the total scanned file count.
    """
    source_dir = _get_extracted_dir(request.upload_id)
    tickets = _tickets_to_dicts(request.tickets)

    try:
        # Not enriched with enrich_scan_result_with_docs here (unlike
        # /api/evaluate below) -- this endpoint returns scan_result directly
        # as JSON with no response_model, and enrichment would embed raw
        # image bytes into it, which isn't JSON-serializable. Harmless: the
        # frontend only awaits this call for the "Scanning code..." progress
        # step and discards the result; /api/evaluate independently
        # recomputes (and enriches) its own scan_result for real evaluation.
        scan_result = await asyncio.get_event_loop().run_in_executor(
            _executor, scan_source_for_tickets, source_dir, tickets
        )
        scanned_files = await asyncio.get_event_loop().run_in_executor(
            _executor, count_scanned_files, source_dir
        )
    except FileNotFoundError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except Exception as exc:  # pragma: no cover
        logger.exception("Scan failed")
        raise HTTPException(status_code=500, detail=f"Scan failed: {exc}")

    return {
        "scan_result": scan_result,
        "scanned_files": scanned_files,
    }


@app.post("/api/evaluate", response_model=EvaluateResponse)
async def evaluate_project(request: EvaluateRequest, current_user: Dict = Depends(require_check_health_role)):
    """
    Evaluate each ticket against the scanned source code using the LLM
    (fallback to heuristics if the LLM is unavailable).
    """
    source_dir = _get_extracted_dir(request.upload_id)
    tickets = _tickets_to_dicts(request.tickets)
    job_id = request.job_id or ""
    scan_progress.start(job_id, phase="scanning")

    try:
        scan_result = await asyncio.get_event_loop().run_in_executor(
            _executor, scan_source_for_tickets, source_dir, tickets
        )
        scan_result = await asyncio.get_event_loop().run_in_executor(
            _executor, enrich_scan_result_with_docs, scan_result, tickets, source_dir
        )
        scanned_files = await asyncio.get_event_loop().run_in_executor(
            _executor, count_scanned_files, source_dir
        )
    except FileNotFoundError as exc:
        scan_progress.finish(job_id, error=str(exc))
        raise HTTPException(status_code=400, detail=str(exc))

    loop = asyncio.get_event_loop()
    try:
        results: List[TicketResult] = await loop.run_in_executor(
            _executor, evaluate_with_llm, tickets, scan_result, job_id
        )
    except Exception as exc:  # pragma: no cover
        logger.exception("Evaluation failed")
        scan_progress.finish(job_id, error=str(exc))
        raise HTTPException(status_code=500, detail=f"Evaluation failed: {exc}")

    if request.enable_deep_dive:
        # Layer 4: no clone needed here (unlike the Connect Git/Jira flow) --
        # the ZIP is already extracted locally at source_dir, so the agent's
        # tools (code_tools.py) can browse it directly.
        results = await _apply_deep_dive(
            loop, source_dir, tickets, results, scan_result, request.deep_dive_threshold, job_id
        )

    summary = _build_summary(results, scanned_files)
    health = build_project_health(tickets, results, date.today())
    trend = build_project_trend(tickets, results)
    scan_progress.finish(job_id)
    return EvaluateResponse(results=results, summary=summary, health=health, trend=trend)


def _persist_single_ticket_result(project_id: int, ticket: Dict, updated_result: TicketResult) -> None:
    """Best-effort: after a single-ticket re-evaluation, patch that one
    evaluation_results row plus the scan_run's cached rollup counters into
    the project's latest saved snapshot, so the change survives a reload
    instead of only living in the requesting browser tab's React state.
    Silently no-ops if the project has no saved snapshot yet (nothing to
    patch into, e.g. a brand-new in-progress check that hasn't been saved) --
    the caller still returns the fresh result to the browser either way."""
    try:
        detail = scan_runs_db.get_latest_scan_detail(project_id)
        if not detail:
            return
        results = [TicketResult(**r) for r in detail["results"]]
        tid = updated_result.ticket_id.upper()
        if not any(r.ticket_id.upper() == tid for r in results):
            return  # ticket isn't part of this snapshot (renamed/removed since) -- nothing to patch
        results = [updated_result if r.ticket_id.upper() == tid else r for r in results]

        summary = _build_summary(results, detail["summary"].get("scanned_files", 0))
        health = build_project_health(detail["tickets"], results, date.today())
        rollup = {
            "total_tickets": summary.total_tickets,
            "match_count": summary.match_count,
            "mismatch_count": summary.mismatch_count,
            "incomplete_count": summary.incomplete_count,
            "match_percent": summary.match_percent,
            "avg_completion": summary.avg_completion,
            "health_status": health.status,
            "health_score": round(summary.avg_completion),
            "late_ticket_count": sum(1 for r in results if r.schedule_status == "Late"),
        }
        scan_runs_db.update_ticket_result_in_run(
            detail["scan_run_id"], ticket, updated_result.model_dump(), rollup
        )
    except Exception:  # pragma: no cover
        logger.exception("Failed to persist single-ticket re-evaluation")


@app.post("/api/re-evaluate-ticket", response_model=TicketResult)
async def re_evaluate_ticket_endpoint(request: ReEvaluateTicketRequest, current_user: Dict = Depends(require_check_health_role)):
    """Re-run AI evaluation for a SINGLE ticket from the Ticket Evaluation
    Results table -- a fast, targeted alternative to re-running the whole
    project via /api/evaluate or /api/git-jira-scan. Always evaluates for
    real (bypasses reeval_cache.py for this one ticket, unlike a bulk
    re-run of an existing project, which skips unchanged Match tickets by
    default). Reuses the same building blocks as the bulk endpoints.

    When request.project_id is given, also patches this one ticket's row
    (plus the recomputed rollup) into that project's latest saved snapshot
    -- see _persist_single_ticket_result -- so the change is reflected the
    next time anyone (re)loads the project, not just in the requesting
    browser tab's local state.

    When request.jira_site_url/jira_email/jira_api_token are given, first
    re-fetches this ticket's CURRENT status/summary/description from Jira
    by key -- otherwise this endpoint would keep re-evaluating against
    whatever ticket text the caller already had in memory (the last full
    scan's data), which never reflects a status fixed on Jira afterwards."""
    if not request.upload_id and not request.repo_url:
        raise HTTPException(status_code=400, detail="upload_id or repo_url is required")

    loop = asyncio.get_event_loop()

    ticket_info = request.ticket
    if request.jira_site_url and request.jira_email and request.jira_api_token:
        fresh = await loop.run_in_executor(
            _executor, jira_client.fetch_ticket,
            request.jira_site_url, request.jira_email, request.jira_api_token, request.ticket.ticket_id,
        )
        ticket_info = TicketInfo(**fresh)

    tickets = _tickets_to_dicts([ticket_info])
    result: TicketResult

    if request.upload_id:
        source_dir = _get_extracted_dir(request.upload_id)
        try:
            scan_result = await loop.run_in_executor(_executor, scan_source_for_tickets, source_dir, tickets)
            scan_result = await loop.run_in_executor(_executor, enrich_scan_result_with_docs, scan_result, tickets, source_dir)
        except FileNotFoundError as exc:
            raise HTTPException(status_code=400, detail=str(exc))

        try:
            results: List[TicketResult] = await loop.run_in_executor(_executor, evaluate_with_llm, tickets, scan_result)
        except Exception as exc:  # pragma: no cover
            logger.exception("Single-ticket re-evaluation failed")
            raise HTTPException(status_code=500, detail=f"Re-evaluation failed: {exc}")

        if request.enable_deep_dive:
            results = await _apply_deep_dive(loop, source_dir, tickets, results, scan_result, request.deep_dive_threshold)
        result = results[0]
    else:
        # Connect Git/Jira flow: re-fetch evidence for the whole repo (Layer 1's
        # branch/commit/PR scan and file tree aren't per-ticket-scoped), but only
        # ever evaluate this one ticket with the LLM.
        try:
            evidence = await loop.run_in_executor(
                _executor,
                git_scan.fetch_git_evidence,
                request.repo_url,
                request.branch,
                request.git_token,
                request.git_provider,
                request.doc_path,
                request.source_path,
            )
        except i18n.TranslatableError:
            raise

        workspace_path = evidence.get("workspace_path")
        try:
            scan_result, certain_mismatches, ticket_files = git_scan.build_scan_result(tickets, evidence)
            tid = tickets[0]["ticket_id"].upper()
            if tid in certain_mismatches:
                result = certain_mismatches[tid]
            else:
                try:
                    results = await loop.run_in_executor(_executor, evaluate_with_llm, tickets, scan_result)
                except Exception as exc:  # pragma: no cover
                    logger.exception("Single-ticket re-evaluation failed")
                    raise HTTPException(status_code=500, detail=f"Re-evaluation failed: {exc}")
                result = git_scan.apply_repo_tree_check(results, ticket_files, evidence["tree_paths"], request.branch)[0]

            if request.enable_deep_dive and workspace_path:
                deep_results = await _apply_deep_dive(
                    loop, workspace_path, tickets, [result], scan_result, request.deep_dive_threshold
                )
                result = deep_results[0]
        finally:
            if workspace_path:
                await loop.run_in_executor(_executor, git_workspace.cleanup_workspace, workspace_path)

    if request.project_id:
        await loop.run_in_executor(_executor, _persist_single_ticket_result, request.project_id, tickets[0], result)
    return result


@app.get("/api/scan-progress/{job_id}", response_model=ScanProgressResponse)
async def get_scan_progress(job_id: str, current_user: Dict = Depends(get_current_user)):
    """Polled by the frontend while /api/evaluate or /api/git-jira-scan is
    still in flight, to render a real progress bar instead of an
    indeterminate spinner. Returns a zeroed/not-done payload for an unknown
    job_id (e.g. not started yet, or already swept by TTL) rather than
    404 -- the frontend just keeps polling."""
    job = scan_progress.get(job_id)
    if job is None:
        return ScanProgressResponse(phase="", current=0, total=0, done=False, error=None)
    return ScanProgressResponse(
        phase=job["phase"], current=job["current"], total=job["total"], done=job["done"], error=job["error"]
    )


@app.post("/api/risk", response_model=ProjectRisk)
async def risk_analysis(request: AnalysisRequest, current_user: Dict = Depends(get_current_user)):
    """
    Score project risk purely from already-computed evaluation results (no
    re-scan needed) — cheap arithmetic, no LLM/IO, runs synchronously.
    """
    tickets = _tickets_to_dicts(request.tickets)
    return build_project_risk(tickets, request.results)


@app.post("/api/recompute-summary", response_model=RecomputeSummaryResponse)
async def recompute_summary_endpoint(request: AnalysisRequest, current_user: Dict = Depends(get_current_user)):
    """
    Pure recomputation of summary/health/trend from an already-evaluated
    ticket+result set -- no AI call, cheap arithmetic like /api/risk. Called
    right after a single-ticket re-evaluation (POST /api/re-evaluate-ticket)
    patches one result in the client's results array, so StatCards/
    ProjectHealthPanel/ProjectTrendChart reflect the change instead of
    showing stale totals from the last full scan.
    """
    tickets = _tickets_to_dicts(request.tickets)
    summary = _build_summary(request.results, request.scanned_files)
    health = build_project_health(tickets, request.results, date.today())
    trend = build_project_trend(tickets, request.results)
    return RecomputeSummaryResponse(summary=summary, health=health, trend=trend)


@app.post("/api/solutions", response_model=ProjectSolutions)
async def solutions_analysis(request: AnalysisRequest, current_user: Dict = Depends(get_current_user)):
    """
    Synthesize project-wide recommendations from already-computed evaluation
    results via one aggregate LLM call (heuristic fallback if unavailable).

    When request.scan_run_id is given and a DB is configured, this is cached
    in project_solutions: a hit returns instantly with no LLM call at all,
    and a miss synthesizes once then saves it for next time. Re-opening the
    Solutions page for the same saved scan is then free -- only an actual
    new scan (new scan_run_id) ever triggers a fresh AI call. No scan_run_id
    (the in-memory/mock-detail case) always synthesizes fresh, uncached.
    """
    loop = asyncio.get_event_loop()
    scan_run_id = request.scan_run_id
    use_cache = scan_run_id is not None and db.is_configured()

    if use_cache:
        try:
            cached = await loop.run_in_executor(_executor, solutions_db.get_cached, scan_run_id)
            if cached is not None:
                return ProjectSolutions(**cached)
        except Exception:  # pragma: no cover
            logger.exception("Solutions cache lookup failed, synthesizing fresh")

    tickets = _tickets_to_dicts(request.tickets)
    try:
        result = await loop.run_in_executor(_executor, build_project_solutions, tickets, request.results)
    except Exception as exc:  # pragma: no cover
        logger.exception("Solutions synthesis failed")
        raise HTTPException(status_code=500, detail=f"Solutions synthesis failed: {exc}")

    if use_cache:
        try:
            await loop.run_in_executor(
                _executor,
                solutions_db.save_cache,
                scan_run_id,
                [item.model_dump() for item in result.items],
                result.generated_by,
                result.message,
            )
        except Exception:  # pragma: no cover
            logger.exception("Failed to save solutions cache")

    return result


def _xlsx_response(buffer, filename: str) -> StreamingResponse:
    return StreamingResponse(
        buffer,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@app.post("/api/report")
async def report_from_results(request: ReportRequest, current_user: Dict = Depends(get_current_user)):
    """
    Excel report (Summary + Tickets sheets, including each ticket's
    Recommended Action) from an already-computed evaluation -- no re-scan
    needed, same "resend tickets+results" pattern as /api/risk and
    /api/solutions. Covers the "just ran a scan, export it now" case.
    """
    tickets = _tickets_to_dicts(request.tickets)
    summary = _build_summary(request.results, scanned_files=0)
    health = build_project_health(tickets, request.results, date.today())
    buffer = await asyncio.get_event_loop().run_in_executor(
        _executor, report.build_report_workbook, request.project_name, tickets, request.results, summary, health
    )
    filename = f"{request.project_name or 'project'}-health-report.xlsx".replace(" ", "_")
    return _xlsx_response(buffer, filename)


@app.get("/api/projects/{project_id}/report")
async def report_from_project(project_id: int, current_user: Dict = Depends(get_current_user)):
    """
    Same Excel report as /api/report, but for a project's latest saved
    snapshot instead of an in-memory scan result -- lets a PM re-download
    the report anytime later without re-running a scan (used from the
    Project List page)."""
    _require_db()
    project = await asyncio.get_event_loop().run_in_executor(_executor, projects_db.get_project, project_id)
    if not project:
        raise HTTPException(status_code=404, detail=f"Project not found: {project_id}")
    await _check_project_visibility(project, current_user)

    data = await asyncio.get_event_loop().run_in_executor(
        _executor, scan_runs_db.get_latest_scan_detail, project_id
    )
    if not data:
        raise HTTPException(status_code=404, detail="No saved per-ticket scan data for this project yet.")

    results = [TicketResult(**r) for r in data["results"]]
    summary = Summary(**data["summary"])
    health = build_project_health(data["tickets"], results, date.today())
    buffer = await asyncio.get_event_loop().run_in_executor(
        _executor, report.build_report_workbook, project["name"], data["tickets"], results, summary, health
    )
    filename = f"{project['name']}-health-report.xlsx".replace(" ", "_")
    return _xlsx_response(buffer, filename)


def _build_summary(results: List[TicketResult], scanned_files: int) -> Summary:
    # Cancelled tickets get an immediate "Skipped" result (evaluator._skipped_result)
    # and must not count toward totals/match-rate/avg-completion -- they were
    # deliberately never evaluated, so including them would just dilute the
    # stats for tickets that actually matter.
    active = [r for r in results if r.assessment != "Skipped"]
    total = len(active)
    if total == 0:
        return Summary(
            total_tickets=0,
            match_count=0,
            mismatch_count=0,
            incomplete_count=0,
            match_percent=0.0,
            avg_completion=0.0,
            scanned_files=scanned_files,
        )

    match_count = sum(1 for r in active if r.assessment == "Match")
    mismatch_count = sum(1 for r in active if r.assessment == "Mismatch")
    incomplete_count = sum(1 for r in active if r.assessment == "Incomplete")
    avg_completion = sum(r.completion_percent for r in active) / total

    return Summary(
        total_tickets=total,
        match_count=match_count,
        mismatch_count=mismatch_count,
        incomplete_count=incomplete_count,
        match_percent=round((match_count / total) * 100, 1),
        avg_completion=round(avg_completion, 1),
        scanned_files=scanned_files,
    )


@app.on_event("shutdown")
async def cleanup_uploads():
    """Remove temporary upload directories on shutdown, plus any leftover
    Layer-4 clone workspaces (git_workspace.py normally cleans those up
    per-request, this is only a safety net for crashed requests)."""
    for path in _active_uploads.values():
        shutil.rmtree(path, ignore_errors=True)
    _active_uploads.clear()
    git_workspace.cleanup_all()


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8000)