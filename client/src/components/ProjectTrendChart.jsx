import { useState } from 'react'
import { TrendingUp, TrendingDown, Minus } from 'lucide-react'
import { useTranslation } from 'react-i18next'

const STATUS_COLOR = {
  Late: 'bg-red-500',
  'At-Risk': 'bg-amber-400',
  'On-time': 'bg-emerald-500',
}

function TrendBar({ bar, maxAbs }) {
  const { t } = useTranslation()
  const pctHalf = maxAbs > 0 ? (Math.abs(bar.variance_days) / maxAbs) * 50 : 0
  const isLate = bar.variance_days > 0
  const color = STATUS_COLOR[bar.schedule_status] || 'bg-slate-400'

  return (
    <div className="flex items-center gap-3 py-1.5">
      <div className="w-32 shrink-0 text-right">
        <span className="font-mono text-xs text-slate-600 truncate block">{bar.ticket_id}</span>
      </div>
      <div className="relative flex-1 h-4 bg-slate-100 rounded-sm overflow-hidden">
        <div className="absolute left-1/2 top-0 bottom-0 w-px bg-slate-300" />
        <div
          className={`absolute top-0 bottom-0 ${color} rounded-sm`}
          style={
            isLate
              ? { left: '50%', width: `${pctHalf}%` }
              : { right: '50%', width: `${pctHalf}%` }
          }
        />
      </div>
      <div className="w-24 shrink-0 text-xs text-slate-500">
        {bar.variance_days === 0
          ? t('projectTrend.dueToday')
          : isLate
            ? t('projectTrend.daysLate', { days: bar.variance_days })
            : t('projectTrend.daysLeft', { days: Math.abs(bar.variance_days) })}
      </div>
    </div>
  )
}

export default function ProjectTrendChart({ trend }) {
  const { t } = useTranslation()
  const [statusFilter, setStatusFilter] = useState('all') // 'all' | 'Late' | 'At-Risk' | 'On-time'

  const STATUS_LEGEND = [
    { label: t('projectTrend.onTime'), color: 'bg-emerald-500' },
    { label: t('projectTrend.atRisk'), color: 'bg-amber-400' },
    { label: t('projectTrend.late'), color: 'bg-red-500' },
  ]

  if (!trend || trend.tickets.length === 0) return null

  const filteredTickets =
    statusFilter === 'all' ? trend.tickets : trend.tickets.filter((b) => b.schedule_status === statusFilter)

  const maxAbs = Math.max(1, ...trend.tickets.map((b) => Math.abs(b.variance_days)))
  const TrendIcon = trend.trend_min_days != null ? TrendingUp : trend.tickets.some((b) => b.schedule_status === 'At-Risk') ? Minus : TrendingDown
  const iconColor = trend.trend_min_days != null ? 'text-red-500' : trend.tickets.some((b) => b.schedule_status === 'At-Risk') ? 'text-amber-500' : 'text-emerald-500'

  return (
    <section className="card p-6">
      <div className="flex items-center justify-between gap-3 mb-1 flex-wrap">
        <div className="flex items-center gap-2">
          <TrendIcon size={18} className={iconColor} />
          <h3 className="text-sm font-semibold text-slate-700">
            {filteredTickets.length !== trend.tickets.length
              ? t('projectTrend.tasksStatusCount', { shown: filteredTickets.length, total: trend.tickets.length })
              : t('projectTrend.tasksStatus')}
          </h3>
        </div>
        <select
          value={statusFilter}
          onChange={(e) => setStatusFilter(e.target.value)}
          className="input-field text-xs py-1 w-auto"
        >
          <option value="all">{t('projectTrend.allStatuses')}</option>
          <option value="Late">{t('projectTrend.late')}</option>
          <option value="At-Risk">{t('projectTrend.atRisk')}</option>
          <option value="On-time">{t('projectTrend.onTime')}</option>
        </select>
      </div>
      <p className="text-sm text-slate-600 mb-4">{trend.message}</p>

      <div>
        {filteredTickets.length === 0 ? (
          <p className="text-sm text-slate-400 py-3 text-center">{t('projectTrend.noTicketsMatchFilter')}</p>
        ) : (
          filteredTickets.map((bar) => <TrendBar key={bar.ticket_id} bar={bar} maxAbs={maxAbs} />)
        )}
      </div>

      <div className="flex items-center gap-4 mt-3 pt-3 border-t border-slate-100 text-xs text-slate-500">
        {STATUS_LEGEND.map((s) => (
          <span key={s.label} className="flex items-center gap-1">
            <span className={`w-2.5 h-2.5 rounded-sm inline-block ${s.color}`} />
            {s.label}
          </span>
        ))}
        <span className="ml-auto">{t('projectTrend.dueDateLegend')}</span>
      </div>
    </section>
  )
}
