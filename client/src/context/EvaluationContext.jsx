import { createContext, useContext, useEffect, useState, useCallback, useMemo } from 'react'
import { getRisk } from '../api'

const EvaluationContext = createContext(null)

const IDLE_ANALYSIS = { status: 'idle', data: null, error: '' }

export function EvaluationProvider({ children }) {
  const [evaluation, setEvaluationState] = useState(null) // { uploadId, tickets, results, summary, health, trend }
  const [risk, setRisk] = useState(IDLE_ANALYSIS)

  const setEvaluation = useCallback((payload) => {
    setEvaluationState(payload)
    setRisk(IDLE_ANALYSIS)
  }, [])

  // Whenever a fresh evaluation lands, fetch risk in the background so the
  // Risk Management page already has data (or a loading state) the moment
  // the user navigates to it.
  useEffect(() => {
    if (!evaluation || !evaluation.results || evaluation.results.length === 0) return

    let cancelled = false
    setRisk({ status: 'loading', data: null, error: '' })

    getRisk(evaluation.tickets, evaluation.results)
      .then((data) => {
        if (!cancelled) setRisk({ status: 'done', data, error: '' })
      })
      .catch((err) => {
        if (!cancelled) setRisk({ status: 'error', data: null, error: err.message || 'Risk analysis failed.' })
      })

    return () => {
      cancelled = true
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [evaluation])

  const value = useMemo(
    () => ({ evaluation, setEvaluation, risk }),
    [evaluation, setEvaluation, risk]
  )

  return <EvaluationContext.Provider value={value}>{children}</EvaluationContext.Provider>
}

export function useEvaluationContext() {
  const ctx = useContext(EvaluationContext)
  if (!ctx) {
    throw new Error('useEvaluationContext must be used within an EvaluationProvider')
  }
  return ctx
}
