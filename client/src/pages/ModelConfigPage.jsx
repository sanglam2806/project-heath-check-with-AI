import { useEffect, useState } from 'react'
import { Settings, Loader2, Save, RotateCcw, Plug, CheckCircle2, XCircle } from 'lucide-react'
import { useTranslation } from 'react-i18next'
import { getModelConfig, updateModelConfig, testModelConfig } from '../api'

function TestResultBanner({ testStatus }) {
  const { t } = useTranslation()
  if (testStatus.state === 'idle') return null
  if (testStatus.state === 'testing') {
    return (
      <p className="text-xs text-slate-500 flex items-center gap-1.5 mt-2">
        <Loader2 size={12} className="animate-spin" /> {t('modelConfig.testing')}
      </p>
    )
  }
  const ok = testStatus.state === 'success'
  return (
    <p className={`text-xs flex items-start gap-1.5 mt-2 ${ok ? 'text-emerald-600' : 'text-red-600'}`}>
      {ok ? <CheckCircle2 size={13} className="shrink-0 mt-0.5" /> : <XCircle size={13} className="shrink-0 mt-0.5" />}
      <span>{testStatus.message}</span>
    </p>
  )
}

function ModelSection({
  title,
  description,
  fields,
  apiKeySet,
  apiKeyMasked,
  apiKeyValue,
  onApiKeyChange,
  clearKey,
  onClearKeyChange,
  onTest,
  testStatus,
}) {
  const { t } = useTranslation()
  return (
    <section className="card p-6 space-y-4">
      <div>
        <h2 className="font-semibold text-slate-800">{title}</h2>
        <p className="text-xs text-slate-500 mt-0.5">{description}</p>
      </div>
      <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
        {fields.map((f) => (
          <label key={f.key} className="block">
            <span className="text-xs font-medium text-slate-600 mb-1 block">{f.label}</span>
            <input
              type="text"
              value={f.value}
              onChange={(e) => f.onChange(e.target.value)}
              placeholder={f.placeholder}
              className="input-field text-sm py-2 w-full"
            />
          </label>
        ))}
      </div>
      <div>
        <span className="text-xs font-medium text-slate-600 mb-1 block">{t('modelConfig.apiKey')}</span>
        <div className="flex items-center gap-2">
          <input
            type="password"
            value={apiKeyValue}
            onChange={(e) => onApiKeyChange(e.target.value)}
            placeholder={
              clearKey
                ? t('modelConfig.apiKeyWillClear')
                : apiKeySet
                  ? t('modelConfig.apiKeySavedPlaceholder', { masked: apiKeyMasked })
                  : t('modelConfig.apiKeyNotSetPlaceholder')
            }
            disabled={clearKey}
            className="input-field text-sm py-2 w-full disabled:bg-slate-100 disabled:text-slate-400"
          />
          {apiKeySet && (
            <button
              type="button"
              onClick={() => onClearKeyChange(!clearKey)}
              className={`shrink-0 inline-flex items-center gap-1 px-3 py-2 rounded-lg text-xs font-medium cursor-pointer border ${
                clearKey
                  ? 'bg-red-50 border-red-200 text-red-700'
                  : 'bg-white border-slate-200 text-slate-500 hover:bg-slate-50'
              }`}
            >
              <RotateCcw size={12} />
              {clearKey ? t('modelConfig.willClear') : t('modelConfig.clearKey')}
            </button>
          )}
        </div>
        <p className="text-[11px] text-slate-400 mt-1">{t('modelConfig.apiKeyHelp')}</p>
      </div>
      <div className="pt-1 border-t border-slate-100">
        <button
          type="button"
          onClick={onTest}
          disabled={testStatus.state === 'testing' || clearKey}
          className="btn-secondary text-xs px-3 py-1.5 mt-3"
        >
          {testStatus.state === 'testing' ? (
            <>
              <Loader2 size={13} className="animate-spin" /> {t('modelConfig.testing')}
            </>
          ) : (
            <>
              <Plug size={13} /> {t('modelConfig.testConnection')}
            </>
          )}
        </button>
        <TestResultBanner testStatus={testStatus} />
      </div>
    </section>
  )
}

