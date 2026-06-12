import { NavLink, Outlet } from 'react-router-dom'
import { useAuth } from '../context/AuthContext'

// Sidebar entries. Later-phase pages are listed but disabled so the final
// information architecture is visible from day one.
const NAV = [
  { to: '/dashboard', label: 'Dashboard', icon: '🏠' },
  { to: '/projects', label: 'Projects', icon: '🐍' },
  { to: '/websites', label: 'Websites', icon: '🌐', phase: 3 },
  { to: '/terminal', label: 'Terminal', icon: '💻', phase: 2 },
  { to: '/logs', label: 'Logs', icon: '📜', phase: 2 },
  { to: '/files', label: 'Files', icon: '📁', phase: 3 },
  { to: '/databases', label: 'Databases', icon: '🗄️', phase: 4 },
  { to: '/nginx', label: 'Nginx', icon: '⚙️', phase: 3 },
  { to: '/server', label: 'Server', icon: '🖥️', phase: 4 },
  { to: '/settings', label: 'Settings', icon: '🔧', phase: 5 },
]

export default function Layout() {
  const { user, logout } = useAuth()

  return (
    <div className="min-h-screen flex">
      {/* Sidebar */}
      <aside className="w-56 shrink-0 bg-panel-card border-r border-panel-border flex flex-col">
        <div className="px-4 py-5 border-b border-panel-border">
          <h1 className="text-xl font-bold text-sky-400">ServerHub</h1>
          <p className="text-xs text-slate-500 mt-0.5">VPS Control Panel</p>
        </div>

        <nav className="flex-1 px-2 py-3 space-y-0.5 overflow-y-auto">
          {NAV.map((item) =>
            item.phase ? (
              <div
                key={item.to}
                className="flex items-center gap-2 px-3 py-2 rounded-lg text-sm text-slate-600 cursor-not-allowed"
                title={`Coming in Phase ${item.phase}`}
              >
                <span>{item.icon}</span>
                {item.label}
                <span className="ml-auto text-[10px] text-slate-600 border border-slate-700 rounded px-1">
                  P{item.phase}
                </span>
              </div>
            ) : (
              <NavLink
                key={item.to}
                to={item.to}
                className={({ isActive }) =>
                  `flex items-center gap-2 px-3 py-2 rounded-lg text-sm transition-colors ${
                    isActive
                      ? 'bg-sky-600/20 text-sky-300'
                      : 'text-slate-300 hover:bg-slate-700/50'
                  }`
                }
              >
                <span>{item.icon}</span>
                {item.label}
              </NavLink>
            ),
          )}
        </nav>

        <div className="px-4 py-3 border-t border-panel-border flex items-center justify-between">
          <span className="text-sm text-slate-400 truncate">👤 {user?.username}</span>
          <button onClick={logout} className="text-xs text-red-400 hover:text-red-300">
            Logout
          </button>
        </div>
      </aside>

      {/* Main content */}
      <main className="flex-1 p-6 overflow-x-hidden">
        <Outlet />
      </main>
    </div>
  )
}
