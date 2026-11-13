import { useEffect, useState } from 'react'
import { UserPlus, Users as UsersIcon, Loader2, Copy, Send } from 'lucide-react'
import { useTranslation } from 'react-i18next'
import { listMembers, inviteMember, updateMemberRole, listGroups, createGroup, inviteGroup } from '../api'
import { useColumnFilters } from '../hooks/useColumnFilters'
import FilterableHeader from '../components/FilterableHeader'

const ROLE_OPTIONS = ['Owner', 'Admin', 'Editor', 'Viewer']
const DEFAULT_ROLE = ROLE_OPTIONS[ROLE_OPTIONS.length - 1]

function StatusBadge({ status }) {
  const { t } = useTranslation()
  return status === 'active' ? (
    <span className="badge-green">{t('members.active')}</span>
  ) : (
    <span className="badge-yellow">{t('members.pending')}</span>
  )
}

function CopyLinkButton({ link }) {
  const { t } = useTranslation()
  const [copied, setCopied] = useState(false)
  if (!link) return null
  return (
    <button
      type="button"
      onClick={() => {
        navigator.clipboard?.writeText(link)
        setCopied(true)
        setTimeout(() => setCopied(false), 1500)
      }}
      className="inline-flex items-center gap-1 text-primary-600 hover:underline cursor-pointer"
    >
      <Copy size={11} /> {copied ? t('members.copied') : t('members.copyLink')}
    </button>
  )
}

function InviteResultBanner({ result, onDismiss }) {
  if (!result) return null
  return (
    <div
      className={`p-3 rounded-lg border text-xs flex items-center justify-between gap-3 ${
        result.email_sent
          ? 'bg-emerald-50 border-emerald-200 text-emerald-700'
          : 'bg-amber-50 border-amber-200 text-amber-700'
      }`}
    >
      <span className="flex-1">{result.message}</span>
      <div className="flex items-center gap-3 shrink-0">
        <CopyLinkButton link={result.invite_link} />
        <button type="button" onClick={onDismiss} className="text-slate-400 hover:text-slate-600 cursor-pointer">
          ✕
        </button>
      </div>
    </div>
  )
}

