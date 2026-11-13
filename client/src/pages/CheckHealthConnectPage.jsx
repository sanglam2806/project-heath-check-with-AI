import { useCallback, useEffect, useRef, useState } from 'react'
import { Search, Sparkles, Loader2, GitBranch, Ticket, Plus, CheckCircle2 } from 'lucide-react'
import { useTranslation } from 'react-i18next'
import {
  listProjects,
  saveScanRun,
  getProjectSnapshots,
  createProject,
  connectGit,
  connectJira,
  runGitJiraScan,
  getScanProgress,
  reEvaluateTicket,
  recomputeSummary,
} from '../api'
import { useEvaluationContext } from '../context/EvaluationContext'
import { useReEvalJob } from '../context/ReEvalJobContext'
import EvaluationResultsView from '../components/EvaluationResultsView'
import ConnectPanel from '../components/ConnectPanel'
import TrendHistoryPanel from '../components/TrendHistoryPanel'
import ScanProgressBar from '../components/ScanProgressBar'

/** "https://github.com/org/cowork-local.git" -> "cowork-local", for naming
 * a newly auto-created project after its connected Git repo. */
function repoNameFromUrl(url) {
  const cleaned = (url || '').trim().replace(/\.git$/i, '').replace(/\/+$/, '')
  const parts = cleaned.split(/[/:]/).filter(Boolean)
  return parts[parts.length - 1] || ''
}

/**
 * "Connect Git/Jira" — half of the former Check Health Project page: connect
 * a project's source (Git) and tickets (Jira) and run a check against them.
 * The manual ZIP/Excel upload path lives on the sibling Upload page instead;
 * this page has no file-upload UI at all.
 */
