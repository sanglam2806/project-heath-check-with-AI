import { useEffect, useState } from 'react'
import {
  ShieldCheck,
  GitBranch,
  Upload,
  LayoutDashboard,
  ListChecks,
  AlertTriangle,
  Users,
  Lightbulb,
  Settings,
  BarChart3,
} from 'lucide-react'
import {
  CHECK_HEALTH_ROLES,
  MEMBER_MANAGEMENT_ROLES,
  MODEL_CONFIG_ROLES,
  MEMBER_PERFORMANCE_ROLES,
} from './utils/permissions'

// The former single "Check Health Project" page split into two: connecting
// a project's Git/Jira source, and uploading a ZIP/Excel source manually.
// Both are grouped under the same sidebar heading (see Sidebar.jsx).
// `labelKey` is an i18next key (see src/i18n/locales) — these are plain JS
// module-level constants, not components, so they can't call useTranslation()
// themselves; Sidebar/TopBar call t(route.labelKey) instead of route.label.
export const CHECK_HEALTH_GROUP = { key: 'checkHealth', labelKey: 'routes.checkHealthGroup', icon: ShieldCheck }

export const ROUTES = [
  {
    path: '#/check-health/connect',
    key: 'checkHealthConnect',
    labelKey: 'routes.connectGitJira',
    icon: GitBranch,
    group: CHECK_HEALTH_GROUP.key,
    roles: CHECK_HEALTH_ROLES,
  },
  {
    path: '#/check-health/upload',
    key: 'checkHealthUpload',
    labelKey: 'routes.uploadZipExcel',
    icon: Upload,
    group: CHECK_HEALTH_GROUP.key,
    roles: CHECK_HEALTH_ROLES,
  },
  { path: '#/dashboard', key: 'dashboard', labelKey: 'routes.dashboard', icon: LayoutDashboard },
  { path: '#/projects', key: 'projects', labelKey: 'routes.projectList', icon: ListChecks },
  { path: '#/risk', key: 'risk', labelKey: 'routes.risk', icon: AlertTriangle },
  { path: '#/solutions', key: 'solutions', labelKey: 'routes.solutions', icon: Lightbulb },
  { path: '#/members', key: 'members', labelKey: 'routes.members', icon: Users, roles: MEMBER_MANAGEMENT_ROLES },
  {
    path: '#/member-performance',
    key: 'memberPerformance',
    labelKey: 'routes.memberPerformance',
    icon: BarChart3,
    roles: MEMBER_PERFORMANCE_ROLES,
  },
  { path: '#/model-config', key: 'modelConfig', labelKey: 'routes.modelConfig', icon: Settings, roles: MODEL_CONFIG_ROLES },
]

const DEFAULT_KEY = ROUTES[0].key

// Dynamic sub-routes: #/<prefix>/<id> -> a detail page, keyed separately
// from the static ROUTES above but still highlighting a parent sidebar item.
const DETAIL_ROUTES = [
  { prefix: 'projects', key: 'projectDetail' },
  // Deep-link into the Connect Git/Jira page's "Existing Project" mode with
  // a project preselected, e.g. from Project List's Re-check button.
  { prefix: 'check-health/connect', key: 'checkHealthConnectExisting' },
]

/** Change the current route. Usable both inside and outside components
 * (e.g. from a page's own "Back" button), since it's just a hash write. */
export function navigate(path) {
  window.location.hash = path
}

function parseHash(hash) {
  for (const { prefix, key } of DETAIL_ROUTES) {
    const match = hash.match(new RegExp(`^#/${prefix}/(.+)$`))
    if (match) {
      return { key, params: { id: decodeURIComponent(match[1]) } }
    }
  }
  const match = ROUTES.find((r) => r.path === hash)
  return { key: match ? match.key : DEFAULT_KEY, params: {} }
}

/** Tiny hash-based router: no external dependency, still gives back/forward
 * navigation and a refreshable URL per section for this app's pages. */
export function useHashRoute() {
  const [route, setRoute] = useState(() => parseHash(window.location.hash))

  useEffect(() => {
    const onHashChange = () => setRoute(parseHash(window.location.hash))
    window.addEventListener('hashchange', onHashChange)
    if (!window.location.hash) {
      navigate(ROUTES[0].path)
    }
    return () => window.removeEventListener('hashchange', onHashChange)
  }, [])

  return { currentKey: route.key, params: route.params, navigate }
}