export default function MemberSettingsPage() {
  const { t } = useTranslation()

  // Click-to-filter columns for the member table. Groups returns an array
  // since one member can belong to several — useColumnFilters.matches()
  // treats an array getValue as "matches if any selected value is in it".
  const FILTER_COLUMNS = [
    { key: 'name', label: t('members.name'), getValue: (m) => m.name },
    { key: 'groups', label: t('members.groups'), getValue: (m) => (m.groups.length ? m.groups : [t('common.unassigned')]) },
  ]
  const FILTER_KEYS = FILTER_COLUMNS.map((c) => c.key)

  const [members, setMembers] = useState([])
  const [membersStatus, setMembersStatus] = useState('loading') // loading | done | error
  const [groups, setGroups] = useState([])
  const [groupsStatus, setGroupsStatus] = useState('loading')

  const [showInvite, setShowInvite] = useState(false)
  const [inviteName, setInviteName] = useState('')
  const [inviteEmail, setInviteEmail] = useState('')
  const [inviteRole, setInviteRole] = useState(DEFAULT_ROLE)
  const [inviting, setInviting] = useState(false)
  const [inviteError, setInviteError] = useState('')
  const [inviteResult, setInviteResult] = useState(null)

  const [showGroupForm, setShowGroupForm] = useState(false)
  const [groupName, setGroupName] = useState('')
  const [groupEmails, setGroupEmails] = useState('')
  const [groupRole, setGroupRole] = useState(DEFAULT_ROLE)
  const [creatingGroup, setCreatingGroup] = useState(false)
  const [groupError, setGroupError] = useState('')
  const [groupCreateResult, setGroupCreateResult] = useState(null) // {groupName, results}

  // Per-group "Invite group" (re-invite pending members) status/result.
  const [groupInviteState, setGroupInviteState] = useState({}) // id -> 'sending' | {results} | {error}

  const { filters, openFilter, setOpenFilter, toggleValue, clearColumn, clearAll, hasActiveFilters, matches } =
    useColumnFilters(FILTER_KEYS)
  const columnByKey = Object.fromEntries(FILTER_COLUMNS.map((c) => [c.key, c]))
  const filteredMembers = members.filter((m) => matches(m, (row, key) => columnByKey[key].getValue(row)))

  const loadMembers = () => {
    setMembersStatus('loading')
    listMembers()
      .then((data) => {
        setMembers(data)
        setMembersStatus('done')
      })
      .catch(() => setMembersStatus('error'))
  }

  const loadGroups = () => {
    setGroupsStatus('loading')
    listGroups()
      .then((data) => {
        setGroups(data)
        setGroupsStatus('done')
      })
      .catch(() => setGroupsStatus('error'))
  }

  useEffect(() => {
    loadMembers()
    loadGroups()
  }, [])

  const handleRoleChange = async (id, role) => {
    const previous = members
    setMembers((prev) => prev.map((m) => (m.id === id ? { ...m, role } : m)))
    try {
      await updateMemberRole(id, role)
    } catch {
      setMembers(previous) // revert on failure — keep in sync with the DB
    }
  }

  const submitInvite = async (e) => {
    e.preventDefault()
    if (!inviteName.trim() || !inviteEmail.trim()) return
    setInviting(true)
    setInviteError('')
    try {
      const data = await inviteMember(inviteName.trim(), inviteEmail.trim(), inviteRole)
      setInviteResult(data)
      setInviteName('')
      setInviteEmail('')
      setInviteRole(DEFAULT_ROLE)
      setShowInvite(false)
      loadMembers()
    } catch (err) {
      setInviteError(err.message || t('members.inviteFailed'))
    } finally {
      setInviting(false)
    }
  }

  const submitGroup = async (e) => {
    e.preventDefault()
    const emails = [...new Set(groupEmails.split(/[,\n]/).map((s) => s.trim()).filter(Boolean))]
    if (!groupName.trim() || emails.length === 0) return
    setCreatingGroup(true)
    setGroupError('')
    try {
      const data = await createGroup(groupName.trim(), emails, groupRole)
      setGroupCreateResult({ groupName: data.group.name, results: data.results })
      setGroupName('')
      setGroupEmails('')
      setGroupRole(DEFAULT_ROLE)
      setShowGroupForm(false)
      loadMembers()
      loadGroups()
    } catch (err) {
      setGroupError(err.message || t('members.createGroupFailed'))
    } finally {
      setCreatingGroup(false)
    }
  }

  const handleInviteGroup = async (group) => {
    setGroupInviteState((prev) => ({ ...prev, [group.id]: 'sending' }))
    try {
      const results = await inviteGroup(group.id)
      setGroupInviteState((prev) => ({ ...prev, [group.id]: { results } }))
      loadGroups()
    } catch (err) {
      setGroupInviteState((prev) => ({ ...prev, [group.id]: { error: err.message || t('members.inviteFailed') } }))
    }
  }

  return (
    <>
      <div className="flex justify-end gap-3">
        <button
          onClick={() => {
            setShowGroupForm((v) => !v)
            setShowInvite(false)
          }}
          className="btn-secondary"
        >
          <UsersIcon size={16} />
          {t('members.inviteGroup')}
        </button>
        <button
          onClick={() => {
            setShowInvite((v) => !v)
            setShowGroupForm(false)
          }}
          className="btn-primary"
        >
          <UserPlus size={16} />
          {t('members.inviteMember')}
        </button>
      </div>

      <InviteResultBanner result={inviteResult} onDismiss={() => setInviteResult(null)} />

      {showInvite && (
        <form onSubmit={submitInvite} className="card p-5 grid grid-cols-1 sm:grid-cols-4 gap-3 items-end">
          <div className="sm:col-span-2">
            <label className="text-xs font-medium text-slate-600 mb-1 block">{t('members.name')}</label>
            <input
              className="input-field"
              value={inviteName}
              onChange={(e) => setInviteName(e.target.value)}
              placeholder={t('members.namePlaceholder')}
            />
          </div>
          <div>
            <label className="text-xs font-medium text-slate-600 mb-1 block">{t('members.email')}</label>
            <input
              type="email"
              className="input-field"
              value={inviteEmail}
              onChange={(e) => setInviteEmail(e.target.value)}
              placeholder="name@company.com"
            />
          </div>
          <div>
            <label className="text-xs font-medium text-slate-600 mb-1 block">{t('members.role')}</label>
            <select className="input-field" value={inviteRole} onChange={(e) => setInviteRole(e.target.value)}>
              {ROLE_OPTIONS.map((r) => (
                <option key={r} value={r}>
                  {r}
                </option>
              ))}
            </select>
          </div>
          {inviteError && (
            <div className="sm:col-span-4 p-2.5 rounded-lg bg-red-50 border border-red-200 text-red-700 text-xs">
              {inviteError}
            </div>
          )}
          <div className="sm:col-span-4 flex justify-end gap-3">
            <button type="button" onClick={() => setShowInvite(false)} className="btn-secondary">
              {t('common.cancel')}
            </button>
            <button type="submit" disabled={inviting} className="btn-primary">
              {inviting && <Loader2 size={14} className="animate-spin" />}
              {t('members.sendInvite')}
            </button>
          </div>
        </form>
      )}

      {showGroupForm && (
        <form onSubmit={submitGroup} className="card p-5 space-y-3">
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
            <div>
              <label className="text-xs font-medium text-slate-600 mb-1 block">{t('members.groupName')}</label>
              <input
                className="input-field"
                value={groupName}
                onChange={(e) => setGroupName(e.target.value)}
                placeholder={t('members.groupNamePlaceholder')}
              />
            </div>
            <div>
              <label className="text-xs font-medium text-slate-600 mb-1 block">{t('members.roleForNewMembers')}</label>
              <select className="input-field" value={groupRole} onChange={(e) => setGroupRole(e.target.value)}>
                {ROLE_OPTIONS.map((r) => (
                  <option key={r} value={r}>
                    {r}
                  </option>
                ))}
              </select>
            </div>
          </div>
          <div>
            <label className="text-xs font-medium text-slate-600 mb-1 block">
              {t('members.memberEmails')}
            </label>
            <textarea
              className="input-field font-mono text-xs"
              rows={3}
              value={groupEmails}
              onChange={(e) => setGroupEmails(e.target.value)}
              placeholder={'a@company.com\nb@company.com'}
            />
          </div>
          {groupError && (
            <div className="p-2.5 rounded-lg bg-red-50 border border-red-200 text-red-700 text-xs">{groupError}</div>
          )}
          <div className="flex justify-end gap-3">
            <button type="button" onClick={() => setShowGroupForm(false)} className="btn-secondary">
              {t('common.cancel')}
            </button>
            <button type="submit" disabled={creatingGroup} className="btn-primary">
              {creatingGroup && <Loader2 size={14} className="animate-spin" />}
              {t('members.createAndInvite')}
            </button>
          </div>
        </form>
      )}

      {groupCreateResult && (
        <div className="card p-4 text-xs space-y-1.5">
          <p className="font-medium text-slate-700 mb-1">{t('members.inviteResultsFor', { name: groupCreateResult.groupName })}</p>
          {groupCreateResult.results.map((r) => (
            <div key={r.email} className="flex items-center justify-between gap-2 text-slate-600">
              <span>{r.email}</span>
              <div className="flex items-center gap-2">
                <span className="text-slate-400">{r.status}</span>
                <CopyLinkButton link={r.invite_link} />
              </div>
            </div>
          ))}
        </div>
      )}

      <div className="card overflow-hidden">
        <div className="px-6 py-4 border-b border-slate-200">
          <h2 className="font-semibold">{t('members.groups')}</h2>
        </div>
        {groupsStatus === 'loading' ? (
          <p className="px-6 py-8 text-sm text-slate-400 text-center flex items-center justify-center gap-2">
            <Loader2 size={16} className="animate-spin" /> {t('members.loading')}
          </p>
        ) : groups.length === 0 ? (
          <p className="px-6 py-8 text-sm text-slate-400 text-center">{t('members.noGroupsYet')}</p>
        ) : (
          <div className="divide-y divide-slate-100">
            {groups.map((g) => {
              const inviteState = groupInviteState[g.id]
              return (
                <div key={g.id} className="px-6 py-4">
                  <div className="flex items-center justify-between gap-3 mb-2">
                    <p className="font-medium text-slate-800">
                      {g.name}{' '}
                      <span className="text-slate-400 text-xs font-normal">{t('members.membersCount', { count: g.members.length })}</span>
                    </p>
                    <button
                      type="button"
                      onClick={() => handleInviteGroup(g)}
                      disabled={inviteState === 'sending'}
                      className="inline-flex items-center gap-1.5 px-3 py-1.5 text-xs font-medium rounded-lg border border-primary-200 text-primary-700 bg-primary-50 hover:bg-primary-100 cursor-pointer disabled:opacity-50"
                    >
                      {inviteState === 'sending' ? <Loader2 size={12} className="animate-spin" /> : <Send size={12} />}
                      {t('members.inviteGroup')}
                    </button>
                  </div>
                  <div className="flex flex-wrap gap-1.5">
                    {g.members.map((m) => (
                      <span key={m.id} className="badge-gray text-xs">
                        {m.email} · {m.status}
                      </span>
                    ))}
                  </div>
                  {inviteState?.error && <p className="mt-2 text-xs text-red-600">{inviteState.error}</p>}
                  {inviteState?.results && (
                    <div className="mt-2 space-y-1">
                      {inviteState.results.map((r) => (
                        <div key={r.email} className="flex items-center justify-between gap-2 text-xs text-slate-500">
                          <span>{r.email}</span>
                          <div className="flex items-center gap-2">
                            <span>{r.status}</span>
                            <CopyLinkButton link={r.invite_link} />
                          </div>
                        </div>
                      ))}
                    </div>
                  )}
                </div>
              )
            })}
          </div>
        )}
      </div>

      <div className="card overflow-hidden">
        {hasActiveFilters && (
          <div className="px-6 py-2.5 border-b border-slate-100 flex justify-end">
            <button onClick={clearAll} className="text-xs text-primary-600 hover:underline cursor-pointer">
              {t('common.clearAllFilters')}
            </button>
          </div>
        )}
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="bg-slate-50 text-left text-xs uppercase tracking-wide text-slate-500">
                <FilterableHeader
                  columnKey="name"
                  label={t('members.name')}
                  options={[...new Set(members.map((m) => m.name))].sort()}
                  selected={filters.name}
                  isOpen={openFilter === 'name'}
                  onToggle={(key) => setOpenFilter((prev) => (prev === key ? null : key))}
                  onChange={toggleValue}
                  onClear={clearColumn}
                />
                <th className="px-6 py-3 font-semibold">{t('members.email')}</th>
                <th className="px-6 py-3 font-semibold">{t('members.status')}</th>
                <FilterableHeader
                  columnKey="groups"
                  label={t('members.groups')}
                  options={[...new Set(members.flatMap((m) => (m.groups.length ? m.groups : [t('common.unassigned')])))].sort()}
                  selected={filters.groups}
                  isOpen={openFilter === 'groups'}
                  onToggle={(key) => setOpenFilter((prev) => (prev === key ? null : key))}
                  onChange={toggleValue}
                  onClear={clearColumn}
                />
                <th className="px-6 py-3 font-semibold">{t('members.role')}</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-100">
              {membersStatus === 'loading' && (
                <tr>
                  <td colSpan={5} className="px-6 py-8 text-center text-slate-400">
                    <Loader2 size={16} className="animate-spin inline mr-2" /> {t('members.loading')}
                  </td>
                </tr>
              )}
              {membersStatus === 'error' && (
                <tr>
                  <td colSpan={5} className="px-6 py-8 text-center text-red-600">
                    {t('members.failedToLoadMembers')}
                  </td>
                </tr>
              )}
              {membersStatus === 'done' && members.length === 0 && (
                <tr>
                  <td colSpan={5} className="px-6 py-8 text-center text-slate-400">
                    {t('members.noMembersYet')}
                  </td>
                </tr>
              )}
              {membersStatus === 'done' && members.length > 0 && filteredMembers.length === 0 && (
                <tr>
                  <td colSpan={5} className="px-6 py-8 text-center text-slate-400">
                    {t('members.noMembersMatchFilters')}
                  </td>
                </tr>
              )}
              {filteredMembers.map((m) => (
                <tr key={m.id} className="hover:bg-slate-50 transition-colors">
                  <td className="px-6 py-3 font-medium text-slate-800">{m.name}</td>
                  <td className="px-6 py-3 text-slate-600">{m.email}</td>
                  <td className="px-6 py-3">
                    <StatusBadge status={m.status} />
                  </td>
                  <td className="px-6 py-3">
                    <div className="flex flex-wrap gap-1">
                      {m.groups.length === 0 ? (
                        <span className="text-slate-300">—</span>
                      ) : (
                        m.groups.map((gName) => (
                          <span key={gName} className="badge-blue text-xs">
                            {gName}
                          </span>
                        ))
                      )}
                    </div>
                  </td>
                  <td className="px-6 py-3">
                    <select
                      className="input-field text-sm py-1.5 w-40"
                      value={m.role}
                      onChange={(e) => handleRoleChange(m.id, e.target.value)}
                    >
                      {ROLE_OPTIONS.map((r) => (
                        <option key={r} value={r}>
                          {r}
                        </option>
                      ))}
                    </select>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
    </>
  )
}
