import { useEffect, useState } from 'react'
import { ChevronRight, Download, Loader2, RotateCw } from 'lucide-react'
import { useTranslation } from 'react-i18next'
import ProjectHealthPanel from './ProjectHealthPanel'
import ProjectTrendChart from './ProjectTrendChart'
import StatCards from './StatCards'
import AssigneeStatsPanel from './AssigneeStatsPanel'
import TicketDetailModal from './TicketDetailModal'
import Pagination from './Pagination'
import FilterableHeader from './FilterableHeader'
import { useColumnFilters } from '../hooks/useColumnFilters'
import { downloadEvaluationReport, downloadProjectReport } from '../api'

const RESULTS_PAGE_SIZE = 20

function AssessmentBadge({ assessment, fromCache }) {
  const { t } = useTranslation()
  if (fromCache) {
    return (
      <span className="badge-blue" title={t('evaluationResults.noChangeCachedHint')}>
        {t('evaluationResults.noChangeCached')}
      </span>
    )
  }
  const map = {
    Match: 'badge-green',
    Mismatch: 'badge-red',
    Incomplete: 'badge-yellow',
  }
  return <span className={map[assessment] || 'badge-gray'}>{assessment}</span>
}

function StatusDot({ status }) {
  const lower = String(status || '').toLowerCase()
  let cls = 'bg-emerald-500'
  if (['in progress', 'in_progress', 'doing'].includes(lower)) cls = 'bg-primary-500'
  else if (['todo', 'to do', 'open'].includes(lower)) cls = 'bg-amber-500'
  return <span className={`inline-block w-2 h-2 rounded-full ${cls}`} />
}

/**
 * Full "scan result" view: project health banner, trend chart, stat cards,
 * and a filterable/paginated ticket table with a detail modal. Shared by
 * the live Check Health Project flow and the mock Project Detail page so
 * both render identically.
 */
