/**
 * Thin upload/download progress bar.
 * Props: dir ('up' | 'down'), name (label), pct (0-100 or null for indeterminate).
 */
export default function ProgressBar({ dir, name, pct }) {
  const label = dir === 'up' ? '⬆ Uploading' : '⬇ Downloading'
  const known = typeof pct === 'number'
  return (
    <div className="my-2">
      <div className="flex justify-between gap-2 text-xs text-slate-400 mb-1">
        <span className="truncate">{label} {name}</span>
        <span>{known ? `${pct}%` : '…'}</span>
      </div>
      <div className="h-1.5 bg-panel-border rounded overflow-hidden">
        <div
          className={`h-full bg-sky-500 transition-[width] duration-150 ${known ? '' : 'animate-pulse w-1/3'}`}
          style={known ? { width: `${pct}%` } : undefined}
        />
      </div>
    </div>
  )
}
