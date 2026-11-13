import { useEffect, useMemo, useState } from 'react'
import { Users } from 'lucide-react'
import { useTranslation } from 'react-i18next'
import Pagination from './Pagination'
import { isDoneStatus, isInProgressStatus } from '../utils/ticketStatus'

const STATS_PAGE_SIZE = 10

/**
 * Per-assignee rollup of the current evaluate result: how many of each
 * assignee's tickets are Complete (reported Done/Closed/Resolved), In
 * Process (reported In Progress), or Late (schedule_status === 'Late').
 * Paginated 10 rows per page, since a project can have many assignees.
 */
export default function AssigneeStatsPanel({ results }) {
  const { t } = useTranslation()
  const [page, setPage] = useState(1)

  const rows = useMemo(() => {
    const byAssignee = new Map()
    for (const r of results) {
      const name = (r.assignee || '').trim() || t('common.unassigned')
      if (!byAssignee.has(name)) {
        byAssignee.set(name, { assignee: name, total: 0, complete: 0, inProgress: 0, late: 0 })
      }
      const bucket = byAssignee.get(name)
      bucket.total += 1
      if (isDoneStatus(r.status)) bucket.complete += 1
      if (isInProgressStatus(r.status)) bucket.inProgress += 1
      if (r.schedule_status === 'Late') bucket.late += 1
    }
    return [...byAssignee.values()].sort((a, b) => b.total - a.total)
  }, [results, t])

  // Reset to page 1 whenever the underlying result set changes.
  useEffect(() => {
    setPage(1)
  }, [results])

  if (rows.length === 0) return null

  const pageCount = Math.max(1, Math.ceil(rows.length / STATS_PAGE_SIZE))
  const safePage = Math.min(page, pageCount)
  const pagedRows = rows.slice((safePage - 1) * STATS_PAGE_SIZE, safePage * STATS_PAGE_SIZE)

  return (
    <section className="card overflow-hidden">
      <div className="px-6 py-4 border-b border-slate-200 flex items-center gap-2">
        <Users size={18} className="text-primary-600" />
        <h2 className="font-semibold">{t('assigneeStats.title')}</h2>
      </div>
      <div className="overflow-x-auto">
        <table className="w-full text-sm">
          <thead>
            <tr className="bg-slate-50 text-left text-xs uppercase tracking-wide text-slate-500">
              <th className="px-6 py-3 font-semibold">{t('assigneeStats.assignTo')}</th>
              <th className="px-6 py-3 font-semibold">{t('assigneeStats.total')}</th>
              <th className="px-6 py-3 font-semibold">{t('assigneeStats.complete')}</th>
              <th className="px-6 py-3 font-semibold">{t('assigneeStats.inProcess')}</th>
              <th className="px-6 py-3 font-semibold">{t('assigneeStats.late')}</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-slate-100">
            {pagedRows.map((row) => (
              <tr key={row.assignee} className="hover:bg-slate-50 transition-colors">
                <td className="px-6 py-3 font-medium text-slate-800">{row.assignee}</td>
                <td className="px-6 py-3 text-slate-600">{row.total}</td>
                <td className="px-6 py-3">
                  <span className="badge-green">{row.complete}</span>
                </td>
                <td className="px-6 py-3">
                  <span className="badge-blue">{row.inProgress}</span>
                </td>
                <td className="px-6 py-3">
                  <span className="badge-red">{row.late}</span>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <Pagination
        page={safePage}
        pageCount={pageCount}
        totalItems={rows.length}
        pageSize={STATS_PAGE_SIZE}
        onPageChange={setPage}
      />
    </section>
  )
}
