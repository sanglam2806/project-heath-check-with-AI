import { ChevronDown } from 'lucide-react'
import { useTranslation } from 'react-i18next'

/**
 * A <th> whose label opens an Excel-style checkbox dropdown listing that
 * column's unique values, so clicking the header itself filters the table.
 * Shared by any table that wants per-column click-to-filter headers.
 */
export default function FilterableHeader({
  columnKey,
  label,
  options,
  selected,
  isOpen,
  onToggle,
  onChange,
  onClear,
  align = 'left',
}) {
  const { t } = useTranslation()
  const isActive = selected.size > 0

  return (
    <th className={`px-6 py-3 font-semibold relative select-none ${align === 'right' ? 'text-right' : ''}`}>
      <button
        type="button"
        onClick={() => onToggle(columnKey)}
        className={`inline-flex items-center gap-1 cursor-pointer hover:text-slate-700 ${
          isActive ? 'text-primary-600' : ''
        }`}
      >
        {label}
        <ChevronDown size={13} />
        {isActive && <span className="w-1.5 h-1.5 rounded-full bg-primary-600" />}
      </button>

      {isOpen && (
        <>
          <div className="fixed inset-0 z-10" onClick={() => onToggle(null)} />
          <div
            className={`absolute top-full mt-1 z-20 w-56 bg-white rounded-lg shadow-lg border border-slate-200 normal-case font-normal text-slate-700 py-2 ${
              align === 'right' ? 'right-0' : 'left-0'
            }`}
          >
            <div className="max-h-56 overflow-y-auto px-1">
              {options.map((opt) => (
                <label
                  key={opt}
                  className="flex items-center gap-2 px-3 py-1.5 text-sm hover:bg-slate-50 rounded-md cursor-pointer"
                >
                  <input
                    type="checkbox"
                    checked={selected.has(opt)}
                    onChange={() => onChange(columnKey, opt)}
                  />
                  <span className="truncate">{opt}</span>
                </label>
              ))}
            </div>
            {isActive && (
              <div className="px-3 pt-1.5 mt-1 border-t border-slate-100">
                <button
                  type="button"
                  onClick={() => onClear(columnKey)}
                  className="text-xs text-primary-600 hover:underline cursor-pointer"
                >
                  {t('common.clearFilter')}
                </button>
              </div>
            )}
          </div>
        </>
      )}
    </th>
  )
}
