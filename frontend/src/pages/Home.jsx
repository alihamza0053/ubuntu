import { useCallback, useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import api from '../api/client'
import ProjectCard from '../components/ProjectCard'
import WebsiteCard from '../components/WebsiteCard'
import Icon from '../components/ui/Icon'
import PageHeader from '../components/ui/PageHeader'
import StatTile from '../components/ui/StatTile'
import { useAuth } from '../context/AuthContext'

/** Section heading with a "manage →" link on the right. */
function SectionHead({ title, count, to, linkLabel }) {
  return (
    <div className="mb-4 flex items-end justify-between gap-4">
      <h2 className="flex items-center gap-2 text-lg font-semibold text-slate-100">
        {title}
        {count != null && <span className="count-chip count-chip-active">{count}</span>}
      </h2>
      <Link
        to={to}
        className="inline-flex items-center gap-1 text-sm text-mint-400 transition-colors hover:text-mint-300"
      >
        {linkLabel}
        <Icon name="arrow-right" size={14} />
      </Link>
    </div>
  )
}

export default function Home() {
  const { can, user } = useAuth()
  const [stats, setStats] = useState(null)
  const [projects, setProjects] = useState([])
  const [websites, setWebsites] = useState([])
  const [loading, setLoading] = useState(true)

  // Users without the projects/websites tabs must not see (or fetch) them here.
  const showProjects = can('projects')
  const showWebsites = can('websites')

  const refresh = useCallback(() => {
    // with_status=true asks the backend for live supervisor states
    if (showProjects) {
      api.get('/projects', { params: { with_status: true } }).then((res) => setProjects(res.data))
    }
    api.get('/server/stats').then((res) => setStats(res.data)).catch(() => {})
  }, [showProjects])

  useEffect(() => {
    Promise.allSettled([
      showProjects &&
        api.get('/projects', { params: { with_status: true } }).then((res) => setProjects(res.data)),
      showWebsites && api.get('/websites').then((res) => setWebsites(res.data)),
      api.get('/server/stats').then((res) => setStats(res.data)),
    ]).finally(() => setLoading(false))

    const interval = setInterval(() => {
      api.get('/server/stats').then((res) => setStats(res.data)).catch(() => {})
    }, 10000) // refresh stats every 10s
    return () => clearInterval(interval)
  }, [showProjects, showWebsites])

  const running = projects.filter((p) => p.dashboard_status === 'RUNNING').length

  return (
    <div className="space-y-8">
      <PageHeader
        title="Dashboard"
        crumbs={[{ label: 'ServerHub' }, { label: 'Overview' }]}
        actions={
          <button className="btn-secondary" onClick={refresh}>
            <Icon name="refresh" size={15} />
            Refresh
          </button>
        }
      >
        <p className="text-sm text-slate-500">
          Welcome back, <span className="text-slate-300">{user?.username}</span>
          {showProjects && projects.length > 0 && (
            <> · {running} of {projects.length} dashboards running</>
          )}
        </p>
      </PageHeader>

      {/* Server stats */}
      <div className="grid grid-cols-2 gap-4 lg:grid-cols-4">
        <StatTile
          label="CPU"
          icon="cpu"
          value={stats ? `${stats.cpu_percent}%` : '…'}
          percent={stats?.cpu_percent}
        />
        <StatTile
          label="Memory"
          icon="layers"
          value={stats ? `${stats.memory.percent}%` : '…'}
          sub={stats && `${stats.memory.used_gb} / ${stats.memory.total_gb} GB`}
          percent={stats?.memory.percent}
        />
        <StatTile
          label="Disk"
          icon="server"
          value={stats ? `${stats.disk.percent}%` : '…'}
          sub={stats && `${stats.disk.used_gb} / ${stats.disk.total_gb} GB`}
          percent={stats?.disk.percent}
        />
        <StatTile label="Uptime" icon="clock" value={stats ? stats.uptime.human : '…'} />
      </div>

      {/* Project cards — only for users with the projects tab */}
      {showProjects && (
        <section>
          <SectionHead
            title="Python Projects"
            count={projects.length}
            to="/projects"
            linkLabel="Manage projects"
          />
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
              {projects.map((p) => (
                <ProjectCard key={p.id} project={p} onChanged={refresh} />
              ))}
            </div>
          )}
        </section>
      )}

      {/* Website cards — only for users with the websites tab */}
      {showWebsites && (
        <section>
          <SectionHead
            title="Websites"
            count={websites.length}
            to="/websites"
            linkLabel="Manage websites"
          />
          {websites.length === 0 ? (
            <div className="empty-state">
              <Icon name="globe" size={26} className="text-slate-600" />
              <p>No websites yet.</p>
              <Link to="/websites" className="link">Create one</Link>
            </div>
          ) : (
            <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
              {websites.map((s) => (
                <WebsiteCard key={s.id} site={s} />
              ))}
            </div>
          )}
        </section>
      )}
    </div>
  )
}
