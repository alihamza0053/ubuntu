import { useCallback, useEffect, useState } from 'react'
import api, { errorMessage } from '../api/client'
import LiveLog from '../components/LiveLog'
import StatusBadge from '../components/StatusBadge'

/**
 * Apps section: one-click install of self-hosted apps (VS Code/code-server,
 * File Browser, …), run them on a port, assign a domain, and manage them.
 */
export default function Apps() {
  const [catalog, setCatalog] = useState([])
  const [ready, setReady] = useState(true)
  const [installed, setInstalled] = useState([])
  const [installWs, setInstallWs] = useState(null) // WS path during an install

  const refresh = useCallback(() => {
    api.get('/apps/catalog').then((res) => {
      setCatalog(res.data.apps || [])
      setReady(res.data.installer_ready !== false)
    }).catch(() => {})
    api.get('/apps').then((res) => setInstalled(res.data)).catch(() => {})
  }, [])

  useEffect(() => {
    refresh()
  }, [refresh])

  // Poll while installing so the new app appears when done
  useEffect(() => {
    if (!installWs) return
    const t = setInterval(refresh, 3000)
    return () => clearInterval(t)
  }, [installWs, refresh])

  function install(slug) {
    setInstallWs(null)
    setTimeout(() => setInstallWs(`/ws/apps/${slug}/install`), 0)
  }

  return (
    <div className="space-y-6">
      <h2 className="text-2xl font-bold">Apps</h2>

      {/* Installer not deployed warning */}
      {!ready && (
        <div className="card border-yellow-600/50 bg-yellow-500/5">
          <p className="text-sm text-yellow-300 font-semibold">⚠️ App installer not enabled on this server yet</p>
          <p className="text-sm text-slate-400 mt-1">
            Installs run through one whitelisted root script (the panel can't run arbitrary
            commands as root). Deploy it once, then installs will work:
          </p>
          <pre className="mt-2 bg-black text-slate-300 text-xs p-2 rounded">cd /opt/serverhub-src && sudo bash deploy/update.sh</pre>
        </div>
      )}

      {/* Live install output */}
      {installWs && (
        <div className="card">
          <h3 className="font-semibold mb-2">Installing…</h3>
          <LiveLog path={installWs} onClose={refresh} />
        </div>
      )}

      {/* Installed apps */}
      <div>
        <h3 className="text-lg font-semibold mb-3">Installed</h3>
        {installed.length === 0 ? (
          <div className="card text-center py-8 text-slate-600">
            No apps installed yet — install one from the catalog below.
          </div>
        ) : (
          <div className="grid md:grid-cols-2 xl:grid-cols-3 gap-4">
            {installed.map((app) => (
              <InstalledApp key={app.id} app={app} onChanged={refresh} />
            ))}
          </div>
        )}
      </div>

      {/* Catalog */}
      <div>
        <h3 className="text-lg font-semibold mb-3">Catalog</h3>
        <div className="grid md:grid-cols-2 xl:grid-cols-3 gap-4">
          {catalog.map((c) => (
            <div key={c.slug} className="card">
              <div className="flex items-start gap-3">
                <span className="text-2xl">{c.icon}</span>
                <div className="min-w-0">
                  <p className="font-semibold">{c.name}</p>
                  <p className="text-xs text-slate-500">{c.description}</p>
                </div>
              </div>
              <div className="mt-3 flex items-center gap-2">
                <span className="text-xs text-slate-600">
                  {c.kind === 'service' ? 'runs on a port' : 'tool / dependency'}
                </span>
                {c.installed ? (
                  <span className="badge bg-green-500/15 text-green-400 ml-auto">installed</span>
                ) : (
                  <button className="btn-primary ml-auto" onClick={() => install(c.slug)}>
                    ⬇ Install
                  </button>
                )}
              </div>
            </div>
          ))}
        </div>
      </div>
    </div>
  )
}

/** One installed app: status, controls, domain/SSL, password, logs, uninstall. */
function InstalledApp({ app, onChanged }) {
  const [domain, setDomain] = useState(app.domain || '')
  const [showLog, setShowLog] = useState(false)
  const [msg, setMsg] = useState('')

  const liveUrl = app.domain
    ? `http://${app.domain}`
    : `http://${window.location.hostname}:${app.port}`

  async function action(name) {
    setMsg('')
    try {
      const res = await api.post(`/apps/${app.id}/${name}`)
      setMsg(res.data.detail)
      onChanged()
    } catch (err) {
      setMsg(errorMessage(err))
    }
  }

  async function assignDomain() {
    setMsg('')
    try {
      const res = await api.post(`/apps/${app.id}/assign-domain`, { domain })
      setMsg(res.data.detail)
      onChanged()
    } catch (err) {
      setMsg(errorMessage(err))
    }
  }

  async function requestSsl() {
    setMsg('')
    try {
      const res = await api.post(`/apps/${app.id}/ssl`)
      setMsg(res.data.detail)
    } catch (err) {
      setMsg(errorMessage(err))
    }
  }

  async function uninstall() {
    if (!window.confirm(`Remove ${app.name} from the panel? (the installed program stays on disk)`)) return
    try {
      await api.delete(`/apps/${app.id}`)
      onChanged()
    } catch (err) {
      alert(errorMessage(err))
    }
  }

  const isService = app.kind === 'service'

  return (
    <div className="card">
      <div className="flex items-start justify-between gap-2">
        <div className="flex items-center gap-2 min-w-0">
          <span className="text-xl">{app.icon}</span>
          <span className="font-semibold truncate">{app.name}</span>
        </div>
        {isService && <StatusBadge status={app.status} />}
      </div>

      {isService ? (
        <>
          <dl className="mt-3 space-y-1.5 text-sm">
            <div className="flex justify-between">
              <dt className="text-slate-500">URL</dt>
              <dd>
                <a href={liveUrl} target="_blank" rel="noreferrer" className="text-sky-400 hover:underline">
                  {app.domain || `:${app.port}`} ↗
                </a>
              </dd>
            </div>
            {app.secret && (
              <div className="flex justify-between">
                <dt className="text-slate-500">Password</dt>
                <dd className="font-mono text-yellow-400">{app.secret}</dd>
              </div>
            )}
          </dl>

          <div className="mt-3 flex flex-wrap gap-2">
            <button className="btn-secondary" onClick={() => action('start')}>▶ Start</button>
            <button className="btn-secondary" onClick={() => action('stop')}>⏹ Stop</button>
            <button className="btn-secondary" onClick={() => action('restart')}>🔄 Restart</button>
            <button className="btn-secondary" onClick={() => setShowLog((v) => !v)}>📜 Logs</button>
          </div>

          <div className="mt-3 flex gap-2 items-center flex-wrap">
            <input className="input max-w-[12rem] py-1" placeholder="app.example.com"
              value={domain} onChange={(e) => setDomain(e.target.value)} />
            <button className="btn-secondary" onClick={assignDomain} disabled={!domain}>Domain</button>
            <button className="btn-secondary" onClick={requestSsl} disabled={!app.domain}>🔒 SSL</button>
          </div>

          {showLog && <LiveLog path={`/ws/logs/app/${app.slug}`} />}
        </>
      ) : (
        <p className="mt-3 text-sm text-slate-500">Installed tool — no web UI to run.</p>
      )}

      {msg && <p className="mt-2 text-xs text-slate-400 break-words">{msg}</p>}

      <div className="mt-3 text-right">
        <button onClick={uninstall} className="text-xs text-red-400 hover:underline">remove</button>
      </div>
    </div>
  )
}
