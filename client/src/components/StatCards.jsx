import {
  Activity,
  CheckCircle2,
  AlertTriangle,
  XCircle,
  Percent,
} from 'lucide-react'
import { useTranslation } from 'react-i18next'

function StatCard({ icon: Icon, label, value, sub, colorClass }) {
  return (
    <div className="card p-5 flex items-start gap-4">
      <div
        className={`w-11 h-11 rounded-lg flex items-center justify-center shrink-0 ${colorClass}`}
      >
        <Icon size={22} />
      </div>
      <div className="min-w-0">
        <p className="text-sm text-slate-500">{label}</p>
        <p className="text-2xl font-bold mt-0.5">{value}</p>
        {sub ? <p className="text-xs text-slate-400 mt-0.5 truncate">{sub}</p> : null}
      </div>
    </div>
  )
}

export default function StatCards({ summary }) {
  const { t } = useTranslation()
  if (!summary) return null

  const cards = [
    {
      icon: Activity,
      label: t('statCards.totalTickets'),
      value: summary.total_tickets ?? 0,
      sub: t('statCards.filesScanned', { count: summary.scanned_files ?? 0 }),
      colorClass: 'bg-blue-100 text-blue-600',
    },
    {
      icon: CheckCircle2,
      label: t('statCards.matched'),
      value: summary.match_count ?? 0,
      sub: t('statCards.ofTickets', { percent: (summary.match_percent ?? 0).toFixed(1) }),
      colorClass: 'bg-emerald-100 text-emerald-600',
    },
    {
      icon: AlertTriangle,
      label: t('statCards.incomplete'),
      value: summary.incomplete_count ?? 0,
      sub: t('statCards.partialImplementation'),
      colorClass: 'bg-amber-100 text-amber-600',
    },
    {
      icon: XCircle,
      label: t('statCards.mismatch'),
      value: summary.mismatch_count ?? 0,
      sub: t('statCards.statusMismatch'),
      colorClass: 'bg-red-100 text-red-600',
    },
    {
      icon: Percent,
      label: t('statCards.avgCompletion'),
      value: `${(summary.avg_completion ?? 0).toFixed(1)}%`,
      sub: t('statCards.acrossAllTickets'),
      colorClass: 'bg-indigo-100 text-indigo-600',
    },
  ]

  return (
    <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-5 gap-4">
      {cards.map((c) => (
        <StatCard key={c.label} {...c} />
      ))}
    </div>
  )
}
