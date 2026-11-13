import { createContext, useCallback, useContext, useMemo, useState } from 'react'

const ReEvalJobContext = createContext(null)

/**
 * Tracks the single most recent per-ticket re-evaluation job (see the
 * "Re-evaluate this ticket with AI" button in EvaluationResultsView),
 * independent of whichever page started it. This provider sits above
 * AppShell's page switch (see App.jsx), so unlike a page component's own
 * useState, it survives navigating away mid-request -- the request itself
 * was never cancelled by leaving the page (a plain HTTP call in flight
 * isn't torn down by client-side hash routing), so this just keeps the UI
 * honest about it instead of silently losing track: a banner (see
 * ReEvalJobBanner) stays visible across page changes while it runs, and
 * still reports the outcome even if you're on a different page by the
 * time it finishes.
 */
export function ReEvalJobProvider({ children }) {
  const [job, setJob] = useState(null) // { ticketId, projectId, projectName, status, assessment, message, startedAt }

  const startJob = useCallback((job) => {
    setJob({ ...job, status: 'running', startedAt: Date.now() })
  }, [])

  const finishJob = useCallback((patch) => {
    setJob((prev) => (prev ? { ...prev, ...patch } : prev))
  }, [])

  const dismissJob = useCallback(() => setJob(null), [])

  const value = useMemo(() => ({ job, startJob, finishJob, dismissJob }), [job, startJob, finishJob, dismissJob])

  return <ReEvalJobContext.Provider value={value}>{children}</ReEvalJobContext.Provider>
}

export function useReEvalJob() {
  const ctx = useContext(ReEvalJobContext)
  if (!ctx) {
    throw new Error('useReEvalJob must be used within a ReEvalJobProvider')
  }
  return ctx
}
