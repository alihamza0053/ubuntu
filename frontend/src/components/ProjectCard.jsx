import { Link, useNavigate } from 'react-router-dom'
import api, { errorMessage } from '../api/client'
import StatusBadge from './StatusBadge'

function formatTime(iso) {
  if (!iso) return '—'
  return new Date(iso + 'Z').toLocaleString()
}

/**
 * Home-page card for one Python project: status, domain, last run,
 * file counts and quick start/stop/restart actions.
 */
export default function ProjectCard({ project, onChanged }) {
  const navigate = useNavigate()

  async function action(name) {
    try {
      await api.post(`/projects/${project.id}/dashboard/${name}`)
      onChanged?.()
    } catch (err) {
      alert(errorMessage(err))
    }
  }

  const liveUrl = project.domain
    ? `http://${project.domain}`
    : `http://${window.location.hostname}:${project.dashboard_port}`

  return (
    <div className="card hover:border-sky-700 transition-colors">
      {/* Header: name + status */}
      <div className="flex items-start justify-between gap-2">
        <Link to={`/projects/${project.id}`} className="text-lg font-semibold text-sky-300 hover:underline">
          {project.name}
        </Link>
        <span className="flex items-center gap-1.5">
          {project.hidden && (
            <span className="badge bg-slate-500/15 text-slate-400" title="Only admins can see this project">
              🙈 hidden
            </span>
          )}
          <StatusBadge status={project.dashboard_status} />
        </span>
      </div>

      {/* Details */}
      <dl className="mt-3 space-y-1.5 text-sm">
        <div className="flex justify-between">
          <dt className="text-slate-500">Dashboard</dt>
          <dd>
            <a href={liveUrl} target="_blank" rel="noreferrer" className="text-sky-400 hover:underline">
              {project.domain || `:${project.dashboard_port}`} ↗
            </a>
          </dd>
        </div>
        <div className="flex justify-between">
          <dt className="text-slate-500">Last script run</dt>
          <dd className="flex items-center gap-1.5">
            {formatTime(project.last_script_run)}
            {project.last_script_status && (
              <span className={project.last_script_status === 'SUCCESS' ? 'text-green-400' : 'text-red-400'}>
                {project.last_script_status === 'SUCCESS' ? '✓' : '✗'}
              </span>
            )}
          </dd>
        </div>
        <div className="flex justify-between">
          <dt className="text-slate-500">Next scheduled</dt>
          <dd>{formatTime(project.next_scheduled_run)}</dd>
        </div>
        <div className="flex justify-between">
          <dt className="text-slate-500">Files</dt>
          <dd className="text-slate-300">
            {project.file_counts?.code ?? 0} scripts · {project.file_counts?.data ?? 0} data ·{' '}
            {project.file_counts?.dashboard ?? 0} dashboard
          </dd>
        </div>
      </dl>

      {/* Quick actions */}
      <div className="mt-4 flex flex-wrap gap-2">
        <button className="btn-secondary" onClick={() => action('start')}>▶ Start</button>
        <button className="btn-secondary" onClick={() => action('stop')}>⏹ Stop</button>
        <button className="btn-secondary" onClick={() => action('restart')}>🔄 Restart</button>
        <button className="btn-secondary" onClick={() => navigate(`/projects/${project.id}?tab=scripts`)}>
          ▶ Run Script
        </button>
        <button className="btn-secondary" onClick={() => navigate(`/projects/${project.id}?tab=files`)}>
          📁 Files
        </button>
      </div>
    </div>
  )
}
