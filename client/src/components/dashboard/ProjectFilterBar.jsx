import { Search } from 'lucide-react'
import { useTranslation } from 'react-i18next'

const PILLS = [
  { key: 'all', labelKey: null },
  { key: 'OK', labelKey: 'healthy' },
  { key: 'Risk', labelKey: 'atRisk' },
  { key: 'Late', labelKey: 'late' },
]

/**
 * Search box (matches project name or checker name) + health-status filter
 * pills, shared by Dashboard and Project List so both filter identically.
 * Pill counts reflect `projects` as already narrowed by the search box
 * (passed in by the caller), not the full unfiltered list.
 */
export default function ProjectFilterBar({ query, onQueryChange, healthFilter, onHealthFilterChange, projects }) {
  const { t } = useTranslation()

  const countFor = (key) => (key === 'all' ? projects.length : projects.filter((p) => p.healthStatus === key).length)

  return (
    <div className="flex flex-wrap items-center justify-between gap-3">
      <div className="relative max-w-sm w-full">
        <Search size={16} className="absolute left-3 top-1/2 -translate-y-1/2 text-slate-400" />
        <input
          type="text"
          value={query}
          onChange={(e) => onQueryChange(e.target.value)}
          placeholder={t('projectFilterBar.searchPlaceholder')}
          className="input-field pl-9"
        />
      </div>
      <div className="inline-flex flex-wrap items-center gap-2">
        {PILLS.map((pill) => {
          const isActive = healthFilter === pill.key
          return (
            <button
              key={pill.key}
              type="button"
              onClick={() => onHealthFilterChange(pill.key)}
              className={`inline-flex items-center gap-1.5 px-3 py-1.5 rounded-full text-sm font-medium border cursor-pointer transition-colors ${
                isActive
                  ? 'bg-primary-700 border-primary-700 text-white'
                  : 'bg-white border-slate-200 text-slate-600 hover:bg-slate-50'
              }`}
            >
              {pill.labelKey ? t(`projectSummaryCards.${pill.labelKey}`) : t('projectFilterBar.all')}
              <span
                className={`px-1.5 py-0.5 rounded-full text-xs ${
                  isActive ? 'bg-white/20 text-white' : 'bg-slate-100 text-slate-500'
                }`}
              >
                {countFor(pill.key)}
              </span>
            </button>
          )
        })}
      </div>
    </div>
  )
}
