import { useEffect, useState } from 'react'
import api, { errorMessage } from '../../api/client'
import LiveLog from '../../components/LiveLog'
import StatusBadge from '../../components/StatusBadge'

/** Streamlit dashboard control: start/stop/restart, status, live logs. */
export default function DashboardTab({ project, onChanged }) {
  const [status, setStatus] = useState(project.dashboard_status)
  const [raw, setRaw] = useState('')
  const [busy, setBusy] = useState(false)
  const [logStream, setLogStream] = useState(null) // 'out' | 'err' | null
  const [domain, setDomain] = useState(project.domain || '')
  const [domainMsg, setDomainMsg] = useState('')
  const [venv, setVenv] = useState(project.venv_status || 'MISSING')

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
          <h3 className="font-semibold">Streamlit Dashboard</h3>
          <StatusBadge status={status} />
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
            <button className="btn-secondary" onClick={buildVenv}>⚙ Build environment</button>
          </div>
        )}

        <div className="mt-4 flex gap-2 flex-wrap">
          <button className="btn-primary" disabled={busy || venv !== 'READY'}
            title={venv !== 'READY' ? 'Dashboard environment is not ready yet' : ''}
            onClick={() => action('start')}>▶ Start</button>
          <button className="btn-secondary" disabled={busy} onClick={() => action('stop')}>⏹ Stop</button>
          <button className="btn-secondary" disabled={busy || venv !== 'READY'} onClick={() => action('restart')}>🔄 Restart</button>
          <button className="btn-secondary" onClick={refreshStatus}>↻ Refresh status</button>
        </div>

        {raw && <p className="mt-3 text-xs font-mono text-slate-500 break-all">{raw}</p>}

        <p className="mt-3 text-xs text-slate-600">
          The dashboard runs <span className="font-mono">dashboard/app.py</span> under Supervisor
          (auto-restart on crash). Upload your Streamlit files on the Files tab.
        </p>
      </div>

      {/* Domain / SSL */}
      <div className="card">
        <h3 className="font-semibold mb-2">Domain & SSL</h3>
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
          <h3 className="font-semibold">Process Logs</h3>
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
          path={logStream ? `/ws/logs/supervisor/${project.name}?stream=${logStream}` : null}
        />
        {!logStream && (
          <p className="text-sm text-slate-600 mt-2">Pick a stream to tail it live.</p>
        )}
      </div>
    </div>
  )
}
