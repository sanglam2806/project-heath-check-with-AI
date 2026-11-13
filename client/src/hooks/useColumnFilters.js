import { useState } from 'react'

const emptyFilters = (columnKeys) => Object.fromEntries(columnKeys.map((k) => [k, new Set()]))

/**
 * State + helpers for Excel-style per-column click-to-filter table headers
 * (see FilterableHeader). `columnKeys` is the fixed list of filterable
 * column keys for the table using this hook.
 */
export function useColumnFilters(columnKeys) {
  const [openFilter, setOpenFilter] = useState(null)
  const [filters, setFilters] = useState(() => emptyFilters(columnKeys))

  const toggleValue = (columnKey, value) => {
    setFilters((prev) => {
      const next = new Set(prev[columnKey])
      if (next.has(value)) next.delete(value)
      else next.add(value)
      return { ...prev, [columnKey]: next }
    })
  }

  const clearColumn = (columnKey) => {
    setFilters((prev) => ({ ...prev, [columnKey]: new Set() }))
  }

  const clearAll = () => setFilters(emptyFilters(columnKeys))

  const hasActiveFilters = Object.values(filters).some((s) => s.size > 0)

  /** Returns true if `row` passes every active column filter. `getValue`
   * maps (row, columnKey) -> the display value to filter on — either a
   * single value, or an array for a column where one row can belong to
   * several values at once (e.g. a member's list of groups), matched if
   * any of them is selected. */
  const matches = (row, getValue) =>
    columnKeys.every((key) => {
      if (filters[key].size === 0) return true
      const value = getValue(row, key)
      return Array.isArray(value) ? value.some((v) => filters[key].has(v)) : filters[key].has(value)
    })

  return {
    filters,
    openFilter,
    setOpenFilter,
    toggleValue,
    clearColumn,
    clearAll,
    hasActiveFilters,
    matches,
  }
}
