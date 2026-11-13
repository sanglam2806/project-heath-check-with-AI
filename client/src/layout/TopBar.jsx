import { LogOut } from 'lucide-react'
import { useTranslation } from 'react-i18next'
import { ROUTES } from '../router'
import { useEvaluationContext } from '../context/EvaluationContext'
import { useAuth } from '../context/AuthContext'
import { setLanguage } from '../i18n'

function LanguageSwitcher() {
  const { t, i18n } = useTranslation()
  return (
    <div className="inline-flex rounded-lg border border-slate-200 p-0.5 bg-slate-50 text-xs">
      <button
        type="button"
        onClick={() => setLanguage('en')}
        className={`px-2 py-1 rounded-md cursor-pointer transition-colors ${
          i18n.language === 'en' ? 'bg-white shadow-sm text-primary-700 font-medium' : 'text-slate-500 hover:text-slate-700'
        }`}
      >
        {t('language.english')}
      </button>
      <button
        type="button"
        onClick={() => setLanguage('ja')}
        className={`px-2 py-1 rounded-md cursor-pointer transition-colors ${
          i18n.language === 'ja' ? 'bg-white shadow-sm text-primary-700 font-medium' : 'text-slate-500 hover:text-slate-700'
        }`}
      >
        {t('language.japanese')}
      </button>
      <button
        type="button"
        onClick={() => setLanguage('vi')}
        className={`px-2 py-1 rounded-md cursor-pointer transition-colors ${
          i18n.language === 'vi' ? 'bg-white shadow-sm text-primary-700 font-medium' : 'text-slate-500 hover:text-slate-700'
        }`}
      >
        {t('language.vietnamese')}
      </button>
    </div>
  )
}

export default function TopBar({ currentKey }) {
  const { t } = useTranslation()
  const { evaluation } = useEvaluationContext()
  const { user, logout } = useAuth()
  const route = ROUTES.find((r) => r.key === currentKey) || ROUTES[0]

  return (
    <header className="bg-white border-b border-slate-200 sticky top-0 z-40">
      <div className="px-6 py-4 flex items-center justify-between">
        <div>
          <h1 className="text-lg font-bold leading-tight text-slate-900">{t(route.labelKey)}</h1>
          <p className="text-xs text-slate-500">{t('topbar.subtitle')}</p>
        </div>
        <div className="flex items-center gap-4">
          <LanguageSwitcher />
          {evaluation && (
            <span className="inline-flex items-center gap-1.5 text-xs text-emerald-600 font-medium">
              <span className="w-1.5 h-1.5 rounded-full bg-emerald-500" />
              {t('topbar.sessionDataAvailable')}
            </span>
          )}
          {user && (
            <div className="flex items-center gap-3 pl-4 border-l border-slate-200">
              <div className="text-right leading-tight">
                <p className="text-sm font-medium text-slate-800">{user.name}</p>
                <p className="text-xs text-slate-400">{user.role}</p>
              </div>
              <button
                type="button"
                onClick={logout}
                title={t('topbar.logout')}
                className="w-8 h-8 rounded-lg flex items-center justify-center text-slate-400 hover:text-red-600 hover:bg-red-50 cursor-pointer transition-colors"
              >
                <LogOut size={16} />
              </button>
            </div>
          )}
        </div>
      </div>
    </header>
  )
}
