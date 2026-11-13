import { Activity } from 'lucide-react'
import { useTranslation } from 'react-i18next'
import { ROUTES, CHECK_HEALTH_GROUP } from '../router'
import { useAuth } from '../context/AuthContext'

function NavLink({ route, isActive, navigate, indent }) {
  const { t } = useTranslation()
  const Icon = route.icon
  return (
    <button
      type="button"
      aria-current={isActive ? 'page' : undefined}
      onClick={() => navigate(route.path)}
      className={`sidebar-link w-full text-left ${indent ? 'pl-8' : ''} ${
        isActive ? 'sidebar-link-active' : 'sidebar-link-idle'
      }`}
    >
      <Icon size={indent ? 15 : 17} className="shrink-0" />
      <span className="truncate">{t(route.labelKey)}</span>
    </button>
  )
}

export default function Sidebar({ currentKey, navigate }) {
  const { t } = useTranslation()
  const { user } = useAuth()
  const visibleRoutes = ROUTES.filter((r) => !r.roles || r.roles.includes(user?.role))
  const checkHealthRoutes = visibleRoutes.filter((r) => r.group === CHECK_HEALTH_GROUP.key)
  const otherRoutes = visibleRoutes.filter((r) => r.group !== CHECK_HEALTH_GROUP.key)
  const GroupIcon = CHECK_HEALTH_GROUP.icon
  if (checkHealthRoutes.length === 0 && otherRoutes.length === 0) return null

  return (
    <aside className="w-64 shrink-0 bg-sidebar min-h-screen flex flex-col">
      <div className="h-16 flex items-center gap-3 px-5 border-b border-sidebar-border">
        <div className="w-9 h-9 rounded-lg bg-primary-600 flex items-center justify-center text-white shrink-0">
          <Activity size={18} />
        </div>
        <div className="min-w-0">
          <p className="text-sm font-semibold text-white truncate">{t('sidebar.appName')}</p>
          <p className="text-[11px] text-slate-400 truncate">{t('sidebar.appSubtitle')}</p>
        </div>
      </div>

      <nav className="flex-1 px-3 py-4 space-y-1">
        {checkHealthRoutes.length > 0 && (
          <>
            <div className="flex items-center gap-2 px-3 py-2 text-xs font-semibold uppercase tracking-wide text-slate-400">
              <GroupIcon size={14} className="shrink-0" />
              <span className="truncate">{t(CHECK_HEALTH_GROUP.labelKey)}</span>
            </div>
            {checkHealthRoutes.map((route) => (
              <NavLink key={route.key} route={route} isActive={currentKey === route.key} navigate={navigate} indent />
            ))}

            <div className="h-2" />
          </>
        )}

        {otherRoutes.map((route) => (
          <NavLink key={route.key} route={route} isActive={currentKey === route.key} navigate={navigate} />
        ))}
      </nav>
    </aside>
  )
}
