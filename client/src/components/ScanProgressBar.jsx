import { useTranslation } from 'react-i18next'

const PHASE_LABEL_KEYS = {
  scanning: 'scanProgress.scanning',
  evaluating: 'scanProgress.evaluating',
  evaluating_deep: 'scanProgress.evaluatingDeep',
  deep_dive: 'scanProgress.deepDive',
}

/**
 * Real "X/Y tickets" progress bar for the long-running scan/evaluate
 * pipeline, polled from GET /api/scan-progress/{job_id} (see
 * server/scan_progress.py). Renders nothing until the first phase with a
 * known total arrives -- callers should still show their own indeterminate
 * spinner/label alongside this for phases with no ticket count yet (e.g.
 * "scanning" before evaluation starts).
 * @param {{ phase?: string, current?: number, total?: number }} progress
 */
export default function ScanProgressBar({ progress }) {
  const { t } = useTranslation()
  if (!progress || !progress.total) return null

  const { phase, current = 0, total } = progress
  const pct = Math.min(100, Math.round((current / total) * 100))
  const label = PHASE_LABEL_KEYS[phase] ? t(PHASE_LABEL_KEYS[phase]) : phase

  return (
    <div className="w-full max-w-sm">
      <div className="flex items-center justify-between text-xs text-slate-500 mb-1">
        <span>{label}</span>
        <span>
          {current}/{total} ({pct}%)
        </span>
      </div>
      <div className="w-full h-2 rounded-full bg-slate-200 overflow-hidden">
        <div
          className="h-full bg-blue-600 rounded-full transition-all duration-300"
          style={{ width: `${pct}%` }}
        />
      </div>
    </div>
  )
}
