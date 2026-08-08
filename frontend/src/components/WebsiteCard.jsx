import { Link, useNavigate } from 'react-router-dom'
import Icon from './ui/Icon'

// Per-stack accent for the type pill + icon tile.
const TYPES = {
  react: { pill: 'border-[#22E5CE]/25 bg-[#22E5CE]/[0.12] text-[#22E5CE]', tile: 'border-[#22E5CE]/25 bg-[#22E5CE]/10 text-[#22E5CE]' },
  php: { pill: 'border-violet-400/25 bg-violet-400/[0.12] text-violet-300', tile: 'border-violet-400/25 bg-violet-400/10 text-violet-300' },
  html: { pill: 'border-amber-400/25 bg-amber-400/[0.12] text-amber-300', tile: 'border-amber-400/25 bg-amber-400/10 text-amber-300' },
  python: { pill: 'border-mint-400/25 bg-mint-400/[0.12] text-mint-300', tile: 'border-mint-400/25 bg-mint-400/10 text-mint-300' },
}
const FALLBACK = { pill: 'border-panel-border bg-panel-raise/70 text-slate-400', tile: 'border-panel-border bg-panel-raise text-slate-400' }

function Meta({ label, children }) {
  return (
    <div className="flex items-baseline justify-between gap-3">
      <dt className="text-xs uppercase tracking-wide text-slate-500">{label}</dt>
      <dd className="min-w-0 truncate text-right text-sm text-slate-300">{children}</dd>
    </div>
  )
}

/** Home / Websites grid card for one website. */
export default function WebsiteCard({ site, onDelete, onToggleHidden }) {
  const navigate = useNavigate()
  const liveUrl = site.domain ? `http://${site.domain}` : null
  const style = TYPES[site.type] || FALLBACK
  const typeLabel =
    site.type === 'python' && site.framework && site.framework !== 'other'
      ? site.framework.toUpperCase()
      : String(site.type || '').toUpperCase()

  return (
    <article className="card card-hover flex flex-col">
      <div className="flex items-start justify-between gap-3">
        <div className="flex min-w-0 items-center gap-3">
          <span className={`flex h-10 w-10 shrink-0 items-center justify-center rounded-xl border ${style.tile}`}>
            <Icon name="globe" size={18} />
          </span>
          <div className="min-w-0">
            <Link
              to={`/websites/${site.id}`}
              className="block truncate font-semibold text-slate-100 transition-colors hover:text-mint-300"
            >
              {site.name}
            </Link>
            <span className="text-xs text-slate-500">{site.domain || 'no domain'}</span>
          </div>
        </div>

        <div className="flex shrink-0 items-center gap-1.5">
          {site.hidden && (
            <span className="badge-muted" title="Only admins can see this website">
              <Icon name="eye-off" size={11} /> hidden
            </span>
          )}
          <span className={`badge ${style.pill}`}>{typeLabel}</span>
        </div>
      </div>

      <dl className="mt-5 space-y-2.5 border-t border-panel-border/50 pt-4">
        <Meta label="Domain">
          {liveUrl ? (
            <a href={liveUrl} target="_blank" rel="noreferrer"
               className="inline-flex items-center gap-1 text-mint-400 hover:text-mint-300 hover:underline">
              {site.domain}
              <Icon name="external" size={12} />
            </a>
          ) : (
            <span className="text-slate-600">not assigned</span>
          )}
        </Meta>
        <Meta label="Database">{site.db_name || '—'}</Meta>
        {site.type === 'python' && (
          <Meta label="Service">
            <span className="inline-flex items-center gap-1.5">
              <span className={`dot ${site.status === 'RUNNING' ? 'bg-mint-400' : 'bg-slate-500'}`} />
              <span className={site.status === 'RUNNING' ? 'text-mint-300' : 'text-slate-400'}>
                {site.status || 'STOPPED'}
              </span>
            </span>
          </Meta>
        )}
      </dl>

      <div className="mt-5 flex items-center gap-1 border-t border-panel-border/50 pt-4">
        <button className="btn-icon" onClick={() => navigate(`/websites/${site.id}?tab=files`)} title="Files">
          <Icon name="folder" size={15} />
        </button>
        {site.type === 'python' && (
          <button className="btn-icon" onClick={() => navigate(`/websites/${site.id}?tab=run`)} title="Run">
            <Icon name="play" size={15} />
          </button>
        )}
        <button className="btn-icon" onClick={() => navigate(`/websites/${site.id}?tab=database`)} title="Database">
          <Icon name="database" size={15} />
        </button>

        <span className="ml-auto flex items-center gap-1">
          {onToggleHidden && (
            <button
              className="btn-icon"
              onClick={() => onToggleHidden(site)}
              title={site.hidden ? 'Hidden from non-admins — click to unhide' : 'Hide from non-admins'}
            >
              <Icon name={site.hidden ? 'eye-off' : 'eye'} size={15} />
            </button>
          )}
          {onDelete && (
            <button className="btn-icon-danger" onClick={() => onDelete(site)} title="Delete website">
              <Icon name="trash" size={15} />
            </button>
          )}
        </span>
      </div>
    </article>
  )
}
