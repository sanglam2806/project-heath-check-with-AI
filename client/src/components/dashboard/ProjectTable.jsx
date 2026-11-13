import { useMemo, useState } from 'react'
import { Eye, RefreshCw, Download, Loader2, ArrowUp, ArrowDown, ArrowUpDown, Users } from 'lucide-react'
import { useTranslation } from 'react-i18next'
import { getInitials, getProjectAvatarClass, CHECKER_AVATAR_CLASS } from '../../utils/avatar'
import { downloadProjectReport } from '../../api'

const HEALTH_DOT = { OK: 'bg-emerald-500', Risk: 'bg-amber-400', Late: 'bg-red-500' }
const HEALTH_TEXT = { OK: 'text-emerald-600', Risk: 'text-amber-600', Late: 'text-red-600' }
const HEALTH_BAR = { OK: 'bg-emerald-500', Risk: 'bg-amber-400', Late: 'bg-red-500' }
const HEALTH_RANK = { OK: 0, Risk: 1, Late: 2 }

function Avatar({ name, shape, classes }) {
  const rounding = shape === 'circle' ? 'rounded-full' : 'rounded-lg'
  const size = shape === 'circle' ? 'w-7 h-7 text-xs' : 'w-8 h-8 text-xs'
  return (
    <span
      className={`inline-flex items-center justify-center shrink-0 font-semibold ${size} ${rounding} ${classes.bg} ${classes.text}`}
    >
      {getInitials(name)}
    </span>
  )
}

function MiniBar({ value, total, colorClass }) {
  const pct = total > 0 ? Math.min(100, (value / total) * 100) : 0
  return (
    <div className="w-16 h-1.5 bg-slate-100 rounded-full overflow-hidden shrink-0">
      <div className={`h-full rounded-full ${colorClass}`} style={{ width: `${pct}%` }} />
    </div>
  )
}

function SortIcon({ active, dir }) {
  if (!active) return <ArrowUpDown size={12} className="text-slate-300" />
  return dir === 'asc' ? <ArrowUp size={12} className="text-primary-600" /> : <ArrowDown size={12} className="text-primary-600" />
}

