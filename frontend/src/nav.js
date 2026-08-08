// Sidebar/nav definition shared by the Layout (rendering) and App (route
// guards). `perm` is the permission key a non-admin user needs to see it.
// `icon` is a key into components/ui/Icon.jsx.
export const NAV = [
  { to: '/dashboard', label: 'Dashboard', icon: 'grid', perm: 'dashboard' },
  { to: '/projects', label: 'Projects', icon: 'code', perm: 'projects' },
  { to: '/websites', label: 'Websites', icon: 'globe', perm: 'websites' },
  { to: '/files', label: 'Files', icon: 'folder', perm: 'files' },
  { to: '/recycle-bin', label: 'Recycle Bin', icon: 'trash', perm: 'files' },
  { to: '/databases', label: 'Databases', icon: 'database', perm: 'databases' },
  { to: '/apps', label: 'Apps', icon: 'puzzle', perm: 'apps' },
  { to: '/settings', label: 'Settings', icon: 'gear', perm: 'settings' },
]

// First nav path a user is allowed to see (for redirects).
export function firstAllowed(can) {
  return (NAV.find((n) => can(n.perm)) || { to: '/dashboard' }).to
}
