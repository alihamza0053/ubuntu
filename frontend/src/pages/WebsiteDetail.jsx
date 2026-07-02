import { useCallback, useEffect, useRef, useState } from 'react'
import { Link, useParams, useSearchParams } from 'react-router-dom'
import api, { errorMessage } from '../api/client'
import EditorModal from '../components/EditorModal'
import LiveLog from '../components/LiveLog'
import StatusBadge from '../components/StatusBadge'

const BASE_TABS = [
  { key: 'overview', label: 'Overview' },
  { key: 'files', label: 'Files' },
  { key: 'database', label: 'Database' },
  { key: 'domain', label: 'Domain & SSL' },
]

// Python apps get a "Run" tab (between Files and Database).
function tabsFor(type) {
  if (type !== 'python') return BASE_TABS
  return [
    BASE_TABS[0], BASE_TABS[1],
    { key: 'run', label: 'Run' },
    BASE_TABS[2], BASE_TABS[3],
  ]
}

function formatSize(bytes) {
  if (bytes < 1024) return `${bytes} B`
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`
  return `${(bytes / 1024 / 1024).toFixed(1)} MB`
}

export default function WebsiteDetail() {
  const { id } = useParams()
  const [searchParams, setSearchParams] = useSearchParams()
  const tab = searchParams.get('tab') || 'overview'

  const [site, setSite] = useState(null)
  const [files, setFiles] = useState([])
  const [editorPath, setEditorPath] = useState(null)
  const uploadRef = useRef(null)
  const [uploadMsg, setUploadMsg] = useState('')

  const refresh = useCallback(() => {
    api.get(`/websites/${id}`).then((res) => setSite(res.data))
    api.get(`/websites/${id}/files`).then((res) => setFiles(res.data)).catch(() => setFiles([]))
  }, [id])

  useEffect(() => {
    refresh()
  }, [refresh])

  async function uploadZip(file, build) {
    if (!file) return
    setUploadMsg('Uploading…')
    const form = new FormData()
    form.append('file', file)
    try {
      const res = await api.post(`/websites/${id}/upload`, form, {
        params: { build, replace: true },
      })
      setUploadMsg(res.data.detail + (res.data.build_output ? `\n${res.data.build_output}` : ''))
      refresh()
    } catch (err) {
      setUploadMsg(errorMessage(err))
    }
  }

  if (!site) return <p className="text-slate-500">Loading…</p>

  const liveUrl = site.domain ? `http://${site.domain}` : null
  const editableFile = (name) => /\.(html?|css|js|jsx|ts|tsx|php|json|md|txt|xml|env|sql)$/i.test(name)
  const sitePath = (name) => `${site.folder_path}/${name.replace(/\/$/, '')}`

  return (
    <div className="space-y-4">
      <div className="flex items-center gap-3 flex-wrap">
        <Link to="/websites" className="text-slate-500 hover:text-slate-300">←</Link>
        <h2 className="text-2xl font-bold">{site.name}</h2>
        <span className="badge bg-slate-500/20 text-slate-300">{site.type.toUpperCase()}</span>
        {liveUrl && <a href={liveUrl} target="_blank" rel="noreferrer" className="text-sm text-sky-400 hover:underline">{site.domain} ↗</a>}
      </div>

      <div className="flex gap-1 border-b border-panel-border overflow-x-auto">
        {tabsFor(site.type).map((t) => (
          <button key={t.key} onClick={() => setSearchParams({ tab: t.key })}
            className={`px-4 py-2 text-sm whitespace-nowrap border-b-2 -mb-px ${
              tab === t.key ? 'border-sky-400 text-sky-300' : 'border-transparent text-slate-400 hover:text-slate-200'
            }`}>{t.label}</button>
        ))}
      </div>

      {/* Overview */}
      {tab === 'overview' && (
        <div className="card max-w-xl">
          <h3 className="font-semibold mb-3">Website Info</h3>
          <dl className="space-y-2 text-sm">
            <div className="flex justify-between"><dt className="text-slate-500">Type</dt><dd>{site.type}</dd></div>
            <div className="flex justify-between"><dt className="text-slate-500">Folder</dt><dd className="font-mono break-all">{site.folder_path}</dd></div>
            <div className="flex justify-between"><dt className="text-slate-500">Domain</dt><dd>{site.domain || '—'}</dd></div>
            <div className="flex justify-between"><dt className="text-slate-500">Database</dt><dd>{site.db_name || '—'}</dd></div>
            {site.type === 'python' && (
              <>
                <div className="flex justify-between"><dt className="text-slate-500">Port</dt><dd className="font-mono">127.0.0.1:{site.port}</dd></div>
                <div className="flex justify-between items-center"><dt className="text-slate-500">Status</dt><dd><StatusBadge status={site.status} /></dd></div>
              </>
            )}
          </dl>
        </div>
      )}

      {/* Run (python apps) */}
      {tab === 'run' && <RunTab site={site} onChanged={refresh} />}

      {/* Files */}
      {tab === 'files' && (
        <div className="space-y-4">
          <div className="card">
            <div className="flex items-center gap-2 flex-wrap">
              <h3 className="font-semibold">Deploy</h3>
              <button className="btn-primary" onClick={() => uploadRef.current?.click()}>⬆ Upload .zip</button>
              {site.type === 'react' && (
                <button className="btn-secondary" onClick={() => {
                  const f = uploadRef.current?.files?.[0]
                  if (f) uploadZip(f, true)
                  else alert('Pick a zip first via Upload')
                }}>⬆ Upload + npm build</button>
              )}
              <input ref={uploadRef} type="file" accept=".zip" className="hidden"
                onChange={(e) => { uploadZip(e.target.files[0], false); e.target.value = '' }} />
              <span className="text-xs text-slate-500">
                Upload a .zip — it replaces the folder contents{site.type === 'react' ? ' (then builds to dist/)' : ''}.
              </span>
            </div>
            {uploadMsg && <pre className="mt-3 bg-black text-slate-300 text-xs p-3 rounded-lg max-h-48 overflow-auto whitespace-pre-wrap">{uploadMsg}</pre>}
          </div>

          <div className="card">
            <h3 className="font-semibold mb-2">Files</h3>
            <table className="w-full text-sm">
              <tbody className="divide-y divide-panel-border">
                {files.map((f) => (
                  <tr key={f.name}>
                    <td className="py-2">
                      {editableFile(f.name)
                        ? <button className="text-sky-400 hover:underline" onClick={() => setEditorPath(sitePath(f.name))}>📝 {f.name}</button>
                        : <span>{f.name.endsWith('/') ? '📁' : '📄'} {f.name}</span>}
                    </td>
                    <td className="text-right text-xs text-slate-500">{f.name.endsWith('/') ? '' : formatSize(f.size)}</td>
                  </tr>
                ))}
                {files.length === 0 && <tr><td className="py-6 text-center text-slate-600">empty — upload a zip</td></tr>}
              </tbody>
            </table>
            <p className="text-xs text-slate-600 mt-2">For full navigation/rename/move use the global File Manager.</p>
          </div>
        </div>
      )}

      {/* Database */}
      {tab === 'database' && <DatabaseTab site={site} onChanged={refresh} />}

      {/* Domain & SSL */}
      {tab === 'domain' && <DomainTab site={site} onChanged={refresh} />}

      <EditorModal path={editorPath} onClose={() => setEditorPath(null)} />
    </div>
  )
}

