import { useEffect, useState } from 'react'
import { ShieldCheck, Loader2, UserPlus } from 'lucide-react'
import { useTranslation } from 'react-i18next'
import { useAuth } from '../context/AuthContext'
import { getInvitePreview } from '../api'

export default function AcceptInvitePage({ token }) {
  const { t } = useTranslation()
  const { acceptInvite } = useAuth()
  const [status, setStatus] = useState('loading') // loading | ready | error
  const [error, setError] = useState('')
  const [preview, setPreview] = useState(null)

  const [name, setName] = useState('')
  const [password, setPassword] = useState('')
  const [confirmPassword, setConfirmPassword] = useState('')
  const [submitting, setSubmitting] = useState(false)
  const [submitError, setSubmitError] = useState('')

  useEffect(() => {
    let cancelled = false
    getInvitePreview(token)
      .then((data) => {
        if (cancelled) return
        setPreview(data)
        setName(data.name || '')
        setStatus('ready')
      })
      .catch((err) => {
        if (cancelled) return
        setError(err.message || t('acceptInvite.inviteInvalid'))
        setStatus('error')
      })
    return () => {
      cancelled = true
    }
  }, [token])

  const handleSubmit = async (e) => {
    e.preventDefault()
    setSubmitError('')
    if (password.length < 6) {
      setSubmitError(t('acceptInvite.passwordTooShort'))
      return
    }
    if (password !== confirmPassword) {
      setSubmitError(t('acceptInvite.passwordMismatch'))
      return
    }
    setSubmitting(true)
    try {
      await acceptInvite(token, name, password)
    } catch (err) {
      setSubmitError(err.message || t('acceptInvite.activationFailed'))
      setSubmitting(false)
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
          <p className="text-sm text-slate-500 mt-1">{t('acceptInvite.subtitle')}</p>
        </div>

        {status === 'loading' && (
          <div className="card p-6 flex items-center justify-center gap-2 text-slate-500 text-sm">
            <Loader2 size={18} className="animate-spin" /> {t('acceptInvite.checkingInvite')}
          </div>
        )}

        {status === 'error' && (
          <div className="card p-6 text-center">
            <p className="text-sm text-red-600">{error}</p>
            <a href="#/login" className="text-primary-600 hover:underline text-sm mt-3 inline-block">
              {t('acceptInvite.backToLogin')}
            </a>
          </div>
        )}

        {status === 'ready' && (
          <form onSubmit={handleSubmit} className="card p-6 space-y-4">
            <div className="p-2.5 rounded-lg bg-primary-50 border border-primary-100 text-primary-700 text-xs flex items-center gap-2">
              <UserPlus size={14} className="shrink-0" />
              {t('acceptInvite.invitedAs', { role: preview.role })}
              {preview.group_name ? ` ${t('acceptInvite.inGroup', { group: preview.group_name })}` : ''}.
            </div>

            <div>
              <label className="text-xs font-medium text-slate-600 mb-1 block">Email</label>
              <input type="email" value={preview.email} disabled className="input-field bg-slate-50 text-slate-500" />
            </div>
            <div>
              <label className="text-xs font-medium text-slate-600 mb-1 block">{t('acceptInvite.fullName')}</label>
              <input
                type="text"
                required
                value={name}
                onChange={(e) => setName(e.target.value)}
                className="input-field"
                autoFocus
              />
            </div>
            <div>
              <label className="text-xs font-medium text-slate-600 mb-1 block">{t('acceptInvite.password')}</label>
              <input
                type="password"
                required
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                className="input-field"
                placeholder={t('acceptInvite.passwordPlaceholder')}
              />
            </div>
            <div>
              <label className="text-xs font-medium text-slate-600 mb-1 block">{t('acceptInvite.confirmPassword')}</label>
              <input
                type="password"
                required
                value={confirmPassword}
                onChange={(e) => setConfirmPassword(e.target.value)}
                className="input-field"
                placeholder="••••••••"
              />
            </div>

            {submitError && (
              <div className="p-2.5 rounded-lg bg-red-50 border border-red-200 text-red-700 text-xs">
                {submitError}
              </div>
            )}

            <button type="submit" disabled={submitting} className="btn-primary w-full">
              {submitting && <Loader2 size={16} className="animate-spin" />}
              {t('acceptInvite.activateButton')}
            </button>
          </form>
        )}
      </div>
    </div>
  )
}