const IDLE_TEST_STATUS = { state: 'idle', message: '' }

export default function ModelConfigPage() {
  const { t } = useTranslation()

  const [status, setStatus] = useState('loading') // loading | done | error
  const [error, setError] = useState('')
  const [config, setConfig] = useState(null)

  const [baseUrl, setBaseUrl] = useState('')
  const [model, setModel] = useState('')
  const [apiKey, setApiKey] = useState('')
  const [clearApiKey, setClearApiKey] = useState(false)
  const [testStatus1, setTestStatus1] = useState(IDLE_TEST_STATUS)

  const [baseUrlDeep, setBaseUrlDeep] = useState('')
  const [modelDeep, setModelDeep] = useState('')
  const [apiKeyDeep, setApiKeyDeep] = useState('')
  const [clearApiKeyDeep, setClearApiKeyDeep] = useState(false)
  const [testStatus2, setTestStatus2] = useState(IDLE_TEST_STATUS)

  const [saveStatus, setSaveStatus] = useState({ state: 'idle', message: '' }) // idle | saving | done | error

  const load = () => {
    setStatus('loading')
    getModelConfig()
      .then((data) => {
        setConfig(data)
        setBaseUrl(data.base_url)
        setModel(data.model)
        setBaseUrlDeep(data.base_url_deep)
        setModelDeep(data.model_deep)
        setApiKey('')
        setClearApiKey(false)
        setApiKeyDeep('')
        setClearApiKeyDeep(false)
        setStatus('done')
      })
      .catch((err) => {
        setError(err.message || t('modelConfig.failedToLoad'))
        setStatus('error')
      })
  }

  useEffect(() => {
    load()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  const runTest = async (phase, { baseUrlValue, modelValue, apiKeyValue, setTestStatus }) => {
    if (!baseUrlValue.trim() || !modelValue.trim()) {
      setTestStatus({ state: 'error', message: t('modelConfig.testMissingFields') })
      return
    }
    setTestStatus({ state: 'testing', message: '' })
    try {
      const result = await testModelConfig({ phase, baseUrl: baseUrlValue, model: modelValue, apiKey: apiKeyValue })
      setTestStatus({ state: result.success ? 'success' : 'error', message: result.message })
    } catch (err) {
      setTestStatus({ state: 'error', message: err.message || t('modelConfig.testFailed') })
    }
  }

  const handleTestPhase1 = () =>
    runTest('phase1', { baseUrlValue: baseUrl, modelValue: model, apiKeyValue: apiKey, setTestStatus: setTestStatus1 })

  const handleTestPhase2 = () =>
    runTest('phase2', {
      baseUrlValue: baseUrlDeep,
      modelValue: modelDeep,
      apiKeyValue: apiKeyDeep,
      setTestStatus: setTestStatus2,
    })

  const handleSave = async () => {
    setSaveStatus({ state: 'saving', message: '' })
    try {
      const data = await updateModelConfig({
        baseUrl,
        model,
        baseUrlDeep,
        modelDeep,
        apiKey: apiKey || undefined,
        clearApiKey,
        apiKeyDeep: apiKeyDeep || undefined,
        clearApiKeyDeep,
      })
      setConfig(data)
      setBaseUrl(data.base_url)
      setModel(data.model)
      setBaseUrlDeep(data.base_url_deep)
      setModelDeep(data.model_deep)
      setApiKey('')
      setClearApiKey(false)
      setApiKeyDeep('')
      setClearApiKeyDeep(false)
      setTestStatus1(IDLE_TEST_STATUS)
      setTestStatus2(IDLE_TEST_STATUS)
      setSaveStatus({ state: 'done', message: t('modelConfig.saved') })
    } catch (err) {
      setSaveStatus({ state: 'error', message: err.message || t('modelConfig.saveFailed') })
    }
  }

  if (status === 'loading') {
    return (
      <div className="card p-10 flex flex-col items-center gap-3">
        <Loader2 size={28} className="animate-spin text-primary-600" />
        <p className="text-sm text-slate-500">{t('modelConfig.loading')}</p>
      </div>
    )
  }

  if (status === 'error') {
    return <div className="p-4 rounded-lg bg-red-50 border border-red-200 text-red-700 text-sm">{error}</div>
  }

  return (
    <>
      <section className="card p-6 flex items-start justify-between gap-4 flex-wrap">
        <div className="flex items-start gap-3">
          <div className="w-10 h-10 rounded-lg bg-primary-50 flex items-center justify-center shrink-0">
            <Settings size={18} className="text-primary-600" />
          </div>
          <div>
            <h1 className="font-semibold text-slate-800">{t('modelConfig.title')}</h1>
            <p className="text-sm text-slate-500 mt-0.5">{t('modelConfig.subtitle')}</p>
            {config?.is_customized ? (
              <p className="text-xs text-slate-400 mt-1.5">
                {config.updated_by_name
                  ? t('modelConfig.lastUpdatedBy', { name: config.updated_by_name, date: config.updated_at?.slice(0, 10) })
                  : t('modelConfig.lastUpdated', { date: config.updated_at?.slice(0, 10) })}
              </p>
            ) : (
              <p className="text-xs text-slate-400 mt-1.5">{t('modelConfig.usingEnvDefaults')}</p>
            )}
          </div>
        </div>
      </section>

      {!config?.db_configured && (
        <div className="p-4 rounded-lg bg-amber-50 border border-amber-200 text-amber-700 text-sm">
          {t('modelConfig.noDbWarning')}
        </div>
      )}

      <ModelSection
        title={t('modelConfig.phase1Title')}
        description={t('modelConfig.phase1Description')}
        fields={[
          { key: 'baseUrl', label: t('modelConfig.baseUrl'), value: baseUrl, onChange: setBaseUrl, placeholder: 'https://api.openai.com/v1' },
          { key: 'model', label: t('modelConfig.modelName'), value: model, onChange: setModel, placeholder: 'gpt-4o-mini' },
        ]}
        apiKeySet={config?.api_key_set}
        apiKeyMasked={config?.api_key_masked}
        apiKeyValue={apiKey}
        onApiKeyChange={setApiKey}
        clearKey={clearApiKey}
        onClearKeyChange={setClearApiKey}
        onTest={handleTestPhase1}
        testStatus={testStatus1}
      />

      <ModelSection
        title={t('modelConfig.phase2Title')}
        description={t('modelConfig.phase2Description')}
        fields={[
          { key: 'baseUrlDeep', label: t('modelConfig.baseUrl'), value: baseUrlDeep, onChange: setBaseUrlDeep, placeholder: 'https://api.openai.com/v1' },
          { key: 'modelDeep', label: t('modelConfig.modelName'), value: modelDeep, onChange: setModelDeep, placeholder: 'gpt-4o' },
        ]}
        apiKeySet={config?.api_key_deep_set}
        apiKeyMasked={config?.api_key_deep_masked}
        apiKeyValue={apiKeyDeep}
        onApiKeyChange={setApiKeyDeep}
        clearKey={clearApiKeyDeep}
        onClearKeyChange={setClearApiKeyDeep}
        onTest={handleTestPhase2}
        testStatus={testStatus2}
      />

      <section className="card p-6 flex items-center gap-4 flex-wrap">
        <button
          type="button"
          onClick={handleSave}
          disabled={saveStatus.state === 'saving' || !config?.db_configured}
          className="btn-primary"
        >
          {saveStatus.state === 'saving' ? (
            <>
              <Loader2 size={16} className="animate-spin" /> {t('modelConfig.saving')}
            </>
          ) : (
            <>
              <Save size={16} /> {t('modelConfig.save')}
            </>
          )}
        </button>
        {saveStatus.state === 'done' && <span className="text-sm text-emerald-600">{saveStatus.message}</span>}
        {saveStatus.state === 'error' && <span className="text-sm text-red-600">{saveStatus.message}</span>}
      </section>
    </>
  )
}
