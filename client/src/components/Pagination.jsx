import { ChevronLeft, ChevronRight } from 'lucide-react'
import { useTranslation } from 'react-i18next'

/**
 * Simple page-number pagination. `page` is 1-indexed.
 */
export default function Pagination({ page, pageCount, totalItems, pageSize, onPageChange }) {
  const { t } = useTranslation()
  if (pageCount <= 1) return null

  const startItem = (page - 1) * pageSize + 1
  const endItem = Math.min(page * pageSize, totalItems)

  // Show up to 5 page numbers centered on the current page.
  const windowSize = 5
  let start = Math.max(1, page - Math.floor(windowSize / 2))
  let end = Math.min(pageCount, start + windowSize - 1)
  start = Math.max(1, end - windowSize + 1)
  const pages = Array.from({ length: end - start + 1 }, (_, i) => start + i)

  return (
    <div className="flex items-center justify-between gap-3 px-6 py-3 border-t border-slate-100 flex-wrap">
      <p className="text-xs text-slate-500">
        {t('pagination.showing', { start: startItem, end: endItem, total: totalItems })}
      </p>
      <div className="flex items-center gap-1">
        <button
          type="button"
          onClick={() => onPageChange(page - 1)}
          disabled={page === 1}
          className="p-1.5 rounded-lg border border-slate-200 text-slate-500 hover:bg-slate-100 disabled:opacity-40 disabled:cursor-not-allowed cursor-pointer"
          aria-label={t('pagination.previousPage')}
        >
          <ChevronLeft size={14} />
        </button>
        {start > 1 && (
          <>
            <button
              type="button"
              onClick={() => onPageChange(1)}
              className="w-7 h-7 text-xs rounded-lg hover:bg-slate-100 text-slate-600 cursor-pointer"
            >
              1
            </button>
            {start > 2 && <span className="text-slate-400 text-xs px-0.5">…</span>}
          </>
        )}
        {pages.map((p) => (
          <button
            key={p}
            type="button"
            onClick={() => onPageChange(p)}
            className={`w-7 h-7 text-xs rounded-lg cursor-pointer ${
              p === page ? 'bg-primary-600 text-white font-semibold' : 'hover:bg-slate-100 text-slate-600'
            }`}
          >
            {p}
          </button>
        ))}
        {end < pageCount && (
          <>
            {end < pageCount - 1 && <span className="text-slate-400 text-xs px-0.5">…</span>}
            <button
              type="button"
              onClick={() => onPageChange(pageCount)}
              className="w-7 h-7 text-xs rounded-lg hover:bg-slate-100 text-slate-600 cursor-pointer"
            >
              {pageCount}
            </button>
          </>
        )}
        <button
          type="button"
          onClick={() => onPageChange(page + 1)}
          disabled={page === pageCount}
          className="p-1.5 rounded-lg border border-slate-200 text-slate-500 hover:bg-slate-100 disabled:opacity-40 disabled:cursor-not-allowed cursor-pointer"
          aria-label={t('pagination.nextPage')}
        >
          <ChevronRight size={14} />
        </button>
      </div>
    </div>
  )
}
