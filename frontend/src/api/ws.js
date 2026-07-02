/**
 * Build an authenticated WebSocket URL for a backend /ws/... path.
 * The JWT is passed as a ?token= query parameter (validated server-side).
 */
export function wsUrl(path) {
  const token = localStorage.getItem('serverhub_token') || ''
  const proto = window.location.protocol === 'https:' ? 'wss' : 'ws'
  const sep = path.includes('?') ? '&' : '?'
  return `${proto}://${window.location.host}${path}${sep}token=${encodeURIComponent(token)}`
}
