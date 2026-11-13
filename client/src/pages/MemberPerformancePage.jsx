import { Fragment, useEffect, useMemo, useState } from 'react'
import { BarChart3, Loader2, ChevronDown, ChevronRight, Search } from 'lucide-react'
import { useTranslation } from 'react-i18next'
import { getMemberPerformance } from '../api'
import Pagination from '../components/Pagination'

const PAGE_SIZE = 15

function ProjectBreakdown({ projects }) {
  const { t } = useTranslation()
  return (
    <tr>
      <td colSpan={5} className="px-0 py-0 bg-slate-50">
        <div className="px-6 py-3">
          <table className="w-full text-xs">
            <thead>
              <tr className="text-left text-slate-400 uppercase tracking-wide">
                <th className="py-1.5 font-medium">{t('memberPerformance.project')}</th>
                <th className="py-1.5 font-medium">{t('memberPerformance.total')}</th>
                <th className="py-1.5 font-medium">{t('memberPerformance.complete')}</th>
                <th className="py-1.5 font-medium">{t('memberPerformance.late')}</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-100">
              {projects.map((p) => (
                <tr key={p.project_id}>
                  <td className="py-1.5 pr-4 text-slate-700 font-medium">{p.project_name}</td>
                  <td className="py-1.5 pr-4 text-slate-600">{p.total}</td>
                  <td className="py-1.5 pr-4">
                    <span className="badge-green">{p.complete}</span>
                  </td>
                  <td className="py-1.5">
                    <span className="badge-red">{p.late}</span>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </td>
    </tr>
  )
}

export default function MemberPerformancePage() {
  const { t } = useTranslation()

  const [status, setStatus] = useState('loading') // loading | done | error
  const [error, setError] = useState('')
  const [members, setMembers] = useState([])
  const [search, setSearch] = useState('')
  const [page, setPage] = useState(1)
  const [expanded, setExpanded] = useState(() => new Set())

  useEffect(() => {
    let cancelled = false
    getMemberPerformance()
      .then((data) => {
        if (cancelled) return
        setMembers(data)
        setStatus('done')
      })
      .catch((err) => {
        if (cancelled) return
        setError(err.message || t('memberPerformance.failedToLoad'))
        setStatus('error')
      })
    return () => {
      cancelled = true
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  const filtered = useMemo(() => {
    const q = search.trim().toLowerCase()
    if (!q) return members
    return members.filter((m) => m.display_name.toLowerCase().includes(q))
  }, [members, search])

  const pageCount = Math.max(1, Math.ceil(filtered.length / PAGE_SIZE))
  const safePage = Math.min(page, pageCount)
  const paged = filtered.slice((safePage - 1) * PAGE_SIZE, safePage * PAGE_SIZE)

  const toggleExpanded = (key) => {
    setExpanded((prev) => {
      const next = new Set(prev)
      if (next.has(key)) next.delete(key)
      else next.add(key)
      return next
    })
  }

  if (status === 'loading') {
    return (
      <div className="card p-10 flex flex-col items-center gap-3">
        <Loader2 size={28} className="animate-spin text-primary-600" />
        <p className="text-sm text-slate-500">{t('memberPerformance.loading')}</p>
      </div>
    )
  }

  if (status === 'error') {
    return <div className="p-4 rounded-lg bg-red-50 border border-red-200 text-red-700 text-sm">{error}</div>
  }

  return (
    <>
      <section className="card p-6 flex items-center justify-between gap-4 flex-wrap">
        <div className="flex items-start gap-3">
          <div className="w-10 h-10 rounded-lg bg-primary-50 flex items-center justify-center shrink-0">
            <BarChart3 size={18} className="text-primary-600" />
          </div>
          <div>
            <h1 className="font-semibold text-slate-800">{t('memberPerformance.title')}</h1>
            <p className="text-sm text-slate-500 mt-0.5">{t('memberPerformance.subtitle')}</p>
          </div>
        </div>
        <div className="relative">
          <Search size={14} className="absolute left-2.5 top-1/2 -translate-y-1/2 text-slate-400" />
          <input
            type="text"
            value={search}
            onChange={(e) => {
              setSearch(e.target.value)
              setPage(1)
            }}
            placeholder={t('memberPerformance.searchPlaceholder')}
            className="input-field w-64 text-sm py-1.5 pl-8"
          />
        </div>
      </section>

      <section className="card overflow-hidden">
        {filtered.length === 0 ? (
          <p className="px-6 py-10 text-sm text-slate-400 text-center">
            {members.length === 0 ? t('memberPerformance.noData') : t('memberPerformance.noMembersMatchFilter')}
          </p>
        ) : (
          <>
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead>
                  <tr className="bg-slate-50 text-left text-xs uppercase tracking-wide text-slate-500">
                    <th className="px-6 py-3 font-semibold w-8"></th>
                    <th className="px-6 py-3 font-semibold">{t('memberPerformance.assignTo')}</th>
                    <th className="px-6 py-3 font-semibold">{t('memberPerformance.total')}</th>
                    <th className="px-6 py-3 font-semibold">{t('memberPerformance.complete')}</th>
                    <th className="px-6 py-3 font-semibold">{t('memberPerformance.inProcess')}</th>
                    <th className="px-6 py-3 font-semibold">{t('memberPerformance.late')}</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-slate-100">
                  {paged.map((m) => {
                    const isOpen = expanded.has(m.assignee_key)
                    return (
                      <Fragment key={m.assignee_key}>
                        <tr
                          onClick={() => toggleExpanded(m.assignee_key)}
                          className="hover:bg-slate-50 transition-colors cursor-pointer"
                        >
                          <td className="px-6 py-3 text-slate-400">
                            {isOpen ? <ChevronDown size={15} /> : <ChevronRight size={15} />}
                          </td>
                          <td className="px-6 py-3 font-medium text-slate-800">
                            {m.display_name}
                            {m.projects.length > 1 && (
                              <span className="ml-2 text-xs text-slate-400 font-normal">
                                {t('memberPerformance.projectCount', { count: m.projects.length })}
                              </span>
                            )}
                          </td>
                          <td className="px-6 py-3 text-slate-600">{m.total}</td>
                          <td className="px-6 py-3">
                            <span className="badge-green">{m.complete}</span>
                          </td>
                          <td className="px-6 py-3">
                            <span className="badge-blue">{m.in_process}</span>
                          </td>
                          <td className="px-6 py-3">
                            <span className="badge-red">{m.late}</span>
                          </td>
                        </tr>
                        {isOpen && <ProjectBreakdown projects={m.projects} />}
                      </Fragment>
                    )
                  })}
                </tbody>
              </table>
            </div>
            <Pagination
              page={safePage}
              pageCount={pageCount}
              totalItems={filtered.length}
              pageSize={PAGE_SIZE}
              onPageChange={setPage}
            />
          </>
        )}
      </section>
    </>
  )
}
