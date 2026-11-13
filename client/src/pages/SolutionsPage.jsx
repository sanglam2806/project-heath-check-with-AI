import { useEffect, useState } from 'react'
import { Lightbulb, Loader2, Search, Sparkles } from 'lucide-react'
import { useTranslation } from 'react-i18next'
import { listProjects, getLatestScan, getSolutions } from '../api'
import { buildMockProjectDetail } from '../mock/projects'
import TicketDetailModal from '../components/TicketDetailModal'
import Pagination from '../components/Pagination'

const PRIORITY_BADGE = { High: 'badge-red', Medium: 'badge-yellow', Low: 'badge-gray' }
const ASSESSMENT_BADGE = { Match: 'badge-green', Mismatch: 'badge-red', Incomplete: 'badge-yellow' }
const TICKETS_PAGE_SIZE = 20

function EmptyState({ t }) {
  return (
    <div className="card p-10 flex flex-col items-center text-center gap-3">
      <Lightbulb size={36} className="text-slate-300" />
      <p className="text-sm font-medium text-slate-600">{t('solutions.selectProjectPrompt')}</p>
    </div>
  )
}

/**
 * "Solution Management" — for a scanned (saved) project, shows both the
 * project-wide pattern recommendations (solutions.build_project_solutions,
 * one LLM call over all results — a root-cause view, e.g. "several tickets
 * are missing input validation") and a per-ticket breakdown of each
 * TicketResult.suggestions ("Recommended fixes" already computed by
 * evaluator.py), so a PM can see exactly what to do about any given ticket
 * without opening every ticket's detail modal.
 */
