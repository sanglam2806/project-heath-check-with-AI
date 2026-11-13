import { useMemo, useState } from 'react'
import { X, Table2 } from 'lucide-react'
import { useTranslation } from 'react-i18next'

function colLabel(i) {
  return `Column ${String.fromCharCode(65 + i)}`
}

export default function ExcelMappingModal({ open, headerRow, previewRows, suggestedMapping, onConfirm, onCancel }) {
  const { t } = useTranslation()
  const [selectedHeaderRow, setSelectedHeaderRow] = useState(headerRow || 1)
  const [mapping, setMapping] = useState(() => ({ ...suggestedMapping }))

  const FIELDS = [
    { key: 'ticket_id', label: t('excelMapping.ticketId'), required: true },
    { key: 'summary', label: t('excelMapping.summary'), required: false },
    { key: 'status', label: t('excelMapping.status'), required: false },
    { key: 'description', label: t('excelMapping.description'), required: false },
    { key: 'due_date', label: t('excelMapping.dueDate'), required: false },
    { key: 'issue_type', label: t('excelMapping.issueType'), required: false },
    { key: 'assignee', label: t('excelMapping.assignTo'), required: false },
  ]

  const headerCells = previewRows[selectedHeaderRow - 1] || []
  const columnCount = Math.max(...previewRows.map((r) => r.length), 1)
  const headerLabels = useMemo(
    () => Array.from({ length: columnCount }, (_, i) => headerCells[i]?.trim() || colLabel(i)),
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [selectedHeaderRow, previewRows]
  )
  const dataRows = previewRows.slice(selectedHeaderRow, selectedHeaderRow + 6)

  if (!open) return null

  const setField = (field, value) => {
    setMapping((prev) => ({ ...prev, [field]: value === '' ? null : Number(value) }))
  }

  const hasUsableMapping = mapping.ticket_id != null || mapping.summary != null

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/50 backdrop-blur-sm"
      onClick={onCancel}
    >
      <div
        className="bg-white rounded-2xl shadow-xl w-full max-w-4xl max-h-[90vh] overflow-hidden flex flex-col"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="px-6 py-4 border-b border-slate-200 flex items-center justify-between">
          <div className="flex items-center gap-2">
            <Table2 size={18} className="text-primary-600" />
            <h2 className="text-lg font-bold">{t('excelMapping.title')}</h2>
          </div>
          <button
            onClick={onCancel}
            className="p-1.5 rounded-lg hover:bg-slate-100 text-slate-500 cursor-pointer"
            aria-label={t('common.close')}
          >
            <X size={20} />
          </button>
        </div>

        <div className="px-6 py-5 overflow-y-auto space-y-5">
          <p className="text-sm text-slate-500">
            {t('excelMapping.instructions1')}
            <br />
            {t('excelMapping.instructions2')}
          </p>

          <div>
            <p className="text-xs font-medium text-slate-600 mb-1.5">{t('excelMapping.headerRow')}</p>
            <div className="overflow-x-auto rounded-lg border border-slate-200">
              <table className="w-full text-xs">
                <tbody className="divide-y divide-slate-100">
                  {previewRows.map((row, ri) => {
                    const rowNum = ri + 1
                    const isHeader = rowNum === selectedHeaderRow
                    return (
                      <tr
                        key={ri}
                        onClick={() => setSelectedHeaderRow(rowNum)}
                        className={`cursor-pointer transition-colors ${
                          isHeader ? 'bg-primary-50' : 'hover:bg-slate-50'
                        }`}
                      >
                        <td className="px-2 py-1.5 text-slate-400 whitespace-nowrap w-16">
                          <label className="flex items-center gap-1.5 cursor-pointer">
                            <input
                              type="radio"
                              checked={isHeader}
                              onChange={() => setSelectedHeaderRow(rowNum)}
                            />
                            {t('excelMapping.rowLabel', { n: rowNum })}
                          </label>
                        </td>
                        {row.map((cell, ci) => (
                          <td
                            key={ci}
                            className={`px-3 py-1.5 whitespace-nowrap max-w-[180px] truncate ${
                              isHeader ? 'font-semibold text-primary-800' : 'text-slate-600'
                            }`}
                          >
                            {cell}
                          </td>
                        ))}
                      </tr>
                    )
                  })}
                </tbody>
              </table>
            </div>
          </div>

          <div>
            <p className="text-xs font-medium text-slate-600 mb-1.5">
              {t('excelMapping.dataPreview')}
            </p>
            <div className="overflow-x-auto rounded-lg border border-slate-200">
              <table className="w-full text-xs">
                <thead>
                  <tr className="bg-slate-50">
                    {headerLabels.map((h, i) => (
                      <th key={i} className="px-3 py-2 text-left font-semibold text-slate-600 whitespace-nowrap">
                        {h}
                      </th>
                    ))}
                  </tr>
                </thead>
                <tbody className="divide-y divide-slate-100">
                  {dataRows.length === 0 ? (
                    <tr>
                      <td colSpan={headerLabels.length} className="px-3 py-3 text-slate-400 text-center">
                        {t('excelMapping.noDataRows')}
                      </td>
                    </tr>
                  ) : (
                    dataRows.map((row, ri) => (
                      <tr key={ri}>
                        {headerLabels.map((_, ci) => (
                          <td key={ci} className="px-3 py-2 text-slate-600 whitespace-nowrap max-w-[200px] truncate">
                            {row[ci] ?? ''}
                          </td>
                        ))}
                      </tr>
                    ))
                  )}
                </tbody>
              </table>
            </div>
          </div>

          <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
            {FIELDS.map((field) => (
              <div key={field.key}>
                <label className="text-xs font-medium text-slate-600 mb-1 block">
                  {field.label}
                  {field.required ? <span className="text-red-500"> *</span> : null}
                </label>
                <select
                  className="input-field text-sm"
                  value={mapping[field.key] ?? ''}
                  onChange={(e) => setField(field.key, e.target.value)}
                >
                  <option value="">{t('excelMapping.none')}</option>
                  {headerLabels.map((h, i) => (
                    <option key={i} value={i}>
                      {h}
                    </option>
                  ))}
                </select>
              </div>
            ))}
          </div>
          {!hasUsableMapping && (
            <p className="text-xs text-red-600">{t('excelMapping.mapAtLeastOne')}</p>
          )}
        </div>

        <div className="px-6 py-3 border-t border-slate-200 flex justify-end gap-3">
          <button onClick={onCancel} className="btn-secondary">
            {t('common.cancel')}
          </button>
          <button
            onClick={() => onConfirm(mapping, selectedHeaderRow)}
            disabled={!hasUsableMapping}
            className="btn-primary"
          >
            {t('excelMapping.loadTickets')}
          </button>
        </div>
      </div>
    </div>
  )
}
