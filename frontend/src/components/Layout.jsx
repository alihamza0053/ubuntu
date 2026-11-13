import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { NavLink, Outlet, useLocation, useNavigate } from 'react-router-dom'
import api from '../api/client'
import { useAuth } from '../context/AuthContext'
import { NAV } from '../nav'
import Icon from './ui/Icon'
import ThemeSwitcher from './ui/ThemeSwitcher'

const COLLAPSE_KEY = 'serverhub.sidebar-collapsed'

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

function Brand({ collapsed }) {
  return (
    <div className={`flex items-center gap-3 ${collapsed ? 'justify-center' : 'px-1'}`}>
      <span className="flex h-10 w-10 shrink-0 items-center justify-center rounded-xl bg-mint-grad
                       text-sm font-black tracking-tight text-ink shadow-rail">
        SH
      </span>
      {!collapsed && (
        <span className="min-w-0">
          <span className="block text-[15px] font-semibold leading-tight text-slate-100">ServerHub</span>
          <span className="block text-xs text-slate-500">Control panel</span>
        </span>
      )}
    </div>
  )
}

/* ── Sidebar: one bento tile with every section, labelled ────────────── */
function Sidebar({ items, collapsed, onToggle, onNavigate, user, isAdmin, onLogout, mobile = false }) {
  const initials = (user?.username || '?').slice(0, 2).toUpperCase()
  return (
    <div className="flex h-full flex-col rounded-tile border border-panel-border/80 bg-panel-rail p-3 shadow-card">
      <div className={`flex items-center ${collapsed ? 'flex-col gap-3' : 'justify-between'} pb-4 pt-1`}>
        <Brand collapsed={collapsed} />
        {!mobile && (
          <button onClick={onToggle} className="btn-icon h-8 w-8"
            title={collapsed ? 'Expand sidebar' : 'Collapse sidebar'}
            aria-label={collapsed ? 'Expand sidebar' : 'Collapse sidebar'}>
            <Icon name="sidebar" size={16} />
          </button>
        )}
      </div>

      <nav aria-label="Main" className="-mx-1 flex-1 space-y-1 overflow-y-auto px-1">
        {!collapsed && <p className="tile-label px-3 pb-1 pt-1">Menu</p>}
        {items.map((item) => (
          <NavLink
            key={item.to}
            to={item.to}
            onClick={onNavigate}
            title={collapsed ? item.label : undefined}
            className={({ isActive }) =>
              `nav-item ${collapsed ? 'justify-center px-0' : ''} ${isActive ? 'nav-item-active' : ''}`}
          >
            <Icon name={item.icon} size={18} />
            {collapsed ? <span className="sr-only">{item.label}</span> : <span className="truncate">{item.label}</span>}
          </NavLink>
        ))}
      </nav>

      {/* Phones: the header has no room for it, so the theme control lives here. */}
      {mobile && (
        <div className="mt-3 sm:hidden">
          <p className="tile-label px-1 pb-1.5">Theme</p>
          <ThemeSwitcher showLabels className="w-full justify-between" />
        </div>
      )}

      {/* Account tile at the foot of the sidebar */}
      <div className={`mt-3 flex items-center gap-2.5 rounded-2xl border border-panel-border/70 bg-panel-raise/60
                      p-2 ${collapsed ? 'flex-col' : ''}`}>
        <span className="flex h-9 w-9 shrink-0 items-center justify-center rounded-xl bg-mint-grad
                         text-xs font-bold text-ink">
          {initials}
        </span>
        {!collapsed && (
          <span className="min-w-0 flex-1">
            <span className="block truncate text-sm font-medium text-slate-100">{user?.username}</span>
            <span className="block text-xs text-slate-500">{isAdmin ? 'Administrator' : 'Standard user'}</span>
          </span>
        )}
        <button onClick={onLogout} className="btn-icon-danger h-8 w-8" title="Sign out" aria-label="Sign out">
          <Icon name="logout" size={16} />
        </button>
      </div>
    </div>
  )
}

