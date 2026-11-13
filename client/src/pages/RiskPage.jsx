import { useEffect, useState } from 'react'
import { AlertTriangle, Loader2, ShieldAlert } from 'lucide-react'
import { useTranslation } from 'react-i18next'
import { useEvaluationContext } from '../context/EvaluationContext'
import { listProjects, getLatestScan, getRisk } from '../api'
import { buildMockProjectDetail } from '../mock/projects'
import ProjectHealthPanel from '../components/ProjectHealthPanel'
import TicketDetailModal from '../components/TicketDetailModal'
import Pagination from '../components/Pagination'

const SEVERITY_BADGE = {
  Critical: 'badge-red',
  High: 'badge-red',
  Medium: 'badge-yellow',
  Low: 'badge-gray',
}

const BREAKDOWN_PAGE_SIZE = 15

function EmptyState({ hasSession }) {
  const { t } = useTranslation()
  return (
    <div className="card p-10 flex flex-col items-center text-center gap-3">
      <ShieldAlert size={36} className="text-slate-300" />
      <p className="text-sm font-medium text-slate-600">{t('risk.selectProjectPrompt')}</p>
      {hasSession && (
        <p className="text-xs text-slate-400">
          {t('risk.orSelectCurrentSession')}
        </p>
      )}
    </div>
  )
}

