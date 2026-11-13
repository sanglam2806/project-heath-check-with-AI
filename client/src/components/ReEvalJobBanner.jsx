import { useEffect } from 'react'
import { Loader2, CheckCircle2, XCircle, X } from 'lucide-react'
import { useTranslation } from 'react-i18next'
import { useReEvalJob } from '../context/ReEvalJobContext'
import { navigate } from '../router'

const ASSESSMENT_LABEL_CLASS = {
  Match: 'text-emerald-700',
  Mismatch: 'text-red-700',
  Incomplete: 'text-amber-700',
}

const AUTO_DISMISS_MS = 8000

/**
 * Always-visible strip (mounted in AppShell, above the page switch) for the
 * single-ticket re-evaluation job tracked by ReEvalJobContext. Rendering it
 * outside the page components is the whole point: a re-check kicked off on
 * Project Detail (or Upload/Connect) keeps showing progress -- and still
 * reports success/failure -- even after navigating to a completely
 * different page while it's in flight, instead of silently disappearing.
 */
export default function ReEvalJobBanner() {
  const { t } = useTranslation()
  const { job, dismissJob } = useReEvalJob()

  useEffect(() => {
    if (job?.status !== 'done' && job?.status !== 'error') return
    const timer = setTimeout(dismissJob, AUTO_DISMISS_MS)
    return () => clearTimeout(timer)
  }, [job?.status, job?.startedAt, dismissJob])

  if (!job) return null

  const canView = !!job.projectId
  const handleView = () => {
    if (canView) navigate(`#/projects/${job.projectId}`)
  }

  return (
    <div className="px-4 sm:px-6 pt-3">
      <div
        className={`max-w-7xl mx-auto rounded-lg border px-4 py-2.5 flex items-center gap-3 text-sm ${
          job.status === 'error'
            ? 'bg-red-50 border-red-200 text-red-700'
            : job.status === 'done'
              ? 'bg-emerald-50 border-emerald-200 text-emerald-700'
              : 'bg-primary-50 border-primary-200 text-primary-700'
        }`}
      >
        {job.status === 'running' && <Loader2 size={16} className="animate-spin shrink-0" />}
        {job.status === 'done' && <CheckCircle2 size={16} className="shrink-0" />}
        {job.status === 'error' && <XCircle size={16} className="shrink-0" />}

        <div className="min-w-0 flex-1">
          {job.status === 'running' && (
            <span>{t('reEvalJobBanner.running', { ticketId: job.ticketId })}</span>
          )}
          {job.status === 'done' && (
            <span>
              {t('reEvalJobBanner.done', { ticketId: job.ticketId })}{' '}
              <strong className={ASSESSMENT_LABEL_CLASS[job.assessment] || ''}>{job.assessment}</strong>
            </span>
          )}
          {job.status === 'error' && (
            <span>{t('reEvalJobBanner.error', { ticketId: job.ticketId, message: job.message || '' })}</span>
          )}
        </div>

        {canView && job.status !== 'running' && (
          <button
            type="button"
            onClick={handleView}
            className="text-xs font-medium underline underline-offset-2 shrink-0 cursor-pointer"
          >
            {t('reEvalJobBanner.view')}
          </button>
        )}
        <button
          type="button"
          onClick={dismissJob}
          className="p-1 rounded hover:bg-black/5 shrink-0 cursor-pointer"
          aria-label={t('ticketDetail.close')}
        >
          <X size={14} />
        </button>
      </div>
    </div>
  )
}
