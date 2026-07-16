import { Link, useNavigate } from 'react-router-dom'

const TYPE_STYLES = {
  react: 'bg-sky-500/15 text-sky-400',
  php: 'bg-violet-500/15 text-violet-400',
  html: 'bg-orange-500/15 text-orange-400',
  python: 'bg-emerald-500/15 text-emerald-400',
}

/** Home / Websites grid card for one website. */
export default function WebsiteCard({ site, onDelete, onToggleHidden }) {
  const navigate = useNavigate()
  const liveUrl = site.domain ? `http://${site.domain}` : null

  return (
    <div className="card hover:border-sky-700 transition-colors">
      <div className="flex items-start justify-between gap-2">
        <Link to={`/websites/${site.id}`} className="text-lg font-semibold text-sky-300 hover:underline">
          {site.name}
        </Link>
        <span className="flex items-center gap-1.5">
          {site.hidden && (
            <span className="badge bg-slate-500/15 text-slate-400" title="Only admins can see this website">
              🙈 hidden
            </span>
          )}
          <span className={`badge ${TYPE_STYLES[site.type] || ''}`}>{site.type.toUpperCase()}</span>
        </span>
      </div>

      <dl className="mt-3 space-y-1.5 text-sm">
        <div className="flex justify-between">
          <dt className="text-slate-500">Domain</dt>
          <dd>
            {liveUrl ? (
              <a href={liveUrl} target="_blank" rel="noreferrer" className="text-sky-400 hover:underline">
                {site.domain} ↗
              </a>
            ) : <span className="text-slate-600">not assigned</span>}
          </dd>
        </div>
        <div className="flex justify-between">
          <dt className="text-slate-500">Database</dt>
          <dd className="text-slate-300">{site.db_name || '—'}</dd>
        </div>
        {site.type === 'python' && (
          <div className="flex justify-between">
            <dt className="text-slate-500">Service</dt>
            <dd className={site.status === 'RUNNING' ? 'text-green-400' : 'text-slate-400'}>
              {site.status || 'STOPPED'}
            </dd>
          </div>
        )}
      </dl>

      <div className="mt-4 flex flex-wrap gap-2">
        <button className="btn-secondary" onClick={() => navigate(`/websites/${site.id}?tab=files`)}>📁 Files</button>
        {site.type === 'python' && (
          <button className="btn-secondary" onClick={() => navigate(`/websites/${site.id}?tab=run`)}>▶ Run</button>
        )}
        <button className="btn-secondary" onClick={() => navigate(`/websites/${site.id}?tab=database`)}>🗄 Database</button>
        {onToggleHidden && (
          <button
            className="btn-secondary"
            onClick={() => onToggleHidden(site)}
            title={site.hidden ? 'Hidden from non-admins — click to unhide' : 'Hide from non-admins'}
          >
            {site.hidden ? '🙈' : '👁'}
          </button>
        )}
        {onDelete && (
          <button className="btn-secondary text-red-400" onClick={() => onDelete(site)}>🗑</button>
        )}
      </div>
    </div>
  )
}
