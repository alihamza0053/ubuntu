// Colored status pill for dashboard / script states.
const STYLES = {
  RUNNING: 'bg-green-500/15 text-green-400',
  SUCCESS: 'bg-green-500/15 text-green-400',
  STOPPED: 'bg-slate-500/20 text-slate-400',
  FAILED: 'bg-red-500/15 text-red-400',
  ERROR: 'bg-red-500/15 text-red-400',
  UNKNOWN: 'bg-yellow-500/15 text-yellow-400',
}

const ICONS = {
  RUNNING: '✅',
  SUCCESS: '✅',
  STOPPED: '🔴',
  FAILED: '❌',
  ERROR: '⚠️',
  UNKNOWN: '❔',
}

export default function StatusBadge({ status }) {
  const key = (status || 'UNKNOWN').toUpperCase()
  return (
    <span className={`badge ${STYLES[key] || STYLES.UNKNOWN}`}>
      {ICONS[key] || ICONS.UNKNOWN} {key}
    </span>
  )
}
