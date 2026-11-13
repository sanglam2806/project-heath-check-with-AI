import { useState } from 'react'
import { ShieldCheck, Loader2 } from 'lucide-react'
import { useTranslation } from 'react-i18next'
import { useAuth } from '../context/AuthContext'
import { navigate, ROUTES } from '../router'

export default function RegisterPage() {
  const { t } = useTranslation()
  const { register } = useAuth()
  const [name, setName] = useState('')
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [confirmPassword, setConfirmPassword] = useState('')
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')

  const handleSubmit = async (e) => {
    e.preventDefault()
    setError('')

    if (password.length < 6) {
      setError(t('register.passwordTooShort'))
      return
    }
    if (password !== confirmPassword) {
      setError(t('register.passwordMismatch'))
      return
    }

    setLoading(true)
    try {
      await register(name, email, password)
      navigate(ROUTES[0].path)
    } catch (err) {
      setError(err.message || t('register.registrationFailed'))
      setLoading(false)
    }
  }

  return (
    <div className="min-h-screen flex items-center justify-center bg-slate-100 px-4">
      <div className="w-full max-w-sm">
        <div className="flex flex-col items-center mb-6">
          <div className="w-12 h-12 rounded-xl bg-primary-600 flex items-center justify-center text-white mb-3">
            <ShieldCheck size={24} />
          </div>
          <h1 className="text-xl font-bold text-slate-900">Project Health Checker</h1>
          <p className="text-sm text-slate-500 mt-1">{t('register.subtitle')}</p>
        </div>

        <form onSubmit={handleSubmit} className="card p-6 space-y-4">
          <div>
            <label className="text-xs font-medium text-slate-600 mb-1 block">{t('register.fullName')}</label>
            <input
              type="text"
              required
              value={name}
              onChange={(e) => setName(e.target.value)}
              className="input-field"
              placeholder="Nguyen Van A"
              autoFocus
            />
          </div>
          <div>
            <label className="text-xs font-medium text-slate-600 mb-1 block">{t('register.email')}</label>
            <input
              type="email"
              required
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              className="input-field"
              placeholder="name@company.com"
            />
          </div>
          <div>
            <label className="text-xs font-medium text-slate-600 mb-1 block">{t('register.password')}</label>
            <input
              type="password"
              required
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              className="input-field"
              placeholder={t('register.passwordPlaceholder')}
            />
          </div>
          <div>
            <label className="text-xs font-medium text-slate-600 mb-1 block">{t('register.confirmPassword')}</label>
            <input
              type="password"
              required
              value={confirmPassword}
              onChange={(e) => setConfirmPassword(e.target.value)}
              className="input-field"
              placeholder="••••••••"
            />
          </div>

          {error && (
            <div className="p-2.5 rounded-lg bg-red-50 border border-red-200 text-red-700 text-xs">
              {error}
            </div>
          )}

          <button type="submit" disabled={loading} className="btn-primary w-full">
            {loading && <Loader2 size={16} className="animate-spin" />}
            {t('register.signUpButton')}
          </button>
        </form>

        <p className="text-center text-sm text-slate-500 mt-4">
          {t('register.haveAccount')}{' '}
          <button
            type="button"
            onClick={() => navigate('#/login')}
            className="text-primary-600 hover:underline cursor-pointer font-medium"
          >
            {t('register.logIn')}
          </button>
        </p>
      </div>
    </div>
  )
}
