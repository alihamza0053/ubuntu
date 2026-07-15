// Sidebar/nav definition shared by the Layout (rendering) and App (route
// guards). `perm` is the permission key a non-admin user needs to see it.
export const NAV = [
  { to: '/shopify-apps', label: 'Shopify Apps', icon: 'Shopify', perm: 'shopify' },
  { to: '/dashboard', label: 'Dashboard', icon: '🏠', perm: 'dashboard' },
  { to: '/projects', label: 'Projects', icon: '🐍', perm: 'projects' },
  { to: '/websites', label: 'Websites', icon: '🌐', perm: 'websites' },
  { to: '/proxies', label: 'Proxies', icon: '🔀', perm: 'proxies' },
  { to: '/apps', label: 'Apps', icon: '🧩', perm: 'apps' },
  { to: '/docker', label: 'Docker', icon: '🐳', perm: 'docker' },
  { to: '/terminal', label: 'Terminal', icon: '💻', perm: 'terminal' },
  { to: '/logs', label: 'Logs', icon: '📜', perm: 'logs' },
  { to: '/files', label: 'Files', icon: '📁', perm: 'files' },
  { to: '/recycle-bin', label: 'Recycle Bin', icon: '🗑️', perm: 'files' },
  { to: '/databases', label: 'Databases', icon: '🗄️', perm: 'databases' },
  { to: '/nginx', label: 'Nginx', icon: '⚙️', perm: 'nginx' },
  { to: '/server', label: 'Server', icon: '🖥️', perm: 'server' },
  { to: '/settings', label: 'Settings', icon: '🔧', perm: 'settings' },
]

// First nav path a user is allowed to see (for redirects).
export function firstAllowed(can) {
  return (NAV.find((n) => can(n.perm)) || { to: '/dashboard' }).to
}