/** Link / change / unlink the website's MySQL database. */
function DatabaseTab({ site, onChanged }) {
  const [databases, setDatabases] = useState([])
  const [selected, setSelected] = useState(site.db_name || '')
  const [msg, setMsg] = useState('')
  const [busy, setBusy] = useState(false)

  useEffect(() => {
    api.get('/databases').then((res) => setDatabases(res.data)).catch(() => {})
  }, [])

  async function save() {
    setBusy(true); setMsg('')
    try {
      const res = await api.post(`/websites/${site.id}/link-database`, { db_name: selected })
      setMsg(res.data.detail)
      onChanged()
    } catch (err) {
      setMsg(errorMessage(err))
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="card max-w-xl space-y-3">
      <h3 className="font-semibold">Linked Database</h3>

      <p className="text-sm text-slate-400">
        Current: {site.db_name
          ? <span className="font-mono text-sky-300">{site.db_name}</span>
          : <span className="text-slate-500">none</span>}
      </p>

      <div>
        <label className="block text-sm text-slate-400 mb-1">Select a database to link</label>
        <select className="input max-w-xs" value={selected} onChange={(e) => setSelected(e.target.value)}>
          <option value="">— none (unlink) —</option>
          {databases.map((d) => <option key={d.name} value={d.name}>{d.name}</option>)}
        </select>
      </div>

      <div className="flex items-center gap-2 flex-wrap">
        <button className="btn-primary" onClick={save} disabled={busy}>
          {busy ? 'Saving…' : 'Save link'}
        </button>
        <Link to="/databases" className="text-sm text-sky-400 hover:underline">
          Manage databases (create / import / query) →
        </Link>
      </div>

      {msg && <p className="text-sm text-slate-300">{msg}</p>}
      {databases.length === 0 && (
        <p className="text-xs text-slate-500">
          No databases exist yet — create one on the Databases page, then link it here.
        </p>
      )}
    </div>
  )
}

/** Python web-service controls: deps, run command, start/stop, logs. */
function RunTab({ site, onChanged }) {
  const [cmd, setCmd] = useState(site.run_command || '')
  const [msg, setMsg] = useState('')
  const [setupWs, setSetupWs] = useState(null)
  const [showAppLogs, setShowAppLogs] = useState(false)

  async function saveCmd() {
    setMsg('')
    try {
      const r = await api.put(`/websites/${site.id}/run-command`, { run_command: cmd })
      setMsg(r.data.detail)
      onChanged()
    } catch (err) { setMsg(errorMessage(err)) }
  }

  async function installDeps() {
    setMsg('')
    try {
      const r = await api.post(`/websites/${site.id}/install-deps`)
      setMsg(r.data.detail)
      setSetupWs(null)
      setTimeout(() => setSetupWs(`/ws/websites/${site.id}/logs?source=setup`), 0)
      onChanged()
    } catch (err) { setMsg(errorMessage(err)) }
  }

  async function action(name) {
    setMsg('')
    try {
      const r = await api.post(`/websites/${site.id}/action/${name}`)
      setMsg(r.data.detail)
      onChanged()
    } catch (err) { setMsg(errorMessage(err)) }
  }

  const envBadge = {
    READY: 'bg-green-500/15 text-green-400',
    BUILDING: 'bg-yellow-500/15 text-yellow-400',
    MISSING: 'bg-slate-500/15 text-slate-400',
  }[site.env_status] || 'bg-slate-500/15 text-slate-400'

  return (
    <div className="space-y-4 max-w-2xl">
      <div className="card space-y-3">
        <div className="flex items-center justify-between flex-wrap gap-2">
          <h3 className="font-semibold">Service</h3>
          <div className="flex items-center gap-2">
            <span className={`badge ${envBadge}`}>deps: {site.env_status || 'MISSING'}</span>
            <StatusBadge status={site.status} />
          </div>
        </div>
        <p className="text-xs text-slate-500">
          Upload your app in the <b>Files</b> tab (a .zip with your code + requirements.txt),
          then install deps and start it. It runs on <span className="font-mono">127.0.0.1:{site.port}</span>;
          assign a domain to reach it.
        </p>
        <div className="flex flex-wrap gap-2">
          <button className="btn-secondary" onClick={installDeps}>📦 Install deps</button>
          <button className="btn-secondary" onClick={() => action('start')}>▶ Start</button>
          <button className="btn-secondary" onClick={() => action('stop')}>⏹ Stop</button>
          <button className="btn-secondary" onClick={() => action('restart')}>🔄 Restart</button>
          <button className="btn-secondary" onClick={() => setShowAppLogs((v) => !v)}>📜 Logs</button>
        </div>
        {setupWs && (
          <div>
            <p className="text-xs text-slate-500 mb-1">Dependency install</p>
            <LiveLog path={setupWs} />
          </div>
        )}
        {showAppLogs && (
          <div>
            <p className="text-xs text-slate-500 mb-1">App logs</p>
            <LiveLog path={`/ws/websites/${site.id}/logs?source=app`} />
          </div>
        )}
      </div>

      <div className="card space-y-2">
        <h3 className="font-semibold">Run command</h3>
        <p className="text-xs text-slate-500">
          Use <span className="font-mono">{'{port}'}</span> for the port. The app’s venv is on PATH,
          so <span className="font-mono">uvicorn</span>/<span className="font-mono">gunicorn</span>/<span className="font-mono">python</span> resolve to it.
        </p>
        <input className="input font-mono text-sm" value={cmd} onChange={(e) => setCmd(e.target.value)} />
        <div className="flex gap-2">
          <button className="btn-primary" onClick={saveCmd}>Save</button>
          <button className="btn-secondary" onClick={() => setCmd('uvicorn app_server:app --host 127.0.0.1 --port {port}')}>
            Reset default
          </button>
        </div>
      </div>

      {msg && <p className="text-sm text-slate-300 break-words">{msg}</p>}
    </div>
  )
}

/** Domain assignment + SSL for a website. */
function DomainTab({ site, onChanged }) {
  const [domain, setDomain] = useState(site.domain || '')
  const [msg, setMsg] = useState('')
  const [busy, setBusy] = useState(false)

  async function assign() {
    setBusy(true); setMsg('')
    try {
      const res = await api.post(`/websites/${site.id}/assign-domain`, { domain })
      setMsg(res.data.detail)
      onChanged()
    } catch (err) { setMsg(errorMessage(err)) } finally { setBusy(false) }
  }

  async function ssl() {
    setBusy(true); setMsg('')
    try {
      const res = await api.post(`/websites/${site.id}/ssl`)
      setMsg(res.data.detail)
    } catch (err) { setMsg(errorMessage(err)) } finally { setBusy(false) }
  }

  return (
    <div className="card max-w-xl space-y-3">
      <h3 className="font-semibold">Domain & SSL</h3>
      <div className="flex gap-2 items-center flex-wrap">
        <input className="input max-w-xs" placeholder="example.com" value={domain} onChange={(e) => setDomain(e.target.value)} />
        <button className="btn-primary" onClick={assign} disabled={busy || !domain}>Assign domain</button>
        <button className="btn-secondary" onClick={ssl} disabled={busy || !site.domain}>🔒 Request SSL</button>
      </div>
      <p className="text-xs text-slate-500">
        Assigning writes an nginx {site.type} server block and reloads nginx. SSL runs certbot for the domain
        (DNS must already point at this server).
      </p>
      {msg && <p className="text-sm text-slate-300 break-words">{msg}</p>}
    </div>
  )
}
