import { useEffect, useState } from 'react'
import { History } from 'lucide-react'
import { useTranslation } from 'react-i18next'
import Pagination from './Pagination'

const HISTORY_PAGE_SIZE = 10

/**
 * "History Check" — table of past snapshot rows for one project (Snapshot
 * Date / Project / Health Score / Late tickets / Mismatch tickets /
 * Sprint note), shown above the scan result whenever the currently
 * displayed result belongs to a re-run of an existing (mock) project.
 * `snapshots` arrives newest-first (see getProjectSnapshots), so the most
 * recent row is the first one -- paginated at HISTORY_PAGE_SIZE per page.
 */
export default function TrendHistoryPanel({ projectName, snapshots }) {
  const { t } = useTranslation()
  const [page, setPage] = useState(1)

  // Reset to page 1 whenever the underlying snapshot set changes (e.g. a
  // fresh scan just added a new row).
  useEffect(() => {
    setPage(1)
  }, [snapshots])

  if (!snapshots || snapshots.length === 0) return null

  const pageCount = Math.max(1, Math.ceil(snapshots.length / HISTORY_PAGE_SIZE))
  const safePage = Math.min(page, pageCount)
  const pagedSnapshots = snapshots.slice(
    (safePage - 1) * HISTORY_PAGE_SIZE,
    safePage * HISTORY_PAGE_SIZE
  )

  return (
    <section className="card overflow-hidden">
      <div className="px-6 py-4 border-b border-slate-200 flex items-center gap-2">
        <History size={18} className="text-primary-600" />
        <h2 className="font-semibold">{t('trendHistory.historyCheck', { name: projectName })}</h2>
      </div>
      <div className="overflow-x-auto">
        <table className="w-full text-sm">
          <thead>
            <tr className="bg-slate-50 text-left text-xs uppercase tracking-wide text-slate-500">
              <th className="px-6 py-3 font-semibold">{t('trendHistory.checkDate')}</th>
              <th className="px-6 py-3 font-semibold">{t('trendHistory.project')}</th>
              <th className="px-6 py-3 font-semibold">{t('trendHistory.healthScore')}</th>
              <th className="px-6 py-3 font-semibold">{t('trendHistory.lateTickets')}</th>
              <th className="px-6 py-3 font-semibold">{t('trendHistory.mismatchTickets')}</th>
              <th className="px-6 py-3 font-semibold">{t('trendHistory.note')}</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-slate-100">
            {pagedSnapshots.map((s, i) => (
              <tr key={i} className={safePage === 1 && i === 0 ? 'bg-primary-50/40' : ''}>
                <td className="px-6 py-3 text-slate-600">{s.date}</td>
                <td className="px-6 py-3 font-medium text-slate-800">{projectName}</td>
                <td className="px-6 py-3 font-semibold text-slate-800">{s.healthScore} / 100</td>
                <td className="px-6 py-3 text-slate-600">{s.lateCount}</td>
                <td className="px-6 py-3 text-slate-600">{s.mismatchCount}</td>
                <td className="px-6 py-3 text-slate-500">{s.note}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <Pagination
        page={safePage}
        pageCount={pageCount}
        totalItems={snapshots.length}
        pageSize={HISTORY_PAGE_SIZE}
        onPageChange={setPage}
      />
    </section>
  )
}
