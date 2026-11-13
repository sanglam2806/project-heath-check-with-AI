import { useEffect, useState } from 'react'
import { X, UserPlus, UserMinus, Loader2 } from 'lucide-react'
import { useTranslation } from 'react-i18next'
import { listMembers, getProjectMembers, addProjectMember, removeProjectMember } from '../api'

/**
 * Owner/Admin-only modal: pick which org members can see a specific
 * project (project_members — a pure visibility grant, independent of
 * whether that member has personally run a scan on it). The project's
 * "Checker" (owner_id, whoever last scanned it) is shown read-only here —
 * it isn't itself grantable/revocable through this list, it's automatic.
 */
export default function ProjectMembersModal({ project, onClose }) {
  const { t } = useTranslation()
  const [allMembers, setAllMembers] = useState([])
  const [grantedIds, setGrantedIds] = useState(() => new Set())
  const [status, setStatus] = useState('loading') // loading | done | error
  const [error, setError] = useState('')
  const [pendingId, setPendingId] = useState(null)

  useEffect(() => {
    let cancelled = false
    setStatus('loading')
    Promise.all([listMembers(), getProjectMembers(project.id)])
      .then(([members, granted]) => {
        if (cancelled) return
        setAllMembers(members)
        setGrantedIds(new Set(granted.map((u) => u.id)))
        setStatus('done')
      })
      .catch((err) => {
        if (cancelled) return
        setError(err.message || t('projectMembers.failedToLoad'))
        setStatus('error')
      })
    return () => {
      cancelled = true
    }
  }, [project.id, t])

  const toggle = async (userId, isGranted) => {
    setPendingId(userId)
    setError('')
    try {
      const updated = isGranted
        ? await removeProjectMember(project.id, userId)
        : await addProjectMember(project.id, userId)
      setGrantedIds(new Set(updated.map((u) => u.id)))
    } catch (err) {
      setError(err.message || t('projectMembers.updateFailed'))
    } finally {
      setPendingId(null)
    }
  }

  // Owner/Admin already see every project regardless -- granting them here
  // would be a no-op, so only offer Editor/Viewer accounts in the picker.
  const pickable = allMembers.filter((m) => m.role === 'Editor' || m.role === 'Viewer')

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/50 backdrop-blur-sm"
      onClick={onClose}
    >
      <div
        className="bg-white rounded-2xl shadow-xl w-full max-w-lg max-h-[85vh] overflow-hidden flex flex-col"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="px-6 py-4 border-b border-slate-200 flex items-start justify-between gap-4">
          <div>
            <h2 className="text-lg font-bold">{t('projectMembers.title')}</h2>
            <p className="text-sm text-slate-500">{project.name}</p>
          </div>
          <button
            onClick={onClose}
            className="p-1.5 rounded-lg hover:bg-slate-100 text-slate-500 cursor-pointer"
            aria-label={t('ticketDetail.close')}
          >
            <X size={20} />
          </button>
        </div>

        <div className="px-6 py-4 overflow-y-auto space-y-3">
          <p className="text-xs text-slate-500">{t('projectMembers.description')}</p>

          {project.owner && (
            <div className="text-xs text-slate-500 bg-slate-50 rounded-lg px-3 py-2 border border-slate-100">
              {t('projectMembers.checkerNote', { name: project.owner })}
            </div>
          )}

          {error && (
            <div className="p-2.5 rounded-lg bg-red-50 border border-red-200 text-red-700 text-xs">{error}</div>
          )}

          {status === 'loading' && (
            <div className="flex items-center justify-center gap-2 py-8 text-sm text-slate-400">
              <Loader2 size={16} className="animate-spin" /> {t('projectMembers.loading')}
            </div>
          )}

          {status === 'error' && !error && (
            <p className="text-sm text-red-600 py-4">{t('projectMembers.failedToLoad')}</p>
          )}

          {status === 'done' && pickable.length === 0 && (
            <p className="text-sm text-slate-400 text-center py-6">{t('projectMembers.noEditorsOrViewers')}</p>
          )}

          {status === 'done' && pickable.length > 0 && (
            <ul className="divide-y divide-slate-100 border border-slate-100 rounded-lg">
              {pickable.map((m) => {
                const isGranted = grantedIds.has(m.id)
                return (
                  <li key={m.id} className="flex items-center justify-between gap-3 px-3 py-2.5">
                    <div className="min-w-0">
                      <p className="text-sm font-medium text-slate-800 truncate">{m.name}</p>
                      <p className="text-xs text-slate-400 truncate">
                        {m.email} · {m.role}
                        {m.status === 'pending' && ` · ${t('members.pending')}`}
                      </p>
                    </div>
                    <button
                      type="button"
                      onClick={() => toggle(m.id, isGranted)}
                      disabled={pendingId === m.id}
                      className={`shrink-0 inline-flex items-center gap-1.5 px-2.5 py-1.5 text-xs font-medium rounded-lg border cursor-pointer disabled:opacity-50 ${
                        isGranted
                          ? 'border-red-200 text-red-700 bg-red-50 hover:bg-red-100'
                          : 'border-primary-200 text-primary-700 bg-primary-50 hover:bg-primary-100'
                      }`}
                    >
                      {pendingId === m.id ? (
                        <Loader2 size={12} className="animate-spin" />
                      ) : isGranted ? (
                        <UserMinus size={12} />
                      ) : (
                        <UserPlus size={12} />
                      )}
                      {isGranted ? t('projectMembers.revoke') : t('projectMembers.grant')}
                    </button>
                  </li>
                )
              })}
            </ul>
          )}
        </div>

        <div className="px-6 py-3 border-t border-slate-200 flex justify-end">
          <button
            onClick={onClose}
            className="px-4 py-2 text-sm font-medium text-slate-600 hover:bg-slate-100 rounded-lg cursor-pointer"
          >
            {t('ticketDetail.close')}
          </button>
        </div>
      </div>
    </div>
  )
}
