import { useState } from 'react'
import { CheckCircle2, Loader2, Plug } from 'lucide-react'
import { useTranslation } from 'react-i18next'

/**
 * Generic "connect to an external source" card (Git repo, Jira project, ...).
 * By default this is a UI-only preview: clicking Connect simulates a short
 * handshake and flips to a mock "Connected" state. Passing `onConnectRequest`
 * (async (values) => { message }) makes it real: it's awaited instead, and a
 * thrown Error's message is shown as the connect error.
 */
export default function ConnectPanel({
  icon: Icon = Plug,
  title,
  description,
  fields,
  connectLabel,
  onConnect,
  onDisconnect,
  onConnectRequest,
}) {
  const { t } = useTranslation()
  const [values, setValues] = useState(() =>
    Object.fromEntries(fields.map((f) => [f.key, f.defaultValue || '']))
  )
  const [status, setStatus] = useState('idle') // idle | connecting | connected | error
  const [errorMsg, setErrorMsg] = useState('')
  const [resultMessage, setResultMessage] = useState('')

  const requiredFilled = fields.every((f) => !f.required || values[f.key]?.trim())

  const handleConnect = async () => {
    if (!requiredFilled) {
      setErrorMsg(t('connectPanel.fillRequired'))
      return
    }
    setErrorMsg('')
    setStatus('connecting')

    if (onConnectRequest) {
      try {
        const result = await onConnectRequest(values)
        setResultMessage(result?.message || '')
        setStatus('connected')
        onConnect?.(values, result)
      } catch (err) {
        setStatus('error')
        setErrorMsg(err?.message || t('connectPanel.connectionFailed'))
      }
      return
    }

    // Simulated handshake — no backend call exists for this field set.
    setTimeout(() => {
      setStatus('connected')
      onConnect?.(values)
    }, 900)
  }

  const handleDisconnect = () => {
    setStatus('idle')
    setResultMessage('')
    onDisconnect?.()
  }

  return (
    <div className="rounded-xl border border-slate-200 bg-slate-50 p-4 mb-4">
      <div className="flex items-center gap-2 mb-2.5">
        <Icon size={15} className="text-primary-600" />
        <p className="text-xs font-semibold text-slate-700">{title}</p>
        {!onConnectRequest && <span className="badge-gray">{t('connectPanel.preview')}</span>}
        {status === 'connected' && (
          <span className="inline-flex items-center gap-1 text-xs text-emerald-600 font-medium ml-auto">
            <CheckCircle2 size={13} /> {t('connectPanel.connected')}
          </span>
        )}
      </div>
      {description && <p className="text-xs text-slate-500 mb-3">{description}</p>}

      {status === 'connected' ? (
        <div className="flex items-center justify-between gap-3">
          <div className="text-xs text-slate-600 space-y-0.5">
            {resultMessage && (
              <p className="text-emerald-700 font-medium mb-1">{resultMessage}</p>
            )}
            {fields.map((f) => (
              <p key={f.key}>
                <span className="text-slate-400">{f.label}: </span>
                <span className="font-mono">
                  {f.sensitive
                    ? '••••••••'
                    : f.type === 'select'
                    ? f.options?.find((o) => o.value === values[f.key])?.label || values[f.key]
                    : values[f.key]}
                </span>
              </p>
            ))}
          </div>
          <button onClick={handleDisconnect} className="btn-secondary text-xs px-3 py-1.5">
            {t('connectPanel.disconnect')}
          </button>
        </div>
      ) : (
        <>
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-2.5 mb-3">
            {fields.map((f) =>
              f.type === 'select' ? (
                <select
                  key={f.key}
                  value={values[f.key]}
                  onChange={(e) => setValues((prev) => ({ ...prev, [f.key]: e.target.value }))}
                  className="input-field text-sm py-2"
                >
                  {f.options?.map((o) => (
                    <option key={o.value} value={o.value}>
                      {o.label}
                    </option>
                  ))}
                </select>
              ) : (
                <input
                  key={f.key}
                  type={f.type || 'text'}
                  value={values[f.key]}
                  onChange={(e) => setValues((prev) => ({ ...prev, [f.key]: e.target.value }))}
                  placeholder={f.placeholder}
                  className="input-field text-sm py-2"
                />
              )
            )}
          </div>
          <button
            onClick={handleConnect}
            disabled={status === 'connecting'}
            className="px-3 py-1.5 text-xs font-medium rounded-lg border border-primary-200 text-primary-700 bg-primary-50 hover:bg-primary-100 cursor-pointer disabled:opacity-50"
          >
            {status === 'connecting' ? (
              <>
                <Loader2 size={12} className="animate-spin inline mr-1" />
                {t('connectPanel.connecting')}
              </>
            ) : (
              <>
                <Plug size={12} className="inline mr-1" />
                {connectLabel || t('connectPanel.connect')}
              </>
            )}
          </button>
          {errorMsg && <p className="text-xs text-red-600 mt-1.5">{errorMsg}</p>}
        </>
      )}
    </div>
  )
}
