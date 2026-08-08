import Icon from './ui/Icon'

/**
 * Thin upload/download progress bar.
 * Props: dir ('up' | 'down'), name (label), pct (0-100 or null for indeterminate).
 */
export default function ProgressBar({ dir, name, pct }) {
  const known = typeof pct === 'number'
  return (
    <div className="my-2.5">
      <div className="mb-1.5 flex justify-between gap-2 text-xs text-slate-400">
        <span className="flex min-w-0 items-center gap-1.5">
          <Icon name={dir === 'up' ? 'upload' : 'download'} size={13} className="text-mint-400" />
          <span className="truncate">
            {dir === 'up' ? 'Uploading' : 'Downloading'} {name}
          </span>
        </span>
        <span className="font-medium text-slate-300">{known ? `${pct}%` : '…'}</span>
      </div>
      <div className="h-1.5 overflow-hidden rounded-full bg-panel-bg">
        <div
          className={`h-full rounded-full bg-mint-grad transition-[width] duration-150
                      ${known ? '' : 'w-1/3 animate-pulse'}`}
          style={known ? { width: `${pct}%` } : undefined}
        />
      </div>
    </div>
  )
}
