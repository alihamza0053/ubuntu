import { useCallback, useEffect, useMemo, useState } from 'react'
import api, { errorMessage } from '../api/client'
import LiveLog from '../components/LiveLog'
import StatusBadge from '../components/StatusBadge'
import { useAuth } from '../context/AuthContext'

const CATEGORY_ORDER = [
  'Infrastructure', 'Database UIs', 'Developer', 'CMS & CRM', 'Files & Sync',
  'Media & Library', 'Productivity', 'Utilities', 'Monitoring', 'Notifications',
  'Browsers & Misc', 'Other',
]

/**
 * Apps section: one-click install of self-hosted apps (VS Code/code-server,
 * File Browser, …), run them on a port, assign a domain, and manage them.
 */
export default function Apps() {
  const [catalog, setCatalog] = useState([])
  const [ready, setReady] = useState(true)
  const [dockerReady, setDockerReady] = useState(true)
  const [installed, setInstalled] = useState([])
  const [installWs, setInstallWs] = useState(null) // WS path during an install
  const [query, setQuery] = useState('')
  const [showCustom, setShowCustom] = useState(false)
  const [custom, setCustom] = useState({ name: '', image: '', container_port: '', env: '' })

  const refresh = useCallback(() => {
    api.get('/apps/catalog').then((res) => {
      setCatalog(res.data.apps || [])
      setReady(res.data.installer_ready !== false)
      setDockerReady(res.data.docker_ready !== false)
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

  function install(app) {
    let path = `/ws/apps/${app.slug}/install`
    if (app.multi) {
      const name = window.prompt(
        `Name this ${app.name} instance (e.g. a site/client name):`, '')
      if (name === null) return            // cancelled
      if (name.trim()) path += `?name=${encodeURIComponent(name.trim())}`
    }
    setInstallWs(null)
    setTimeout(() => setInstallWs(path), 0)
  }

  function runCustom(e) {
    e.preventDefault()
    if (!custom.image.trim() || !custom.container_port) {
      alert('Image and container port are required')
      return
    }
    const qs = new URLSearchParams({
      name: custom.name.trim(),
      image: custom.image.trim(),
      container_port: String(custom.container_port),
      env: custom.env,
    })
    setInstallWs(null)
    setTimeout(() => setInstallWs(`/ws/apps/custom/install?${qs.toString()}`), 0)
  }

  // Group catalog by category (filtered by the search query) in defined order
  const grouped = useMemo(() => {
    const q = query.trim().toLowerCase()
    const match = (c) => !q || `${c.name} ${c.description} ${c.slug} ${c.category}`.toLowerCase().includes(q)
    const byCat = {}
    for (const c of catalog) if (match(c)) (byCat[c.category || 'Other'] ||= []).push(c)
    return CATEGORY_ORDER
      .filter((cat) => byCat[cat]?.length)
      .map((cat) => [cat, byCat[cat]])
  }, [catalog, query])

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

      {/* Run any Docker Hub image */}
      <div className="card">
        <div className="flex items-center justify-between gap-2">
          <div>
            <h3 className="font-semibold">🐳 Run any Docker image</h3>
            <p className="text-xs text-slate-500">
              Pull any Docker Hub image and run it on a port (you can run several).
              Needs the Docker Engine app.
            </p>
          </div>
          <button className="btn-secondary" onClick={() => setShowCustom((v) => !v)}>
            {showCustom ? 'Close' : '＋ New container'}
          </button>
        </div>
        {showCustom && (
          <form onSubmit={runCustom} className="mt-3 grid sm:grid-cols-2 gap-3">
            <div>
              <label className="block text-xs text-slate-400 mb-1">Image *</label>
              <input className="input font-mono" placeholder="e.g. nginx:latest or user/app:tag"
                value={custom.image} onChange={(e) => setCustom({ ...custom, image: e.target.value })} required />
            </div>
            <div>
              <label className="block text-xs text-slate-400 mb-1">Container port *</label>
              <input className="input" type="number" placeholder="e.g. 80"
                value={custom.container_port} onChange={(e) => setCustom({ ...custom, container_port: e.target.value })} required />
            </div>
            <div>
              <label className="block text-xs text-slate-400 mb-1">Name (optional)</label>
              <input className="input" placeholder="my-app"
                value={custom.name} onChange={(e) => setCustom({ ...custom, name: e.target.value })} />
            </div>
            <div className="sm:col-span-2">
              <label className="block text-xs text-slate-400 mb-1">Environment variables (optional, one KEY=value per line)</label>
              <textarea className="input font-mono text-sm h-20" placeholder={'TZ=UTC\nFOO=bar'}
                value={custom.env} onChange={(e) => setCustom({ ...custom, env: e.target.value })} />
            </div>
            <div className="sm:col-span-2 flex items-center gap-2">
              <button type="submit" className="btn-primary" disabled={!dockerReady}>⬇ Pull &amp; run</button>
              {!dockerReady && <span className="text-xs text-yellow-500">Install the Docker Engine app first</span>}
              <span className="text-xs text-slate-600">
                The container’s port is proxied to localhost; assign a domain after it’s running.
              </span>
            </div>
          </form>
        )}
      </div>

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

      {/* Catalog grouped by category */}
      <div>
        <div className="flex items-center gap-3 mb-3 flex-wrap">
          <h3 className="text-lg font-semibold">Catalog</h3>
          <input
            className="input max-w-xs ml-auto"
            placeholder="🔎 Search apps…"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
          />
        </div>
        {grouped.length === 0 && (
          <p className="text-slate-600 text-sm">No apps match “{query}”.</p>
        )}
        {grouped.map(([category, apps]) => (
          <div key={category} className="mb-6">
            <p className="text-sm font-semibold text-slate-400 mb-2">{category}</p>
            <div className="grid md:grid-cols-2 xl:grid-cols-3 gap-4">
              {apps.map((c) => (
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
                      {c.kind === 'tool' ? 'tool / dependency'
                        : c.kind === 'docker' ? (c.web_ui === false ? '🐳 backend' : '🐳 docker')
                        : c.kind === 'compose' ? '🐳 compose stack'
                        : 'runs on a port'}
                    </span>
                    {c.installed ? (
                      <span className="badge bg-green-500/15 text-green-400 ml-auto">installed</span>
                    ) : (c.kind === 'docker' || c.kind === 'compose') && !dockerReady ? (
                      <span className="text-xs text-yellow-500 ml-auto" title="Install the Docker Engine app first">
                        needs Docker
                      </span>
                    ) : (
                      <button className="btn-primary ml-auto" onClick={() => install(c)}>
                        {c.multi ? '⬇ Install instance' : '⬇ Install'}
                      </button>
                    )}
                  </div>
                </div>
              ))}
            </div>
          </div>
        ))}
      </div>
    </div>
  )
}

/** One installed app: status, controls, domain/SSL, password, logs, uninstall. */
function InstalledApp({ app, onChanged }) {
  const { isAdmin } = useAuth()
  const [domain, setDomain] = useState(app.domain || '')
  const [showLog, setShowLog] = useState(false)
  const [msg, setMsg] = useState('')
  const [reveal, setReveal] = useState(false)
  const [newPw, setNewPw] = useState('')
  const [showPwForm, setShowPwForm] = useState(false)
  const [creds, setCreds] = useState(null) // full credential list when opened

  async function toggleCreds() {
    if (creds) { setCreds(null); return }
    try {
      const res = await api.get(`/apps/${app.id}/credentials`)
      setCreds(res.data.items)
    } catch (err) {
      alert(errorMessage(err))
    }
  }

  async function setPassword() {
    setMsg('')
    try {
      const res = await api.post(`/apps/${app.id}/set-password`, { password: newPw })
      setMsg(res.data.detail)
      setNewPw('')
      setShowPwForm(false)
      onChanged()
    } catch (err) {
      setMsg(errorMessage(err))
    }
  }

  async function generatePw() {
    try {
      const res = await api.get('/apps/generate-password')
      setNewPw(res.data.password)
    } catch (err) {
      alert(errorMessage(err))
    }
  }

  const liveUrl = app.domain
    ? `http://${app.domain}`
    : `http://${window.location.hostname}:${app.port}`

  async function action(name) {
    setMsg('')
    try {
      const res = await api.post(`/apps/${app.id}/action/${name}`)
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

  async function toggleHidden() {
    try {
      await api.put(`/apps/${app.id}/hidden`, { hidden: !app.hidden })
      onChanged()
    } catch (err) {
      alert(errorMessage(err))
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

  const isRunnable = app.kind !== 'tool'

  return (
    <div className="card">
      <div className="flex items-start justify-between gap-2">
        <div className="flex items-center gap-2 min-w-0">
          <span className="text-xl">{app.icon}</span>
          <span className="font-semibold truncate">{app.name}</span>
        </div>
        <span className="flex items-center gap-1.5">
          {app.hidden && (
            <span className="badge bg-slate-500/15 text-slate-400" title="Only admins can see this app">
              🙈 hidden
            </span>
          )}
          {isRunnable && <StatusBadge status={app.status} />}
        </span>
      </div>

      {isRunnable ? (
        <>
          <dl className="mt-3 space-y-1.5 text-sm">
            <div className="flex justify-between gap-2">
              <dt className="text-slate-500">{app.web_ui === false ? 'Port' : 'URL'}</dt>
              <dd className="text-right">
                {app.web_ui === false ? (
                  <span className="font-mono text-slate-300" title="Backend service — connect other apps to this port">
                    127.0.0.1:{app.port} <span className="text-xs text-slate-600">(backend)</span>
                  </span>
                ) : app.domain ? (
                  <a href={liveUrl} target="_blank" rel="noreferrer" className="text-sky-400 hover:underline">
                    {app.domain} ↗
                  </a>
                ) : (
                  <span className="text-slate-400" title="Port is localhost-only — assign a domain to reach it">
                    :{app.port} <span className="text-xs text-slate-600">(internal — assign a domain)</span>
                  </span>
                )}
              </dd>
            </div>
            {app.username && (
              <div className="flex justify-between">
                <dt className="text-slate-500">Username</dt>
                <dd className="font-mono text-slate-200">{app.username}</dd>
              </div>
            )}
            {(app.secret || app.can_set_password) && (
              <div className="flex justify-between gap-2">
                <dt className="text-slate-500">{app.secret_label || 'Password'}</dt>
                <dd className="font-mono text-yellow-400 flex items-center gap-2">
                  {app.secret
                    ? (reveal ? app.secret : '••••••••')
                    : <span className="text-slate-500">not set</span>}
                  {app.secret && (
                    <button className="text-xs text-slate-500 hover:text-slate-300"
                      onClick={() => setReveal((v) => !v)}>{reveal ? 'hide' : 'show'}</button>
                  )}
                </dd>
              </div>
            )}
          </dl>

          {app.can_set_password && (
            <div className="mt-2">
              {showPwForm ? (
                <div className="flex gap-2 items-center flex-wrap">
                  <input className="input py-1 max-w-[14rem] font-mono" placeholder="new password"
                    value={newPw} onChange={(e) => setNewPw(e.target.value)} />
                  <button className="btn-secondary" onClick={generatePw} title="Generate a strong password">🎲 Generate</button>
                  <button className="btn-primary" onClick={setPassword} disabled={newPw.length < 4}>Set</button>
                  <button className="btn-secondary" onClick={() => { setShowPwForm(false); setNewPw('') }}>Cancel</button>
                </div>
              ) : (
                <button className="text-xs text-sky-400 hover:underline" onClick={() => setShowPwForm(true)}>
                  ✎ change {(app.secret_label || 'password').toLowerCase()}
                </button>
              )}
            </div>
          )}

          <div className="mt-3 flex flex-wrap gap-2">
            <button className="btn-secondary" onClick={() => action('start')}>▶ Start</button>
            <button className="btn-secondary" onClick={() => action('stop')}>⏹ Stop</button>
            <button className="btn-secondary" onClick={() => action('restart')}>🔄 Restart</button>
            <button className="btn-secondary" onClick={() => setShowLog((v) => !v)}>📜 Logs</button>
            {app.has_credentials && (
              <button className="btn-secondary" onClick={toggleCreds}>🔑 Credentials</button>
            )}
          </div>

          {creds && (
            <div className="mt-3 rounded-lg border border-panel-border bg-slate-900 p-3 space-y-1.5">
              <p className="text-xs text-slate-500 mb-1">All credentials (from the stack's config)</p>
              {creds.map((c) => (
                <div key={c.label} className="flex items-start justify-between gap-3 text-xs">
                  <span className="text-slate-400 shrink-0">{c.label}</span>
                  <span className="font-mono text-yellow-300 break-all text-right flex items-center gap-1">
                    {c.value || <span className="text-slate-600">—</span>}
                    {c.value && (
                      <button className="text-slate-500 hover:text-slate-200"
                        onClick={() => navigator.clipboard?.writeText(c.value)} title="Copy">⧉</button>
                    )}
                  </span>
                </div>
              ))}
            </div>
          )}

          {app.web_ui !== false && (
            <div className="mt-3 flex gap-2 items-center flex-wrap">
              <input className="input max-w-[12rem] py-1" placeholder="app.example.com"
                value={domain} onChange={(e) => setDomain(e.target.value)} />
              <button className="btn-secondary" onClick={assignDomain} disabled={!domain}>Domain</button>
              <button className="btn-secondary" onClick={requestSsl} disabled={!app.domain}>🔒 SSL</button>
            </div>
          )}

          {showLog && <LiveLog path={`/ws/apps/${app.id}/logs`} />}
        </>
      ) : app.slug === 'onedrive' ? (
        <OneDriveSetup />
      ) : (
        <p className="mt-3 text-sm text-slate-500">Installed tool — no web UI to run.</p>
      )}

      {msg && <p className="mt-2 text-xs text-slate-400 break-words">{msg}</p>}

      <div className="mt-3 flex justify-end gap-3">
        {isAdmin && (
          <button onClick={toggleHidden} className="text-xs text-slate-400 hover:underline"
            title={app.hidden ? 'Hidden from non-admins — click to unhide' : 'Hide from non-admins'}>
            {app.hidden ? '🙈 unhide' : '👁 hide'}
          </button>
        )}
        <button onClick={uninstall} className="text-xs text-red-400 hover:underline">remove</button>
      </div>
    </div>
  )
}

/**
 * OneDrive setup: authorize a Microsoft account, then start/stop the read-only
 * sync monitor. Files appear under /srv/onedrive and in each project's
 * OneDrive tab (where a folder is mapped per project).
 */
function OneDriveSetup() {
  const [status, setStatus] = useState(null) // { installed, authorized, monitor, sync_dir }
  const [authUrl, setAuthUrl] = useState('')
  const [responseUrl, setResponseUrl] = useState('')
  const [msg, setMsg] = useState('')
  const [busy, setBusy] = useState(false)

  const refresh = useCallback(() => {
    api.get('/onedrive/status').then((r) => setStatus(r.data)).catch(() => {})
  }, [])

  useEffect(() => { refresh() }, [refresh])

  async function startAuth() {
    setMsg(''); setBusy(true)
    try {
      const r = await api.post('/onedrive/auth/start')
      setAuthUrl(r.data.auth_url)
    } catch (err) {
      setMsg(errorMessage(err))
    } finally {
      setBusy(false)
    }
  }

  async function completeAuth() {
    setMsg(''); setBusy(true)
    try {
      const r = await api.post('/onedrive/auth/complete', { response_url: responseUrl })
      setMsg(r.data.detail)
      setAuthUrl(''); setResponseUrl('')
      refresh()
    } catch (err) {
      setMsg(errorMessage(err))
    } finally {
      setBusy(false)
    }
  }

  async function monitor(action) {
    setMsg('')
    try {
      const r = await api.post(`/onedrive/monitor/${action}`)
      setMsg(r.data.detail)
      setTimeout(refresh, 1200)
    } catch (err) {
      setMsg(errorMessage(err))
    }
  }

  async function resync() {
    if (!window.confirm('Full resync re-checks the whole drive and pulls shared '
      + 'items. This can take a while. Continue?')) return
    setMsg('')
    try {
      const r = await api.post('/onedrive/resync')
      setMsg(r.data.detail)
      setTimeout(refresh, 1500)
    } catch (err) {
      setMsg(errorMessage(err))
    }
  }

  if (!status) return <p className="mt-3 text-sm text-slate-500">Loading…</p>

  return (
    <div className="mt-3 space-y-3">
      <dl className="space-y-1.5 text-sm">
        <div className="flex justify-between">
          <dt className="text-slate-500">Authorized</dt>
          <dd className={status.authorized ? 'text-green-400' : 'text-yellow-400'}>
            {status.authorized ? 'yes' : 'not yet'}
          </dd>
        </div>
        <div className="flex justify-between">
          <dt className="text-slate-500">Sync monitor</dt>
          <dd className="text-slate-200">{status.monitor}</dd>
        </div>
        <div className="flex justify-between gap-2">
          <dt className="text-slate-500">Folder</dt>
          <dd className="font-mono text-slate-300">{status.sync_dir}</dd>
        </div>
      </dl>

      {!status.authorized ? (
        <div className="space-y-2">
          {!authUrl ? (
            <button className="btn-primary" disabled={busy} onClick={startAuth}>
              {busy ? 'Starting…' : '🔑 Authorize OneDrive'}
            </button>
          ) : (
            <div className="space-y-2 rounded-lg border border-panel-border bg-slate-900 p-3">
              <p className="text-xs text-slate-400">
                1. Open this URL, sign in, and approve access:
              </p>
              <a href={authUrl} target="_blank" rel="noreferrer"
                 className="text-sky-400 hover:underline text-xs break-all block">
                {authUrl} ↗
              </a>
              <p className="text-xs text-slate-400">
                2. After approving, your browser lands on a blank page. Copy that page’s
                full URL from the address bar and paste it here:
              </p>
              <input
                className="input w-full font-mono text-xs"
                placeholder="https://login.microsoftonline.com/.../nativeclient?code=…"
                value={responseUrl}
                onChange={(e) => setResponseUrl(e.target.value)}
              />
              <button className="btn-primary" disabled={busy || !responseUrl} onClick={completeAuth}>
                {busy ? 'Finishing…' : '✓ Finish & start syncing'}
              </button>
            </div>
          )}
        </div>
      ) : (
        <div className="space-y-2">
          <div className="flex flex-wrap gap-2">
            <button className="btn-secondary" onClick={() => monitor('start')}>▶ Start</button>
            <button className="btn-secondary" onClick={() => monitor('stop')}>⏹ Stop</button>
            <button className="btn-secondary" onClick={() => monitor('restart')}>🔄 Sync now</button>
            <button className="btn-secondary" disabled={status.resyncing} onClick={resync}>
              {status.resyncing ? '⏳ Resyncing…' : '⬇ Pull shared items (resync)'}
            </button>
          </div>
          <p className="text-xs text-slate-500">
            Files others shared with you (Work/School) only appear after a one-time
            <b> resync</b>.
          </p>
        </div>
      )}

      {msg && <p className="text-xs text-slate-400 break-words">{msg}</p>}
    </div>
  )
}
