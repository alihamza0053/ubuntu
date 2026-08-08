import { Link, useNavigate } from 'react-router-dom'
import api, { errorMessage } from '../api/client'
import { formatDateTime } from '../lib/datetime'
import StatusBadge from './StatusBadge'
import Icon from './ui/Icon'

const formatTime = (iso) => formatDateTime(iso)

/** One label/value line in the card body. */
function Meta({ label, children }) {
  return (
    <div className="flex items-baseline justify-between gap-3">
      <dt className="text-xs uppercase tracking-wide text-slate-500">{label}</dt>
      <dd className="min-w-0 truncate text-right text-sm text-slate-300">{children}</dd>
    </div>
  )
}

/**
 * Grid card for one Python project: status, dashboard URL, last run,
 * file counts and quick start/stop/restart actions.
 */
export default function ProjectCard({ project, onChanged, onDelete, onToggleHidden }) {
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
    <article className="card card-hover flex flex-col">
      {/* Header */}
      <div className="flex items-start justify-between gap-3">
        <div className="flex min-w-0 items-center gap-3">
          <span
            className="flex h-10 w-10 shrink-0 items-center justify-center rounded-xl
                       border border-mint-400/25 bg-mint-400/10 text-mint-300"
          >
            <Icon name="code" size={18} />
          </span>
          <div className="min-w-0">
            <Link
              to={`/projects/${project.id}`}
              className="block truncate font-semibold text-slate-100 transition-colors hover:text-mint-300"
            >
              {project.name}
            </Link>
            <span className="text-xs text-slate-500">port {project.dashboard_port}</span>
          </div>
        </div>

        <div className="flex shrink-0 items-center gap-1.5">
          {project.hidden && (
            <span className="badge-muted" title="Only admins can see this project">
              <Icon name="eye-off" size={11} /> hidden
            </span>
          )}
          <StatusBadge status={project.dashboard_status} />
        </div>
      </div>

      {/* Details */}
      <dl className="mt-5 space-y-2.5 border-t border-panel-border/50 pt-4">
        <Meta label="Dashboard">
          <a href={liveUrl} target="_blank" rel="noreferrer"
             className="inline-flex items-center gap-1 text-mint-400 hover:text-mint-300 hover:underline">
            {project.domain || `:${project.dashboard_port}`}
            <Icon name="external" size={12} />
          </a>
        </Meta>
        <Meta label="Last run">
          <span className="inline-flex items-center gap-1.5">
            {formatTime(project.last_script_run)}
            {project.last_script_status && (
              <Icon
                name={project.last_script_status === 'SUCCESS' ? 'check' : 'x'}
                size={13}
                className={project.last_script_status === 'SUCCESS' ? 'text-mint-400' : 'text-red-400'}
              />
            )}
          </span>
        </Meta>
        <Meta label="Next run">{formatTime(project.next_scheduled_run)}</Meta>
        <Meta label="Files">
          {project.file_counts?.code ?? 0} scripts · {project.file_counts?.data ?? 0} data ·{' '}
          {project.file_counts?.dashboard ?? 0} dashboard
        </Meta>
      </dl>

      {/* Actions */}
      <div className="mt-5 flex items-center gap-1 border-t border-panel-border/50 pt-4">
        <button className="btn-icon" onClick={() => action('start')} title="Start dashboard">
          <Icon name="play" size={15} />
        </button>
        <button className="btn-icon" onClick={() => action('stop')} title="Stop dashboard">
          <Icon name="stop" size={15} />
        </button>
        <button className="btn-icon" onClick={() => action('restart')} title="Restart dashboard">
          <Icon name="refresh" size={15} />
        </button>
        <span className="mx-1 h-5 w-px bg-panel-border" />
        <button
          className="btn-icon"
          onClick={() => navigate(`/projects/${project.id}?tab=scripts`)}
          title="Run a script"
        >
          <Icon name="terminal" size={15} />
        </button>
        <button
          className="btn-icon"
          onClick={() => navigate(`/projects/${project.id}?tab=files`)}
          title="Browse files"
        >
          <Icon name="folder" size={15} />
        </button>

        <span className="ml-auto flex items-center gap-1">
          {onToggleHidden && (
            <button
              className="btn-icon"
              onClick={() => onToggleHidden(project)}
              title={project.hidden ? 'Hidden from non-admins — click to unhide' : 'Hide from non-admins'}
            >
              <Icon name={project.hidden ? 'eye-off' : 'eye'} size={15} />
            </button>
          )}
          {onDelete && (
            <button className="btn-icon-danger" onClick={() => onDelete(project)} title="Delete project">
              <Icon name="trash" size={15} />
            </button>
          )}
        </span>
      </div>
    </article>
  )
}
