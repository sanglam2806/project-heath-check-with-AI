import { useEffect, useMemo, useState } from 'react'
import { Loader2 } from 'lucide-react'
import { useTranslation } from 'react-i18next'
import { listProjects } from '../api'
import ProjectSummaryCards from '../components/dashboard/ProjectSummaryCards'
import ProjectFilterBar from '../components/dashboard/ProjectFilterBar'
import ProjectTable from '../components/dashboard/ProjectTable'
import ProjectMembersModal from '../components/ProjectMembersModal'
import { navigate } from '../router'
import { useAuth } from '../context/AuthContext'
import { canAccessCheckHealth, canManageMembers } from '../utils/permissions'

export default function ProjectListPage() {
  const { t } = useTranslation()
  const { user } = useAuth()
  const canRecheck = canAccessCheckHealth(user?.role)
  const canShare = canManageMembers(user?.role)
  const [membersModalProject, setMembersModalProject] = useState(null)
  const [query, setQuery] = useState('')
  const [healthFilter, setHealthFilter] = useState('all')
  const [projects, setProjects] = useState([])
  const [status, setStatus] = useState('loading') // loading | done | error
  const [error, setError] = useState('')

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
        setError(err.message || t('projectList.failedToLoad'))
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

  const handleDetail = (project) => {
    navigate(`#/projects/${encodeURIComponent(project.id)}`)
  }

  // Send the user to the Connect Git/Jira page in "Existing Project" mode with
  // this project already selected, so they can review/run the re-check
  // there instead of silently mutating the list row in place.
  const handleRecheck = (project) => {
    navigate(`#/check-health/connect/${encodeURIComponent(project.id)}`)
  }

  return (
    <>
      {status === 'loading' && (
        <div className="card p-8 flex items-center justify-center gap-2 text-slate-500 text-sm">
          <Loader2 size={18} className="animate-spin" /> {t('projectList.loadingProjects')}
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

          <ProjectTable
            projects={filtered}
            onDetail={handleDetail}
            onRecheck={handleRecheck}
            canRecheck={canRecheck}
            showChecker
            showTicketBreakdown={false}
            showCompleteTickets
            showReport
            onManageMembers={canShare ? setMembersModalProject : undefined}
          />
        </>
      )}

      {membersModalProject && (
        <ProjectMembersModal project={membersModalProject} onClose={() => setMembersModalProject(null)} />
      )}
    </>
  )
}
