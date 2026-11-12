import { useCallback, useEffect, useRef, useState } from 'react'
import { Link, useParams, useSearchParams } from 'react-router-dom'
import api, { errorMessage, isCancel } from '../api/client'
import { useAuth } from '../context/AuthContext'
import { openInEditor } from '../lib/openEditor'
import EditorModal from '../components/EditorModal'
import LiveLog from '../components/LiveLog'
import ProgressBar from '../components/ProgressBar'
import StatusBadge from '../components/StatusBadge'
import Icon from '../components/ui/Icon'
import PageHeader from '../components/ui/PageHeader'
import Tabs from '../components/ui/Tabs'

const BASE_TABS = [
  { key: 'overview', label: 'Overview' },
  { key: 'files', label: 'Files' },
  { key: 'database', label: 'Database' },
  { key: 'domain', label: 'Domain & SSL' },
]

// nginx's client_max_body_size for the panel (deploy/nginx-panel.conf).
const MAX_UPLOAD_BYTES = 200 * 1024 * 1024

const FRAMEWORK_LABELS = {
  flask: 'Flask (gunicorn)',
  fastapi: 'FastAPI (uvicorn)',
  other: 'Other (custom command)',
  node: 'Node.js',
}
const SERVICE_TYPES = ['python', 'node']

