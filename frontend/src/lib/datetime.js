/**
 * One place that turns an API timestamp into text.
 *
 * The backend stores and returns UTC, but most timestamps are naive — they
 * arrive as "2026-07-29T05:48:00" with no zone marker. `new Date()` reads a
 * bare string like that as *local* time, so a UTC value silently shifts by the
 * viewer's offset. Every caller here goes through `parseServerDate`, which
 * treats an unmarked timestamp as UTC, and then renders it in the display
 * timezone configured in Settings.
 */

/** IANA zones offered in Settings. "" = follow the browser. */
export const TIMEZONES = [
  { value: '', label: 'Auto — this browser’s timezone' },
  { value: 'UTC', label: 'UTC' },
  { value: 'Asia/Karachi', label: 'Asia/Karachi (PKT, UTC+5)' },
  { value: 'Asia/Dubai', label: 'Asia/Dubai (GST, UTC+4)' },
  { value: 'Asia/Riyadh', label: 'Asia/Riyadh (AST, UTC+3)' },
  { value: 'Asia/Dhaka', label: 'Asia/Dhaka (UTC+6)' },
  { value: 'Asia/Kolkata', label: 'Asia/Kolkata (IST, UTC+5:30)' },
  { value: 'Asia/Shanghai', label: 'Asia/Shanghai (CST, UTC+8)' },
  { value: 'Asia/Singapore', label: 'Asia/Singapore (UTC+8)' },
  { value: 'Europe/London', label: 'Europe/London (GMT/BST)' },
  { value: 'Europe/Berlin', label: 'Europe/Berlin (CET/CEST)' },
  { value: 'Europe/Istanbul', label: 'Europe/Istanbul (UTC+3)' },
  { value: 'America/New_York', label: 'America/New_York (ET)' },
  { value: 'America/Chicago', label: 'America/Chicago (CT)' },
  { value: 'America/Denver', label: 'America/Denver (MT)' },
  { value: 'America/Los_Angeles', label: 'America/Los_Angeles (PT)' },
  { value: 'Australia/Sydney', label: 'Australia/Sydney (AET)' },
]

/**
 * The zone currently in force, mirrored out of SettingsContext.
 *
 * Most date helpers in the app are plain module-level functions, not hooks, so
 * they can't read context. The provider pushes the value here instead and
 * remounts the tree when it changes, which keeps those helpers correct without
 * threading a timezone argument through every component.
 */
let activeTimezone = ''

export function setActiveTimezone(value) {
  activeTimezone = value || ''
}

export function getActiveTimezone() {
  return activeTimezone
}

/** True when the string already carries a zone: trailing Z, or ±HH:MM. */
function hasZone(iso) {
  return /(?:Z|[+-]\d{2}:?\d{2})$/.test(iso)
}

/**
 * Parse an API timestamp. A naive one is UTC — that is the contract the backend
 * follows (datetime.utcnow() everywhere). Returns null for junk so callers can
 * fall back instead of rendering "Invalid Date".
 */
export function parseServerDate(value) {
  if (!value) return null
  if (value instanceof Date) return isNaN(value.getTime()) ? null : value
  const iso = String(value).trim()
  if (!iso) return null
  const date = new Date(hasZone(iso) ? iso : `${iso}Z`)
  return isNaN(date.getTime()) ? null : date
}

/** Options accepted by Intl, with an undefined timeZone meaning "browser". */
function withZone(timezone, options) {
  return timezone ? { ...options, timeZone: timezone } : options
}

const DATE_TIME = { year: 'numeric', month: 'short', day: '2-digit',
  hour: '2-digit', minute: '2-digit' }
const DATE_ONLY = { year: 'numeric', month: 'short', day: '2-digit' }
const TIME_ONLY = { hour: '2-digit', minute: '2-digit', second: '2-digit' }

/** "29 Jul 2026, 10:48" in the given zone. `dash` is shown for empty values. */
export function formatDateTime(value, timezone = getActiveTimezone(), dash = '—') {
  const date = parseServerDate(value)
  if (!date) return dash
  try {
    return date.toLocaleString(undefined, withZone(timezone, DATE_TIME))
  } catch {
    return date.toLocaleString()      // unknown zone: never break the page
  }
}

export function formatDate(value, timezone = getActiveTimezone(), dash = '—') {
  const date = parseServerDate(value)
  if (!date) return dash
  try {
    return date.toLocaleDateString(undefined, withZone(timezone, DATE_ONLY))
  } catch {
    return date.toLocaleDateString()
  }
}

export function formatTime(value, timezone = getActiveTimezone(), dash = '—') {
  const date = parseServerDate(value)
  if (!date) return dash
  try {
    return date.toLocaleTimeString(undefined, withZone(timezone, TIME_ONLY))
  } catch {
    return date.toLocaleTimeString()
  }
}

/** The zone actually in use, resolving "" to whatever the browser reports. */
export function resolveTimezone(timezone) {
  if (timezone) return timezone
  try {
    return Intl.DateTimeFormat().resolvedOptions().timeZone || 'UTC'
  } catch {
    return 'UTC'
  }
}

/** Short offset label like "UTC+05:00", for the Settings preview. */
export function offsetLabel(timezone, at = new Date()) {
  try {
    const zone = resolveTimezone(timezone)
    const parts = new Intl.DateTimeFormat('en-US', {
      timeZone: zone, timeZoneName: 'longOffset',
    }).formatToParts(at)
    const name = parts.find((p) => p.type === 'timeZoneName')?.value
    return name && name !== 'GMT' ? name.replace('GMT', 'UTC') : 'UTC+00:00'
  } catch {
    return ''
  }
}
