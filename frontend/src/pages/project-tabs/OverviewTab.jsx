import StatusBadge from '../../components/StatusBadge'

function formatTime(iso) {
  if (!iso) return '—'
  return new Date(iso + 'Z').toLocaleString()
}

/** Read-only summary of the whole project. */
export default function OverviewTab({ project, files }) {
  const liveUrl = project.domain
    ? `http://${project.domain}`
    : `http://${window.location.hostname}:${project.dashboard_port}`

  const rows = [
    ['Folder', project.folder_path],
    ['Dashboard port', project.dashboard_port],
    ['Domain', project.domain || 'not assigned (Phase 3)'],
    ['Created', formatTime(project.created_at)],
    ['Last script run', formatTime(project.last_script_run)],
    ['Last script status', project.last_script_status || '—'],
  ]

  return (
    <div className="grid lg:grid-cols-2 gap-4">
      <div className="card">
        <h3 className="font-semibold mb-3">Project Info</h3>
        <dl className="space-y-2 text-sm">
          {rows.map(([label, value]) => (
            <div key={label} className="flex justify-between gap-4">
              <dt className="text-slate-500 shrink-0">{label}</dt>
              <dd className="text-right break-all">{value}</dd>
            </div>
          ))}
          <div className="flex justify-between gap-4">
            <dt className="text-slate-500">Dashboard status</dt>
            <dd><StatusBadge status={project.dashboard_status} /></dd>
          </div>
          <div className="flex justify-between gap-4">
            <dt className="text-slate-500">Live URL</dt>
            <dd>
              <a href={liveUrl} target="_blank" rel="noreferrer" className="text-sky-400 hover:underline">
                {liveUrl} ↗
              </a>
            </dd>
          </div>
        </dl>
      </div>

      <div className="card">
        <h3 className="font-semibold mb-3">Folder Contents</h3>
        {files ? (
          <ul className="space-y-2 text-sm">
            {Object.entries(files.folders).map(([folder, list]) => (
              <li key={folder} className="flex justify-between">
                <span className="text-slate-400 font-mono">{folder}/</span>
                <span>{list.length} file{list.length === 1 ? '' : 's'}</span>
              </li>
            ))}
          </ul>
        ) : (
          <p className="text-slate-500 text-sm">Loading…</p>
        )}
      </div>
    </div>
  )
}
