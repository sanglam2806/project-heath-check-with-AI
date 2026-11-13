import { ShieldCheck, ShieldAlert, ShieldX } from 'lucide-react'
import { useTranslation } from 'react-i18next'

const SEGMENTS = [
  { key: 'OK', color: 'bg-emerald-500', dot: 'bg-emerald-500', labelKey: 'healthy' },
  { key: 'Risk', color: 'bg-amber-400', dot: 'bg-amber-400', labelKey: 'atRisk' },
  { key: 'Late', color: 'bg-red-500', dot: 'bg-red-500', labelKey: 'late' },
]

/** One combined project-health summary card: big total, three icon-stats,
 * a stacked proportion bar, and a percent legend. Shared by Dashboard and
 * Project List so both pages present identical totals. */
export default function ProjectSummaryCards({ projects }) {
  const { t } = useTranslation()
  const total = projects.length
  const counts = {
    OK: projects.filter((p) => p.healthStatus === 'OK').length,
    Risk: projects.filter((p) => p.healthStatus === 'Risk').length,
    Late: projects.filter((p) => p.healthStatus === 'Late').length,
  }

  return (
    <div className="card p-6">
      <div className="flex flex-wrap items-center gap-x-10 gap-y-4">
        <div>
          <p className="text-4xl font-bold text-slate-900 leading-none">{total}</p>
          <p className="text-sm text-slate-500 mt-1.5">{t('projectSummaryCards.totalProjects')}</p>
        </div>

        <div className="flex items-center gap-3">
          <div className="w-9 h-9 rounded-lg bg-emerald-100 text-emerald-600 flex items-center justify-center shrink-0">
            <ShieldCheck size={18} />
          </div>
          <div>
            <p className="text-lg font-bold text-slate-900 leading-none">{counts.OK}</p>
            <p className="text-xs text-slate-500 mt-1">{t('projectSummaryCards.healthy')}</p>
          </div>
        </div>

        <div className="flex items-center gap-3">
          <div className="w-9 h-9 rounded-lg bg-amber-100 text-amber-600 flex items-center justify-center shrink-0">
            <ShieldAlert size={18} />
          </div>
          <div>
            <p className="text-lg font-bold text-slate-900 leading-none">{counts.Risk}</p>
            <p className="text-xs text-slate-500 mt-1">{t('projectSummaryCards.atRisk')}</p>
          </div>
        </div>

        <div className="flex items-center gap-3">
          <div className="w-9 h-9 rounded-lg bg-red-100 text-red-600 flex items-center justify-center shrink-0">
            <ShieldX size={18} />
          </div>
          <div>
            <p className="text-lg font-bold text-slate-900 leading-none">{counts.Late}</p>
            <p className="text-xs text-slate-500 mt-1">{t('projectSummaryCards.late')}</p>
          </div>
        </div>
      </div>

      {total > 0 && (
        <>
          <div className="mt-5 h-2.5 rounded-full overflow-hidden bg-slate-100 flex">
            {SEGMENTS.map((seg) => {
              const pct = (counts[seg.key] / total) * 100
              if (pct <= 0) return null
              return <div key={seg.key} className={seg.color} style={{ width: `${pct}%` }} />
            })}
          </div>
          <div className="mt-3 flex flex-wrap items-center gap-4 text-xs text-slate-500">
            {SEGMENTS.map((seg) => (
              <span key={seg.key} className="inline-flex items-center gap-1.5">
                <span className={`w-2 h-2 rounded-full inline-block ${seg.dot}`} />
                {t('projectSummaryCards.legend', {
                  label: t(`projectSummaryCards.${seg.labelKey}`),
                  percent: Math.round((counts[seg.key] / total) * 100),
                })}
              </span>
            ))}
          </div>
        </>
      )}
    </div>
  )
}