export default function SolutionsPage() {
  const { t } = useTranslation()

  const [projectsList, setProjectsList] = useState([])
  const [projectsStatus, setProjectsStatus] = useState('loading') // loading | done | error

  // '' = nothing picked yet, otherwise a project id (string, from the
  // <select> value).
  const [selection, setSelection] = useState('')

  const [detail, setDetail] = useState(null)
  const [detailStatus, setDetailStatus] = useState('idle') // idle | loading | done | empty | error
  const [detailError, setDetailError] = useState('')
  const [solutionsState, setSolutionsState] = useState({ status: 'idle', data: null, error: '' })

  const [selectedTicket, setSelectedTicket] = useState(null)
  const [ticketsPage, setTicketsPage] = useState(1)
  const [ticketFilter, setTicketFilter] = useState('')

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

  // Load the selected project's scan detail, then synthesize its solutions.
  useEffect(() => {
    setTicketsPage(1)
    setTicketFilter('')
    if (selection === '') {
      setDetail(null)
      setDetailStatus('idle')
      setSolutionsState({ status: 'idle', data: null, error: '' })
      return
    }

    const projectId = Number(selection)
    const project = projectsList.find((p) => p.id === projectId)
    if (!project) return

    let cancelled = false
    setDetailStatus('loading')
    setDetailError('')
    setSolutionsState({ status: 'idle', data: null, error: '' })

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
        setSolutionsState({ status: 'loading', data: null, error: '' })
        // build_project_solutions falls back to each result's own fields
        // when a ticket isn't found in `tickets`, so an empty list is fine.
        // resolved.scan_run_id (real getLatestScan) lets the backend cache
        // this synthesis -- undefined for the mock-detail fallback, which
        // always synthesizes fresh (see getSolutions' jsdoc).
        getSolutions([], resolved.results, resolved.scan_run_id)
          .then((data) => {
            if (!cancelled) setSolutionsState({ status: 'done', data, error: '' })
          })
          .catch((err) => {
            if (!cancelled)
              setSolutionsState({ status: 'error', data: null, error: err.message || t('solutions.solutionsFailed') })
          })
      })
      .catch((err) => {
        if (cancelled) return
        setDetailStatus('error')
        setDetailError(err.message || t('solutions.failedToLoadProject'))
      })

    return () => {
      cancelled = true
    }
  }, [selection, projectsList])

  const results = detail?.results || []

  const openTicket = (ticketId) => {
    const match = results.find((r) => r.ticket_id === ticketId)
    if (match) setSelectedTicket(match)
  }

  const showEmpty = selection === '' || detailStatus === 'empty'
  const loadingDetail = selection !== '' && detailStatus === 'loading'
  const loadingSolutions = solutionsState.status === 'loading'
  const showLoading = loadingDetail || loadingSolutions

  const solutionItems = solutionsState.data?.items || []
  const ticketsWithSuggestions = results.filter((r) => (r.suggestions || []).length > 0)
  const filteredTickets = ticketFilter.trim()
    ? ticketsWithSuggestions.filter((r) => r.ticket_id.toLowerCase().includes(ticketFilter.trim().toLowerCase()))
    : ticketsWithSuggestions
  const ticketsPageCount = Math.max(1, Math.ceil(filteredTickets.length / TICKETS_PAGE_SIZE))
  const safeTicketsPage = Math.min(ticketsPage, ticketsPageCount)
  const pagedTickets = filteredTickets.slice(
    (safeTicketsPage - 1) * TICKETS_PAGE_SIZE,
    safeTicketsPage * TICKETS_PAGE_SIZE
  )

  const handleTicketFilterChange = (value) => {
    setTicketFilter(value)
    setTicketsPage(1)
  }

  return (
    <>
      <section className="card p-4 flex flex-wrap items-center gap-3">
        <span className="text-sm font-medium text-slate-700">{t('solutions.selectProject')}</span>
        {projectsStatus === 'loading' ? (
          <span className="inline-flex items-center gap-1.5 text-sm text-slate-400">
            <Loader2 size={14} className="animate-spin" /> {t('solutions.loadingProjectList')}
          </span>
        ) : projectsStatus === 'error' ? (
          <span className="text-sm text-red-600">{t('solutions.failedToLoadProjectList')}</span>
        ) : (
          <select
            value={selection}
            onChange={(e) => setSelection(e.target.value)}
            className="input-field w-auto text-sm py-1.5"
          >
            <option value="">{t('solutions.selectProjectPlaceholder')}</option>
            {projectsList.map((p) => (
              <option key={p.id} value={p.id}>
                {p.name}
              </option>
            ))}
          </select>
        )}
      </section>

      {showEmpty && <EmptyState t={t} />}

      {!showEmpty && detailStatus === 'error' && (
        <div className="p-4 rounded-lg bg-red-50 border border-red-200 text-red-700 text-sm">{detailError}</div>
      )}

      {!showEmpty && detailStatus !== 'error' && showLoading && (
        <div className="card p-10 flex flex-col items-center gap-3">
          <Loader2 size={28} className="animate-spin text-primary-600" />
          <p className="text-sm text-slate-500">{t('solutions.loadingSolutions')}</p>
        </div>
      )}

      {!showEmpty && detailStatus !== 'error' && !showLoading && (
        <>
          {solutionsState.status === 'error' ? (
            <div className="p-4 rounded-lg bg-red-50 border border-red-200 text-red-700 text-sm">
              {solutionsState.error || t('solutions.solutionsFailed')}
            </div>
          ) : (
            <section className="card overflow-hidden">
              <div className="px-6 py-4 border-b border-slate-200 flex items-center justify-between gap-3">
                <h2 className="font-semibold flex items-center gap-2">
                  <Sparkles size={16} className="text-primary-600" /> {t('solutions.projectWideTitle')}
                </h2>
                {solutionsState.data && (
                  <span className="text-xs text-slate-400">
                    {solutionsState.data.generated_by === 'llm'
                      ? t('solutions.generatedByAi')
                      : t('solutions.generatedByHeuristic')}
                  </span>
                )}
              </div>
              {solutionItems.length === 0 ? (
                <p className="px-6 py-8 text-sm text-slate-400 text-center">
                  {solutionsState.data?.message || t('solutions.noPatternsFound')}
                </p>
              ) : (
                <div className="divide-y divide-slate-100">
                  {solutionItems.map((item, i) => (
                    <div key={i} className="px-6 py-4">
                      <div className="flex items-center justify-between gap-3 mb-1 flex-wrap">
                        <div className="flex items-center gap-2 min-w-0">
                          <span className={PRIORITY_BADGE[item.priority] || 'badge-gray'}>{item.priority}</span>
                          <span className="badge-gray">{item.category}</span>
                          <span className="text-sm font-semibold text-slate-800 truncate">{item.title}</span>
                        </div>
                      </div>
                      <p className="text-sm text-slate-700 mt-1">{item.recommendation}</p>
                      {item.rationale && <p className="text-xs text-slate-500 mt-1">{item.rationale}</p>}
                      {item.affected_tickets?.length > 0 && (
                        <div className="flex flex-wrap gap-1.5 mt-2">
                          {item.affected_tickets.map((tid) => (
                            <button
                              key={tid}
                              type="button"
                              onClick={() => openTicket(tid)}
                              className="text-xs font-mono text-primary-700 bg-primary-50 border border-primary-200 rounded px-1.5 py-0.5 hover:bg-primary-100 cursor-pointer"
                            >
                              {tid}
                            </button>
                          ))}
                        </div>
                      )}
                    </div>
                  ))}
                </div>
              )}
            </section>
          )}

          <section className="card overflow-hidden">
            <div className="px-6 py-4 border-b border-slate-200 flex items-center justify-between gap-3 flex-wrap">
              <h2 className="font-semibold">{t('solutions.perTicketTitle')}</h2>
              <div className="flex items-center gap-3 flex-wrap">
                <div className="relative">
                  <Search size={14} className="absolute left-2.5 top-1/2 -translate-y-1/2 text-slate-400" />
                  <input
                    type="text"
                    value={ticketFilter}
                    onChange={(e) => handleTicketFilterChange(e.target.value)}
                    placeholder={t('solutions.filterByTicketIdPlaceholder')}
                    className="input-field w-52 text-sm py-1.5 pl-8"
                  />
                </div>
                <span className="text-sm text-slate-500">
                  {t('solutions.ofTickets', { shown: filteredTickets.length, total: results.length })}
                </span>
              </div>
            </div>
            {ticketsWithSuggestions.length === 0 ? (
              <p className="px-6 py-8 text-sm text-slate-400 text-center">{t('solutions.noTicketSuggestions')}</p>
            ) : filteredTickets.length === 0 ? (
              <p className="px-6 py-8 text-sm text-slate-400 text-center">{t('solutions.noTicketsMatchFilter')}</p>
            ) : (
              <div className="divide-y divide-slate-100">
                {pagedTickets.map((r) => (
                  <div
                    key={r.ticket_id}
                    onClick={() => setSelectedTicket(r)}
                    className="px-6 py-4 hover:bg-slate-50 cursor-pointer transition-colors"
                  >
                    <div className="flex items-center gap-2 mb-1.5 flex-wrap">
                      <span className={ASSESSMENT_BADGE[r.assessment] || 'badge-gray'}>{r.assessment}</span>
                      <span className="font-mono text-primary-700 text-sm font-semibold">{r.ticket_id}</span>
                      <span className="text-sm text-slate-700 truncate">{r.summary}</span>
                    </div>
                    <ul className="space-y-0.5">
                      {r.suggestions.map((s, i) => (
                        <li key={i} className="text-xs text-slate-600 flex gap-1.5">
                          <span>→</span>
                          <span>{s}</span>
                        </li>
                      ))}
                    </ul>
                  </div>
                ))}
              </div>
            )}
            <Pagination
              page={safeTicketsPage}
              pageCount={ticketsPageCount}
              totalItems={ticketsWithSuggestions.length}
              pageSize={TICKETS_PAGE_SIZE}
              onPageChange={setTicketsPage}
            />
          </section>
        </>
      )}

      <TicketDetailModal ticket={selectedTicket} onClose={() => setSelectedTicket(null)} />
    </>
  )
}
