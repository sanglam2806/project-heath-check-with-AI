import { useMemo } from 'react'
import { ArrowLeft, FolderKanban } from 'lucide-react'
import { useTranslation } from 'react-i18next'
import { buildMockProjectDetail } from '../mock/projects'
import EvaluationResultsView from './EvaluationResultsView'
import TrendHistoryPanel from './TrendHistoryPanel'
import { navigate } from '../router'

const HEALTH_BADGE = {
  OK: 'badge-green',
  Risk: 'badge-yellow',
  Late: 'badge-red',
}

/**
 * Full mock "scan result" detail page shell: title + badge + meta line +
 * back link + the shared results view. Used by both Project Detail
 * (looked up by project id) and History Scan Detail (looked up by scan id)
 * since both are just a project-shaped snapshot under the hood.
 */
export default function ScanSnapshotDetail({
  record,
  detail,
  snapshots,
  meta,
  backPath,
  backLabel,
  notFoundLabel,
  onReEvaluateTicket,
  reEvaluatingTicketId,
}) {
  const { t } = useTranslation()
  const hasScan = !!record?.ticketCount
  const isRealDetail = !!detail
  // Re-evaluating a single ticket needs a live Git source to re-fetch
  // evidence from -- only possible for a real (DB-backed) scan of a
  // Git-connected project, never for the mock/synthesized fallback detail
  // or an Excel/ZIP-sourced project (no live source to re-scan against).
  const canReEvaluate = isRealDetail && !!record?.source?.repoUrl
  // Only synthesize mock ticket-level detail when there's no real saved
  // scan to show — e.g. the seed_db.py demo projects, which have rollup
  // numbers but no per-ticket evaluation_results yet.
  const fallbackDetail = useMemo(
    () => (record && hasScan && !isRealDetail ? buildMockProjectDetail(record) : null),
    [record, hasScan, isRealDetail]
  )
  const resolvedDetail = detail || fallbackDetail

  if (!record) {
    return (
      <div className="card p-10 flex flex-col items-center text-center gap-3">
        <p className="text-sm font-medium text-slate-600">{notFoundLabel}</p>
        <button onClick={() => navigate(backPath)} className="btn-secondary">
          <ArrowLeft size={14} /> {backLabel}
        </button>
      </div>
    )
  }

  return (
    <>
      <button
        onClick={() => navigate(backPath)}
        className="inline-flex items-center gap-1.5 text-sm text-slate-500 hover:text-primary-600 cursor-pointer"
      >
        <ArrowLeft size={15} /> {backLabel}
      </button>

      {/* Project title — result of the latest scan for this snapshot */}
      <div className="flex items-center gap-4">
        <div className="w-14 h-14 rounded-2xl bg-primary-100 text-primary-600 flex items-center justify-center shrink-0">
          <FolderKanban size={26} />
        </div>
        <div className="min-w-0">
          <h1 className="text-2xl font-bold text-slate-900 truncate">{record.name}</h1>
          <div className="flex items-center gap-2 mt-1 flex-wrap">
            <span className={HEALTH_BADGE[record.healthStatus] || 'badge-gray'}>
              {record.healthStatus}
            </span>
            {meta.map((m, i) => (
              <span key={i} className="text-sm text-slate-500">
                {m}
              </span>
            ))}
          </div>
        </div>
      </div>

      <TrendHistoryPanel projectName={record.name} snapshots={snapshots} />

      {hasScan ? (
        <>
          {!isRealDetail && (
            <div className="p-3 rounded-lg bg-amber-50 border border-amber-200 text-amber-700 text-xs">
              {t('scanSnapshot.realDataNote')}
            </div>
          )}
          <EvaluationResultsView
            projectName={record.name}
            projectId={isRealDetail ? record.id : undefined}
            tickets={resolvedDetail.tickets}
            results={resolvedDetail.results}
            summary={resolvedDetail.summary}
            health={resolvedDetail.health}
            trend={resolvedDetail.trend}
            onReEvaluateTicket={canReEvaluate ? onReEvaluateTicket : undefined}
            reEvaluatingTicketId={reEvaluatingTicketId}
          />
        </>
      ) : (
        <div className="card p-10 flex flex-col items-center text-center gap-2">
          <p className="text-sm font-medium text-slate-600">{t('scanSnapshot.noScansYet')}</p>
          <p className="text-xs text-slate-400">{t('scanSnapshot.runToGetResults')}</p>
        </div>
      )}
    </>
  )
}
