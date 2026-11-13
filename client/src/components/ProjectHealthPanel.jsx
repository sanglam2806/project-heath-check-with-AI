import { useEffect, useState } from 'react'
import {
  ShieldCheck,
  ShieldAlert,
  ShieldX,
  Flag,
  Clock,
} from 'lucide-react'
import { useTranslation } from 'react-i18next'
import Pagination from './Pagination'

const ISSUES_PAGE_SIZE = 20

const MILESTONE_BADGE = {
  Early: 'badge-blue',
  'On-time': 'badge-green',
  'At-Risk': 'badge-yellow',
  Late: 'badge-red',
  None: 'badge-gray',
}

function IssueRow({ issue, isFirst }) {
  const badgeClass =
    issue.assessment === 'Mismatch' || issue.schedule_status === 'Late'
      ? 'badge-red'
      : 'badge-yellow'
  const label = issue.schedule_status && issue.schedule_status !== 'No due date provided'
    ? `${issue.assessment} · ${issue.schedule_status}`
    : issue.assessment
  const rowBorder = isFirst ? '' : 'border-t border-slate-100'

  return (
    <li className="contents">
      <div className={`flex items-start py-2.5 pr-3 ${rowBorder}`}>
        <span className={`${badgeClass} whitespace-nowrap mt-0.5`}>{label}</span>
      </div>
      <div className={`min-w-0 py-2.5 ${rowBorder}`}>
        <p className="text-sm font-medium text-slate-800">
          <span className="font-mono text-blue-700 mr-1.5">{issue.ticket_id}</span>
          {issue.summary}
        </p>
        <p className="text-xs text-slate-500 mt-0.5">{issue.reason}</p>
      </div>
    </li>
  )
}

export default function ProjectHealthPanel({ health }) {
  const { t } = useTranslation()
  const [issuesPage, setIssuesPage] = useState(1)
  const [assessmentFilter, setAssessmentFilter] = useState('all') // 'all' | 'Mismatch' | 'Incomplete'

  const HEALTH_META = {
    OK: {
      label: t('projectHealth.ok'),
      icon: ShieldCheck,
      badge: 'bg-emerald-100 text-emerald-700',
      ring: 'border-emerald-200 bg-emerald-50',
      text: 'text-emerald-700',
      subtitle: () => t('projectHealth.subtitleOk'),
    },
    Risk: {
      label: t('projectHealth.risk'),
      icon: ShieldAlert,
      badge: 'bg-amber-100 text-amber-700',
      ring: 'border-amber-200 bg-amber-50',
      text: 'text-amber-700',
      subtitle: (n) => t('projectHealth.subtitleRisk', { count: n }),
    },
    Late: {
      label: t('projectHealth.late'),
      icon: ShieldX,
      badge: 'bg-red-100 text-red-700',
      ring: 'border-red-200 bg-red-50',
      text: 'text-red-700',
      subtitle: (n) => t('projectHealth.subtitleLate', { count: n }),
    },
  }

  // Reset to page 1 whenever a new evaluation result comes in, or the filter changes.
  useEffect(() => {
    setIssuesPage(1)
  }, [health, assessmentFilter])

  if (!health) return null

  const meta = HEALTH_META[health.status] || HEALTH_META.OK
  const Icon = meta.icon
  const milestone = health.next_milestone

  const filteredIssues =
    assessmentFilter === 'all'
      ? health.issues
      : health.issues.filter((issue) => issue.assessment === assessmentFilter)

  const issuesPageCount = Math.max(1, Math.ceil(filteredIssues.length / ISSUES_PAGE_SIZE))
  const safeIssuesPage = Math.min(issuesPage, issuesPageCount)
  const pagedIssues = filteredIssues.slice(
    (safeIssuesPage - 1) * ISSUES_PAGE_SIZE,
    safeIssuesPage * ISSUES_PAGE_SIZE
  )

  return (
    <section className="card overflow-hidden">
      {/* Overall project health — big, focused hero banner */}
      <div className={`px-6 py-8 sm:px-8 sm:py-10 border-b ${meta.ring}`}>
        <div className="flex items-center gap-5 sm:gap-6">
          <div className={`w-16 h-16 sm:w-20 sm:h-20 rounded-2xl flex items-center justify-center shrink-0 ${meta.badge}`}>
            <Icon size={40} />
          </div>
          <div className="min-w-0">
            <p className="text-sm font-medium uppercase tracking-wide text-slate-500">
              {t('projectHealth.title')}
            </p>
            <p className={`text-4xl sm:text-5xl font-extrabold leading-tight ${meta.text}`}>
              {meta.label}
            </p>
            <p className="text-sm text-slate-600 mt-1">{meta.subtitle(health.issues.length)}</p>
          </div>
        </div>
      </div>

      <div className="p-6 space-y-5">
        {/* Next milestone — secondary, compact */}
        <div className="flex items-center gap-3 rounded-xl border border-slate-200 px-4 py-3">
          <div className="w-9 h-9 rounded-lg bg-indigo-100 text-indigo-600 flex items-center justify-center shrink-0">
            {milestone.status === 'None' ? <Clock size={16} /> : <Flag size={16} />}
          </div>
          <div className="min-w-0 flex-1">
            <div className="flex items-center gap-2">
              <p className="text-xs text-slate-500">{t('projectHealth.nextMilestone')}</p>
              {milestone.status !== 'None' && (
                <span className={MILESTONE_BADGE[milestone.status] || 'badge-gray'}>
                  {milestone.status}
                </span>
              )}
            </div>
            {milestone.status !== 'None' ? (
              <p className="text-sm font-semibold text-slate-800 truncate">
                <span className="font-mono text-indigo-700 mr-1.5">{milestone.ticket_id}</span>
                {milestone.summary}
              </p>
            ) : null}
            <p className="text-xs text-slate-500 mt-0.5">{milestone.message}</p>
          </div>
        </div>

        {/* Issues / Risks */}
        <div>
          <div className="flex items-center justify-between gap-3 mb-1 flex-wrap">
            <h3 className="text-sm font-semibold text-slate-700">
              {health.issues.length > 0
                ? t('projectHealth.issuesRisksCount', { shown: filteredIssues.length, total: health.issues.length })
                : t('projectHealth.issuesRisks')}
            </h3>
            {health.issues.length > 0 && (
              <select
                value={assessmentFilter}
                onChange={(e) => setAssessmentFilter(e.target.value)}
                className="input-field text-xs py-1 w-auto"
              >
                <option value="all">{t('projectHealth.allAssessments')}</option>
                <option value="Mismatch">{t('projectHealth.mismatch')}</option>
                <option value="Incomplete">{t('projectHealth.incomplete')}</option>
              </select>
            )}
          </div>
          {health.issues.length === 0 ? (
            <p className="text-sm text-emerald-600">{t('projectHealth.noIssues')}</p>
          ) : filteredIssues.length === 0 ? (
            <p className="text-sm text-slate-400 py-3 text-center">{t('projectHealth.noIssuesMatchFilter')}</p>
          ) : (
            <>
              <ul className="grid grid-cols-[auto_1fr]">
                {pagedIssues.map((issue, i) => (
                  <IssueRow key={issue.ticket_id} issue={issue} isFirst={i === 0} />
                ))}
              </ul>
              <div className="-mx-6 -mb-6 mt-3">
                <Pagination
                  page={safeIssuesPage}
                  pageCount={issuesPageCount}
                  totalItems={filteredIssues.length}
                  pageSize={ISSUES_PAGE_SIZE}
                  onPageChange={setIssuesPage}
                />
              </div>
            </>
          )}
        </div>
      </div>
    </section>
  )
}