export default function EvaluationResultsView({
  projectName,
  projectId,
  tickets = [],
  results,
  summary,
  health,
  trend,
  onReEvaluateTicket,
  reEvaluatingTicketId,
}) {
  const { t } = useTranslation()
  const [selectedTicket, setSelectedTicket] = useState(null)
  const [resultsPage, setResultsPage] = useState(1)
  const [reportStatus, setReportStatus] = useState('idle') // idle | downloading | error
  const [reportError, setReportError] = useState('')

  // Prefer the in-memory tickets+results just scanned (Check Health Upload/
  // Connect pages); fall back to re-fetching the project's latest saved
  // snapshot by id (Project Detail / History Scan Detail, whose EvaluateResponse
  // doesn't carry the raw tickets list).
  const canDownloadFromResults = !!(tickets && tickets.length > 0 && results && results.length > 0)
  const canDownloadReport = canDownloadFromResults || !!projectId

  const handleDownloadReport = async () => {
    setReportStatus('downloading')
    setReportError('')
    try {
      if (canDownloadFromResults) {
        await downloadEvaluationReport(projectName, tickets, results)
      } else {
        await downloadProjectReport(projectId)
      }
      setReportStatus('idle')
    } catch (err) {
      setReportStatus('error')
      setReportError(err.message || t('evaluationResults.reportFailed'))
    }
  }

  // "Previous Assessment" only makes sense (and is only ever populated) for
  // an existing-project "Re-evaluate with AI" re-run, via the re-evaluation
  // cache (server/reeval_cache.py) -- hide the extra columns entirely for
  // a brand-new project's first check, where they'd just be all "—".
  const hasReeval = results.some((r) => r.previous_assessment != null || r.from_cache)

  // Click-to-filter columns for the Ticket Evaluation Results table, and how
  // to read each one's value off a result row (see useColumnFilters).
  const FILTER_COLUMNS = [
    { key: 'ticket_id', label: t('evaluationResults.ticket'), getValue: (r) => r.ticket_id },
    { key: 'summary', label: t('evaluationResults.summary'), getValue: (r) => r.summary },
    { key: 'status', label: t('evaluationResults.status'), getValue: (r) => r.status },
    {
      key: 'assessment',
      label: hasReeval ? t('evaluationResults.currentAssessment') : t('evaluationResults.assessment'),
      getValue: (r) => r.assessment,
    },
    { key: 'assignee', label: t('evaluationResults.assignTo'), getValue: (r) => r.assignee || t('common.unassigned') },
  ]
  const FILTER_KEYS = FILTER_COLUMNS.map((c) => c.key)
  const headerColumnsBeforePrevAssessment = FILTER_COLUMNS.filter((c) => c.key !== 'assignee')
  const headerColumnsAfterPrevAssessment = FILTER_COLUMNS.filter((c) => c.key === 'assignee')

  const { filters, openFilter, setOpenFilter, toggleValue, clearColumn, clearAll, hasActiveFilters, matches } =
    useColumnFilters(FILTER_KEYS)

  const columnByKey = Object.fromEntries(FILTER_COLUMNS.map((c) => [c.key, c]))
  const filteredResults = results.filter((r) => matches(r, (row, key) => columnByKey[key].getValue(row)))

  // Reset to page 1 whenever the underlying result set or filters change.
  useEffect(() => {
    setResultsPage(1)
  }, [results, filters])

  const resultsPageCount = Math.max(1, Math.ceil(filteredResults.length / RESULTS_PAGE_SIZE))
  const safeResultsPage = Math.min(resultsPage, resultsPageCount)
  const pagedResults = filteredResults.slice(
    (safeResultsPage - 1) * RESULTS_PAGE_SIZE,
    safeResultsPage * RESULTS_PAGE_SIZE
  )

  if (!summary) return null

  return (
    <>
      <ProjectHealthPanel health={health} />

      <ProjectTrendChart trend={trend} />

      <StatCards summary={summary} />

      <AssigneeStatsPanel results={results} />

      <section className="card overflow-hidden">
        <div className="px-6 py-4 border-b border-slate-200 flex items-center justify-between gap-3 flex-wrap">
          <h2 className="font-semibold">{t('evaluationResults.ticketEvaluationResults')}</h2>
          <div className="flex items-center gap-3">
            <span className="text-sm text-slate-500">
              {t('evaluationResults.ofTickets', { shown: filteredResults.length, total: results.length })}
            </span>
            {canDownloadReport && (
              <button
                type="button"
                onClick={handleDownloadReport}
                disabled={reportStatus === 'downloading'}
                className="inline-flex items-center gap-1.5 px-3 py-1.5 text-xs font-medium rounded-lg border border-primary-200 text-primary-700 bg-primary-50 hover:bg-primary-100 cursor-pointer disabled:opacity-50"
              >
                {reportStatus === 'downloading' ? (
                  <Loader2 size={13} className="animate-spin" />
                ) : (
                  <Download size={13} />
                )}
                {t('evaluationResults.downloadReport')}
              </button>
            )}
          </div>
        </div>
        {reportStatus === 'error' && (
          <div className="px-6 py-2.5 border-b border-red-100 bg-red-50 text-xs text-red-700">
            {reportError}
          </div>
        )}
        {hasActiveFilters && (
          <div className="px-6 py-2.5 border-b border-slate-100 flex justify-end">
            <button onClick={clearAll} className="text-xs text-primary-600 hover:underline cursor-pointer">
              {t('common.clearAllFilters')}
            </button>
          </div>
        )}
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="bg-slate-50 text-left text-xs uppercase tracking-wide text-slate-500">
                {headerColumnsBeforePrevAssessment.map((column) => (
                  <FilterableHeader
                    key={column.key}
                    columnKey={column.key}
                    label={column.label}
                    options={[...new Set(results.map(column.getValue).filter(Boolean))].sort()}
                    selected={filters[column.key]}
                    isOpen={openFilter === column.key}
                    onToggle={(key) => setOpenFilter((prev) => (prev === key ? null : key))}
                    onChange={toggleValue}
                    onClear={clearColumn}
                  />
                ))}
                {hasReeval && (
                  <th className="px-6 py-3 font-semibold">{t('evaluationResults.previousAssessment')}</th>
                )}
                {headerColumnsAfterPrevAssessment.map((column) => (
                  <FilterableHeader
                    key={column.key}
                    columnKey={column.key}
                    label={column.label}
                    options={[...new Set(results.map(column.getValue).filter(Boolean))].sort()}
                    selected={filters[column.key]}
                    isOpen={openFilter === column.key}
                    onToggle={(key) => setOpenFilter((prev) => (prev === key ? null : key))}
                    onChange={toggleValue}
                    onClear={clearColumn}
                  />
                ))}
                <th className="px-6 py-3 font-semibold">{t('evaluationResults.completion')}</th>
                <th className="px-6 py-3 font-semibold">{t('evaluationResults.confidence')}</th>
                <th className="px-6 py-3 font-semibold">{t('evaluationResults.files')}</th>
                <th className="px-6 py-3" />
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-100">
              {pagedResults.length === 0 && (
                <tr>
                  <td colSpan={hasReeval ? 10 : 9} className="px-6 py-8 text-center text-slate-400">
                    {t('evaluationResults.noTicketsMatchFilters')}
                  </td>
                </tr>
              )}
              {pagedResults.map((r) => (
                <tr
                  key={r.ticket_id}
                  onClick={() => setSelectedTicket(r)}
                  className="hover:bg-slate-50 cursor-pointer transition-colors"
                >
                  <td className="px-6 py-3 font-mono font-semibold text-primary-700">
                    {r.ticket_id}
                  </td>
                  <td className="px-6 py-3 text-slate-700 max-w-[280px] truncate">
                    {r.summary}
                  </td>
                  <td className="px-6 py-3">
                    <span className="inline-flex items-center gap-1.5">
                      <StatusDot status={r.status} />
                      <span className="text-slate-600">{r.status}</span>
                    </span>
                  </td>
                  <td className="px-6 py-3">
                    <AssessmentBadge assessment={r.assessment} fromCache={r.from_cache} />
                  </td>
                  {hasReeval && (
                    <td className="px-6 py-3">
                      {r.previous_assessment ? (
                        <AssessmentBadge assessment={r.previous_assessment} />
                      ) : (
                        <span className="text-slate-400">—</span>
                      )}
                    </td>
                  )}
                  <td className="px-6 py-3 text-slate-600">{r.assignee || '—'}</td>
                  <td className="px-6 py-3">
                    <div className="flex items-center gap-2">
                      <div className="w-20 h-1.5 bg-slate-100 rounded-full overflow-hidden">
                        <div
                          className="h-full bg-primary-600 rounded-full"
                          style={{ width: `${r.completion_percent ?? 0}%` }}
                        />
                      </div>
                      <span className="text-xs font-medium text-slate-600">
                        {r.completion_percent?.toFixed(0) ?? 0}%
                      </span>
                    </div>
                  </td>
                  <td className="px-6 py-3 text-slate-500">
                    {typeof r.confidence === 'number'
                      ? `${(r.confidence * 100).toFixed(0)}%`
                      : '—'}
                  </td>
                  <td className="px-6 py-3">
                    <span className="badge-blue">
                      {t('evaluationResults.filesCount', { count: r.evidence_files?.length ?? 0 })}
                    </span>
                  </td>
                  <td className="px-6 py-3 text-right">
                    <div className="flex items-center justify-end gap-2">
                      {onReEvaluateTicket && (
                        <button
                          type="button"
                          title={t('evaluationResults.reEvaluateTicket')}
                          disabled={reEvaluatingTicketId === r.ticket_id}
                          onClick={(e) => {
                            e.stopPropagation()
                            const ticket = tickets.find((tk) => tk.ticket_id === r.ticket_id)
                            if (ticket) onReEvaluateTicket(ticket)
                          }}
                          className="p-1.5 rounded-md text-slate-400 hover:text-primary-600 hover:bg-primary-50 disabled:opacity-50 disabled:cursor-not-allowed cursor-pointer"
                        >
                          <RotateCw
                            size={14}
                            className={reEvaluatingTicketId === r.ticket_id ? 'animate-spin' : ''}
                          />
                        </button>
                      )}
                      <ChevronRight size={16} className="text-slate-400" />
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <Pagination
          page={safeResultsPage}
          pageCount={resultsPageCount}
          totalItems={filteredResults.length}
          pageSize={RESULTS_PAGE_SIZE}
          onPageChange={setResultsPage}
        />
      </section>

      <TicketDetailModal ticket={selectedTicket} onClose={() => setSelectedTicket(null)} />
    </>
  )
}
