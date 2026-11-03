import { useCallback, useEffect, useState } from 'react'
import api, { errorMessage } from '../api/client'
import Icon from './ui/Icon'

function when(iso) {
  return iso ? iso.replace('T', ' ').slice(0, 16) : ''
}

/** Projects page (admins): pause/resume every pipeline + scheduled script, stop/start every dashboard. */
export default function BulkControls({ onChanged }) {
  const [open, setOpen] = useState(false)
  const [st, setSt] = useState(null)
  const [busy, setBusy] = useState('')
  const [msg, setMsg] = useState(null)          // {text, error, results}

  const load = useCallback(() => {
    api.get('/bulk/status').then((r) => setSt(r.data)).catch((err) => setMsg({ text: errorMessage(err), error: true }))
  }, [])

  useEffect(() => { if (open) load() }, [open, load])

  async function run(label, confirmText, request) {
    if (confirmText && !window.confirm(confirmText)) return
    setBusy(label); setMsg(null)
    try {
      const r = await request()
      setMsg({ text: r.data.detail, results: r.data.results })
      onChanged?.()
    } catch (err) {
      setMsg({ text: errorMessage(err), error: true })
    } finally {
      setBusy(''); load()
    }
  }

  const failed = (msg?.results || []).filter((r) => !r.ok)

  return (
    <div className="card space-y-3">
      <button className="flex w-full items-center justify-between text-left" onClick={() => setOpen(!open)}>
        <span className="section-title">Bulk controls</span>
        <span className="flex items-center gap-2 text-xs text-slate-500">
          Pause / resume every pipeline and dashboard at once
          <Icon name={open ? 'chevron-up' : 'chevron-down'} size={15} />
        </span>
      </button>

      {open && (
        <>
          {msg && (
            <div className={`rounded-lg border px-3 py-2 text-sm ${msg.error ? 'border-red-500/30 bg-red-500/10 text-red-300' : 'border-emerald-500/30 bg-emerald-500/10 text-emerald-200'}`}>
              {msg.text}
              {failed.length > 0 && (
                <ul className="mt-1 list-disc pl-5 text-xs text-amber-200">
                  {failed.map((r) => <li key={r.project}><b>{r.project}</b>: {String(r.error).slice(0, 200)}</li>)}
                </ul>
              )}
            </div>
          )}

          {!st ? <p className="text-sm text-slate-500">Loading…</p> : (
            <div className="grid gap-3 lg:grid-cols-2">
              {/* Pipelines + scheduled scripts */}
              <div className="rounded-lg border border-panel-border p-3 space-y-2">
                <p className="text-sm font-medium text-slate-200">Pipelines &amp; scheduled scripts</p>
                <p className="text-xs text-slate-400">
                  Pipelines on: <b>{st.pipelines.active}</b> / {st.pipelines.total}
                  {' · '}script schedules on: <b>{st.schedules.active}</b> / {st.schedules.total}
                  {st.pipelines.running_now > 0 && <> · <span className="text-amber-300">{st.pipelines.running_now} running now</span></>}
                </p>
                {st.paused && (
                  <p className="text-xs text-amber-300">
                    Paused {when(st.paused.at)}: {st.paused.pipelines} pipeline(s), {st.paused.schedules} script schedule(s) remembered.
                  </p>
                )}
                <div className="flex flex-wrap gap-2">
                  <button className="btn-secondary" disabled={!!busy || (st.pipelines.active + st.schedules.active === 0 && !st.pipelines.running_now)}
                    onClick={() => run('ppause', 'Pause ALL pipelines and scheduled scripts, and stop pipelines running right now?',
                      () => api.post('/bulk/pipelines/pause'))}>
                    <Icon name="stop" size={14} />{busy === 'ppause' ? 'Pausing…' : 'Pause all'}</button>
                  <button className="btn-primary" disabled={!!busy || !st.paused}
                    title="Turn back on only the ones that were on before “Pause all”"
                    onClick={() => run('presume', null, () => api.post('/bulk/pipelines/resume', null, { params: { mode: 'previous' } }))}>
                    <Icon name="play" size={14} />{busy === 'presume' ? 'Resuming…' : 'Resume previous'}</button>
                  <button className="btn-secondary" disabled={!!busy || st.pipelines.active + st.schedules.active === st.pipelines.total + st.schedules.total}
                    onClick={() => run('presumeall', 'Turn ON every pipeline and script schedule — including ones that were off before?',
                      () => api.post('/bulk/pipelines/resume', null, { params: { mode: 'all' } }))}>
                    {busy === 'presumeall' ? 'Resuming…' : 'Resume all'}</button>
                </div>
              </div>

              {/* Dashboards */}
              <div className="rounded-lg border border-panel-border p-3 space-y-2">
                <p className="text-sm font-medium text-slate-200">Dashboards</p>
                <p className="text-xs text-slate-400">
                  Running: <b>{st.dashboards.running}</b> / {st.dashboards.total} with a dashboard
                </p>
                {st.stopped && (
                  <p className="text-xs text-amber-300">
                    Stopped {when(st.stopped.at)}: {st.stopped.projects.length} remembered
                    {st.stopped.projects.length > 0 && ` (${st.stopped.projects.slice(0, 4).join(', ')}${st.stopped.projects.length > 4 ? '…' : ''})`}.
                  </p>
                )}
                <div className="flex flex-wrap gap-2">
                  <button className="btn-secondary" disabled={!!busy || st.dashboards.running === 0}
                    onClick={() => run('dstop', `Stop all ${st.dashboards.running} running dashboard(s)? Their sites go offline until started again.`,
                      () => api.post('/bulk/dashboards/stop'))}>
                    <Icon name="stop" size={14} />{busy === 'dstop' ? 'Stopping…' : 'Stop all'}</button>
                  <button className="btn-primary" disabled={!!busy || !st.stopped}
                    title="Start only the dashboards that were running before “Stop all”"
                    onClick={() => run('dstart', null, () => api.post('/bulk/dashboards/start', null, { params: { mode: 'previous' } }))}>
                    <Icon name="play" size={14} />{busy === 'dstart' ? 'Starting… (can take a minute)' : 'Start previous'}</button>
                  <button className="btn-secondary" disabled={!!busy || st.dashboards.running === st.dashboards.total}
                    onClick={() => run('dstartall', `Start ALL ${st.dashboards.total} dashboard(s) — including ones that were stopped before? This can load the server for a few minutes.`,
                      () => api.post('/bulk/dashboards/start', null, { params: { mode: 'all' } }))}>
                    {busy === 'dstartall' ? 'Starting… (can take a minute)' : 'Start all'}</button>
                </div>
              </div>
            </div>
          )}
        </>
      )}
    </div>
  )
}
