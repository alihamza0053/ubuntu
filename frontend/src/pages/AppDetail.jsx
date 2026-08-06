import { useCallback, useEffect, useState } from 'react'
import { Link, useParams, useSearchParams } from 'react-router-dom'
import api, { errorMessage } from '../api/client'
import LiveLog from '../components/LiveLog'
import StatusBadge from '../components/StatusBadge'
import { useAuth } from '../context/AuthContext'
import { appUrl } from '../lib/appUrl'

const TABS = [
  { key: 'overview', label: 'Overview' },
  { key: 'screen', label: 'Screen' },      // desktop apps only
  { key: 'domain', label: 'Domain & SSL' },
  { key: 'logs', label: 'Logs' },
]

function tabsFor(app) {
  return app.kind === 'desktop' ? TABS : TABS.filter((t) => t.key !== 'screen')
}

export default function AppDetail() {
  const { key } = useParams()
  const { isAdmin } = useAuth()
  const [searchParams, setSearchParams] = useSearchParams()
  const [app, setApp] = useState(null)
  const [msg, setMsg] = useState('')

  const refresh = useCallback(() => {
    api.get(`/apps/${key}`).then((res) => setApp(res.data)).catch(() => setApp(null))
  }, [key])

  useEffect(() => {
    refresh()
  }, [refresh])

  async function action(name) {
    setMsg('')
    try {
      const res = await api.post(`/apps/${key}/action/${name}`)
      setMsg(res.data.detail || `${name} ${key}`)
      refresh()
    } catch (err) {
      setMsg(errorMessage(err))
    }
  }

  async function uninstall() {
    const deleteData = window.confirm(
      `Remove ${app.label}?\n\nOK = also delete its data (browser profile / workflows)\n` +
      'Cancel = keep the data so a re-install picks up where you left off',
    )
    try {
      const res = await api.delete(`/apps/${key}`, { params: { delete_data: deleteData } })
      setMsg(res.data.detail)
      refresh()
    } catch (err) {
      setMsg(errorMessage(err))
    }
  }

  if (!app) return <p className="text-slate-500">Loading…</p>

  const installed = app.install_state === 'INSTALLED'
  const tab = searchParams.get('tab') || 'overview'
  const openUrl = appUrl(app)

  return (
    <div className="space-y-4">
      <div className="flex items-center gap-3 flex-wrap">
        <Link to="/apps" className="text-slate-500 hover:text-slate-300">←</Link>
        <span className="text-2xl">{app.icon}</span>
        <h2 className="text-2xl font-bold">{app.label}</h2>
        {installed && <StatusBadge status={app.status} />}
        {installed && app.status === 'RUNNING' && (
          <a href={openUrl} target="_blank" rel="noreferrer"
            className="text-sm text-sky-400 hover:underline">open ↗</a>
        )}
      </div>

      {!installed && (
        <div className="card text-slate-400">
          {app.install_state === 'INSTALLING'
            ? 'Installing right now — the Logs tab shows what the installer is doing.'
            : `${app.label} isn't installed on this server yet. Install it from the Apps page.`}
        </div>
      )}

      <div className="flex gap-1 border-b border-panel-border overflow-x-auto">
        {tabsFor(app).map((t) => (
          <button key={t.key} onClick={() => setSearchParams({ tab: t.key })}
            className={`px-4 py-2 text-sm whitespace-nowrap border-b-2 -mb-px ${
              tab === t.key ? 'border-sky-400 text-sky-300'
                : 'border-transparent text-slate-400 hover:text-slate-200'
            }`}>{t.label}</button>
        ))}
      </div>

      {msg && <p className="text-sm text-slate-300 break-words">{msg}</p>}

      {tab === 'overview' && (
        <OverviewTab app={app} installed={installed} isAdmin={isAdmin}
          openUrl={openUrl} onAction={action} onUninstall={uninstall}
          onChanged={refresh} setMsg={setMsg} />
      )}
      {tab === 'screen' && <ScreenTab app={app} openUrl={openUrl} />}
      {tab === 'domain' && <DomainTab app={app} onChanged={refresh} />}
      {tab === 'logs' && <LogsTab app={app} />}
    </div>
  )
}

