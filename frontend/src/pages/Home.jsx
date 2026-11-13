import { useCallback, useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import api from '../api/client'
import ProjectCard from '../components/ProjectCard'
import WebsiteCard from '../components/WebsiteCard'
import Icon from '../components/ui/Icon'
import StatTile from '../components/ui/StatTile'
import { useAuth } from '../context/AuthContext'

function greeting() {
  const h = new Date().getHours()
  return h < 12 ? 'Good morning' : h < 17 ? 'Good afternoon' : 'Good evening'
}

/** Section heading with a "manage →" link on the right. */
function SectionHead({ title, count, to, linkLabel }) {
  return (
    <div className="mb-4 flex items-end justify-between gap-4">
      <h2 className="flex items-center gap-2 text-lg font-semibold text-slate-100">
        {title}
        {count != null && <span className="count-chip count-chip-active">{count}</span>}
      </h2>
      <Link to={to} className="inline-flex items-center gap-1 text-sm font-medium text-mint-400 hover:text-mint-300">
        {linkLabel}
        <Icon name="arrow-right" size={14} />
      </Link>
    </div>
  )
}

/** Running / stopped / failed split as one segmented bar with a legend. */
function StatusSplit({ counts }) {
  const total = counts.reduce((sum, c) => sum + c.value, 0)
  return (
    <>
      <div className="mt-4 flex h-2.5 overflow-hidden rounded-full bg-panel-raise" role="img"
        aria-label={counts.map((c) => `${c.value} ${c.label.toLowerCase()}`).join(', ')}>
        {total > 0 && counts.map((c) => c.value > 0 && (
          <div key={c.label} className={c.bar} style={{ width: `${(c.value / total) * 100}%` }} />
        ))}
      </div>
      <dl className="mt-3 flex flex-wrap gap-x-5 gap-y-1.5">
        {counts.map((c) => (
          <div key={c.label} className="flex items-center gap-1.5 text-sm">
            <span className={`dot ${c.bar}`} />
            <dt className="text-slate-500">{c.label}</dt>
            <dd className="font-semibold text-slate-200">{c.value}</dd>
          </div>
        ))}
      </dl>
    </>
  )
}

export default function Home() {
  const { can, user } = useAuth()
  const [stats, setStats] = useState(null)
  const [projects, setProjects] = useState([])
  const [websites, setWebsites] = useState([])
  const [loading, setLoading] = useState(true)
  const [refreshing, setRefreshing] = useState(false)

  // Users without the projects/websites tabs must not see (or fetch) them here.
  const showProjects = can('projects')
  const showWebsites = can('websites')

  const load = useCallback(() => Promise.allSettled([
    showProjects &&
      api.get('/projects', { params: { with_status: true } }).then((res) => setProjects(res.data)),
    showWebsites && api.get('/websites').then((res) => setWebsites(res.data)),
    api.get('/server/stats').then((res) => setStats(res.data)),
  ]), [showProjects, showWebsites])

  const refresh = useCallback(() => {
    setRefreshing(true)
    load().finally(() => setRefreshing(false))
  }, [load])

  useEffect(() => {
    load().finally(() => setLoading(false))
    const interval = setInterval(() => {
      api.get('/server/stats').then((res) => setStats(res.data)).catch(() => {})
    }, 10000) // live server stats every 10 s
    return () => clearInterval(interval)
  }, [load])

  const status = (p) => (p.dashboard_status || '').toUpperCase()
  const running = projects.filter((p) => status(p) === 'RUNNING').length
  const failed = projects.filter((p) => ['FATAL', 'ERROR', 'BACKOFF', 'FAILED'].includes(status(p))).length
  const services = websites.filter((s) => s.type === 'python' || s.type === 'node')
  const servicesUp = services.filter((s) => s.status === 'RUNNING').length

  const actions = [
    showProjects && { to: '/projects', icon: 'code', label: 'Projects' },
    showWebsites && { to: '/websites', icon: 'globe', label: 'Websites' },
    can('files') && { to: '/files', icon: 'folder', label: 'Files' },
    can('databases') && { to: '/databases', icon: 'database', label: 'Databases' },
  ].filter(Boolean)

  return (
    <div className="space-y-8">
      {/* ── Bento overview ─────────────────────────────────────────────── */}
      <section className="bento" aria-label="Overview">
        {/* Welcome tile */}
        <div className="card col-span-2 flex flex-col justify-between gap-6 sm:col-span-6 lg:col-span-6 lg:row-span-2">
          <div className="flex items-start justify-between gap-4">
            <div className="min-w-0">
              <p className="tile-label">Dashboard</p>
              <h1 className="mt-2 text-2xl font-semibold tracking-tight text-slate-100 sm:text-3xl">
                {greeting()}, <span className="text-mint-300">{user?.username}</span>
              </h1>
              <p className="mt-2 text-sm text-slate-500">
                {showProjects && projects.length > 0
                  ? `${running} of ${projects.length} dashboards running${failed ? ` · ${failed} need attention` : ''}.`
                  : 'Here is how your server is doing.'}
              </p>
            </div>
            <button className="btn-secondary shrink-0" onClick={refresh} disabled={refreshing}>
              <Icon name="refresh" size={15} className={refreshing ? 'animate-spin' : ''} />
              <span className="hidden sm:inline">{refreshing ? 'Refreshing…' : 'Refresh'}</span>
            </button>
          </div>

          {actions.length > 0 && (
            <div>
              <p className="tile-label mb-2.5">Go to</p>
              <div className="grid grid-cols-2 gap-2.5 sm:grid-cols-4">
                {actions.map((a) => (
                  <Link key={a.to} to={a.to}
                    className="group flex flex-col gap-3 rounded-2xl border border-panel-border/80 bg-panel-raise/60 p-3.5
                               transition-colors hover:border-mint-400/40 hover:bg-mint-400/[0.06]">
                    <Icon name={a.icon} size={18} className="text-mint-300" />
                    <span className="flex items-center justify-between text-sm font-medium text-slate-200">
                      {a.label}
                      <Icon name="arrow-right" size={14}
                        className="text-slate-500 transition-transform group-hover:translate-x-0.5 group-hover:text-mint-300" />
                    </span>
                  </Link>
                ))}
              </div>
            </div>
          )}
        </div>

        {/* Live server tiles, 2 × 2 beside the welcome tile */}
        <div className="sm:col-span-3 lg:col-span-3">
          <StatTile label="CPU" icon="cpu" value={stats ? `${stats.cpu_percent}%` : '…'}
            sub={stats?.cpu_cores && `${stats.cpu_cores} cores${stats.load_avg != null ? ` · load ${stats.load_avg}` : ''}`}
            percent={stats?.cpu_percent} />
        </div>
        <div className="sm:col-span-3 lg:col-span-3">
          <StatTile label="Memory" icon="layers" value={stats ? `${stats.memory.percent}%` : '…'}
            sub={stats && `${stats.memory.used_gb} / ${stats.memory.total_gb} GB`} percent={stats?.memory.percent} />
        </div>
        <div className="sm:col-span-3 lg:col-span-3">
          <StatTile label="Disk" icon="server" value={stats ? `${stats.disk.percent}%` : '…'}
            sub={stats && `${stats.disk.used_gb} / ${stats.disk.total_gb} GB`} percent={stats?.disk.percent} />
        </div>
        <div className="sm:col-span-3 lg:col-span-3">
          <StatTile label="Uptime" icon="clock" value={stats ? stats.uptime.human : '…'} sub="since last restart" />
        </div>

        {/* Dashboards split */}
        {showProjects && (
          <Link to="/projects" className="card card-hover col-span-2 block sm:col-span-6 lg:col-span-6">
            <div className="flex items-start justify-between gap-3">
              <div>
                <p className="tile-label">Dashboards</p>
                <p className="mt-1.5 text-2xl font-semibold tracking-tight text-slate-100">
                  {running}<span className="text-base font-medium text-slate-500"> / {projects.length} running</span>
                </p>
              </div>
              <span className="tile-icon"><Icon name="code" size={18} /></span>
            </div>
            <StatusSplit counts={[
              { label: 'Running', value: running, bar: 'bg-mint-400' },
              { label: 'Stopped', value: projects.length - running - failed, bar: 'bg-slate-600' },
              { label: 'Failed', value: failed, bar: 'bg-red-400' },
            ]} />
          </Link>
        )}

        {/* Websites summary */}
        {showWebsites && (
          <Link to="/websites" className="card card-hover col-span-2 block sm:col-span-6 lg:col-span-6">
            <div className="flex items-start justify-between gap-3">
              <div>
                <p className="tile-label">Websites</p>
                <p className="mt-1.5 text-2xl font-semibold tracking-tight text-slate-100">
                  {websites.length}<span className="text-base font-medium text-slate-500"> sites</span>
                </p>
              </div>
              <span className="tile-icon"><Icon name="globe" size={18} /></span>
            </div>
            <StatusSplit counts={[
              { label: 'Static sites', value: websites.length - services.length, bar: 'bg-aqua' },
              { label: 'Apps running', value: servicesUp, bar: 'bg-mint-400' },
              { label: 'Apps stopped', value: services.length - servicesUp, bar: 'bg-slate-600' },
            ]} />
          </Link>
        )}
      </section>

      {/* ── Projects ───────────────────────────────────────────────────── */}
      {showProjects && (
        <section>
          <SectionHead title="Python Projects" count={projects.length} to="/projects" linkLabel="Manage projects" />
          {loading ? (
            <div className="empty-state">Loading…</div>
          ) : projects.length === 0 ? (
            <div className="empty-state">
              <Icon name="code" size={26} className="text-slate-600" />
              <p>No projects yet.</p>
              <Link to="/projects" className="link">Create your first project</Link>
            </div>
          ) : (
            <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
              {projects.map((p) => <ProjectCard key={p.id} project={p} onChanged={refresh} />)}
            </div>
          )}
        </section>
      )}

      {/* ── Websites ───────────────────────────────────────────────────── */}
      {showWebsites && (
        <section>
          <SectionHead title="Websites" count={websites.length} to="/websites" linkLabel="Manage websites" />
          {loading ? (
            <div className="empty-state">Loading…</div>
          ) : websites.length === 0 ? (
            <div className="empty-state">
              <Icon name="globe" size={26} className="text-slate-600" />
              <p>No websites yet.</p>
              <Link to="/websites" className="link">Create one</Link>
            </div>
          ) : (
            <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
              {websites.map((s) => <WebsiteCard key={s.id} site={s} />)}
            </div>
          )}
        </section>
      )}
    </div>
  )
}