export default function ProjectTable({
  projects,
  onDetail,
  onRecheck,
  canRecheck = true,
  showChecker = true,
  showTicketBreakdown = true,
  showCompleteTickets = false,
  showReport = false,
  onManageMembers,
}) {
  const { t } = useTranslation()
  const [sortKey, setSortKey] = useState(null)
  const [sortDir, setSortDir] = useState('asc')
  const [downloadingId, setDownloadingId] = useState(null)
  const [downloadError, setDownloadError] = useState('')

  const handleDownloadReport = async (p) => {
    setDownloadingId(p.id)
    setDownloadError('')
    try {
      await downloadProjectReport(p.id)
    } catch (err) {
      setDownloadError(err.message || t('projectTable.reportFailed'))
    } finally {
      setDownloadingId(null)
    }
  }

  const COLUMNS = [
    { key: 'name', label: t('projectTable.project') },
    { key: 'owner', label: t('projectTable.checker'), checkerOnly: true },
    { key: 'healthStatus', label: t('projectTable.health'), sortValue: (p) => HEALTH_RANK[p.healthStatus] ?? -1 },
    {
      key: 'completeCount',
      label: t('projectTable.completeTickets'),
      sortValue: (p) => p.completeCount ?? 0,
      completeOnly: true,
    },
    { key: 'ticketCount', label: t('projectTable.tickets'), sortValue: (p) => p.ticketCount ?? 0 },
    { key: 'matchCount', label: t('projectTable.matchTickets'), sortValue: (p) => p.matchCount ?? 0, breakdownOnly: true },
    { key: 'mismatchCount', label: t('projectTable.mismatchTickets'), sortValue: (p) => p.mismatchCount ?? 0, breakdownOnly: true },
    { key: 'lateCount', label: t('projectTable.lateTickets'), sortValue: (p) => p.lateCount ?? 0, breakdownOnly: true },
    { key: 'avgCompletion', label: t('projectTable.avgCompletion'), sortValue: (p) => p.avgCompletion ?? 0 },
    { key: 'lastCheckedAt', label: t('projectTable.lastChecked') },
  ]

  const showActions = !!(onDetail || onRecheck || showReport || onManageMembers)
  const visibleColumns = COLUMNS.filter(
    (c) =>
      (!c.checkerOnly || showChecker) &&
      (!c.breakdownOnly || showTicketBreakdown) &&
      (!c.completeOnly || showCompleteTickets)
  )
  const colCount = visibleColumns.length + (showActions ? 1 : 0)

  const handleSort = (column) => {
    if (!column.sortValue) return
    if (sortKey === column.key) {
      setSortDir((d) => (d === 'asc' ? 'desc' : 'asc'))
    } else {
      setSortKey(column.key)
      setSortDir('asc')
    }
  }

  const sortedProjects = useMemo(() => {
    if (!sortKey) return projects
    const column = COLUMNS.find((c) => c.key === sortKey)
    if (!column?.sortValue) return projects
    const sorted = [...projects].sort((a, b) => column.sortValue(a) - column.sortValue(b))
    return sortDir === 'asc' ? sorted : sorted.reverse()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [projects, sortKey, sortDir])

  return (
    <div className="card overflow-hidden">
      {downloadError && (
        <div className="px-6 py-2.5 border-b border-red-100 bg-red-50 text-xs text-red-700">
          {downloadError}
        </div>
      )}
      <div className="overflow-x-auto">
        <table className="w-full text-sm">
          <thead>
            <tr className="bg-slate-50 text-left text-xs uppercase tracking-wide text-slate-500">
              {visibleColumns.map((column) => (
                <th key={column.key} className="px-6 py-3 font-semibold">
                  {column.sortValue ? (
                    <button
                      type="button"
                      onClick={() => handleSort(column)}
                      className="inline-flex items-center gap-1 cursor-pointer hover:text-slate-700"
                    >
                      {column.label}
                      <SortIcon active={sortKey === column.key} dir={sortDir} />
                    </button>
                  ) : (
                    column.label
                  )}
                </th>
              ))}
              {showActions && <th className="px-6 py-3 font-semibold text-right">{t('common.actions')}</th>}
            </tr>
          </thead>
          <tbody className="divide-y divide-slate-100">
            {sortedProjects.length === 0 ? (
              <tr>
                <td colSpan={colCount} className="px-6 py-8 text-center text-slate-400">
                  {t('projectTable.noProjects')}
                </td>
              </tr>
            ) : (
              sortedProjects.map((p) => (
                <tr key={p.id} className="hover:bg-slate-50 transition-colors">
                  <td className="px-6 py-3">
                    <div className="flex items-center gap-2.5">
                      <Avatar name={p.name} shape="square" classes={getProjectAvatarClass(p.name)} />
                      <span className="font-medium text-slate-800">{p.name}</span>
                    </div>
                  </td>
                  {showChecker && (
                    <td className="px-6 py-3">
                      {p.owner ? (
                        <div className="flex items-center gap-2">
                          <Avatar name={p.owner} shape="circle" classes={CHECKER_AVATAR_CLASS} />
                          <span className="text-slate-600">{p.owner}</span>
                        </div>
                      ) : (
                        <span className="inline-flex items-center px-2 py-0.5 rounded-full border border-dashed border-slate-300 text-xs text-slate-400">
                          {t('projectTable.unassigned')}
                        </span>
                      )}
                    </td>
                  )}
                  <td className="px-6 py-3">
                    <span className="inline-flex items-center gap-1.5">
                      <span className={`w-1.5 h-1.5 rounded-full ${HEALTH_DOT[p.healthStatus] || 'bg-slate-300'}`} />
                      <span className={`font-medium ${HEALTH_TEXT[p.healthStatus] || 'text-slate-500'}`}>
                        {p.healthStatus || '—'}
                      </span>
                    </span>
                  </td>
                  {showCompleteTickets && (
                    <td className="px-6 py-3">
                      <div className="flex items-center gap-2">
                        <span className="text-slate-700 font-medium w-5 text-right">{p.completeCount ?? 0}</span>
                        <MiniBar value={p.completeCount ?? 0} total={p.ticketCount} colorClass="bg-emerald-500" />
                      </div>
                    </td>
                  )}
                  <td className="px-6 py-3 text-slate-600">{p.ticketCount}</td>
                  {showTicketBreakdown && (
                    <>
                      <td className="px-6 py-3">
                        <div className="flex items-center gap-2">
                          <span className="text-slate-700 font-medium w-5 text-right">{p.matchCount ?? 0}</span>
                          <MiniBar value={p.matchCount ?? 0} total={p.ticketCount} colorClass="bg-emerald-500" />
                        </div>
                      </td>
                      <td className="px-6 py-3">
                        <div className="flex items-center gap-2">
                          <span className="text-slate-700 font-medium w-5 text-right">{p.mismatchCount ?? 0}</span>
                          <MiniBar value={p.mismatchCount ?? 0} total={p.ticketCount} colorClass="bg-red-500" />
                        </div>
                      </td>
                      <td className="px-6 py-3">
                        <div className="flex items-center gap-2">
                          <span className="text-slate-700 font-medium w-5 text-right">{p.lateCount ?? 0}</span>
                          <MiniBar value={p.lateCount ?? 0} total={p.ticketCount} colorClass="bg-amber-500" />
                        </div>
                      </td>
                    </>
                  )}
                  <td className="px-6 py-3">
                    <div className="flex items-center gap-2">
                      <span className="text-slate-700 font-medium w-11">{(p.avgCompletion ?? 0).toFixed(1)}%</span>
                      <MiniBar value={p.avgCompletion ?? 0} total={100} colorClass={HEALTH_BAR[p.healthStatus] || 'bg-slate-300'} />
                    </div>
                  </td>
                  <td className="px-6 py-3">
                    <p className="text-slate-600">{p.lastCheckedRelative || '—'}</p>
                    {p.lastCheckedAt && <p className="text-xs text-slate-400">{p.lastCheckedAt}</p>}
                  </td>
                  {showActions && (
                    <td className="px-6 py-3">
                      <div className="flex items-center justify-end gap-2">
                        {onDetail && (
                          <button
                            type="button"
                            onClick={() => onDetail(p)}
                            className="inline-flex items-center gap-1.5 px-2.5 py-1.5 text-xs font-medium rounded-lg border border-slate-200 text-slate-600 hover:bg-slate-100 cursor-pointer"
                          >
                            <Eye size={13} /> {t('projectTable.detail')}
                          </button>
                        )}
                        {onRecheck && (
                          <button
                            type="button"
                            onClick={() => canRecheck && onRecheck(p)}
                            disabled={!canRecheck}
                            title={canRecheck ? undefined : t('projectTable.recheckForbidden')}
                            className={`inline-flex items-center gap-1.5 px-2.5 py-1.5 text-xs font-medium rounded-lg border ${
                              canRecheck
                                ? 'border-primary-200 text-primary-700 bg-primary-50 hover:bg-primary-100 cursor-pointer'
                                : 'border-slate-200 text-slate-400 bg-slate-50 cursor-not-allowed'
                            }`}
                          >
                            <RefreshCw size={13} />
                            {t('projectTable.recheck')}
                          </button>
                        )}
                        {showReport && p.lastCheckedAt && (
                          <button
                            type="button"
                            onClick={() => handleDownloadReport(p)}
                            disabled={downloadingId === p.id}
                            className="inline-flex items-center gap-1.5 px-2.5 py-1.5 text-xs font-medium rounded-lg border border-slate-200 text-slate-600 hover:bg-slate-100 cursor-pointer disabled:opacity-50"
                          >
                            {downloadingId === p.id ? (
                              <Loader2 size={13} className="animate-spin" />
                            ) : (
                              <Download size={13} />
                            )}
                            {t('projectTable.report')}
                          </button>
                        )}
                        {onManageMembers && (
                          <button
                            type="button"
                            onClick={() => onManageMembers(p)}
                            className="inline-flex items-center gap-1.5 px-2.5 py-1.5 text-xs font-medium rounded-lg border border-slate-200 text-slate-600 hover:bg-slate-100 cursor-pointer"
                          >
                            <Users size={13} /> {t('projectTable.members')}
                          </button>
                        )}
                      </div>
                    </td>
                  )}
                </tr>
              ))
            )}
          </tbody>
        </table>
      </div>
    </div>
  )
}
