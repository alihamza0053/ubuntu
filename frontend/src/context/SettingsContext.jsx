import { createContext, useCallback, useContext, useEffect, useMemo, useState } from 'react'
import api from '../api/client'
import { formatDate, formatDateTime, formatTime, setActiveTimezone } from '../lib/datetime'

/**
 * Panel-wide settings that the whole UI reads — currently the display timezone.
 *
 * Loaded once from /api/settings and cached here so every page formats dates
 * the same way without each of them fetching. The value is also mirrored into
 * localStorage: it is read on the very first render, before the request comes
 * back, so timestamps don't visibly jump from one zone to another on load.
 */
const SettingsContext = createContext(null)

const TZ_KEY = 'serverhub.timezone'

export function SettingsProvider({ children }) {
  const [timezone, setTimezoneState] = useState(() => {
    let initial = ''
    try {
      initial = localStorage.getItem(TZ_KEY) || ''
    } catch { /* private mode */ }
    // Before the first render, so module-level formatters are already correct.
    setActiveTimezone(initial)
    return initial
  })

  // Keep the module-level mirror in step with state.
  setActiveTimezone(timezone)

  useEffect(() => {
    api.get('/settings')
      .then((res) => {
        const stored = res.data?.display_timezone || ''
        setTimezoneState(stored)
        try { localStorage.setItem(TZ_KEY, stored) } catch { /* private mode */ }
      })
      .catch(() => { /* not logged in yet, or offline — keep the cached value */ })
  }, [])

  /** Persist to the panel DB so the zone follows the user to any browser. */
  const setTimezone = useCallback(async (value) => {
    setTimezoneState(value)
    try { localStorage.setItem(TZ_KEY, value) } catch { /* private mode */ }
    await api.put('/settings', { values: { display_timezone: value } })
  }, [])

  const value = useMemo(() => ({
    timezone,
    setTimezone,
    fmtDateTime: (v, dash) => formatDateTime(v, timezone, dash),
    fmtDate: (v, dash) => formatDate(v, timezone, dash),
    fmtTime: (v, dash) => formatTime(v, timezone, dash),
  }), [timezone, setTimezone])

  // Keying on the timezone remounts the tree when it changes, so pages whose
  // date helpers are module-level functions (not context consumers) re-render
  // with the new zone instead of waiting for a manual refresh.
  return (
    <SettingsContext.Provider value={value}>
      <div key={timezone || 'auto'} className="contents">{children}</div>
    </SettingsContext.Provider>
  )
}

export function usePanelSettings() {
  const ctx = useContext(SettingsContext)
  if (!ctx) throw new Error('usePanelSettings must be used inside <SettingsProvider>')
  return ctx
}

/** Convenience for the common case: just the formatters. */
export function useDateFormat() {
  const { fmtDateTime, fmtDate, fmtTime, timezone } = usePanelSettings()
  return { fmtDateTime, fmtDate, fmtTime, timezone }
}