/* ── Quick search over the sections (Ctrl/⌘-K) ───────────────────────── */
function QuickSearch({ items }) {
  const navigate = useNavigate()
  const [query, setQuery] = useState('')
  const [open, setOpen] = useState(false)
  const [cursor, setCursor] = useState(0)
  const inputRef = useRef(null)
  const close = useCallback(() => setOpen(false), [])
  const boxRef = useClickOutside(close)

  const matches = useMemo(() => {
    const q = query.trim().toLowerCase()
    return q ? items.filter((i) => i.label.toLowerCase().includes(q)) : items
  }, [query, items])

  useEffect(() => setCursor(0), [query])

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
    <div ref={boxRef} className="relative w-full max-w-sm">
      <div className="search-pill">
        <Icon name="search" size={15} className="text-slate-500" />
        <input
          ref={inputRef}
          value={query}
          placeholder="Jump to a section…"
          aria-label="Jump to a section"
          role="combobox"
          aria-expanded={open}
          aria-controls="quick-search-list"
          onFocus={() => setOpen(true)}
          onChange={(e) => { setQuery(e.target.value); setOpen(true) }}
          onKeyDown={(e) => {
            if (e.key === 'ArrowDown') { e.preventDefault(); setCursor((c) => Math.min(c + 1, matches.length - 1)) }
            if (e.key === 'ArrowUp') { e.preventDefault(); setCursor((c) => Math.max(c - 1, 0)) }
            if (e.key === 'Enter' && matches[cursor]) go(matches[cursor].to)
            if (e.key === 'Escape') { setOpen(false); inputRef.current?.blur() }
          }}
        />
        <span className="kbd hidden sm:inline">Ctrl K</span>
      </div>

      {open && (
        <div id="quick-search-list" role="listbox"
          className="absolute left-0 right-0 top-12 z-40 animate-fade-up overflow-hidden rounded-2xl
                     border border-panel-border bg-panel-card p-1.5 shadow-pop">
          {matches.length === 0 ? (
            <p className="px-3 py-2.5 text-sm text-slate-500">No section matches “{query}”.</p>
          ) : (
            matches.map((item, i) => (
              <button
                key={item.to}
                role="option"
                aria-selected={i === cursor}
                onMouseEnter={() => setCursor(i)}
                onClick={() => go(item.to)}
                className={`flex w-full items-center gap-2.5 rounded-xl px-3 py-2 text-left text-sm transition-colors
                            ${i === cursor ? 'bg-mint-400/10 text-mint-300' : 'text-slate-300'}`}
              >
                <Icon name={item.icon} size={15} className={i === cursor ? '' : 'text-slate-500'} />
                {item.label}
                {i === cursor && <span className="kbd ml-auto">Enter</span>}
              </button>
            ))
          )}
        </div>
      )}
    </div>
  )
}