function OverviewTab({ app, installed, isAdmin, openUrl, onAction, onUninstall,
                      onChanged, setMsg }) {
  return (
    <div className="space-y-4 max-w-2xl">
      <div className="card space-y-3">
        <div className="flex items-center justify-between flex-wrap gap-2">
          <h3 className="font-semibold">Service</h3>
          <div className="flex gap-2 flex-wrap">
            <button className="btn-primary" disabled={!installed}
              onClick={() => onAction('start')}>▶ Start</button>
            <button className="btn-secondary" disabled={!installed}
              onClick={() => onAction('stop')}>■ Stop</button>
            <button className="btn-secondary" disabled={!installed}
              onClick={() => onAction('restart')}>⟳ Restart</button>
          </div>
        </div>

        <dl className="space-y-2 text-sm">
          <div className="flex justify-between">
            <dt className="text-slate-500">Kind</dt>
            <dd>{app.kind === 'desktop' ? 'Browser on a virtual display (noVNC)' : 'Web service'}</dd>
          </div>
          <div className="flex justify-between">
            <dt className="text-slate-500">Port</dt><dd className="font-mono">{app.port ?? '—'}</dd>
          </div>
          {app.kind === 'desktop' && (
            <div className="flex justify-between">
              <dt className="text-slate-500">Display</dt>
              <dd className="font-mono">:{app.display ?? '—'}</dd>
            </div>
          )}
          <div className="flex justify-between">
            <dt className="text-slate-500">Domain</dt><dd>{app.domain || '—'}</dd>
          </div>
          <div className="flex justify-between items-center">
            <dt className="text-slate-500">URL</dt>
            <dd>
              {installed
                ? <a className="text-sky-400 hover:underline break-all" href={openUrl}
                    target="_blank" rel="noreferrer">{openUrl}</a>
                : '—'}
            </dd>
          </div>
        </dl>

        <p className="text-xs text-slate-500">{app.notes}</p>
      </div>

      {app.kind === 'desktop' && installed && (
        <BrowserSettings app={app} onChanged={onChanged} setMsg={setMsg} />
      )}

      {isAdmin && installed && (
        <div className="card space-y-2">
          <h3 className="font-semibold text-red-400">Remove</h3>
          <p className="text-xs text-slate-500">
            Stops {app.label}, removes its nginx block and uninstalls the packages.
            You choose whether its data goes too.
          </p>
          <button className="btn-secondary text-red-400" onClick={onUninstall}>
            🗑 Uninstall {app.label}
          </button>
        </div>
      )}
    </div>
  )
}

/** Start page + noVNC password for a browser app. */
function BrowserSettings({ app, onChanged, setMsg }) {
  const [startUrl, setStartUrl] = useState(app.start_url || '')
  const [password, setPassword] = useState(app.vnc_password || '')
  const [busy, setBusy] = useState(false)

  async function save() {
    setBusy(true); setMsg('')
    try {
      const res = await api.put(`/apps/${app.key}/settings`, {
        start_url: startUrl, vnc_password: password,
      })
      setMsg(res.data.detail)
      onChanged()
    } catch (err) { setMsg(errorMessage(err)) } finally { setBusy(false) }
  }

  return (
    <div className="card space-y-3">
      <h3 className="font-semibold">Browser settings</h3>
      <div>
        <label className="block text-sm text-slate-400 mb-1">Start page</label>
        <input className="input" value={startUrl} placeholder="https://example.com"
          onChange={(e) => setStartUrl(e.target.value)} />
      </div>
      <div>
        <label className="block text-sm text-slate-400 mb-1">noVNC password</label>
        <input className="input font-mono" value={password}
          onChange={(e) => setPassword(e.target.value)} />
        <p className="text-xs text-slate-500 mt-1">
          Typed into noVNC when you open the screen. 6–8 characters — x11vnc ignores
          anything past the eighth.
        </p>
      </div>
      <button className="btn-primary" onClick={save} disabled={busy}>Save</button>
      <p className="text-xs text-slate-500">Restart the app to apply.</p>
    </div>
  )
}

