import { useCallback, useEffect, useState } from 'react'
import api, { errorMessage } from '../../api/client'
import LiveLog from '../../components/LiveLog'
import StatusBadge from '../../components/StatusBadge'

// Simple frequency → cron builder (same idea as the per-script scheduler).
const FREQUENCIES = [
  { key: 'daily', label: 'Daily' },
  { key: 'hourly', label: 'Hourly' },
  { key: 'weekly', label: 'Weekly' },
  { key: 'custom', label: 'Custom cron' },
]
const DAYS = ['Sun', 'Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat']

function buildCron(b) {
  switch (b.frequency) {
    case 'hourly': return `${b.minute} * * * *`
    case 'daily': return `${b.minute} ${b.hour} * * *`
    case 'weekly': return `${b.minute} ${b.hour} * * ${b.weekday}`
    case 'custom': return b.custom
    default: return '0 6 * * *'
  }
}

function fmt(iso) {
  if (!iso) return '—'
  return new Date(iso).toLocaleString()
}

/**
 * Pipeline tab: run ALL code/ scripts in order, mark each pass/fail (red),
 * then restart the dashboard. Plus a cron schedule for the whole pipeline.
 */
export default function PipelineTab({ project }) {
  const [info, setInfo] = useState(null)
  const [builder, setBuilder] = useState({
    frequency: 'daily', minute: 0, hour: 6, weekday: 1, custom: '0 6 * * *',
  })
  const [active, setActive] = useState(false)
  const [runWs, setRunWs] = useState(null)
  const [msg, setMsg] = useState('')

  const refresh = useCallback(() => {
    api.get(`/projects/${project.id}/pipeline`).then((res) => {
      setInfo(res.data)
      setActive(res.data.is_active)
      if (res.data.cron_expression) {
        setBuilder((b) => ({ ...b, frequency: 'custom', custom: res.data.cron_expression }))
      }
    })
  }, [project.id])

  useEffect(() => { refresh() }, [refresh])

  // Poll the last run while a pipeline is streaming so the table updates
  useEffect(() => {
    if (!runWs) return
    const t = setInterval(refresh, 3000)
    return () => clearInterval(t)
  }, [runWs, refresh])

  const cron = buildCron(builder)

  function runNow() {
    setRunWs(null)
    setTimeout(() => setRunWs(`/ws/pipeline/${project.id}/run`), 0)
  }

  async function stopNow() {
    try {
      const res = await api.post(`/projects/${project.id}/stop-pipeline`)
      setMsg(res.data.detail)
      setRunWs(null)
      setTimeout(refresh, 1000)   // let the run wind down, then refresh status
    } catch (err) {
      alert(errorMessage(err))
    }
  }

  async function saveSchedule() {
    setMsg('')
    try {
      await api.put(`/projects/${project.id}/pipeline`, {
        cron_expression: cron,
        is_active: active,
      })
      setMsg('Schedule saved ✓')
      refresh()
    } catch (err) {
      setMsg(errorMessage(err))
    }
  }

  // Quickly turn the schedule on/off without changing the cron
  async function setActiveState(next) {
    setMsg('')
    try {
      await api.put(`/projects/${project.id}/pipeline`, {
        cron_expression: info?.cron_expression || cron,
        is_active: next,
      })
      setActive(next)
      setMsg(next ? 'Schedule enabled ✓' : 'Schedule stopped ✓')
      refresh()
    } catch (err) {
      setMsg(errorMessage(err))
    }
  }

  async function deleteSchedule() {
    if (!window.confirm('Delete this pipeline schedule? (the pipeline can still be run manually)')) return
    setMsg('')
    try {
      await api.delete(`/projects/${project.id}/pipeline`)
      setMsg('Schedule deleted ✓')
      refresh()
    } catch (err) {
      setMsg(errorMessage(err))
    }
  }

  const lastRun = info?.last_run
  const scheduled = !!info?.cron_expression
  // Running if we're locally streaming, or the latest run is still RUNNING
  const running = !!runWs || lastRun?.status === 'RUNNING'

  return (
    <div className="space-y-4">
      {/* Run-all panel */}
      <div className="card">
        <div className="flex items-center gap-3 flex-wrap">
          <h3 className="font-semibold">Project Pipeline</h3>
          <span className="text-xs text-slate-500">
            Runs all {info?.scripts?.length ?? 0} code/ script(s) in order, retries any that fail
            at the end, then restarts the dashboard.
          </span>
          <div className="ml-auto flex gap-2">
            {running && (
              <button className="btn-danger" onClick={stopNow}>⏹ Stop</button>
            )}
            <button className="btn-primary" onClick={runNow} disabled={running}>
              {running ? 'Running…' : '▶ Run All Now'}
            </button>
          </div>
        </div>

        {/* Ordered script list */}
        {info?.scripts?.length > 0 && (
          <ol className="mt-3 text-sm list-decimal list-inside text-slate-400 space-y-0.5">
            {info.scripts.map((s) => <li key={s} className="font-mono">{s}</li>)}
          </ol>
        )}
        <p className="text-xs text-slate-600 mt-2">
          Scripts run in filename order — prefix with 01_, 02_, … to control the sequence.
        </p>

        <LiveLog path={runWs} onClose={refresh} />
      </div>

      {/* Last run results */}
      <div className="card">
        <div className="flex items-center gap-2 mb-3">
          <h3 className="font-semibold">Last Run</h3>
          {lastRun && <StatusBadge status={lastRun.status} />}
          {lastRun && (
            <span className="text-xs text-slate-500">
              {fmt(lastRun.started_at + 'Z')} → {lastRun.finished_at ? fmt(lastRun.finished_at + 'Z') : 'running…'}
            </span>
          )}
        </div>
        {!lastRun ? (
          <p className="text-slate-600 text-sm">No runs yet.</p>
        ) : (
          <>
            <table className="w-full text-sm">
              <thead>
                <tr className="text-left text-xs uppercase text-slate-500 border-b border-panel-border">
                  <th className="py-1">#</th><th>Script</th><th>Result</th><th>Finished</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-panel-border">
                {lastRun.results.map((r, i) => (
                  <tr key={r.filename}>
                    <td className="py-1.5 text-slate-500">{i + 1}</td>
                    <td className="font-mono">{r.filename}</td>
                    <td className="space-x-1">
                      <span className={`badge ${r.status === 'SUCCESS'
                        ? 'bg-green-500/15 text-green-400' : 'bg-red-500/15 text-red-400'}`}>
                        {r.status === 'SUCCESS' ? '✓ OK' : `✗ FAILED (exit ${r.exit_code})`}
                      </span>
                      {r.retried && (
                        <span className="badge bg-sky-500/15 text-sky-300"
                          title={`Re-run at the end (${r.attempts} attempts)`}>
                          ↻ {r.status === 'SUCCESS' ? 'recovered on retry' : 'retried'}
                        </span>
                      )}
                    </td>
                    <td className="text-slate-500 text-xs">{fmt(r.finished + 'Z')}</td>
                  </tr>
                ))}
              </tbody>
            </table>
            <p className="text-xs mt-2 text-slate-500">
              Dashboard restarted: {lastRun.dashboard_restarted
                ? <span className="text-green-400">yes ✓</span>
                : <span className="text-slate-400">no</span>}
            </p>
          </>
        )}
      </div>

      {/* Schedule the whole pipeline */}
      <div className="card">
        <h3 className="font-semibold mb-3">Schedule the Pipeline</h3>
        {msg && <p className={`text-sm mb-2 ${msg.includes('✓') ? 'text-green-400' : 'text-red-400'}`}>{msg}</p>}

        {/* Current schedule status + stop/delete */}
        <div className="flex items-center gap-3 flex-wrap mb-4 p-3 rounded-lg bg-slate-900 border border-panel-border">
          {scheduled ? (
            <>
              <span className={`badge ${info.is_active ? 'bg-green-500/15 text-green-400' : 'bg-slate-500/20 text-slate-400'}`}>
                {info.is_active ? '● Scheduled (active)' : '○ Scheduled (stopped)'}
              </span>
              <code className="text-sky-300 text-xs bg-slate-800 px-2 py-1 rounded">{info.cron_expression}</code>
              {info.is_active && info.next_run && (
                <span className="text-xs text-slate-500">next run: {fmt(info.next_run)}</span>
              )}
              <div className="ml-auto flex gap-2">
                {info.is_active ? (
                  <button className="btn-secondary" onClick={() => setActiveState(false)}>⏸ Stop</button>
                ) : (
                  <button className="btn-secondary" onClick={() => setActiveState(true)}>▶ Enable</button>
                )}
                <button className="btn-secondary text-red-400" onClick={deleteSchedule}>🗑 Delete</button>
              </div>
            </>
          ) : (
            <span className="text-sm text-slate-500">No schedule yet — set one below.</span>
          )}
        </div>

        <div className="grid sm:grid-cols-2 gap-3">
          <div>
            <label className="block text-sm text-slate-400 mb-1">Frequency</label>
            <select className="input" value={builder.frequency}
              onChange={(e) => setBuilder({ ...builder, frequency: e.target.value })}>
              {FREQUENCIES.map((f) => <option key={f.key} value={f.key}>{f.label}</option>)}
            </select>
          </div>
          {['hourly', 'daily', 'weekly'].includes(builder.frequency) && (
            <div>
              <label className="block text-sm text-slate-400 mb-1">Minute</label>
              <input type="number" min="0" max="59" className="input" value={builder.minute}
                onChange={(e) => setBuilder({ ...builder, minute: e.target.value })} />
            </div>
          )}
          {['daily', 'weekly'].includes(builder.frequency) && (
            <div>
              <label className="block text-sm text-slate-400 mb-1">Hour (0–23)</label>
              <input type="number" min="0" max="23" className="input" value={builder.hour}
                onChange={(e) => setBuilder({ ...builder, hour: e.target.value })} />
            </div>
          )}
          {builder.frequency === 'weekly' && (
            <div>
              <label className="block text-sm text-slate-400 mb-1">Day of week</label>
              <select className="input" value={builder.weekday}
                onChange={(e) => setBuilder({ ...builder, weekday: e.target.value })}>
                {DAYS.map((d, i) => <option key={d} value={i}>{d}</option>)}
              </select>
            </div>
          )}
          {builder.frequency === 'custom' && (
            <div className="sm:col-span-2">
              <label className="block text-sm text-slate-400 mb-1">Cron expression</label>
              <input className="input font-mono" value={builder.custom}
                onChange={(e) => setBuilder({ ...builder, custom: e.target.value })} placeholder="0 6 * * *" />
            </div>
          )}
        </div>

        <div className="mt-3 flex items-center gap-3 flex-wrap">
          <label className="flex items-center gap-2 text-sm">
            <input type="checkbox" checked={active} onChange={(e) => setActive(e.target.checked)} />
            Active
          </label>
          <span className="text-sm text-slate-500">cron:</span>
          <code className="text-sky-300 bg-slate-900 px-2 py-1 rounded">{cron}</code>
          {info?.next_run && (
            <span className="text-xs text-slate-500">next run: {fmt(info.next_run)}</span>
          )}
          <button className="btn-primary ml-auto" onClick={saveSchedule}>Save schedule</button>
        </div>
      </div>
    </div>
  )
}