/* ── Server health popover ────────────────────────────────────────────── */
function HealthBell() {
  const [open, setOpen] = useState(false)
  const [stats, setStats] = useState(null)
  const close = useCallback(() => setOpen(false), [])
  const ref = useClickOutside(close)

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
      <button onClick={() => setOpen((v) => !v)} className="btn-icon" aria-label="Server health" title="Server health">
        <Icon name="bell" size={17} />
        <span className={`absolute right-2 top-2 h-1.5 w-1.5 rounded-full
                          ${alert ? 'bg-red-400' : 'bg-mint-400'} animate-pulse-ring`} />
      </button>

      {open && (
        <div className="absolute right-0 top-12 z-40 w-72 animate-fade-up rounded-2xl border
                        border-panel-border bg-panel-card p-4 shadow-pop">
          <p className="tile-label mb-3">Server health</p>
          {!stats ? (
            <p className="text-sm text-slate-500">Loading…</p>
          ) : (
            <div className="space-y-3">
              {rows.map((r) => (
                <div key={r.label}>
                  <div className="mb-1 flex justify-between text-xs">
                    <span className="text-slate-400">{r.label}</span>
                    <span className="font-medium text-slate-200">{r.value}</span>
                  </div>
                  <div className="h-1.5 overflow-hidden rounded-full bg-panel-raise">
                    <div className={`h-full rounded-full ${r.pct > 85 ? 'bg-red-500' : 'bg-mint-grad'}`}
                      style={{ width: `${Math.min(r.pct, 100)}%` }} />
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

/* ── Shell ────────────────────────────────────────────────────────────── */
export default function Layout() {
  const { user, logout, isAdmin, can } = useAuth()
  const items = NAV.filter((item) => can(item.perm))
  const location = useLocation()
  const [drawer, setDrawer] = useState(false)
  const [collapsed, setCollapsed] = useState(() => {
    try { return localStorage.getItem(COLLAPSE_KEY) === '1' } catch { return false }
  })

  function toggleCollapsed() {
    setCollapsed((c) => {
      try { localStorage.setItem(COLLAPSE_KEY, c ? '0' : '1') } catch { /* private mode */ }
      return !c
    })
  }

  // The mobile menu closes on navigation and with Escape.
  useEffect(() => setDrawer(false), [location.pathname])
  useEffect(() => {
    if (!drawer) return undefined
    const onKey = (e) => e.key === 'Escape' && setDrawer(false)
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [drawer])

  const current = items.find((i) => location.pathname.startsWith(i.to))
  const sidebarProps = { items, user, isAdmin, onLogout: logout }

  return (
    <div className="relative z-10 min-h-screen">
      <a href="#main" className="sr-only focus:not-sr-only focus:fixed focus:left-4 focus:top-4 focus:z-[60]
                                 focus:rounded-xl focus:bg-panel-card focus:px-4 focus:py-2 focus:text-sm
                                 focus:text-mint-300 focus:shadow-pop">
        Skip to content
      </a>

      {/* Desktop sidebar: a floating tile */}
      <aside className={`fixed inset-y-0 left-0 z-30 hidden p-3 transition-[width] duration-200 lg:block
                         ${collapsed ? 'w-[92px]' : 'w-[264px]'}`}>
        <Sidebar {...sidebarProps} collapsed={collapsed} onToggle={toggleCollapsed} />
      </aside>

      {/* Mobile drawer */}
      {drawer && (
        <div className="fixed inset-0 z-50 lg:hidden" role="dialog" aria-modal="true" aria-label="Menu">
          <button className="absolute inset-0 bg-scrim/60 backdrop-blur-sm" aria-label="Close menu"
            onClick={() => setDrawer(false)} />
          <div className="absolute inset-y-0 left-0 w-[280px] max-w-[85vw] animate-fade-up p-3">
            <Sidebar {...sidebarProps} collapsed={false} mobile onNavigate={() => setDrawer(false)} />
          </div>
        </div>
      )}

      <div className={`transition-[padding] duration-200 ${collapsed ? 'lg:pl-[92px]' : 'lg:pl-[264px]'}`}>
        <header className="sticky top-0 z-20 px-3 pt-3">
          <div className="flex h-16 items-center gap-3 rounded-tile border border-panel-border/80
                          bg-panel-card/85 px-3 shadow-card backdrop-blur-xl sm:px-4">
            <button className="btn-icon lg:hidden" onClick={() => setDrawer(true)} aria-label="Open menu">
              <Icon name="menu" size={18} />
            </button>
            <span className="truncate text-sm font-semibold text-slate-100 sm:hidden">
              {current?.label || 'ServerHub'}
            </span>
            <div className="hidden min-w-0 flex-1 sm:block">
              <QuickSearch items={items} />
            </div>

            <div className="ml-auto flex items-center gap-1.5">
              <ThemeSwitcher className="hidden sm:inline-flex" />
              <HealthBell />
            </div>
          </div>
        </header>

        <main id="main" className="mx-auto w-full max-w-[1600px] px-3 pb-10 pt-6 sm:px-5 lg:px-6">
          <Outlet />
        </main>
      </div>
    </div>
  )
}
