import { useEffect, useState } from 'react'
import api, { errorMessage } from '../../api/client'
import LiveLog from '../../components/LiveLog'
import StatusBadge from '../../components/StatusBadge'
import Icon from '../../components/ui/Icon'

const FRAMEWORK_LABELS = {
  streamlit: 'Streamlit',
  flask: 'Flask (gunicorn)',
  fastapi: 'FastAPI (uvicorn)',
}

/** Dashboard control: framework, start/stop/restart, status, live logs. */
export default function DashboardTab({ project, onChanged }) {
  const [status, setStatus] = useState(project.dashboard_status)
  const [raw, setRaw] = useState('')
  const [busy, setBusy] = useState(false)
  const [logStream, setLogStream] = useState(null) // 'out' | 'err' | null
  const [domain, setDomain] = useState(project.domain || '')
  const [domainMsg, setDomainMsg] = useState('')
  const [venv, setVenv] = useState(project.venv_status || 'MISSING')
  const [detect, setDetect] = useState(null)      // { detected, pinned, framework, command }
  const [fwMsg, setFwMsg] = useState('')

  async function refreshDetect() {
    try {
      const res = await api.get(`/projects/${project.id}/dashboard/detect`)
      setDetect(res.data)
    } catch { /* ignore — the panel falls back to Streamlit */ }
  }

  async function pinFramework(value) {
    setFwMsg('')
    try {
      const res = await api.put(`/projects/${project.id}/dashboard/framework`,
        { framework: value || null })
      setFwMsg(res.data.detail)
      await refreshDetect()
      onChanged?.()
    } catch (err) {
      setFwMsg(errorMessage(err))
    }
  }

  async function refreshStatus() {
    try {
      const res = await api.get(`/projects/${project.id}/dashboard/status`)
      setStatus(res.data.status)
      setRaw(res.data.raw)
    } catch (err) {
      setRaw(errorMessage(err))
    }
  }

  async function refreshVenv() {
    try {
      const res = await api.get(`/projects/${project.id}`)
      setVenv(res.data.venv_status)
      return res.data.venv_status
    } catch { /* ignore */ }
  }

  async function buildVenv() {
    try {
      const res = await api.post(`/projects/${project.id}/build-venv`)
      setVenv('BUILDING')
      alert(res.data.detail)
    } catch (err) {
      alert(errorMessage(err))
    }
  }

  useEffect(() => {
    refreshStatus()
    refreshVenv()
    refreshDetect()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [project.id])

  // While the env is building, poll until it's ready.
  useEffect(() => {
    if (venv !== 'BUILDING') return
    const t = setInterval(async () => {
      if ((await refreshVenv()) === 'READY') clearInterval(t)
    }, 4000)
    return () => clearInterval(t)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [venv])

  async function action(name) {
    setBusy(true)
    try {
      await api.post(`/projects/${project.id}/dashboard/${name}`)
      await refreshStatus()
      onChanged?.()
    } catch (err) {
      alert(errorMessage(err))
    } finally {
      setBusy(false)
    }
  }

  function toggleLog(stream) {
    setLogStream((prev) => (prev === stream ? null : stream))
  }

  async function assignDomain() {
    setDomainMsg('')
    try {
      const res = await api.post(`/projects/${project.id}/assign-domain`, { domain })
      setDomainMsg(res.data.detail)
      onChanged?.()
    } catch (err) {
      setDomainMsg(errorMessage(err))
    }
  }

  async function requestSsl() {
    setDomainMsg('')
    try {
      const res = await api.post(`/projects/${project.id}/ssl`)
      setDomainMsg(res.data.detail)
    } catch (err) {
      setDomainMsg(errorMessage(err))
    }
  }

  const liveUrl = project.domain
    ? `http://${project.domain}`
    : `http://${window.location.hostname}:${project.dashboard_port}`

  return (
    <div className="space-y-4">
      <div className="card">
        <div className="flex items-center gap-3 flex-wrap">
          <h3 className="section-title">Dashboard</h3>
          <StatusBadge status={status} />
          {detect?.framework && (
            <span className="badge bg-emerald-500/15 text-emerald-400">
              {FRAMEWORK_LABELS[detect.framework] || detect.framework}
            </span>
          )}
          <span className="text-sm text-slate-500">port {project.dashboard_port}</span>
          <a href={liveUrl} target="_blank" rel="noreferrer" className="text-sm text-sky-400 hover:underline">
            Open live URL ↗
          </a>
        </div>

        {/* Dashboard Python environment status */}
        {venv === 'BUILDING' && (
          <div className="mt-3 p-3 rounded-lg bg-amber-500/10 border border-amber-600/40 text-sm text-amber-200">
            ⏳ Preparing the dashboard's Python environment (installing streamlit + packages)…
            you can start it once this finishes. Progress is in <span className="font-mono">logs/venv-setup.log</span>.
          </div>
        )}
        {venv === 'MISSING' && (
          <div className="mt-3 p-3 rounded-lg bg-red-500/10 border border-red-600/40 text-sm text-red-200 flex items-center gap-3 flex-wrap">
            <span>⚠️ The dashboard environment isn't built yet, so Start would fail.</span>
            <button className="btn-secondary" onClick={buildVenv}><Icon name="gear" size={15} />Build environment</button>
          </div>
        )}

        <div className="mt-4 flex gap-2 flex-wrap">
          <button className="btn-primary" disabled={busy || venv !== 'READY'}
            title={venv !== 'READY' ? 'Dashboard environment is not ready yet' : ''}
            onClick={() => action('start')}><Icon name="play" size={15} />Start</button>
          <button className="btn-secondary" disabled={busy} onClick={() => action('stop')}><Icon name="stop" size={15} />Stop</button>
          <button className="btn-secondary" disabled={busy || venv !== 'READY'} onClick={() => action('restart')}><Icon name="refresh" size={15} />Restart</button>
          <button className="btn-secondary" onClick={refreshStatus}><Icon name="refresh" size={15} />Refresh status</button>
        </div>

        {raw && <p className="mt-3 text-xs font-mono text-slate-500 break-all">{raw}</p>}

        <p className="mt-3 text-xs text-slate-600">
          The dashboard runs <span className="font-mono">dashboard/app.py</span> under Supervisor
          (auto-restart on crash). Upload it on the Files tab — Streamlit, Flask and
          FastAPI apps are all supported, and the right server is picked from your code.
        </p>
      </div>

      {/* How the app is served */}
      <div className="card space-y-2">
        <div className="flex items-center gap-2 flex-wrap">
          <h3 className="section-title">How it runs</h3>
          <button className="btn-secondary ml-auto" onClick={refreshDetect}><Icon name="search" size={15} />Re-detect</button>
        </div>

        <p className="text-sm text-slate-400">
          {detect?.detected
            ? <>Found a <b>{FRAMEWORK_LABELS[detect.detected.framework] || detect.detected.framework}</b> app
                in <span className="font-mono">dashboard/{detect.detected.file}</span>
                {detect.detected.target && <> (<span className="font-mono">{detect.detected.target}</span>)</>}.</>
            : <>No Streamlit, Flask or FastAPI app recognised in <span className="font-mono">dashboard/</span> yet
                — it will be started as Streamlit.</>}
        </p>

        {detect?.warning && (
          <div className="p-3 rounded-lg bg-amber-500/10 border border-amber-600/40 text-sm text-amber-200">
            {detect.warning}
          </div>
        )}

        <div>
          <label className="label">Run as</label>
          <select className="select max-w-xs" value={detect?.pinned || ''}
            onChange={(e) => pinFramework(e.target.value)}>
            <option value="">Auto — detect from the code</option>
            <option value="streamlit">Streamlit</option>
            <option value="flask">Flask (gunicorn)</option>
            <option value="fastapi">FastAPI (uvicorn)</option>
          </select>
          <p className="text-xs text-slate-500 mt-1">
            Leave on Auto and the panel re-reads your code every time you start or
            restart — swap app.py from Streamlit to Flask and it just follows.
            Pick one to override. Restart to apply.
          </p>
        </div>

        {fwMsg && <p className="text-sm text-slate-300 break-words">{fwMsg}</p>}
      </div>

      {/* Domain / SSL */}
      <div className="card">
        <h3 className="section-title mb-3">Domain & SSL</h3>
        <div className="flex gap-2 items-center flex-wrap">
          <input className="input max-w-xs" placeholder="dashboard.example.com" value={domain}
            onChange={(e) => setDomain(e.target.value)} />
          <button className="btn-primary" onClick={assignDomain} disabled={!domain}>Assign domain</button>
          <button className="btn-secondary" onClick={requestSsl} disabled={!project.domain}>🔒 Request SSL</button>
        </div>
        <p className="text-xs text-slate-500 mt-2">
          Writes an nginx proxy block to the dashboard's port and reloads nginx. SSL runs certbot
          (DNS must already point at this server).
        </p>
        {domainMsg && <p className="text-sm text-slate-300 mt-2 break-words">{domainMsg}</p>}
      </div>

      {/* Live process logs */}
      <div className="card">
        <div className="flex items-center gap-2">
          <h3 className="section-title">Process Logs</h3>
          <div className="ml-auto flex gap-2">
            <button
              className={logStream === 'out' ? 'btn-primary' : 'btn-secondary'}
              onClick={() => toggleLog('out')}
            >
              stdout {logStream === 'out' ? '(live)' : ''}
            </button>
            <button
              className={logStream === 'err' ? 'btn-primary' : 'btn-secondary'}
              onClick={() => toggleLog('err')}
            >
              stderr {logStream === 'err' ? '(live)' : ''}
            </button>
          </div>
        </div>
        <LiveLog
          path={logStream ? `/ws/projects/${project.name}/dashboard-log?stream=${logStream}` : null}
        />
        {!logStream && (
          <p className="text-sm text-slate-600 mt-2">Pick a stream to tail it live.</p>
        )}
      </div>
    </div>
  )
}