export default function RiskPage() {
  const { t } = useTranslation()
  const { evaluation, risk: sessionRisk } = useEvaluationContext()

  const [projectsList, setProjectsList] = useState([])
  const [projectsStatus, setProjectsStatus] = useState('loading') // loading | done | error

  // 'session' = the in-memory Check Health Project result, '' = nothing
  // picked yet, otherwise a project id (string, from the <select> value).
  const [selection, setSelection] = useState(() => (evaluation ? 'session' : ''))

  // The selected project's scan detail — real (getLatestScan) when saved,
  // else synthesized from its aggregate stats, same fallback as Project
  // Detail. null while nothing resolved yet.
  const [detail, setDetail] = useState(null)
  const [detailStatus, setDetailStatus] = useState('idle') // idle | loading | done | empty | error
  const [detailError, setDetailError] = useState('')
  const [projectRisk, setProjectRisk] = useState({ status: 'idle', data: null, error: '' })

  const [selectedTicket, setSelectedTicket] = useState(null)
  const [breakdownPage, setBreakdownPage] = useState(1)

  // Reset to page 1 whenever the selected project (or session) changes.
  useEffect(() => {
    setBreakdownPage(1)
  }, [selection])

  useEffect(() => {
    let cancelled = false
    listProjects()
      .then((data) => {
        if (cancelled) return
        setProjectsList(data)
        setProjectsStatus('done')
      })
      .catch(() => {
        if (!cancelled) setProjectsStatus('error')
      })
    return () => {
      cancelled = true
    }
  }, [])

  // Load the selected project's scan detail, then score its risk.
  useEffect(() => {
    if (selection === 'session' || selection === '') {
      setDetail(null)
      setDetailStatus('idle')
      setProjectRisk({ status: 'idle', data: null, error: '' })
      return
    }

    const projectId = Number(selection)
    const project = projectsList.find((p) => p.id === projectId)
    if (!project) return

    let cancelled = false
    setDetailStatus('loading')
    setDetailError('')
    setProjectRisk({ status: 'idle', data: null, error: '' })

    getLatestScan(projectId)
      .catch(() => null)
      .then((latest) => {
        if (cancelled) return
        const resolved = latest || (project.ticketCount ? buildMockProjectDetail(project) : null)
        if (!resolved) {
          setDetail(null)
          setDetailStatus('empty')
          return
        }
        setDetail(resolved)
        setDetailStatus('done')
        setProjectRisk({ status: 'loading', data: null, error: '' })
        // build_project_risk falls back to each result's own `status` when
        // a ticket isn't found in `tickets`, so an empty list here is fine.
        getRisk([], resolved.results)
          .then((data) => {
            if (!cancelled) setProjectRisk({ status: 'done', data, error: '' })
          })
          .catch((err) => {
            if (!cancelled)
              setProjectRisk({ status: 'error', data: null, error: err.message || t('risk.riskAnalysisFailed') })
          })
      })
      .catch((err) => {
        if (cancelled) return
        setDetailStatus('error')
        setDetailError(err.message || t('risk.failedToLoadProject'))
      })

    return () => {
      cancelled = true
    }
  }, [selection, projectsList])

  const isSession = selection === 'session'
  const health = isSession ? evaluation?.health : detail?.health
  const results = isSession ? evaluation?.results || [] : detail?.results || []
  const riskState = isSession ? sessionRisk : projectRisk

  const openTicket = (ticketId) => {
    const match = results.find((r) => r.ticket_id === ticketId)
    if (match) setSelectedTicket(match)
  }

  const showEmpty = selection === '' || (!isSession && detailStatus === 'empty')
  const loadingDetail = !isSession && selection !== '' && detailStatus === 'loading'
  const loadingRisk = riskState.status === 'loading' || (isSession && riskState.status === 'idle' && !!evaluation)
  const showLoading = loadingDetail || loadingRisk

  // Ticket Risk Breakdown only lists genuinely actionable risk: code that
  // contradicts the reported status (Mismatch, any schedule), or honestly
  // in-progress work that has actually slipped its due date (Incomplete +
  // Late) — not e.g. Match tickets or Incomplete-but-On-time work.
  const breakdownItems = (riskState.data?.items || []).filter(
    (item) => item.assessment === 'Mismatch' || (item.assessment === 'Incomplete' && item.schedule_status === 'Late')
  )
  const breakdownPageCount = Math.max(1, Math.ceil(breakdownItems.length / BREAKDOWN_PAGE_SIZE))
  const safeBreakdownPage = Math.min(breakdownPage, breakdownPageCount)
  const pagedBreakdownItems = breakdownItems.slice(
    (safeBreakdownPage - 1) * BREAKDOWN_PAGE_SIZE,
    safeBreakdownPage * BREAKDOWN_PAGE_SIZE
  )

  return (
    <>
      <section className="card p-4 flex flex-wrap items-center gap-3">
        <span className="text-sm font-medium text-slate-700">{t('risk.selectProject')}</span>
        {projectsStatus === 'loading' ? (
          <span className="inline-flex items-center gap-1.5 text-sm text-slate-400">
            <Loader2 size={14} className="animate-spin" /> {t('risk.loadingProjectList')}
          </span>
        ) : projectsStatus === 'error' ? (
          <span className="text-sm text-red-600">{t('risk.failedToLoadProjectList')}</span>
        ) : (
          <select
            value={selection}
            onChange={(e) => setSelection(e.target.value)}
            className="input-field w-auto text-sm py-1.5"
          >
            <option value="">{t('risk.selectProjectPlaceholder')}</option>
            {evaluation && <option value="session">{t('risk.currentSession')}</option>}
            {projectsList.map((p) => (
              <option key={p.id} value={p.id}>
                {p.name}
              </option>
            ))}
          </select>
        )}
      </section>

      {showEmpty && <EmptyState hasSession={!!evaluation} />}

      {!showEmpty && !isSession && detailStatus === 'error' && (
        <div className="p-4 rounded-lg bg-red-50 border border-red-200 text-red-700 text-sm">{detailError}</div>
      )}

      {!showEmpty && detailStatus !== 'error' && showLoading && (
        <div className="card p-10 flex flex-col items-center gap-3">
          <Loader2 size={28} className="animate-spin text-primary-600" />
          <p className="text-sm text-slate-500">{t('risk.loadingRiskData')}</p>
        </div>
      )}

      {!showEmpty && detailStatus !== 'error' && !showLoading && health && (
        <>
          <ProjectHealthPanel health={health} />

          {riskState.status === 'error' ? (
            <div className="p-4 rounded-lg bg-red-50 border border-red-200 text-red-700 text-sm">
              {riskState.error || t('risk.riskAnalysisFailed')}
            </div>
          ) : (
            <>
              <section className="card p-6 flex items-center gap-5">
                <div className="w-16 h-16 rounded-2xl bg-red-100 text-red-600 flex items-center justify-center shrink-0">
                  <AlertTriangle size={30} />
                </div>
                <div>
                  <p className="text-sm text-slate-500 uppercase tracking-wide">{t('risk.overallRiskScore')}</p>
                  <p className="text-4xl font-extrabold text-slate-800">
                    {riskState.data?.overall_risk_score ?? 0}
                  </p>
                  <p className="text-sm text-slate-600 mt-1">{riskState.data?.message}</p>
                </div>
              </section>

              <section className="grid grid-cols-2 sm:grid-cols-4 gap-4">
                {['Critical', 'High', 'Medium', 'Low'].map((sev) => (
                  <div key={sev} className="card p-4 text-center">
                    <p className="text-2xl font-bold text-slate-800">
                      {riskState.data?.distribution?.[sev] ?? 0}
                    </p>
                    <span className={SEVERITY_BADGE[sev]}>{sev}</span>
                  </div>
                ))}
              </section>

              <section className="card overflow-hidden">
                <div className="px-6 py-4 border-b border-slate-200">
                  <h2 className="font-semibold">{t('risk.ticketRiskBreakdown')}</h2>
                </div>
                <div className="divide-y divide-slate-100">
                  {breakdownItems.length === 0 ? (
                    <p className="px-6 py-8 text-sm text-slate-400 text-center">{t('risk.noRiskItems')}</p>
                  ) : (
                    pagedBreakdownItems.map((item) => (
                      <div
                        key={item.ticket_id}
                        onClick={() => openTicket(item.ticket_id)}
                        className="px-6 py-4 hover:bg-slate-50 cursor-pointer transition-colors"
                      >
                        <div className="flex items-center justify-between gap-3 mb-1">
                          <div className="flex items-center gap-2 min-w-0">
                            <span className={SEVERITY_BADGE[item.severity] || 'badge-gray'}>
                              {item.severity}
                            </span>
                            <span className="font-mono text-primary-700 text-sm font-semibold">
                              {item.ticket_id}
                            </span>
                            <span className="text-sm text-slate-700 truncate">{item.summary}</span>
                          </div>
                          <span className="text-sm font-bold text-slate-700 shrink-0">
                            {item.risk_score}
                          </span>
                        </div>
                        {item.factors?.length > 0 && (
                          <ul className="mt-1.5 space-y-0.5">
                            {item.factors.map((f, i) => (
                              <li key={i} className="text-xs text-slate-500 flex gap-1.5">
                                <span>•</span>
                                <span>{f}</span>
                              </li>
                            ))}
                          </ul>
                        )}
                        {item.recommended_action && (
                          <p className="text-xs text-primary-600 mt-1.5">→ {item.recommended_action}</p>
                        )}
                      </div>
                    ))
                  )}
                </div>
                <Pagination
                  page={safeBreakdownPage}
                  pageCount={breakdownPageCount}
                  totalItems={breakdownItems.length}
                  pageSize={BREAKDOWN_PAGE_SIZE}
                  onPageChange={setBreakdownPage}
                />
              </section>
            </>
          )}
        </>
      )}

      <TicketDetailModal ticket={selectedTicket} onClose={() => setSelectedTicket(null)} />
    </>
  )
}