// Python and Node.js apps get a "Run" tab (between Files and Database).
function tabsFor(type) {
  if (!SERVICE_TYPES.includes(type)) return BASE_TABS
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
  const { can } = useAuth()
  const { id } = useParams()
  const [searchParams, setSearchParams] = useSearchParams()
  const tab = searchParams.get('tab') || 'overview'

  const [site, setSite] = useState(null)
  const [files, setFiles] = useState([])
  const [editorPath, setEditorPath] = useState(null)
  const uploadRef = useRef(null)
  const [uploadMsg, setUploadMsg] = useState('')
  const [transfer, setTransfer] = useState(null)   // { name, pct, sent } while uploading
  const transferRef = useRef(null)                 // AbortController for the upload

  const refresh = useCallback(() => {
    api.get(`/websites/${id}`).then((res) => setSite(res.data))
    api.get(`/websites/${id}/files`).then((res) => setFiles(res.data)).catch(() => setFiles([]))
  }, [id])

  useEffect(() => {
    refresh()
  }, [refresh])

  async function uploadZip(file, build) {
    if (!file || transferRef.current) return
    if (file.size > MAX_UPLOAD_BYTES) {
      setUploadMsg(`${file.name} is ${formatSize(file.size)}; the limit is 200 MB. ` +
        'Leave out node_modules, venv and other generated folders and zip it again.')
      return
    }
    setUploadMsg('')
    const form = new FormData()
    form.append('file', file)
    const controller = new AbortController()
    transferRef.current = controller
    setTransfer({ name: file.name, pct: 0, sent: false })
    try {
      const res = await api.post(`/websites/${id}/upload`, form, {
        params: { build, replace: true },
        signal: controller.signal,
        onUploadProgress: (e) => {
          if (!e.total) return
          const pct = Math.round((e.loaded / e.total) * 100)
          setTransfer((t) => t && { ...t, pct, sent: pct >= 100 })
        },
      })
      setUploadMsg(res.data.detail + (res.data.build_output ? `\n${res.data.build_output}` : ''))
    } catch (err) {
      setUploadMsg(isCancel(err) ? 'Upload cancelled.' : errorMessage(err))
    } finally {
      setTransfer(null)
      transferRef.current = null
      refresh()
    }
  }

  if (!site) return <div className="empty-state">Loading…</div>

  const liveUrl = site.domain ? `http://${site.domain}` : null
  const editableFile = (name) => /\.(html?|css|js|jsx|ts|tsx|php|json|md|txt|xml|env|sql)$/i.test(name)
  const sitePath = (name) => `${site.folder_path}/${name.replace(/\/$/, '')}`

  return (
    <div className="space-y-5">
      <PageHeader
        title={site.name}
        crumbs={[{ label: 'Websites', to: '/websites' }, { label: site.name }]}
        actions={
          <>
            <span className="badge-muted">{site.type.toUpperCase()}</span>
            {can('code') && (
              <button className="btn-primary" title="Open this website's files in the code editor"
                onClick={() => openInEditor({ kind: 'website', name: site.name })}>
                <Icon name="external" size={15} />Open in editor</button>
            )}
            {liveUrl && (
              <a href={liveUrl} target="_blank" rel="noreferrer" className="btn-secondary">
                <Icon name="external" size={15} />
                {site.domain}
              </a>
            )}
            <Link to="/websites" className="btn-secondary">
              <Icon name="arrow-left" size={15} />
              All websites
            </Link>
          </>
        }
      />

      <Tabs tabs={tabsFor(site.type)} active={tab} onChange={(key) => setSearchParams({ tab: key })} />

      {/* Overview */}
      {tab === 'overview' && (
        <div className="card max-w-xl">
          <h3 className="section-title mb-4">Website Info</h3>
          <dl className="space-y-2 text-sm">
            <div className="flex justify-between"><dt className="text-slate-500">Type</dt><dd>{site.type}</dd></div>
            <div className="flex justify-between"><dt className="text-slate-500">Folder</dt><dd className="font-mono break-all">{site.folder_path}</dd></div>
            <div className="flex justify-between"><dt className="text-slate-500">Domain</dt><dd>{site.domain || '—'}</dd></div>
            <div className="flex justify-between"><dt className="text-slate-500">Database</dt><dd>{site.db_name || '—'}</dd></div>
            {SERVICE_TYPES.includes(site.type) && (
              <>
                <div className="flex justify-between"><dt className="text-slate-500">Framework</dt><dd>{FRAMEWORK_LABELS[site.framework] || '—'}</dd></div>
                <div className="flex justify-between"><dt className="text-slate-500">Port</dt><dd className="font-mono">127.0.0.1:{site.port}</dd></div>
                <div className="flex justify-between items-center"><dt className="text-slate-500">Status</dt><dd><StatusBadge status={site.status} /></dd></div>
              </>
            )}
          </dl>
        </div>
      )}

      {/* Run (python and node apps) */}
      {tab === 'run' && <RunTab site={site} onChanged={refresh} />}

      {/* Files */}
      {tab === 'files' && (
        <div className="space-y-4">
          <div className="card">
            <div className="flex items-center gap-2 flex-wrap">
              <h3 className="section-title">Deploy</h3>
              <button className="btn-primary" disabled={!!transfer} onClick={() => uploadRef.current?.click()}><Icon name="upload" size={15} />Upload .zip</button>
              {site.type === 'react' && (
                <button className="btn-secondary" disabled={!!transfer} onClick={() => {
                  const f = uploadRef.current?.files?.[0]
                  if (f) uploadZip(f, true)
                  else alert('Pick a zip first via Upload')
                }}><Icon name="upload" size={15} />Upload + npm build</button>
              )}
              <input ref={uploadRef} type="file" accept=".zip" className="hidden"
                onChange={(e) => { uploadZip(e.target.files[0], false); e.target.value = '' }} />
              <span className="text-xs text-slate-500">
                Upload a .zip — it replaces the folder contents
                {site.type === 'react' && ' (then builds to dist/)'}
                {site.type === 'python' && ' (include requirements.txt; the panel then detects your app and sets the run command)'}
                {site.type === 'node' && ' (include package.json and package-lock.json, but leave out node_modules; the panel then finds the start file)'}.
              </span>
            </div>
            {transfer && (transfer.sent
              // Every byte has arrived: the server is unpacking it (and building, for React).
              // Cancelling now wouldn't stop that, so the button goes away.
              ? <ProgressBar dir="up" name={`${transfer.name}: unpacking on the server`} pct={null} />
              : <ProgressBar dir="up" name={transfer.name} pct={transfer.pct}
                  onCancel={() => transferRef.current?.abort()} />)}
            {uploadMsg && <pre className="mt-3 bg-black text-slate-300 text-xs p-3 rounded-lg max-h-48 overflow-auto whitespace-pre-wrap">{uploadMsg}</pre>}
          </div>

          <div className="card">
            <h3 className="section-title mb-3">Files</h3>
            <table className="w-full text-sm">
              <tbody className="divide-y divide-panel-border">
                {files.map((f) => (
                  <tr key={f.name}>
                    <td className="py-2">
                      {editableFile(f.name)
                        ? <button className="text-sky-400 hover:underline" onClick={() => setEditorPath(sitePath(f.name))}><Icon name="pencil" size={15} />{f.name}</button>
                        : (
                          <span className="inline-flex items-center gap-2">
                            <Icon name={f.name.endsWith('/') ? 'folder' : 'file'} size={15} className="text-slate-500" />
                            {f.name}
                          </span>
                        )}
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
      <h3 className="section-title">Linked Database</h3>

      <p className="text-sm text-slate-400">
        Current: {site.db_name
          ? <span className="font-mono text-sky-300">{site.db_name}</span>
          : <span className="text-slate-500">none</span>}
      </p>

      <div>
        <label className="label">Select a database to link</label>
        <select className="select max-w-xs" value={selected} onChange={(e) => setSelected(e.target.value)}>
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

/** Python / Node.js web-service controls: framework, deps, run command, start/stop, logs. */
function RunTab({ site, onChanged }) {
  const isNode = site.type === 'node'
  const [cmd, setCmd] = useState(site.run_command || '')
  const [framework, setFramework] = useState(site.framework || 'fastapi')
  const [presets, setPresets] = useState([])
  const [msg, setMsg] = useState('')
  const [setupWs, setSetupWs] = useState(null)
  const [showAppLogs, setShowAppLogs] = useState(false)

  // Default run command per framework — drives the "use the default" shortcut.
  useEffect(() => {
    api.get(`/websites/${site.id}/frameworks`).then((r) => setPresets(r.data)).catch(() => {})
  }, [site.id])

  const defaultFor = (key) => presets.find((p) => p.key === key)?.run_command || ''
  const isPreset = !cmd.trim() || presets.some((p) => p.run_command === cmd.trim())

  // Switching framework rewrites the command only while it is still one of ours
  // — a command typed by hand is never thrown away silently.
  function changeFramework(key) {
    setFramework(key)
    if (isPreset && key !== 'other') setCmd(defaultFor(key))
  }

  async function saveCmd() {
    setMsg('')
    try {
      const r = await api.put(`/websites/${site.id}/run-command`,
        { run_command: cmd, framework: isNode ? null : framework })
      setMsg(r.data.detail)
      onChanged()
    } catch (err) { setMsg(errorMessage(err)) }
  }

  async function detect() {
    setMsg('Scanning your code…')
    try {
      const r = await api.post(`/websites/${site.id}/detect`)
      setMsg(r.data.detail)
      if (r.data.detected) {
        setCmd(r.data.run_command)
        setFramework(r.data.framework)
      }
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
          <h3 className="section-title">Service</h3>
          <div className="flex items-center gap-2">
            <span className={`badge ${envBadge}`}>deps: {site.env_status || 'MISSING'}</span>
            <StatusBadge status={site.status} />
          </div>
        </div>
        <p className="text-xs text-slate-500">
          {isNode
            ? <>Upload your app in the <b>Files</b> tab (a .zip with your code + package.json, without node_modules),
              then install deps and start it. Install deps runs <span className="font-mono">npm ci</span>, which builds
              a fresh node_modules for this server. </>
            : <>Upload your app in the <b>Files</b> tab (a .zip with your code + requirements.txt),
              then install deps and start it. </>}
          It runs on <span className="font-mono">127.0.0.1:{site.port}</span>;
          assign a domain to reach it.
        </p>
        <div className="flex flex-wrap gap-2">
          <button className="btn-secondary" onClick={detect}
            title="Read the uploaded code and set the framework + run command"><Icon name="search" size={15} />Detect app</button>
          <button className="btn-secondary" onClick={installDeps}>📦 Install deps</button>
          <button className="btn-secondary" onClick={() => action('start')}><Icon name="play" size={15} />Start</button>
          <button className="btn-secondary" onClick={() => action('stop')}><Icon name="stop" size={15} />Stop</button>
          <button className="btn-secondary" onClick={() => action('restart')}><Icon name="refresh" size={15} />Restart</button>
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

      <div className="card space-y-3">
        <h3 className="section-title">{isNode ? 'Run command' : <>Framework &amp; run command</>}</h3>

        {!isNode && <div>
          <label className="label">Framework</label>
          <select className="select max-w-xs" value={framework}
            onChange={(e) => changeFramework(e.target.value)}>
            <option value="flask">Flask — served by gunicorn</option>
            <option value="fastapi">FastAPI — served by uvicorn</option>
            <option value="other">Other — custom command</option>
          </select>
          <p className="text-xs text-slate-500 mt-1">
            Picks the server installed with your deps and the nginx proxy style
            (Flask/WSGI has no websockets). Save to apply.
          </p>
        </div>}

        <div>
          <label className="label">Run command</label>
          <input className="input font-mono text-sm" value={cmd} onChange={(e) => setCmd(e.target.value)} />
          {isNode ? <p className="text-xs text-slate-500 mt-1">
            Usually <span className="font-mono">node server.js</span>. The app gets its port in the{' '}
            <span className="font-mono">PORT</span> environment variable (this wins over a PORT in the app&apos;s .env),
            and its own .env file is read by the app as usual.
          </p> : <p className="text-xs text-slate-500 mt-1">
            Use <span className="font-mono">{'{port}'}</span> for the port. The app’s venv is on PATH,
            so <span className="font-mono">gunicorn</span>/<span className="font-mono">uvicorn</span>/<span className="font-mono">python</span> resolve to it.
            The import path is <span className="font-mono">module:variable</span> —
            e.g. <span className="font-mono">app:app</span> for an <span className="font-mono">app = Flask(__name__)</span> in <span className="font-mono">app.py</span>.
          </p>}
        </div>

        <div className="flex gap-2 flex-wrap">
          <button className="btn-primary" onClick={saveCmd}>Save</button>
          {framework !== 'other' && defaultFor(framework) && (
            <button className="btn-secondary" onClick={() => setCmd(defaultFor(framework))}>
              Reset to {isNode ? 'detected' : framework} default
            </button>
          )}
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
      <h3 className="section-title">Domain & SSL</h3>
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
