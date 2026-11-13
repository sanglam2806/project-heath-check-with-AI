import { useEffect } from 'react'
import { ROUTES, useHashRoute } from '../router'
import { useAuth } from '../context/AuthContext'
import Sidebar from './Sidebar'
import TopBar from './TopBar'
import ReEvalJobBanner from '../components/ReEvalJobBanner'
import CheckHealthConnectPage from '../pages/CheckHealthConnectPage'
import CheckHealthUploadPage from '../pages/CheckHealthUploadPage'
import Dashboard from '../pages/Dashboard'
import ProjectListPage from '../pages/ProjectListPage'
import ProjectDetailPage from '../pages/ProjectDetailPage'
import RiskPage from '../pages/RiskPage'
import SolutionsPage from '../pages/SolutionsPage'
import MemberSettingsPage from '../pages/MemberSettingsPage'
import ModelConfigPage from '../pages/ModelConfigPage'
import MemberPerformancePage from '../pages/MemberPerformancePage'

const PAGES = {
  checkHealthConnect: CheckHealthConnectPage,
  checkHealthUpload: CheckHealthUploadPage,
  dashboard: Dashboard,
  projects: ProjectListPage,
  risk: RiskPage,
  solutions: SolutionsPage,
  members: MemberSettingsPage,
  modelConfig: ModelConfigPage,
  memberPerformance: MemberPerformancePage,
}

// Sub-routes that render a dedicated component (with dynamic params) rather
// than a plain entry in PAGES, but should keep a parent sidebar item
// highlighted.
const DETAIL_PAGES = {
  projectDetail: { Component: ProjectDetailPage, propKey: 'projectId', sidebarKey: 'projects' },
  checkHealthConnectExisting: {
    Component: CheckHealthConnectPage,
    propKey: 'initialProjectId',
    sidebarKey: 'checkHealthConnect',
  },
}

export default function AppShell() {
  const { currentKey, params, navigate } = useHashRoute()
  const { user } = useAuth()
  const detailRoute = DETAIL_PAGES[currentKey]
  const sidebarKey = detailRoute ? detailRoute.sidebarKey : currentKey

  // Defense in depth for a direct/deep link (typed URL, bookmark, or the
  // Project List's Re-check button) into a route the user's role can't see
  // in the sidebar -- redirect away instead of rendering it (the underlying
  // API calls would just fail with 403 anyway, see main.py's role checks).
  const routeDef = ROUTES.find((r) => r.key === sidebarKey)
  const forbidden = !!routeDef?.roles && !routeDef.roles.includes(user?.role)
  useEffect(() => {
    if (forbidden) navigate('#/dashboard')
  }, [forbidden, navigate])

  let page
  if (forbidden) {
    page = null
  } else if (detailRoute) {
    const { Component, propKey } = detailRoute
    page = <Component {...{ [propKey]: params.id }} />
  } else {
    const Page = PAGES[currentKey] || CheckHealthConnectPage
    page = <Page />
  }

  return (
    <div className="min-h-screen flex">
      <Sidebar currentKey={sidebarKey} navigate={navigate} />
      <div className="flex-1 min-w-0">
        <TopBar currentKey={sidebarKey} />
        <ReEvalJobBanner />
        <main className="max-w-7xl mx-auto px-4 sm:px-6 py-8 space-y-8">{page}</main>
      </div>
    </div>
  )
}
