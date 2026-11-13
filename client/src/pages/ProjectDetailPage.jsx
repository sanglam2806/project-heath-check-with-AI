import { useEffect, useState } from 'react'
import { Loader2 } from 'lucide-react'
import { useTranslation } from 'react-i18next'
import { getProject, getLatestScan, getProjectSnapshots, reEvaluateTicket, recomputeSummary } from '../api'
import ScanSnapshotDetail from '../components/ScanSnapshotDetail'
import GitTokenPromptModal from '../components/GitTokenPromptModal'
import { useReEvalJob } from '../context/ReEvalJobContext'

export default function ProjectDetailPage({ projectId }) {
  const { t } = useTranslation()
  const { job, startJob, finishJob } = useReEvalJob()
  const [project, setProject] = useState(null)
  // Real per-ticket scan detail from the database (see getLatestScan) —
  // null means "not saved yet", in which case ScanSnapshotDetail falls
  // back to synthesizing detail from the project's aggregate stats.
  const [scanDetail, setScanDetail] = useState(null)
  // Trend History rows (see getProjectSnapshots) — empty array renders
  // nothing (TrendHistoryPanel hides itself), so a fetch failure here is
  // non-fatal and never blocks the rest of the page.
  const [snapshots, setSnapshots] = useState([])
  const [status, setStatus] = useState('loading') // loading | done | not_found | error
  const [error, setError] = useState('')

  // Per-ticket re-scan from the Ticket Evaluation Results table. This page
  // has no live connection state (unlike Check Health Connect, which just
  // ran a scan) -- repo_url/branch are known (project_git_connections,
  // non-secret), but the Git token is deliberately never persisted, so it
  // has to be asked for here every time via GitTokenPromptModal.
  const [pendingTicket, setPendingTicket] = useState(null) // ticket awaiting token entry, or null
  const [reEvaluatingTicketId, setReEvaluatingTicketId] = useState(null)
  const [tokenPromptLoading, setTokenPromptLoading] = useState(false)
  const [tokenPromptError, setTokenPromptError] = useState('')

  useEffect(() => {
    let cancelled = false
    setStatus('loading')
    setScanDetail(null)
    setSnapshots([])
    Promise.all([
      getProject(Number(projectId)),
      getLatestScan(Number(projectId)).catch(() => null),
      getProjectSnapshots(Number(projectId)).catch(() => []),
    ])
      .then(([projectData, latestScan, snapshotRows]) => {
        if (cancelled) return
        setProject(projectData)
        setScanDetail(latestScan)
        setSnapshots(snapshotRows)
        setStatus('done')
      })
      .catch((err) => {
        if (cancelled) return
        if (String(err.message || '').includes('404') || /not found/i.test(err.message || '')) {
          setStatus('not_found')
        } else {
          setError(err.message || t('projectDetail.failedToLoad'))
          setStatus('error')
        }
      })
    return () => {
      cancelled = true
    }
  }, [projectId])

  // Covers the narrow race where this page was (re)mounted WHILE a
  // background re-check for this same project was still running (so its
  // own initial fetch above caught the pre-recheck data) and the job then
  // finishes while we're still sitting here -- silently pick up the fresh
  // result instead of requiring a manual reload. (The far more common case
  // -- navigating back well after the job finished -- is already covered
  // by the initial fetch itself needing no help from this.)
  useEffect(() => {
    if (!job || job.status !== 'done' || job.projectId !== Number(projectId)) return
    getLatestScan(Number(projectId))
      .then((latestScan) => {
        if (latestScan) setScanDetail(latestScan)
      })
      .catch(() => {})
  }, [job, projectId])

  const handleReEvaluateTicketRequest = (ticket) => {
    setTokenPromptError('')
    setPendingTicket(ticket)
  }

  const isJiraSourced = project?.ticketSource?.type === 'jira'

  const handleConfirmToken = async ({ gitToken, gitUsername, jiraEmail, jiraApiToken }) => {
    if (!pendingTicket || !project?.source?.repoUrl || !scanDetail) return
    setTokenPromptLoading(true)
    setTokenPromptError('')
    setReEvaluatingTicketId(pendingTicket.ticket_id)
    // Tracked globally (survives navigating to a different page mid-request
    // -- see ReEvalJobContext/ReEvalJobBanner) since the request itself
    // isn't cancelled by leaving this page, only this page's own loading/
    // error state would be lost.
    startJob({ ticketId: pendingTicket.ticket_id, projectId: Number(projectId), projectName: project?.name })
    try {
      const newResult = await reEvaluateTicket({
        ticket: pendingTicket,
        repoUrl: project.source.repoUrl,
        branch: project.source.branch,
        docPath: project.source.docPath,
        sourcePath: project.source.sourcePath,
        gitToken,
        gitUsername,
        // This page only ever shows an already-saved snapshot, so it's
        // always safe to persist the patched result + rollup back into it.
        projectId: Number(projectId),
        // Refreshes the ticket's status/summary/description from Jira
        // before evaluating (e.g. a status that was fixed on Jira since
        // the last full scan) -- only when this project's tickets actually
        // came from Jira (an Excel/manual project has no live source).
        jiraSiteUrl: isJiraSourced ? project.ticketSource.jiraSiteUrl : undefined,
        jiraEmail: isJiraSourced ? jiraEmail : undefined,
        jiraApiToken: isJiraSourced ? jiraApiToken : undefined,
      })
      const newResults = scanDetail.results.map((r) => (r.ticket_id === newResult.ticket_id ? newResult : r))
      let { summary: newSummary, health: newHealth, trend: newTrend } = scanDetail
      try {
        const recomputed = await recomputeSummary({
          tickets: scanDetail.tickets,
          results: newResults,
          scannedFiles: scanDetail.summary?.scanned_files,
        })
        newSummary = recomputed.summary
        newHealth = recomputed.health
        newTrend = recomputed.trend
      } catch {
        // best-effort -- keep the last-known totals if recompute fails
      }
      setScanDetail((prev) =>
        prev ? { ...prev, results: newResults, summary: newSummary, health: newHealth, trend: newTrend } : prev
      )
      // The top banner badge reads project.healthStatus, a separate value
      // from scanDetail.health -- keep both in sync so it doesn't show a
      // stale status right above an up-to-date ticket table.
      setProject((prev) => (prev ? { ...prev, healthStatus: newHealth.status } : prev))
      setPendingTicket(null)
      finishJob({ status: 'done', assessment: newResult.assessment })
    } catch (err) {
      const message = err.message || t('evaluationResults.reEvaluateTicketFailed')
      setTokenPromptError(message)
      finishJob({ status: 'error', message })
    } finally {
      setTokenPromptLoading(false)
      setReEvaluatingTicketId(null)
    }
  }

  if (status === 'loading') {
    return (
      <div className="card p-10 flex items-center justify-center gap-2 text-slate-500 text-sm">
        <Loader2 size={18} className="animate-spin" /> {t('projectDetail.loadingProject')}
      </div>
    )
  }

  if (status === 'error') {
    return (
      <div className="p-3 rounded-lg bg-red-50 border border-red-200 text-red-700 text-sm">
        {error}
      </div>
    )
  }

  return (
    <>
      <ScanSnapshotDetail
        record={status === 'done' ? project : null}
        detail={scanDetail}
        snapshots={snapshots}
        meta={project ? [project.owner, `Last checked ${project.lastCheckedAt || '—'}`] : []}
        backPath="#/projects"
        backLabel={t('projectDetail.backToProjectList')}
        notFoundLabel={t('projectDetail.projectNotFound')}
        onReEvaluateTicket={handleReEvaluateTicketRequest}
        reEvaluatingTicketId={reEvaluatingTicketId}
      />
      {pendingTicket && (
        <GitTokenPromptModal
          repoUrl={project?.source?.repoUrl}
          branch={project?.source?.branch}
          jiraSiteUrl={isJiraSourced ? project.ticketSource.jiraSiteUrl : undefined}
          jiraProjectKey={isJiraSourced ? project.ticketSource.jiraProjectKey : undefined}
          loading={tokenPromptLoading}
          error={tokenPromptError}
          onConfirm={handleConfirmToken}
          onCancel={() => {
            if (!tokenPromptLoading) setPendingTicket(null)
          }}
        />
      )}
    </>
  )
}
