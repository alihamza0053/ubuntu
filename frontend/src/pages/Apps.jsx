import { useCallback, useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import api, { errorMessage } from '../api/client'
import StatusBadge from '../components/StatusBadge'
import { useAuth } from '../context/AuthContext'
import { appUrl } from '../lib/appUrl'

const INSTALL_BADGE = {
  INSTALLED: 'bg-green-500/15 text-green-400',
  INSTALLING: 'bg-yellow-500/15 text-yellow-400',
  MISSING: 'bg-slate-500/15 text-slate-400',
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

  if (loading) return <p className="text-slate-500">Loading…</p>

  return (
    <div className="space-y-6">
      <div>
        <h2 className="text-2xl font-bold">Apps</h2>
        <p className="text-sm text-slate-500 mt-1">
          Ready-made software this panel installs, runs and puts behind one of your
          domains. Browsers run on a virtual display you view right here.
        </p>
      </div>

      {msg && <p className="text-sm text-slate-300 break-words">{msg}</p>}

      <div className="grid md:grid-cols-2 xl:grid-cols-3 gap-4">
        {apps.map((app) => (
          <AppCard key={app.key} app={app} isAdmin={isAdmin}
            onInstall={() => install(app)} onAction={(n) => action(app, n)} />
        ))}
      </div>
    </div>
  )
}

function AppCard({ app, isAdmin, onInstall, onAction }) {
  const installed = app.install_state === 'INSTALLED'
  const installing = app.install_state === 'INSTALLING'
  const running = app.status === 'RUNNING'
  const openUrl = appUrl(app)

  return (
    <div className="card flex flex-col gap-3">
      <div className="flex items-start justify-between gap-2">
        <div className="flex items-center gap-2">
          <span className="text-2xl">{app.icon}</span>
          <div>
            <h3 className="font-semibold leading-tight">{app.label}</h3>
            <span className="text-[11px] text-slate-500">
              {app.kind === 'desktop' ? 'browser · noVNC' : 'web service'}
            </span>
          </div>
        </div>
        <div className="flex flex-col items-end gap-1">
          <span className={`badge ${INSTALL_BADGE[app.install_state]}`}>
            {app.install_state}
          </span>
          {installed && <StatusBadge status={app.status} />}
        </div>
      </div>

      <p className="text-sm text-slate-400">{app.summary}</p>

      {installed && (
        <dl className="text-xs text-slate-500 space-y-1">
          <div className="flex justify-between">
            <dt>Port</dt><dd className="font-mono">{app.port}</dd>
          </div>
          <div className="flex justify-between">
            <dt>Domain</dt><dd>{app.domain || '—'}</dd>
          </div>
        </dl>
      )}

      <div className="flex items-center gap-2 flex-wrap mt-auto pt-1">
        {!installed && !installing && isAdmin && (
          <button className="btn-primary" onClick={onInstall}>⬇ Install</button>
        )}
        {!installed && !installing && !isAdmin && (
          <span className="text-xs text-slate-500">Ask an admin to install this.</span>
        )}
        {installing && <span className="text-xs text-yellow-400">Installing…</span>}

        {installed && !running && (
          <button className="btn-primary" onClick={() => onAction('start')}>▶ Start</button>
        )}
        {installed && running && (
          <>
            <a className="btn-primary" href={openUrl} target="_blank" rel="noreferrer">↗ Open</a>
            <button className="btn-secondary" onClick={() => onAction('stop')}>■ Stop</button>
          </>
        )}
        <Link to={`/apps/${app.key}`} className="btn-secondary">Manage</Link>
      </div>
    </div>
  )
}
