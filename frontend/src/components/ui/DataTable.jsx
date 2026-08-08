import Icon from './Icon'

/**
 * Bordered data table matching the reference list view.
 *
 * columns: [{ key, label, align?: 'left'|'right'|'center', width?, render?(row) }]
 * rows:    array of objects (each needs a stable `id` or pass `rowKey`)
 */
export default function DataTable({
  columns,
  rows,
  rowKey = (row, i) => row.id ?? i,
  empty = 'Nothing here yet.',
  onRowClick,
  className = '',
}) {
  const align = { left: 'text-left', right: 'text-right', center: 'text-center' }

  return (
    <div className={`table-wrap ${className}`}>
      <table className="table">
        <thead>
          <tr>
            {columns.map((col) => (
              <th key={col.key} style={col.width ? { width: col.width } : undefined}
                  className={align[col.align] || 'text-left'}>
                {col.label}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.length === 0 ? (
            <tr>
              <td colSpan={columns.length} className="px-4 py-12 text-center text-slate-500">
                {empty}
              </td>
            </tr>
          ) : (
            rows.map((row, i) => (
              <tr
                key={rowKey(row, i)}
                onClick={onRowClick ? () => onRowClick(row) : undefined}
                className={onRowClick ? 'cursor-pointer' : undefined}
              >
                {columns.map((col) => (
                  <td key={col.key} className={align[col.align] || 'text-left'}>
                    {col.render ? col.render(row, i) : row[col.key]}
                  </td>
                ))}
              </tr>
            ))
          )}
        </tbody>
      </table>
    </div>
  )
}

/** Name + subtitle cell with a leading square icon tile — the reference's first column. */
export function NameCell({ icon, tint = 'mint', title, subtitle, onClick }) {
  const tints = {
    mint: 'bg-mint-400/[0.12] text-mint-300 border-mint-400/25',
    aqua: 'bg-[#22E5CE]/[0.12] text-[#22E5CE] border-[#22E5CE]/25',
    amber: 'bg-amber-400/[0.12] text-amber-300 border-amber-400/25',
    violet: 'bg-violet-400/[0.12] text-violet-300 border-violet-400/25',
    slate: 'bg-panel-raise text-slate-400 border-panel-border',
  }
  return (
    <div className="flex items-center gap-3">
      <span className={`flex h-9 w-9 items-center justify-center rounded-lg border ${tints[tint] || tints.mint}`}>
        {typeof icon === 'string' ? <Icon name={icon} size={17} /> : icon}
      </span>
      <span className="min-w-0">
        <span
          onClick={onClick}
          className={`block truncate font-medium text-slate-100 ${onClick ? 'cursor-pointer hover:text-mint-300' : ''}`}
        >
          {title}
        </span>
        {subtitle && <span className="block truncate text-xs text-slate-500">{subtitle}</span>}
      </span>
    </div>
  )
}

/** Right-aligned icon action cluster for the last table column. */
export function RowActions({ children }) {
  return <div className="flex items-center justify-end gap-1">{children}</div>
}
