import { X, FileCode2, Lightbulb, AlertOctagon, MessageSquare, FileSearch } from 'lucide-react'
import { useTranslation } from 'react-i18next'
import { isDoneStatus, isInProgressStatus } from '../utils/ticketStatus'

function AssessmentBadge({ assessment }) {
  const map = {
    Match: 'badge-green',
    Mismatch: 'badge-red',
    Incomplete: 'badge-yellow',
  }
  return <span className={map[assessment] || 'badge-gray'}>{assessment}</span>
}

function DocMatchBadge({ value }) {
  const map = {
    Match: 'badge-green',
    'Doc Outdated': 'badge-yellow',
    'Doc Drift': 'badge-yellow',
    'Missing UI': 'badge-yellow',
    Mismatch: 'badge-red',
    'No Doc Found': 'badge-gray',
    'No Screen Found': 'badge-gray',
    'N/A': 'badge-gray',
  }
  return <span className={map[value] || 'badge-gray'}>{value || 'N/A'}</span>
}

function StatusBadge({ status }) {
  const { t } = useTranslation()
  const lower = String(status || '').toLowerCase()
  let cls = 'badge-gray'
  if (isDoneStatus(status)) cls = 'badge-green'
  else if (isInProgressStatus(status)) cls = 'badge-blue'
  else if (['todo', 'to do', 'open'].includes(lower)) cls = 'badge-yellow'
  return <span className={cls}>{status || t('ticketDetail.unknown')}</span>
}

