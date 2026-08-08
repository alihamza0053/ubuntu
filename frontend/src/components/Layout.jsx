import { useEffect, useMemo, useRef, useState } from 'react'
import { NavLink, Outlet, useNavigate } from 'react-router-dom'
import api from '../api/client'
import { useAuth } from '../context/AuthContext'
import { NAV } from '../nav'
import Icon from './ui/Icon'

/** Close a popover when the user clicks anywhere outside it. */
function useClickOutside(onOutside) {
  const ref = useRef(null)
  useEffect(() => {
    function handler(e) {
      if (ref.current && !ref.current.contains(e.target)) onOutside()
    }
    document.addEventListener('mousedown', handler)
    return () => document.removeEventListener('mousedown', handler)
  }, [onOutside])
  return ref
}

/* ── Left icon rail ───────────────────────────────────────────────────── */
function Rail({ items, onLogout }) {
  return (
    <aside
      className="fixed inset-y-0 left-0 z-30 flex w-[68px] flex-col items-center
                 border-r border-panel-border/60 bg-panel-rail/90 py-4 backdrop-blur-md"
    >
      {/* Brand mark */}
      <NavLink
        to={items[0]?.to || '/dashboard'}
        className="mb-6 flex h-10 w-10 items-center justify-center rounded-xl
                   bg-mint-grad text-sm font-black tracking-tight text-[#04231a] shadow-rail"
        title="ServerHub"
      >
        SH
      </NavLink>

      <nav className="flex flex-1 flex-col items-center gap-1.5">
        {items.map((item) => (
          <NavLink
            key={item.to}
            to={item.to}
            className={({ isActive }) => `group rail-btn ${isActive ? 'rail-btn-active' : ''}`}
          >
            <Icon name={item.icon} size={19} />
            {/* Hover tooltip */}
            <span
              className="pointer-events-none absolute left-full z-40 ml-3 whitespace-nowrap rounded-lg
                         border border-panel-border bg-panel-card px-2.5 py-1 text-xs font-medium
                         text-slate-200 opacity-0 shadow-card transition-opacity duration-150
                         group-hover:opacity-100"
            >
              {item.label}
            </span>
          </NavLink>
        ))}
      </nav>

      <button onClick={onLogout} className="group rail-btn mt-2" title="Sign out">
        <Icon name="logout" size={19} />
        <span
          className="pointer-events-none absolute left-full z-40 ml-3 whitespace-nowrap rounded-lg
                     border border-panel-border bg-panel-card px-2.5 py-1 text-xs font-medium
                     text-slate-200 opacity-0 shadow-card transition-opacity duration-150
                     group-hover:opacity-100"
        >
          Sign out
        </span>
      </button>
    </aside>
  )
}

/* ── Quick search over the nav sections ───────────────────────────────── */
function QuickSearch({ items }) {
  const navigate = useNavigate()
  const [query, setQuery] = useState('')
  const [open, setOpen] = useState(false)
  const inputRef = useRef(null)
  const boxRef = useClickOutside(() => setOpen(false))

  const matches = useMemo(() => {
    const q = query.trim().toLowerCase()
    return q ? items.filter((i) => i.label.toLowerCase().includes(q)) : items
  }, [query, items])

  // Ctrl/⌘-K focuses the search box.
  useEffect(() => {
    function onKey(e) {
      if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 'k') {
        e.preventDefault()
        inputRef.current?.focus()
        setOpen(true)
      }
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [])

  function go(to) {
    navigate(to)
    setQuery('')
    setOpen(false)
    inputRef.current?.blur()
  }

  return (
    <div ref={boxRef} className="relative w-full max-w-xs">
      <div className="search-pill">
        <Icon name="search" size={15} className="text-slate-500" />
        <input
          ref={inputRef}
          value={query}
          placeholder="Search…"
          onFocus={() => setOpen(true)}
          onChange={(e) => {
            setQuery(e.target.value)
            setOpen(true)
          }}
          onKeyDown={(e) => {
            if (e.key === 'Enter' && matches[0]) go(matches[0].to)
            if (e.key === 'Escape') setOpen(false)
          }}
        />
        <span className="kbd hidden sm:inline">Ctrl K</span>
      </div>

      {open && (
        <div className="absolute left-0 right-0 top-11 z-40 animate-fade-up overflow-hidden rounded-xl
                        border border-panel-border bg-panel-card/95 py-1.5 shadow-card backdrop-blur-md">
          {matches.length === 0 ? (
            <p className="px-3 py-2.5 text-sm text-slate-500">No section matches “{query}”.</p>
          ) : (
            matches.map((item) => (
              <button
                key={item.to}
                onClick={() => go(item.to)}
                className="flex w-full items-center gap-2.5 px-3 py-2 text-left text-sm text-slate-300
                           transition-colors hover:bg-mint-400/10 hover:text-mint-300"
              >
                <Icon name={item.icon} size={15} className="text-slate-500" />
                {item.label}
              </button>
            ))
          )}
        </div>
      )}
    </div>
  )
}

/* ── Server-health popover behind the bell ────────────────────────────── */
function HealthBell() {
  const [open, setOpen] = useState(false)
  const [stats, setStats] = useState(null)
  const ref = useClickOutside(() => setOpen(false))

  useEffect(() => {
    if (!open) return
    api.get('/server/stats').then((res) => setStats(res.data)).catch(() => setStats(null))
  }, [open])

  const rows = stats
    ? [
        { label: 'CPU', value: `${stats.cpu_percent}%`, pct: stats.cpu_percent },
        { label: 'Memory', value: `${stats.memory.percent}%`, pct: stats.memory.percent },
        { label: 'Disk', value: `${stats.disk.percent}%`, pct: stats.disk.percent },
      ]
    : []
  const alert = rows.some((r) => r.pct > 85)

  return (
    <div ref={ref} className="relative">
      <button onClick={() => setOpen((v) => !v)} className="btn-icon" aria-label="Server health">
        <Icon name="bell" size={17} />
        <span
          className={`absolute right-1.5 top-1.5 h-1.5 w-1.5 rounded-full
                      ${alert ? 'bg-red-400' : 'bg-mint-400'} animate-pulse-ring`}
        />
      </button>

      {open && (
        <div className="absolute right-0 top-11 z-40 w-64 animate-fade-up rounded-xl border
                        border-panel-border bg-panel-card/95 p-4 shadow-card backdrop-blur-md">
          <p className="mb-3 text-[11px] font-semibold uppercase tracking-wider text-slate-500">
            Server health
          </p>
          {!stats ? (
            <p className="text-sm text-slate-500">Stats unavailable.</p>
          ) : (
            <div className="space-y-3">
              {rows.map((r) => (
                <div key={r.label}>
                  <div className="mb-1 flex justify-between text-xs">
                    <span className="text-slate-400">{r.label}</span>
                    <span className="font-medium text-slate-200">{r.value}</span>
                  </div>
                  <div className="h-1.5 overflow-hidden rounded-full bg-panel-bg">
                    <div
                      className={`h-full rounded-full ${r.pct > 85 ? 'bg-red-500' : 'bg-mint-grad'}`}
                      style={{ width: `${Math.min(r.pct, 100)}%` }}
                    />
                  </div>
                </div>
              ))}
              <p className="border-t border-panel-border/70 pt-2.5 text-xs text-slate-500">
                Uptime · <span className="text-slate-300">{stats.uptime?.human}</span>
              </p>
            </div>
          )}
        </div>
      )}
    </div>
  )
}

/* ── Account chip ─────────────────────────────────────────────────────── */
function AccountMenu({ user, isAdmin, onLogout }) {
  const [open, setOpen] = useState(false)
  const ref = useClickOutside(() => setOpen(false))
  const initials = (user?.username || '?').slice(0, 2).toUpperCase()

  return (
    <div ref={ref} className="relative">
      <button
        onClick={() => setOpen((v) => !v)}
        className="flex items-center gap-2.5 rounded-full border border-transparent py-1 pl-2.5 pr-1
                   transition-colors hover:border-panel-border hover:bg-panel-raise/60"
      >
        <span className="hidden text-sm font-medium text-slate-200 sm:block">{user?.username}</span>
        <span
          className="flex h-8 w-8 items-center justify-center rounded-full bg-mint-grad
                     text-xs font-bold text-[#04231a]"
        >
          {initials}
        </span>
      </button>

      {open && (
        <div className="absolute right-0 top-12 z-40 w-52 animate-fade-up overflow-hidden rounded-xl
                        border border-panel-border bg-panel-card/95 shadow-card backdrop-blur-md">
          <div className="border-b border-panel-border/70 px-4 py-3">
            <p className="truncate text-sm font-medium text-slate-100">{user?.username}</p>
            <p className="mt-0.5 text-xs text-mint-400">{isAdmin ? 'Administrator' : 'Standard user'}</p>
          </div>
          <button
            onClick={onLogout}
            className="flex w-full items-center gap-2.5 px-4 py-2.5 text-left text-sm text-slate-300
                       transition-colors hover:bg-red-500/10 hover:text-red-300"
          >
            <Icon name="logout" size={15} />
            Sign out
          </button>
        </div>
      )}
    </div>
  )
}

/* ── Shell ────────────────────────────────────────────────────────────── */
export default function Layout() {
  const { user, logout, isAdmin, can } = useAuth()
  const items = NAV.filter((item) => can(item.perm))
  // Top-bar shortcuts: the first few sections this user is allowed to open.
  const quickLinks = items.filter((i) => i.to !== '/settings').slice(0, 3)

  return (
    <div className="relative z-10 min-h-screen">
      <Rail items={items} onLogout={logout} />

      <div className="pl-[68px]">
        <header
          className="sticky top-0 z-20 flex h-16 items-center gap-4 border-b border-panel-border/60
                     bg-panel-bg/80 px-5 backdrop-blur-xl"
        >
          <QuickSearch items={items} />

          <nav className="mx-auto hidden items-center gap-1 lg:flex">
            {quickLinks.map((item) => (
              <NavLink
                key={item.to}
                to={item.to}
                className={({ isActive }) =>
                  `rounded-lg px-3.5 py-1.5 text-sm font-medium transition-colors ${
                    isActive ? 'text-mint-300' : 'text-slate-400 hover:text-slate-100'
                  }`
                }
              >
                {item.label}
              </NavLink>
            ))}
          </nav>

          <div className="ml-auto flex items-center gap-1.5">
            {can('databases') && (
              <NavLink to="/databases" className="btn-icon" title="Databases">
                <Icon name="database" size={17} />
              </NavLink>
            )}
            {can('files') && (
              <NavLink to="/files" className="btn-icon" title="File manager">
                <Icon name="folder" size={17} />
              </NavLink>
            )}
            <HealthBell />
            <span className="mx-1 h-6 w-px bg-panel-border" />
            <AccountMenu user={user} isAdmin={isAdmin} onLogout={logout} />
          </div>
        </header>

        <main className="mx-auto w-full max-w-[1600px] px-6 py-7">
          <Outlet />
        </main>
      </div>
    </div>
  )
}
