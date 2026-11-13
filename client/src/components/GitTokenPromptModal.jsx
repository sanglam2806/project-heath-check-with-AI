import { useState } from 'react'
import { X, GitBranch, Loader2 } from 'lucide-react'
import { useTranslation } from 'react-i18next'

/**
 * Prompts for a Git credential (and, for a Jira-sourced project, a Jira
 * credential too) before re-evaluating a single ticket from a page that
 * has no live connection state (Project Detail) -- repo_url/branch/
 * jiraSiteUrl/jiraProjectKey are already known (project_git_connections /
 * project_ticket_connections, non-secret), but the tokens themselves are
 * deliberately never persisted (see the app-wide never-persist-Git/Jira-
 * credentials rule), so they must be re-entered here every time, same as
 * Connect Git/Jira's own ConnectPanel.
 *
 * The Jira fields matter for a real reason: re-checking a ticket without
 * them just re-evaluates against the LAST KNOWN status/summary/description
 * (whatever was saved from the last full scan) -- if the reason a ticket
 * mismatched was a wrong status that has since been fixed ON Jira, that
 * fix would never be seen unless this re-fetches the ticket fresh first.
 */
export default function GitTokenPromptModal({
  repoUrl,
  branch,
  jiraSiteUrl,
  jiraProjectKey,
  loading,
  error,
  onConfirm,
  onCancel,
}) {
  const { t } = useTranslation()
  const [gitToken, setGitToken] = useState('')
  const [gitUsername, setGitUsername] = useState('')
  const [jiraEmail, setJiraEmail] = useState('')
  const [jiraApiToken, setJiraApiToken] = useState('')

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/50 backdrop-blur-sm"
      onClick={onCancel}
    >
      <div
        className="bg-white rounded-2xl shadow-xl w-full max-w-md overflow-hidden"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="px-6 py-4 border-b border-slate-200 flex items-start justify-between gap-4">
          <div className="flex items-center gap-2">
            <GitBranch size={18} className="text-primary-600" />
            <h2 className="text-lg font-bold">{t('gitTokenPrompt.title')}</h2>
          </div>
          <button
            onClick={onCancel}
            className="p-1.5 rounded-lg hover:bg-slate-100 text-slate-500 cursor-pointer"
            aria-label={t('ticketDetail.close')}
          >
            <X size={20} />
          </button>
        </div>

        <form
          className="px-6 py-5 space-y-4"
          onSubmit={(e) => {
            e.preventDefault()
            onConfirm({ gitToken, gitUsername, jiraEmail, jiraApiToken })
          }}
        >
          <p className="text-sm text-slate-600">{t('gitTokenPrompt.description')}</p>

          <div className="text-xs text-slate-500 bg-slate-50 rounded-lg p-3 space-y-0.5">
            <div><span className="font-medium text-slate-600">{t('checkHealthConnect.repositoryUrl')}:</span> {repoUrl}</div>
            <div><span className="font-medium text-slate-600">{t('checkHealthConnect.branchLabel')}:</span> {branch || 'main'}</div>
            {jiraSiteUrl && (
              <div><span className="font-medium text-slate-600">{t('checkHealthConnect.jiraSiteUrl')}:</span> {jiraSiteUrl}</div>
            )}
            {jiraProjectKey && (
              <div><span className="font-medium text-slate-600">{t('checkHealthConnect.projectKey')}:</span> {jiraProjectKey}</div>
            )}
          </div>

          <div>
            <label className="block text-xs font-medium text-slate-600 mb-1">
              {t('checkHealthConnect.gitUsernameLabel')}
            </label>
            <input
              type="text"
              value={gitUsername}
              onChange={(e) => setGitUsername(e.target.value)}
              placeholder="your.username"
              className="input-field text-sm py-2"
              autoFocus
            />
          </div>

          <div>
            <label className="block text-xs font-medium text-slate-600 mb-1">
              {t('checkHealthConnect.gitTokenLabel')}
            </label>
            <input
              type="password"
              value={gitToken}
              onChange={(e) => setGitToken(e.target.value)}
              placeholder={t('gitTokenPrompt.tokenPlaceholder')}
              className="input-field text-sm py-2"
            />
            <p className="text-xs text-slate-400 mt-1">{t('gitTokenPrompt.tokenHelp')}</p>
          </div>

          {jiraSiteUrl && (
            <>
              <div className="border-t border-slate-100 pt-4 -mt-1">
                <p className="text-xs text-slate-500">{t('gitTokenPrompt.jiraDescription')}</p>
              </div>
              <div>
                <label className="block text-xs font-medium text-slate-600 mb-1">
                  {t('checkHealthConnect.jiraEmail')}
                </label>
                <input
                  type="text"
                  value={jiraEmail}
                  onChange={(e) => setJiraEmail(e.target.value)}
                  placeholder="you@company.com or username"
                  className="input-field text-sm py-2"
                />
              </div>
              <div>
                <label className="block text-xs font-medium text-slate-600 mb-1">
                  {t('checkHealthConnect.apiToken')}
                </label>
                <input
                  type="password"
                  value={jiraApiToken}
                  onChange={(e) => setJiraApiToken(e.target.value)}
                  placeholder="API token, password, or PAT"
                  className="input-field text-sm py-2"
                />
                <p className="text-xs text-slate-400 mt-1">{t('gitTokenPrompt.jiraTokenHelp')}</p>
              </div>
            </>
          )}

          {error && (
            <div className="p-2.5 rounded-lg bg-red-50 border border-red-200 text-red-700 text-xs">{error}</div>
          )}

          <div className="flex items-center justify-end gap-2 pt-1">
            <button type="button" onClick={onCancel} className="btn-secondary text-sm">
              {t('common.cancel')}
            </button>
            <button type="submit" disabled={loading} className="btn-primary text-sm">
              {loading && <Loader2 size={14} className="animate-spin" />}
              {t('gitTokenPrompt.confirm')}
            </button>
          </div>
        </form>
      </div>
    </div>
  )
}
