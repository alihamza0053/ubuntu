/**
 * Public URL of an installed app (Apps section).
 *
 * With a domain assigned, the scheme follows whether certbot has issued a
 * certificate for it — the panel itself is usually on https, and an http frame
 * inside an https page is blocked as mixed content. Without a domain the app is
 * only reachable on its own port, on whatever host the panel is being used from.
 */
export function appUrl(app) {
  if (!app.port) return null
  const path = app.url_path || '/'
  if (app.domain) return `${app.ssl ? 'https' : 'http'}://${app.domain}${path}`
  return `http://${window.location.hostname}:${app.port}${path}`
}
