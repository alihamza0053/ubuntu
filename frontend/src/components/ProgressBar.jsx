import Icon from './ui/Icon'

/**
 * Thin upload/download progress bar.
 * Props: dir ('up' | 'down'), name (label), pct (0-100 or null for indeterminate),
 *        onCancel (optional — shows an ✕ that aborts the transfer).
 */
export default function ProgressBar({ dir, name, pct, onCancel }) {
  const known = typeof pct === 'number'
  const verb = dir === 'up' ? 'Uploading' : 'Downloading'
  return (
    <div className="my-2.5">
      <div className="mb-1.5 flex justify-between gap-2 text-xs text-slate-400">
        <span className="flex min-w-0 items-center gap-1.5">
          <Icon name={dir === 'up' ? 'upload' : 'download'} size={13} className="text-mint-400" />
          <span className="truncate">
            {verb} {name}
          </span>
        </span>
        <span className="flex flex-shrink-0 items-center gap-2">
          <span className="font-medium text-slate-300">{known ? `${pct}%` : '…'}</span>
          {onCancel && (
            <button
              type="button"
              onClick={onCancel}
              title={`Cancel ${verb.toLowerCase()}`}
              aria-label={`Cancel ${verb.toLowerCase()}`}
              className="rounded p-0.5 text-slate-500 transition-colors hover:bg-red-500/10 hover:text-red-300"
            >
              <Icon name="x" size={13} />
            </button>
          )}
        </span>
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
