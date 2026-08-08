/**
 * Underlined tab strip with optional count bubbles — the
 * "Features Cloud 3 · Private Cloud 2 · Public Cloud 4" bar from the reference.
 *
 * tabs: [{ key, label, count? }]
 */
export default function Tabs({ tabs, active, onChange, className = '' }) {
  return (
    <div className={`tab-bar ${className}`} role="tablist">
      {tabs.map((tab) => {
        const isActive = tab.key === active
        return (
          <button
            key={tab.key}
            role="tab"
            aria-selected={isActive}
            onClick={() => onChange(tab.key)}
            className={`tab ${isActive ? 'tab-active' : ''}`}
          >
            {tab.label}
            {tab.count != null && (
              <span className={`count-chip ${isActive ? 'count-chip-active' : ''}`}>{tab.count}</span>
            )}
          </button>
        )
      })}
    </div>
  )
}
