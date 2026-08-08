// Status pill for dashboard / script states: a coloured dot plus the state name.
const STYLES = {
  RUNNING: { pill: 'border-mint-400/25 bg-mint-400/[0.12] text-mint-300', dot: 'bg-mint-400', pulse: true },
  SUCCESS: { pill: 'border-mint-400/25 bg-mint-400/[0.12] text-mint-300', dot: 'bg-mint-400' },
  STOPPED: { pill: 'border-panel-border bg-panel-raise/70 text-slate-400', dot: 'bg-slate-500' },
  FAILED: { pill: 'border-red-500/25 bg-red-500/[0.12] text-red-300', dot: 'bg-red-400' },
  ERROR: { pill: 'border-red-500/25 bg-red-500/[0.12] text-red-300', dot: 'bg-red-400' },
  UNKNOWN: { pill: 'border-amber-500/25 bg-amber-500/[0.12] text-amber-300', dot: 'bg-amber-400' },
}

export default function StatusBadge({ status }) {
  const key = (status || 'UNKNOWN').toUpperCase()
  const style = STYLES[key] || STYLES.UNKNOWN
  return (
    <span className={`badge ${style.pill}`}>
      <span className={`dot ${style.dot} ${style.pulse ? 'animate-pulse-ring' : ''}`} />
      {key}
    </span>
  )
}