export default function TicketDetailModal({ ticket, onClose }) {
  const { t } = useTranslation()
  if (!ticket) return null

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/50 backdrop-blur-sm"
      onClick={onClose}
    >
      <div
        className="bg-white rounded-2xl shadow-xl w-full max-w-2xl max-h-[90vh] overflow-hidden flex flex-col"
        onClick={(e) => e.stopPropagation()}
      >
        {/* Header */}
        <div className="px-6 py-4 border-b border-slate-200 flex items-start justify-between gap-4">
          <div>
            <div className="flex items-center gap-2 mb-1">
              <h2 className="text-lg font-bold">{ticket.ticket_id}</h2>
              <AssessmentBadge assessment={ticket.assessment} />
              <StatusBadge status={ticket.status} />
            </div>
            <p className="text-sm text-slate-600">{ticket.summary}</p>
            {ticket.assignee && (
              <p className="text-xs text-slate-400 mt-1">{t('ticketDetail.assignTo', { assignee: ticket.assignee })}</p>
            )}
          </div>
          <button
            onClick={onClose}
            className="p-1.5 rounded-lg hover:bg-slate-100 text-slate-500 cursor-pointer"
            aria-label={t('ticketDetail.close')}
          >
            <X size={20} />
          </button>
        </div>

        {/* Body */}
        <div className="px-6 py-5 overflow-y-auto space-y-5">
          {/* Completion */}
          <div>
            <div className="flex items-center justify-between mb-1.5">
              <span className="text-sm font-medium text-slate-700">{t('ticketDetail.completion')}</span>
              <span className="text-sm font-bold text-blue-600">
                {ticket.completion_percent?.toFixed(1) ?? 0}%
              </span>
            </div>
            <div className="h-2.5 bg-slate-100 rounded-full overflow-hidden">
              <div
                className="h-full bg-blue-600 rounded-full transition-all"
                style={{ width: `${ticket.completion_percent ?? 0}%` }}
              />
            </div>
            {typeof ticket.confidence === 'number' && (
              <p className="text-xs text-slate-400 mt-1.5">
                {t('ticketDetail.confidence', { percent: (ticket.confidence * 100).toFixed(0) })}
              </p>
            )}
          </div>

          {/* Evidence files */}
          <div>
            <h3 className="flex items-center gap-2 text-sm font-semibold text-slate-700 mb-2">
              <FileCode2 size={16} className="text-blue-600" /> {t('ticketDetail.evidenceFiles')}
            </h3>
            {ticket.evidence_files && ticket.evidence_files.length > 0 ? (
              <ul className="space-y-1">
                {ticket.evidence_files.map((f) => (
                  <li
                    key={f}
                    className="text-sm font-mono text-slate-600 bg-slate-50 rounded px-2.5 py-1.5 border border-slate-100"
                  >
                    {f}
                  </li>
                ))}
              </ul>
            ) : (
              <p className="text-sm text-slate-400 italic">{t('ticketDetail.noMatchingFiles')}</p>
            )}
          </div>

          {/* Missing parts */}
          <div>
            <h3 className="flex items-center gap-2 text-sm font-semibold text-slate-700 mb-2">
              <AlertOctagon size={16} className="text-red-500" /> {t('ticketDetail.missingParts')}
            </h3>
            {ticket.missing_parts && ticket.missing_parts.length > 0 ? (
              <ul className="space-y-1">
                {ticket.missing_parts.map((m, i) => (
                  <li key={i} className="text-sm text-slate-600 flex gap-2">
                    <span className="text-red-500">•</span>
                    <span>{m}</span>
                  </li>
                ))}
              </ul>
            ) : (
              <p className="text-sm text-emerald-600">{t('ticketDetail.noMissingParts')}</p>
            )}
          </div>

          {/* Suggestions */}
          <div>
            <h3 className="flex items-center gap-2 text-sm font-semibold text-slate-700 mb-2">
              <Lightbulb size={16} className="text-amber-500" /> {t('ticketDetail.suggestions')}
            </h3>
            {ticket.suggestions && ticket.suggestions.length > 0 ? (
              <ul className="space-y-1">
                {ticket.suggestions.map((s, i) => (
                  <li key={i} className="text-sm text-slate-600 flex gap-2">
                    <span className="text-amber-500">→</span>
                    <span>{s}</span>
                  </li>
                ))}
              </ul>
            ) : (
              <p className="text-sm text-slate-400 italic">{t('ticketDetail.none')}</p>
            )}
          </div>

          {/* Doc cross-check (Doc vs Ticket / Doc vs Code / UI Screen vs Code) */}
          {ticket.doc_ticket_match || ticket.doc_code_match ? (
            <div>
              <h3 className="flex items-center gap-2 text-sm font-semibold text-slate-700 mb-2">
                <FileSearch size={16} className="text-indigo-500" /> {t('ticketDetail.docCrossCheck')}
                {ticket.escalated && (
                  <span className="text-xs font-normal text-indigo-500 bg-indigo-50 rounded-full px-2 py-0.5">
                    {t('ticketDetail.deepReviewed')}
                  </span>
                )}
              </h3>
              <div className="flex items-center gap-3 mb-2 text-sm flex-wrap">
                <span className="text-slate-500">{t('ticketDetail.docVsTicket')}:</span>
                <DocMatchBadge value={ticket.doc_ticket_match} />
                <span className="text-slate-500">{t('ticketDetail.docVsCode')}:</span>
                <DocMatchBadge value={ticket.doc_code_match} />
              </div>
              {ticket.ui_screen_match && (
                <div className="flex items-center gap-3 mb-2 text-sm flex-wrap">
                  <span className="text-slate-500">{t('ticketDetail.uiScreenMatch')}:</span>
                  <DocMatchBadge value={ticket.ui_screen_match} />
                </div>
              )}
              {ticket.doc_notes && (
                <p className="text-sm text-slate-600 bg-slate-50 rounded-lg p-3 border border-slate-100 mb-2">
                  {ticket.doc_notes}
                </p>
              )}
              {ticket.matched_doc_files && ticket.matched_doc_files.length > 0 && (
                <ul className="space-y-1 mb-2">
                  {ticket.matched_doc_files.map((f) => (
                    <li
                      key={f}
                      className="text-sm font-mono text-slate-600 bg-slate-50 rounded px-2.5 py-1.5 border border-slate-100"
                    >
                      {f}
                    </li>
                  ))}
                </ul>
              )}
              {ticket.matched_image_files && ticket.matched_image_files.length > 0 && (
                <ul className="space-y-1">
                  {ticket.matched_image_files.map((f) => (
                    <li
                      key={f}
                      className="text-sm font-mono text-slate-600 bg-slate-50 rounded px-2.5 py-1.5 border border-slate-100"
                    >
                      {f}
                    </li>
                  ))}
                </ul>
              )}
            </div>
          ) : null}

          {/* Notes */}
          {ticket.notes ? (
            <div>
              <h3 className="flex items-center gap-2 text-sm font-semibold text-slate-700 mb-2">
                <MessageSquare size={16} className="text-slate-500" /> {t('ticketDetail.notes')}
              </h3>
              <p className="text-sm text-slate-600 bg-slate-50 rounded-lg p-3 border border-slate-100">
                {ticket.notes}
              </p>
            </div>
          ) : null}
        </div>

        {/* Footer */}
        <div className="px-6 py-3 border-t border-slate-200 flex justify-end">
          <button
            onClick={onClose}
            className="px-4 py-2 text-sm font-medium text-slate-600 hover:bg-slate-100 rounded-lg cursor-pointer"
          >
            {t('ticketDetail.close')}
          </button>
        </div>
      </div>
    </div>
  )
}