export default function CheckHealthConnectPage({ initialProjectId = null }) {
  const { t } = useTranslation()
  const { evaluation, setEvaluation } = useEvaluationContext()
  const { startJob, finishJob } = useReEvalJob()

  // --- Mode: New Check vs Re-run Existing Project ---
  // Deep-linked here (e.g. Project List's Re-check button) with a project
  // id already lands directly in "Existing Project" mode with it preselected.
  const [mode, setMode] = useState(() => (initialProjectId ? 'existing' : 'new'))
  const [selectedProjectId, setSelectedProjectId] = useState(() => (initialProjectId ? Number(initialProjectId) : ''))
  const [projectsList, setProjectsList] = useState([])
  const [projectsStatus, setProjectsStatus] = useState('loading') // loading | done | error
  const [projectsError, setProjectsError] = useState('')
  const [saveSnapshot, setSaveSnapshot] = useState(true)
  // Layer 4 opt-in: agentic deep-dive (local clone + tool-calling LLM) for
  // whatever the fast pipeline leaves Incomplete/low-confidence. Off by
  // default — it's slower and costlier than Layers 1-3.
  const [enableDeepDive, setEnableDeepDive] = useState(false)
  // Existing-project re-run only: bypasses the re-evaluation cache
  // (reeval_cache.py) and runs every ticket through AI fresh. Off by
  // default -- the cache is meant to be transparent/automatic; this is an
  // escape hatch for when the user wants a full audit regardless.
  const [forceFullReevaluate, setForceFullReevaluate] = useState(false)
  // Captured from the real Git/Jira ConnectPanels — feeds both the real
  // Scan & Evaluate pipeline and (for Git) the auto-created project name.
  // Credentials are never persisted (see project_git_connections/
  // project_ticket_connections in schema.sql, which only keep repo_url/
  // branch/jira_site_url/jira_project_key) -- re-running an existing
  // project pre-fills those non-secret fields (see the ConnectPanel props
  // below) but always requires the token/password to be re-entered here.
  const [connectedGitInfo, setConnectedGitInfo] = useState(null) // { repoUrl, branch, gitToken } | null
  const [connectedJiraInfo, setConnectedJiraInfo] = useState(null) // { siteUrl, projectKey, email, apiToken } | null
  // Which project (if any) the currently-displayed result belongs to, so
  // the Trend History panel above the results knows whose snapshots to show.
  const [resultProjectId, setResultProjectId] = useState(null)
  const [trendSnapshots, setTrendSnapshots] = useState([])
  // Feedback for the background POST /api/scan-runs save (best-effort — a
  // failure here never blocks the already-computed results from showing).
  const [dbSaveStatus, setDbSaveStatus] = useState({ status: 'idle', message: '' }) // idle | saving | saved | error
  // Polled from GET /api/scan-progress/{job_id} while the scan is in flight
  // -- see ScanProgressBar. Cleared whenever we're not loading.
  const [scanProgress, setScanProgress] = useState(null)
  const progressPollRef = useRef(null)
  // Which ticket (if any) is currently being re-evaluated individually via
  // the Ticket Evaluation Results table's per-row re-scan button.
  const [reEvaluatingTicketId, setReEvaluatingTicketId] = useState(null)

  useEffect(() => {
    return () => {
      if (progressPollRef.current) clearInterval(progressPollRef.current)
    }
  }, [])

  useEffect(() => {
    if (!resultProjectId) {
      setTrendSnapshots([])
      return
    }
    let cancelled = false
    getProjectSnapshots(resultProjectId)
      .then((data) => {
        if (!cancelled) setTrendSnapshots(data)
      })
      .catch(() => {
        if (!cancelled) setTrendSnapshots([])
      })
    return () => {
      cancelled = true
    }
  }, [resultProjectId, dbSaveStatus.status])

  useEffect(() => {
    let cancelled = false
    listProjects()
      .then((data) => {
        if (cancelled) return
        setProjectsList(data)
        setProjectsStatus('done')
      })
      .catch((err) => {
        if (cancelled) return
        setProjectsError(err.message || t('projectList.failedToLoad'))
        setProjectsStatus('error')
      })
    return () => {
      cancelled = true
    }
  }, [])

  const selectedProject = projectsList.find((p) => p.id === selectedProjectId) || null

  const [phase, setPhase] = useState(() => (evaluation?.summary ? 'done' : 'idle')) // idle | uploading | scanning | evaluating | done | error
  const [error, setError] = useState('')

  const tickets = evaluation?.tickets || []
  const results = evaluation?.results || []
  const summary = evaluation?.summary || null
  const health = evaluation?.health || null
  const trend = evaluation?.trend || null

  // The real Git/Jira scan (runGitJiraScan) only knows how to fetch tickets
  // from Jira -- a project whose tickets came from an Excel upload has no
  // live ticket source to re-query, so it can't be re-run for real from
  // this page (its tickets would need a fresh Excel upload via the Check
  // Health Upload page instead).
  const hasJiraTicketSource = mode === 'existing' && selectedProject?.ticketSource?.type === 'jira'
  const isRealRunPossible = mode === 'new' || (!!selectedProject && hasJiraTicketSource)

  const handleModeChange = (newMode) => {
    setMode(newMode)
    if (newMode === 'new') setSelectedProjectId('')
    setConnectedGitInfo(null)
    setConnectedJiraInfo(null)
    setError('')
  }

  const handleSelectProject = (id) => {
    setSelectedProjectId(id ? Number(id) : '')
    // A different project means different (or no) saved connection info --
    // never carry over a previous project's live-connected credentials.
    setConnectedGitInfo(null)
    setConnectedJiraInfo(null)
    setError('')
  }

  // Persist a completed run to PostgreSQL (scan_runs + evaluation_results)
  // when it belongs to a real tracked project and the "Save as new
  // snapshot" checkbox is on. Best-effort: the results are already on screen by
  // the time this runs, so a save failure only surfaces as a small inline
  // notice, never an error state for the whole pipeline.
  const persistScanRun = useCallback(
    async ({
      projectId,
      runType,
      scope,
      scopeNote,
      uploadId,
      tickets,
      results,
      summary,
      healthStatus,
      repoUrl,
      branch,
      docPath,
      sourcePath,
      jiraSiteUrl,
      jiraProjectKey,
      commitSha,
    }) => {
      if (!projectId) return
      setDbSaveStatus({ status: 'saving', message: '' })
      try {
        await saveScanRun({
          project_id: projectId,
          run_type: runType,
          scope: scope || 'all',
          scope_note: scopeNote || null,
          upload_id: uploadId || null,
          is_snapshot: true,
          tickets,
          results,
          summary,
          health_status: healthStatus || 'OK',
          repo_url: repoUrl || null,
          branch: branch || null,
          doc_path: docPath || null,
          source_path: sourcePath || null,
          source_type: jiraSiteUrl ? 'jira' : null,
          jira_site_url: jiraSiteUrl || null,
          jira_project_key: jiraProjectKey || null,
          commit_sha: commitSha || null,
        })
        setDbSaveStatus({ status: 'saved', message: t('checkHealthConnect.checkSavedToDb') })
      } catch (err) {
        setDbSaveStatus({ status: 'error', message: err.message || t('checkHealthConnect.failedToSaveDb') })
      }
    },
    [t]
  )

  // "New Check" real-scan flow has no project to attach the run to yet, so
  // auto-create one — named from the connected Git repo — then save the
  // run under it. In practice this page has no way to provide a real ZIP,
  // so this only ever runs once a real source becomes available.
  const createProjectAndPersist = useCallback(
    async ({
      name, uploadId, tickets, results, summary, healthStatus,
      repoUrl, branch, docPath, sourcePath, jiraSiteUrl, jiraProjectKey, commitSha,
    }) => {
      setDbSaveStatus({ status: 'saving', message: '' })
      try {
        const project = await createProject(name)
        setResultProjectId(project.id)
        await saveScanRun({
          project_id: project.id,
          run_type: 'new_check',
          scope: 'all',
          scope_note: null,
          upload_id: uploadId || null,
          is_snapshot: true,
          tickets,
          results,
          summary,
          health_status: healthStatus || 'OK',
          repo_url: repoUrl || null,
          branch: branch || null,
          doc_path: docPath || null,
          source_path: sourcePath || null,
          source_type: jiraSiteUrl ? 'jira' : null,
          jira_site_url: jiraSiteUrl || null,
          jira_project_key: jiraProjectKey || null,
          commit_sha: commitSha || null,
        })
        try {
          setProjectsList(await listProjects())
        } catch {
          // non-fatal — it just won't appear in the picker until reload
        }
        setDbSaveStatus({
          status: 'saved',
          message: project.created
            ? t('checkHealthConnect.createdProjectAndSaved', { name: project.name })
            : t('checkHealthConnect.savedToExistingProject', { name: project.name }),
        })
      } catch (err) {
        setDbSaveStatus({ status: 'error', message: err.message || t('checkHealthConnect.failedToCreateProject') })
      }
    },
    [t]
  )

  // Ticket Evaluation Results table's per-row re-scan button: re-runs AI
  // for just this one ticket against the connected repo, and patches only
  // its row in place -- no full re-scan of the whole project.
  const handleReEvaluateTicket = useCallback(
    async (ticket) => {
      if (!evaluation || !connectedGitInfo) return
      setReEvaluatingTicketId(ticket.ticket_id)
      // Tracked globally (see ReEvalJobContext/ReEvalJobBanner) so the
      // in-progress/outcome feedback survives navigating to a different
      // page mid-request -- the request itself keeps running regardless.
      startJob({
        ticketId: ticket.ticket_id,
        projectId: resultProjectId,
        projectName: resultProjectId ? projectsList.find((p) => p.id === resultProjectId)?.name : undefined,
      })
      try {
        // Only ask the backend to persist this into the DB when the current
        // results are actually what's saved as the project's latest
        // snapshot -- otherwise we'd silently patch an older, unrelated
        // snapshot while this page still shows a newer unsaved scan.
        const canPersist = dbSaveStatus.status === 'saved' && !!resultProjectId
        const newResult = await reEvaluateTicket({
          ticket,
          repoUrl: connectedGitInfo.repoUrl,
          branch: connectedGitInfo.branch,
          gitToken: connectedGitInfo.gitToken,
          gitProvider: connectedGitInfo.gitProvider === 'auto' ? '' : connectedGitInfo.gitProvider,
          docPath: connectedGitInfo.docPath,
          sourcePath: connectedGitInfo.sourcePath,
          enableDeepDive,
          projectId: canPersist ? resultProjectId : undefined,
          // Refreshes the ticket's status/summary/description from Jira
          // before evaluating (e.g. a status that was fixed on Jira since
          // the last full scan) -- always available here since both
          // ConnectPanels must be connected before this button ever shows.
          jiraSiteUrl: connectedJiraInfo?.siteUrl,
          jiraEmail: connectedJiraInfo?.email,
          jiraApiToken: connectedJiraInfo?.apiToken,
        })
        const newResults = evaluation.results.map((r) => (r.ticket_id === newResult.ticket_id ? newResult : r))
        let { summary: newSummary, health: newHealth, trend: newTrend } = evaluation
        try {
          const recomputed = await recomputeSummary({
            tickets: evaluation.tickets,
            results: newResults,
            scannedFiles: evaluation.summary?.scanned_files,
          })
          newSummary = recomputed.summary
          newHealth = recomputed.health
          newTrend = recomputed.trend
        } catch {
          // best-effort -- keep the last-known totals if recompute fails
        }
        setEvaluation({ ...evaluation, results: newResults, summary: newSummary, health: newHealth, trend: newTrend })
        finishJob({ status: 'done', assessment: newResult.assessment })
      } catch (err) {
        const message = err.message || t('evaluationResults.reEvaluateTicketFailed')
        setError(message)
        finishJob({ status: 'error', message })
      } finally {
        setReEvaluatingTicketId(null)
      }
    },
    [
      evaluation, connectedGitInfo, connectedJiraInfo, enableDeepDive, dbSaveStatus, resultProjectId,
      projectsList, startJob, finishJob, setEvaluation, t,
    ]
  )

  // Real 3-layer Git/Jira scan: rule-based ticket-ID matching across
  // branches/commits/PR-MR titles (Layer 1), LLM diff review for tickets
  // with evidence (Layer 2), repo-tree existence check (Layer 3). Requires
  // both ConnectPanels above to be connected first.
  const runPipeline = useCallback(async () => {
    if (!connectedGitInfo || !connectedJiraInfo) {
      setError(t('checkHealthConnect.connectBothFirst'))
      return
    }
    setError('')
    setDbSaveStatus({ status: 'idle', message: '' })
    setScanProgress(null)

    const jobId = crypto.randomUUID()
    progressPollRef.current = setInterval(() => {
      getScanProgress(jobId)
        .then((p) => {
          if (p && p.total > 0) setScanProgress(p)
        })
        .catch(() => {})
    }, 1500)

    try {
      setPhase('evaluating')
      const scanRes = await runGitJiraScan({
        repoUrl: connectedGitInfo.repoUrl,
        branch: connectedGitInfo.branch,
        gitToken: connectedGitInfo.gitToken,
        gitProvider: connectedGitInfo.gitProvider === 'auto' ? '' : connectedGitInfo.gitProvider,
        docPath: connectedGitInfo.docPath,
        sourcePath: connectedGitInfo.sourcePath,
        enableDeepDive,
        jiraSiteUrl: connectedJiraInfo.siteUrl,
        jiraProjectKey: connectedJiraInfo.projectKey,
        jiraEmail: connectedJiraInfo.email,
        jiraApiToken: connectedJiraInfo.apiToken,
        jobId,
        projectId: mode === 'existing' ? selectedProject?.id : null,
        forceFullReevaluate,
      })
      setPhase('done')

      const tickets = scanRes.tickets || []
      setEvaluation({
        uploadId: null,
        tickets,
        results: scanRes.results || [],
        summary: scanRes.summary || null,
        health: scanRes.health || null,
        trend: scanRes.trend || null,
      })
      if (selectedProject) {
        setResultProjectId(selectedProject.id)
        if (saveSnapshot) {
          persistScanRun({
            projectId: selectedProject.id,
            runType: 'existing_rerun',
            scope: 'all',
            tickets,
            results: scanRes.results || [],
            summary: scanRes.summary || null,
            healthStatus: scanRes.health?.status,
            repoUrl: connectedGitInfo.repoUrl,
            branch: connectedGitInfo.branch,
            docPath: connectedGitInfo.docPath,
            sourcePath: connectedGitInfo.sourcePath,
            jiraSiteUrl: connectedJiraInfo.siteUrl,
            jiraProjectKey: connectedJiraInfo.projectKey,
            commitSha: scanRes.commit_sha,
          })
        }
      } else {
        setResultProjectId(null)
        const derivedName = repoNameFromUrl(connectedGitInfo.repoUrl)
        if (derivedName) {
          createProjectAndPersist({
            name: derivedName,
            tickets,
            results: scanRes.results || [],
            summary: scanRes.summary || null,
            healthStatus: scanRes.health?.status,
            repoUrl: connectedGitInfo.repoUrl,
            branch: connectedGitInfo.branch,
            docPath: connectedGitInfo.docPath,
            sourcePath: connectedGitInfo.sourcePath,
            jiraSiteUrl: connectedJiraInfo.siteUrl,
            jiraProjectKey: connectedJiraInfo.projectKey,
            commitSha: scanRes.commit_sha,
          })
        }
      }
    } catch (err) {
      setPhase('error')
      setError(err.message || t('checkHealthUpload.unexpectedError'))
    } finally {
      clearInterval(progressPollRef.current)
      progressPollRef.current = null
      setScanProgress(null)
    }
  }, [
    connectedGitInfo,
    connectedJiraInfo,
    enableDeepDive,
    forceFullReevaluate,
    mode,
    setEvaluation,
    selectedProject,
    saveSnapshot,
    persistScanRun,
    createProjectAndPersist,
    t,
  ])

  const handleRunClick = () => {
    if (!isRealRunPossible) return
    runPipeline()
  }

  const resetAll = () => {
    setPhase('idle')
    setError('')
    setDbSaveStatus({ status: 'idle', message: '' })
    setEvaluation(null)
    setResultProjectId(null)
  }

  const isLoading = ['uploading', 'scanning', 'evaluating'].includes(phase)
  const runButtonLabel = mode === 'new' ? t('checkHealthConnect.scanAndEvaluate') : t('checkHealthConnect.reEvaluateWithAi')

  return (
    <>
      {/* Input Section */}
      <section className="card p-6">
        {/* Mode switch: New Check vs Re-run Existing Project */}
        <div className="mb-6 pb-6 border-b border-slate-100">
          <div className="flex flex-wrap items-center gap-3">
            <div className="inline-flex rounded-lg border border-slate-200 p-1 bg-slate-50">
              <button
                type="button"
                onClick={() => handleModeChange('new')}
                className={`px-3 py-1.5 text-sm font-medium rounded-md cursor-pointer transition-colors ${
                  mode === 'new' ? 'bg-white shadow-sm text-primary-700' : 'text-slate-500 hover:text-slate-700'
                }`}
              >
                {t('checkHealthConnect.newProject')}
              </button>
              <button
                type="button"
                onClick={() => handleModeChange('existing')}
                className={`px-3 py-1.5 text-sm font-medium rounded-md cursor-pointer transition-colors ${
                  mode === 'existing' ? 'bg-white shadow-sm text-primary-700' : 'text-slate-500 hover:text-slate-700'
                }`}
              >
                {t('checkHealthConnect.existingProject')}
              </button>
            </div>

            {mode === 'existing' && (
              <>
                <span className="text-sm text-slate-600">{t('checkHealthConnect.selectProjectToRerun')}</span>
                {projectsStatus === 'loading' && (
                  <span className="inline-flex items-center gap-1.5 text-sm text-slate-400">
                    <Loader2 size={14} className="animate-spin" /> {t('checkHealthConnect.loadingProjectList')}
                  </span>
                )}
                {projectsStatus === 'error' && (
                  <span className="text-sm text-red-600">{projectsError}</span>
                )}
                {projectsStatus === 'done' && (
                  <select
                    value={selectedProjectId}
                    onChange={(e) => handleSelectProject(e.target.value)}
                    className="input-field w-auto text-sm py-1.5"
                  >
                    <option value="">{t('checkHealthConnect.selectProjectPlaceholder')}</option>
                    {projectsList.map((p) => (
                      <option key={p.id} value={p.id}>
                        {p.name} ({t('checkHealthConnect.lastCheckedLabel', { date: p.lastCheckedAt || t('checkHealthConnect.never') })})
                      </option>
                    ))}
                  </select>
                )}
                <button type="button" onClick={() => handleModeChange('new')} className="btn-secondary text-xs px-3 py-1.5">
                  <Plus size={13} /> {t('checkHealthConnect.newProjectButton')}
                </button>
              </>
            )}
          </div>
          {mode === 'existing' && selectedProject && hasJiraTicketSource && (
            <p className="text-xs text-slate-500 mt-3">
              {t('checkHealthConnect.realDataNote')}
            </p>
          )}
          {mode === 'existing' && selectedProject && !hasJiraTicketSource && (
            <p className="text-xs text-amber-600 mt-3">
              {t('checkHealthConnect.noJiraSourceWarning')}
            </p>
          )}
        </div>

        <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
          {/* Left: Project Source */}
          <div>
            <h2 className="text-sm font-semibold text-slate-700 mb-3 flex items-center gap-2">
              <GitBranch size={16} className="text-primary-600" /> {t('checkHealthConnect.projectSource')}
            </h2>

            {/* key forces a remount (fresh form + fresh Connected state) when
                switching projects, so a previous project's saved values never
                linger in this form. The loaded/loading suffix forces a SECOND
                remount once `selectedProject` resolves from listProjects() --
                deep-linked here (Re-check button) selectedProjectId is set
                from the URL before that fetch even starts, so without this
                ConnectPanel would mount once with empty defaultValues and
                never pick up the real repo_url/branch once they arrive. */}
            <ConnectPanel
              key={`git-${mode}-${selectedProjectId || 'new'}-${selectedProject ? 'loaded' : 'loading'}`}
              icon={GitBranch}
              title={t('checkHealthConnect.gitTitle')}
              description={t('checkHealthConnect.gitDescription')}
              connectLabel={t('connectPanel.connect')}
              fields={[
                {
                  key: 'repoUrl',
                  label: t('checkHealthConnect.repositoryUrl'),
                  placeholder: 'https://github.com/org/repo.git',
                  required: true,
                  defaultValue: selectedProject?.source?.repoUrl || '',
                },
                {
                  key: 'branch',
                  label: t('checkHealthConnect.branchLabel'),
                  placeholder: 'main',
                  defaultValue: selectedProject?.source?.branch || 'main',
                },
                { key: 'sourcePath', label: t('checkHealthConnect.gitSourcePathLabel'), placeholder: 'src/, backend/' },
                { key: 'docPath', label: t('checkHealthConnect.gitDocPathLabel'), placeholder: 'docs/, README.md' },
                {
                  key: 'gitProvider',
                  label: t('checkHealthConnect.gitProviderLabel'),
                  type: 'select',
                  defaultValue: 'auto',
                  options: [
                    { value: 'auto', label: t('checkHealthConnect.gitProviderAuto') },
                    { value: 'github', label: t('checkHealthConnect.gitProviderGithub') },
                    { value: 'gitlab', label: t('checkHealthConnect.gitProviderGitlab') },
                  ],
                },
                { key: 'gitUsername', label: t('checkHealthConnect.gitUsernameLabel'), placeholder: 'your.username' },
                {
                  key: 'gitToken',
                  label: t('checkHealthConnect.gitTokenLabel'),
                  placeholder: 'Personal Access Token',
                  type: 'password',
                  sensitive: true,
                },
              ]}
              onConnect={setConnectedGitInfo}
              onDisconnect={() => setConnectedGitInfo(null)}
              onConnectRequest={async (values) => {
                const data = await connectGit(values.repoUrl, values.branch, values.gitToken, values.gitUsername)
                return { message: data.message || t('checkHealthConnect.gitConnected', { sha: data.commit_sha }) }
              }}
            />
          </div>

          {/* Right: Tickets Source */}
          <div>
            <h2 className="text-sm font-semibold text-slate-700 mb-3 flex items-center gap-2">
              <Sparkles size={16} className="text-primary-600" /> {t('checkHealthConnect.ticketsSource')}
            </h2>

            {mode === 'existing' && selectedProject && !hasJiraTicketSource ? (
              <div className="rounded-xl border border-amber-200 bg-amber-50 p-4 text-sm text-amber-700">
                {t('checkHealthConnect.excelSourceNoLiveRerun')}
              </div>
            ) : (
              <ConnectPanel
                key={`jira-${mode}-${selectedProjectId || 'new'}-${selectedProject ? 'loaded' : 'loading'}`}
                icon={Ticket}
                title={t('checkHealthConnect.jiraTitle')}
                description={t('checkHealthConnect.jiraDescription')}
                connectLabel={t('connectPanel.connect')}
                fields={[
                  {
                    key: 'siteUrl',
                    label: t('checkHealthConnect.jiraSiteUrl'),
                    placeholder: 'https://yourcompany.atlassian.net',
                    required: true,
                    defaultValue: selectedProject?.ticketSource?.jiraSiteUrl || '',
                  },
                  {
                    key: 'projectKey',
                    label: t('checkHealthConnect.projectKey'),
                    placeholder: 'PROJ',
                    required: true,
                    defaultValue: selectedProject?.ticketSource?.jiraProjectKey || '',
                  },
                  { key: 'email', label: t('checkHealthConnect.jiraEmail'), placeholder: 'you@company.com or username', required: true },
                  {
                    key: 'apiToken',
                    label: t('checkHealthConnect.apiToken'),
                    placeholder: 'API token, password, or PAT',
                    required: true,
                    type: 'password',
                    sensitive: true,
                  },
                ]}
                onConnect={setConnectedJiraInfo}
                onDisconnect={() => setConnectedJiraInfo(null)}
                onConnectRequest={async (values) => {
                  const data = await connectJira(values.siteUrl, values.projectKey, values.email, values.apiToken)
                  return { message: data.message || t('checkHealthConnect.jiraConnected', { count: data.ticket_count }) }
                }}
              />
            )}
          </div>
        </div>


        {/* Action buttons */}
        <div className="mt-6 flex flex-wrap items-center gap-4">
          <div className="flex items-center gap-3">
            <button
              onClick={handleRunClick}
              disabled={isLoading || !isRealRunPossible}
              className="btn-primary"
            >
              {isLoading ? (
                <>
                  <Loader2 size={16} className="animate-spin" />
                  {phase === 'uploading'
                    ? t('checkHealthConnect.uploading')
                    : phase === 'scanning'
                      ? t('checkHealthConnect.scanningCode')
                      : enableDeepDive
                        ? t('checkHealthConnect.evaluatingWithAiDeepDive')
                        : t('checkHealthConnect.evaluatingWithAi')}
                </>
              ) : (
                <>
                  <Search size={16} />
                  {runButtonLabel}
                </>
              )}
            </button>
            {phase !== 'idle' && (
              <button onClick={resetAll} className="btn-secondary">
                {t('checkHealthConnect.reset')}
              </button>
            )}
          </div>
          {mode === 'existing' && selectedProject && hasJiraTicketSource && (
            <label className="flex items-center gap-2 text-sm text-slate-600 cursor-pointer">
              <input type="checkbox" checked={saveSnapshot} onChange={(e) => setSaveSnapshot(e.target.checked)} />
              {t('checkHealthConnect.saveSnapshot')}
            </label>
          )}
          {isRealRunPossible && (
            <label className="flex items-center gap-2 text-sm text-slate-600 cursor-pointer" title={t('checkHealthConnect.deepDiveHelp')}>
              <input type="checkbox" checked={enableDeepDive} onChange={(e) => setEnableDeepDive(e.target.checked)} />
              {t('checkHealthConnect.deepDiveLabel')}
            </label>
          )}
          {mode === 'existing' && selectedProject && hasJiraTicketSource && (
            <label
              className="flex items-center gap-2 text-sm text-slate-600 cursor-pointer"
              title={t('checkHealthConnect.forceFullReevaluateHelp')}
            >
              <input
                type="checkbox"
                checked={forceFullReevaluate}
                onChange={(e) => setForceFullReevaluate(e.target.checked)}
              />
              {t('checkHealthConnect.forceFullReevaluateLabel')}
            </label>
          )}
          {phase === 'done' && dbSaveStatus.status !== 'idle' && (
            <span
              className={`inline-flex items-center gap-1.5 text-xs ${
                dbSaveStatus.status === 'error'
                  ? 'text-red-600'
                  : dbSaveStatus.status === 'saving'
                    ? 'text-slate-400'
                    : 'text-emerald-600'
              }`}
            >
              {dbSaveStatus.status === 'saving' && <Loader2 size={12} className="animate-spin" />}
              {dbSaveStatus.status === 'saved' && <CheckCircle2 size={12} />}
              {dbSaveStatus.status === 'saving' ? t('checkHealthConnect.savingToDb') : dbSaveStatus.message}
            </span>
          )}
        </div>

        {error && (
          <div className="mt-4 p-3 rounded-lg bg-red-50 border border-red-200 text-red-700 text-sm">
            {error}
          </div>
        )}
      </section>

      {/* Loading indicator */}
      {isLoading && (
        <div className="card p-8 flex flex-col items-center justify-center gap-3">
          <Loader2 size={36} className="animate-spin text-primary-600" />
          <p className="text-sm text-slate-600">
            {phase === 'uploading'
              ? t('checkHealthUpload.uploadingArchive')
              : phase === 'scanning'
                ? t('checkHealthUpload.scanningSource')
                : t('checkHealthConnect.runningAiEvaluation')}
          </p>
          {scanProgress ? (
            <ScanProgressBar progress={scanProgress} />
          ) : (
            <p className="text-xs text-slate-400">
              {t('checkHealthConnect.mayTakeAMinute')}
            </p>
          )}
        </div>
      )}

      {/* Results */}
      {phase === 'done' && summary && (
        <>
          {resultProjectId && (
            <TrendHistoryPanel
              projectName={projectsList.find((p) => p.id === resultProjectId)?.name || ''}
              snapshots={trendSnapshots}
            />
          )}
          <EvaluationResultsView
            projectName={
              (resultProjectId && projectsList.find((p) => p.id === resultProjectId)?.name) ||
              repoNameFromUrl(connectedGitInfo?.repoUrl) ||
              ''
            }
            tickets={tickets}
            results={results}
            summary={summary}
            health={health}
            trend={trend}
            onReEvaluateTicket={handleReEvaluateTicket}
            reEvaluatingTicketId={reEvaluatingTicketId}
          />
        </>
      )}
    </>
  )
}
