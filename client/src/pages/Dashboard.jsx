import { useEffect, useMemo, useState } from 'react'
import { Activity, Loader2 } from 'lucide-react'
import { useTranslation } from 'react-i18next'
import { listProjects } from '../api'
import ProjectSummaryCards from '../components/dashboard/ProjectSummaryCards'
import ProjectFilterBar from '../components/dashboard/ProjectFilterBar'
import ProjectTable from '../components/dashboard/ProjectTable'
import { useEvaluationContext } from '../context/EvaluationContext'

export default function Dashboard() {
  const { t } = useTranslation()
  const { evaluation } = useEvaluationContext()
  const [projects, setProjects] = useState([])
  const [status, setStatus] = useState('loading') // loading | done | error
  const [error, setError] = useState('')
  const [query, setQuery] = useState('')
  const [healthFilter, setHealthFilter] = useState('all')

  useEffect(() => {
    let cancelled = false
    setStatus('loading')
    listProjects()
      .then((data) => {
        if (cancelled) return
        setProjects(data)
        setStatus('done')
      })
      .catch((err) => {
        if (cancelled) return
        setError(err.message || t('dashboard.failedToLoad'))
        setStatus('error')
      })
    return () => {
      cancelled = true
    }
  }, [])

  const searchFiltered = useMemo(() => {
    const q = query.trim().toLowerCase()
    if (!q) return projects
    return projects.filter(
      (p) => p.name.toLowerCase().includes(q) || (p.owner || '').toLowerCase().includes(q)
    )
  }, [query, projects])

  const filtered = useMemo(() => {
    if (healthFilter === 'all') return searchFiltered
    return searchFiltered.filter((p) => p.healthStatus === healthFilter)
  }, [searchFiltered, healthFilter])

  return (
    <>
      {status === 'loading' && (
        <div className="card p-8 flex items-center justify-center gap-2 text-slate-500 text-sm">
          <Loader2 size={18} className="animate-spin" /> {t('dashboard.loadingProjects')}
        </div>
      )}

      {status === 'error' && (
        <div className="p-3 rounded-lg bg-red-50 border border-red-200 text-red-700 text-sm">
          {error}
        </div>
      )}

      {status === 'done' && (
        <>
          <ProjectSummaryCards projects={projects} />

          {evaluation?.summary && (
            <section className="card p-5 flex items-center gap-4 border-l-4 border-l-primary-600">
              <div className="w-11 h-11 rounded-lg bg-primary-100 text-primary-600 flex items-center justify-center shrink-0">
                <Activity size={22} />
              </div>
              <div>
                <p className="text-sm font-semibold text-slate-800">{t('dashboard.sessionCheck')}</p>
                <p className="text-xs text-slate-500">
                  {t('dashboard.sessionCheckDetail', {
                    total: evaluation.summary.total_tickets,
                    match: evaluation.summary.match_percent,
                    health: evaluation.health?.status,
                  })}
                </p>
              </div>
            </section>
          )}

          <ProjectFilterBar
            query={query}
            onQueryChange={setQuery}
            healthFilter={healthFilter}
            onHealthFilterChange={setHealthFilter}
            projects={searchFiltered}
          />

          <p className="text-sm text-slate-500">
            {t('projectFilterBar.showingCount', { shown: filtered.length, total: projects.length })}
          </p>

          <ProjectTable projects={filtered} />
        </>
      )}
    </>
  )
}
