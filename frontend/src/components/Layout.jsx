import { NavLink, Outlet } from 'react-router-dom'
import { useAuth } from '../context/AuthContext'
import { NAV } from '../nav'

export default function Layout() {
  const { user, logout, isAdmin, can } = useAuth()
  const items = NAV.filter((item) => can(item.perm))

  return (
    <div className="min-h-screen flex">
      {/* Sidebar */}
      <aside className="w-56 shrink-0 bg-panel-card border-r border-panel-border flex flex-col">
        <div className="px-4 py-5 border-b border-panel-border">
          <h1 className="text-xl font-bold text-sky-400">ServerHub</h1>
          <p className="text-xs text-slate-500 mt-0.5">VPS Control Panel</p>
        </div>

        <nav className="flex-1 px-2 py-3 space-y-0.5 overflow-y-auto">
          {items.map((item) => (
            <NavLink
              key={item.to}
              to={item.to}
              className={({ isActive }) =>
                `flex items-center gap-2 px-3 py-2 rounded-lg text-sm transition-colors ${
                  isActive ? 'bg-sky-600/20 text-sky-300' : 'text-slate-300 hover:bg-slate-700/50'
                }`
              }
            >
              <span>{item.icon}</span>
              {item.label}
            </NavLink>
          ))}
        </nav>

        <div className="px-4 py-3 border-t border-panel-border flex items-center justify-between">
          <span className="text-sm text-slate-400 truncate">
            👤 {user?.username}
            <span className="ml-1 text-[10px] text-slate-600">{isAdmin ? 'admin' : 'user'}</span>
          </span>
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
