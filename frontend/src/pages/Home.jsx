import { useCallback, useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import api from '../api/client'
import ProjectCard from '../components/ProjectCard'
import WebsiteCard from '../components/WebsiteCard'
import { useAuth } from '../context/AuthContext'

/** Small stat widget (CPU / RAM / Disk / Uptime). */
function StatWidget({ label, value, sub, percent }) {
  const barColor =
    percent == null ? '' : percent > 90 ? 'bg-red-500' : percent > 70 ? 'bg-yellow-500' : 'bg-sky-500'
  return (
    <div className="card">
      <p className="text-xs uppercase tracking-wide text-slate-500">{label}</p>
      <p className="text-2xl font-bold mt-1">{value}</p>
      {sub && <p className="text-xs text-slate-500 mt-0.5">{sub}</p>}
      {percent != null && (
        <div className="mt-2 h-1.5 rounded bg-slate-700 overflow-hidden">
          <div className={`h-full ${barColor}`} style={{ width: `${Math.min(percent, 100)}%` }} />
        </div>
      )}
    </div>
  )
}

export default function Home() {
  const { can } = useAuth()
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

  return (
    <div className="space-y-6">
      <h2 className="text-2xl font-bold">Dashboard</h2>

      {/* Server stats */}
      <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
        <StatWidget
          label="CPU"
          value={stats ? `${stats.cpu_percent}%` : '…'}
          percent={stats?.cpu_percent}
        />
        <StatWidget
          label="RAM"
          value={stats ? `${stats.memory.percent}%` : '…'}
          sub={stats && `${stats.memory.used_gb} / ${stats.memory.total_gb} GB`}
          percent={stats?.memory.percent}
        />
        <StatWidget
          label="Disk"
          value={stats ? `${stats.disk.percent}%` : '…'}
          sub={stats && `${stats.disk.used_gb} / ${stats.disk.total_gb} GB`}
          percent={stats?.disk.percent}
        />
        <StatWidget label="Uptime" value={stats ? stats.uptime.human : '…'} />
      </div>

      {/* Project cards — only for users with the projects tab */}
      {showProjects && (
      <div>
        <div className="flex items-center justify-between mb-3">
          <h3 className="text-lg font-semibold">Python Projects</h3>
          <Link to="/projects" className="text-sm text-sky-400 hover:underline">
            Manage projects →
          </Link>
        </div>
        {loading ? (
          <p className="text-slate-500">Loading…</p>
        ) : projects.length === 0 ? (
          <div className="card text-center py-10 text-slate-500">
            No projects yet.{' '}
            <Link to="/projects" className="text-sky-400 hover:underline">
              Create your first project
            </Link>
          </div>
        ) : (
          <div className="grid md:grid-cols-2 xl:grid-cols-3 gap-4">
            {projects.map((p) => (
              <ProjectCard key={p.id} project={p} onChanged={refresh} />
            ))}
          </div>
        )}
      </div>
      )}

      {/* Website cards — only for users with the websites tab */}
      {showWebsites && (
      <div>
        <div className="flex items-center justify-between mb-3">
          <h3 className="text-lg font-semibold">Websites</h3>
          <Link to="/websites" className="text-sm text-sky-400 hover:underline">Manage websites →</Link>
        </div>
        {websites.length === 0 ? (
          <div className="card text-center py-8 text-slate-600">
            No websites yet. <Link to="/websites" className="text-sky-400 hover:underline">Create one</Link>
          </div>
        ) : (
          <div className="grid md:grid-cols-2 xl:grid-cols-3 gap-4">
            {websites.map((s) => <WebsiteCard key={s.id} site={s} />)}
          </div>
        )}
      </div>
      )}
    </div>
  )
}
