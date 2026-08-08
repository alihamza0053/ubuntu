import { useCallback, useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import api, { errorMessage } from '../api/client'
import StatusBadge from '../components/StatusBadge'
import Icon from '../components/ui/Icon'
import PageHeader from '../components/ui/PageHeader'
import { useAuth } from '../context/AuthContext'
import { appUrl } from '../lib/appUrl'

const INSTALL_BADGE = {
  INSTALLED: 'border-mint-400/25 bg-mint-400/[0.12] text-mint-300',
  INSTALLING: 'border-amber-400/25 bg-amber-400/[0.12] text-amber-300',
  MISSING: 'border-panel-border bg-panel-raise/70 text-slate-400',
}

/**
 * Apps: a fixed catalogue of software the panel can install and run for you.
 * Everything is addressed by its catalogue key — there is nothing to create.
 */
export default function Apps() {
  const { isAdmin } = useAuth()
  const [apps, setApps] = useState([])
  const [loading, setLoading] = useState(true)
  const [msg, setMsg] = useState('')

  const refresh = useCallback(() => {
    api.get('/apps').then((res) => setApps(res.data)).finally(() => setLoading(false))
  }, [])

  useEffect(() => {
    refresh()
  }, [refresh])

  // An install is a long apt/npm run in the background, so keep the cards
  // honest while one is in flight instead of waiting for a manual reload.
  useEffect(() => {
    if (!apps.some((a) => a.install_state === 'INSTALLING')) return undefined
    const timer = setInterval(refresh, 4000)
    return () => clearInterval(timer)
  }, [apps, refresh])

  async function install(app) {
    setMsg('')
    try {
      const res = await api.post(`/apps/${app.key}/install`)
      setMsg(res.data.detail)
      refresh()
    } catch (err) {
      setMsg(errorMessage(err))
    }
  }

  async function action(app, name) {
    setMsg('')
    try {
      const res = await api.post(`/apps/${app.key}/action/${name}`)
      setMsg(res.data.detail || `${name} ${app.key}`)
      refresh()
    } catch (err) {
      setMsg(errorMessage(err))
    }
  }

  return (
    <div className="space-y-6">
      <PageHeader
        title="Apps"
        crumbs={[{ label: 'Catalogue' }, { label: 'Apps' }]}
        actions={
          <button className="btn-secondary" onClick={refresh}>
            <Icon name="refresh" size={15} />
            Refresh
          </button>
        }
      >
        <p className="max-w-2xl text-sm text-slate-500">
          Ready-made software this panel installs, runs and puts behind one of your domains.
          Browsers run on a virtual display you view right here.
        </p>
      </PageHeader>

      {msg && (
        <div className="flex items-start gap-2 rounded-lg border border-panel-border bg-panel-card/70 px-3.5 py-2.5 text-sm text-slate-300">
          <Icon name="info" size={15} className="mt-0.5 text-mint-400" />
          <span className="min-w-0 break-words">{msg}</span>
        </div>
      )}

      {loading ? (
        <div className="empty-state">Loading…</div>
      ) : (
        <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
          {apps.map((app) => (
            <AppCard
              key={app.key}
              app={app}
              isAdmin={isAdmin}
              onInstall={() => install(app)}
              onAction={(n) => action(app, n)}
            />
          ))}
        </div>
      )}
    </div>
  )
}

function AppCard({ app, isAdmin, onInstall, onAction }) {
  const installed = app.install_state === 'INSTALLED'
  const installing = app.install_state === 'INSTALLING'
  const running = app.status === 'RUNNING'
  const openUrl = appUrl(app)

  return (
    <article className="card card-hover flex flex-col">
      <div className="flex items-start justify-between gap-3">
        <div className="flex min-w-0 items-center gap-3">
          <span
            className="flex h-10 w-10 shrink-0 items-center justify-center rounded-xl
                       border border-panel-border bg-panel-raise text-lg"
          >
            {app.icon}
          </span>
          <div className="min-w-0">
            <h3 className="truncate font-semibold text-slate-100">{app.label}</h3>
            <span className="text-xs text-slate-500">
              {app.kind === 'desktop' ? 'browser · noVNC' : 'web service'}
            </span>
          </div>
        </div>
        <div className="flex shrink-0 flex-col items-end gap-1.5">
          <span className={`badge ${INSTALL_BADGE[app.install_state] || INSTALL_BADGE.MISSING}`}>
            {app.install_state}
          </span>
          {installed && <StatusBadge status={app.status} />}
        </div>
      </div>

      <p className="mt-4 text-sm text-slate-400">{app.summary}</p>

      {installed && (
        <dl className="mt-4 space-y-2 border-t border-panel-border/50 pt-4 text-sm">
          <div className="flex justify-between gap-3">
            <dt className="text-xs uppercase tracking-wide text-slate-500">Port</dt>
            <dd className="font-mono text-slate-300">{app.port}</dd>
          </div>
          <div className="flex justify-between gap-3">
            <dt className="text-xs uppercase tracking-wide text-slate-500">Domain</dt>
            <dd className="min-w-0 truncate text-slate-300">{app.domain || '—'}</dd>
          </div>
        </dl>
      )}

      <div className="mt-5 flex flex-wrap items-center gap-2 border-t border-panel-border/50 pt-4">
        {!installed && !installing && isAdmin && (
          <button className="btn-primary btn-sm" onClick={onInstall}>
            <Icon name="download" size={14} />
            Install
          </button>
        )}
        {!installed && !installing && !isAdmin && (
          <span className="text-xs text-slate-500">Ask an admin to install this.</span>
        )}
        {installing && (
          <span className="badge-warn">
            <span className="dot animate-pulse-ring bg-amber-400" />
            Installing…
          </span>
        )}

        {installed && !running && (
          <button className="btn-primary btn-sm" onClick={() => onAction('start')}>
            <Icon name="play" size={14} />
            Start
          </button>
        )}
        {installed && running && (
          <>
            <a className="btn-primary btn-sm" href={openUrl} target="_blank" rel="noreferrer">
              <Icon name="external" size={14} />
              Open
            </a>
            <button className="btn-secondary btn-sm" onClick={() => onAction('stop')}>
              <Icon name="stop" size={14} />
              Stop
            </button>
          </>
        )}
        <Link to={`/apps/${app.key}`} className="btn-secondary btn-sm ml-auto">
          Manage
          <Icon name="chevron-right" size={14} />
        </Link>
      </div>
    </article>
  )
}
