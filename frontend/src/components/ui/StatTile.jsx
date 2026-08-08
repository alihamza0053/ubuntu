import Icon from './Icon'

/**
 * KPI tile: label, big value, optional sub-line and a usage meter.
 * The meter shifts mint → amber → red as it fills.
 */
export default function StatTile({ label, value, sub, percent, icon }) {
  const known = typeof percent === 'number'
  const tone = !known ? 'mint' : percent > 90 ? 'red' : percent > 70 ? 'amber' : 'mint'
  const bar = {
    mint: 'bg-mint-grad',
    amber: 'bg-gradient-to-r from-amber-400 to-amber-500',
    red: 'bg-gradient-to-r from-red-400 to-red-500',
  }[tone]
  const glyph = {
    mint: 'text-mint-300 border-mint-400/25 bg-mint-400/10',
    amber: 'text-amber-300 border-amber-400/25 bg-amber-400/10',
    red: 'text-red-300 border-red-400/25 bg-red-400/10',
  }[tone]

  return (
    <div className="card card-hover overflow-hidden">
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <p className="text-[11px] font-semibold uppercase tracking-wider text-slate-500">{label}</p>
          <p className="mt-1.5 truncate text-2xl font-semibold tracking-tight text-slate-100">{value}</p>
          {sub && <p className="mt-0.5 truncate text-xs text-slate-500">{sub}</p>}
        </div>
        {icon && (
          <span className={`flex h-9 w-9 items-center justify-center rounded-lg border ${glyph}`}>
            <Icon name={icon} size={17} />
          </span>
        )}
      </div>

      {known && (
        <div className="mt-4 h-1.5 overflow-hidden rounded-full bg-panel-bg">
          <div
            className={`h-full rounded-full ${bar} transition-[width] duration-500`}
            style={{ width: `${Math.min(Math.max(percent, 0), 100)}%` }}
          />
        </div>
      )}
    </div>
  )
}