/** The browser's virtual screen, embedded via noVNC. */
function ScreenTab({ app, openUrl }) {
  if (app.install_state !== 'INSTALLED') {
    return <div className="card text-slate-500">Install {app.label} first.</div>
  }
  if (app.status !== 'RUNNING') {
    return (
      <div className="card text-slate-500">
        {app.label} isn&apos;t running — start it from the Overview tab, then come back.
      </div>
    )
  }
  // The panel is usually on https; an http frame inside it is blocked as mixed
  // content and would just render blank, so say what to do instead.
  const mixedContent = window.location.protocol === 'https:' && openUrl.startsWith('http:')

  return (
    <div className="space-y-2">
      <div className="flex items-center gap-3 flex-wrap text-xs text-slate-500">
        <span>Password: <code className="text-slate-300">{app.vnc_password}</code></span>
        <a href={openUrl} target="_blank" rel="noreferrer" className="text-sky-400 hover:underline">
          open in a full tab ↗
        </a>
      </div>

      {mixedContent ? (
        <div className="card text-sm text-slate-400 space-y-2">
          <p>
            This panel is on https and {app.label} is only reachable over plain http
            (<code className="text-slate-300">{openUrl}</code>), so your browser won&apos;t
            let it be embedded here.
          </p>
          <p className="text-xs">
            Assign a domain and request SSL on the Domain &amp; SSL tab and the screen
            appears here — or use &ldquo;open in a full tab&rdquo; above in the meantime.
          </p>
        </div>
      ) : (
        <>
          <div className="rounded-lg border border-panel-border overflow-hidden bg-black">
            <iframe title={`${app.label} screen`} src={openUrl}
              className="w-full h-[70vh]" allow="clipboard-read; clipboard-write" />
          </div>
          <p className="text-xs text-slate-500">
            Served straight from the app&apos;s own address, so the frame stays blank if
            that port is firewalled off from your machine — assigning a domain routes it
            through nginx on 80/443 instead.
          </p>
        </>
      )}
    </div>
  )
}

function DomainTab({ app, onChanged }) {
  const [domain, setDomain] = useState(app.domain || '')
  const [msg, setMsg] = useState('')
  const [busy, setBusy] = useState(false)

  async function assign() {
    setBusy(true); setMsg('')
    try {
      const res = await api.post(`/apps/${app.key}/assign-domain`, { domain })
      setMsg(res.data.detail)
      onChanged()
    } catch (err) { setMsg(errorMessage(err)) } finally { setBusy(false) }
  }

  async function ssl() {
    setBusy(true); setMsg('')
    try {
      const res = await api.post(`/apps/${app.key}/ssl`)
      setMsg(res.data.detail)
      onChanged()
    } catch (err) { setMsg(errorMessage(err)) } finally { setBusy(false) }
  }

  return (
    <div className="card max-w-xl space-y-3">
      <h3 className="font-semibold">Domain &amp; SSL</h3>
      <div className="flex gap-2 items-center flex-wrap">
        <input className="input max-w-xs" placeholder="n8n.example.com" value={domain}
          onChange={(e) => setDomain(e.target.value)} />
        <button className="btn-primary" onClick={assign} disabled={busy || !domain}>
          Assign domain
        </button>
        <button className="btn-secondary" onClick={ssl} disabled={busy || !app.domain}>
          🔒 Request SSL
        </button>
      </div>
      <p className="text-xs text-slate-500">
        Assigning writes a websocket-capable nginx proxy to 127.0.0.1:{app.port} and reloads
        nginx. SSL runs certbot for the domain (DNS must already point at this server).
        {app.key === 'n8n' && ' n8n is restarted on both, because it builds its webhook URLs from this address.'}
      </p>
      {msg && <p className="text-sm text-slate-300 break-words">{msg}</p>}
    </div>
  )
}

function LogsTab({ app }) {
  const [source, setSource] = useState('app')
  return (
    <div className="card space-y-2">
      <div className="flex items-center gap-2">
        <h3 className="font-semibold">Logs</h3>
        <select className="input max-w-[12rem]" value={source}
          onChange={(e) => setSource(e.target.value)}>
          <option value="app">Running app</option>
          <option value="install">Installer</option>
        </select>
      </div>
      <LiveLog path={`/ws/apps/${app.key}/logs?source=${source}`} />
    </div>
  )
}
