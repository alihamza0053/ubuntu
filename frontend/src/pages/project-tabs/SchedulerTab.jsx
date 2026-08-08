import { useCallback, useEffect, useState } from 'react'
import api, { errorMessage } from '../../api/client'
import { formatDateTime } from '../../lib/datetime'
import Icon from '../../components/ui/Icon'

/** Visual cron builder → cron expression. */
const FREQUENCIES = [
  { key: 'minutely', label: 'Every N minutes' },
  { key: 'hourly', label: 'Hourly' },
  { key: 'daily', label: 'Daily' },
  { key: 'weekly', label: 'Weekly' },
  { key: 'monthly', label: 'Monthly' },
  { key: 'custom', label: 'Custom expression' },
]

const DAYS = ['Sun', 'Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat']

function buildCron(b) {
  const m = String(b.minute).padStart(1, '0')
  const h = String(b.hour)
  switch (b.frequency) {
    case 'minutely': return `*/${b.interval} * * * *`
    case 'hourly': return `${m} * * * *`
    case 'daily': return `${m} ${h} * * *`
    case 'weekly': return `${m} ${h} * * ${b.weekday}`
    case 'monthly': return `${m} ${h} ${b.day} * *`
    case 'custom': return b.custom
    default: return '0 * * * *'
  }
}

// next_run from APScheduler is tz-aware ISO; last_run is naive UTC. The shared
// formatter handles both: it only assumes UTC when no zone is present.
const formatTime = (iso) => formatDateTime(iso)

/** Scheduler tab: cron builder + list of this project's schedules. */
export default function SchedulerTab({ project }) {
  const [scripts, setScripts] = useState([])
  const [schedules, setSchedules] = useState([])
  const [builder, setBuilder] = useState({
    scriptId: '', frequency: 'daily', interval: 5, minute: 0, hour: 9, weekday: 1, day: 1, custom: '0 9 * * *',
  })
  const [error, setError] = useState('')

  const refresh = useCallback(() => {
    api.get(`/projects/${project.id}/scripts`).then((res) => setScripts(res.data))
    api.get('/schedules').then((res) => {
      const ids = new Set()
      api.get(`/projects/${project.id}/scripts`).then((r) => {
        r.data.forEach((s) => ids.add(s.id))
        setSchedules(res.data.filter((sc) => ids.has(sc.script_id)))
      })
    })
  }, [project.id])

  useEffect(() => {
    refresh()
  }, [refresh])

  const cron = buildCron(builder)

  async function create() {
    setError('')
    if (!builder.scriptId) {
      setError('Pick a script first')
      return
    }
    try {
      await api.post('/schedules', {
        script_id: Number(builder.scriptId),
        cron_expression: cron,
        is_active: true,
      })
      refresh()
    } catch (err) {
      setError(errorMessage(err))
    }
  }

  async function toggle(id) {
    await api.post(`/schedules/${id}/toggle`)
    refresh()
  }

  async function remove(id) {
    if (!window.confirm('Delete this schedule?')) return
    await api.delete(`/schedules/${id}`)
    refresh()
  }

  async function stopRun(scriptId) {
    try {
      await api.post(`/scripts/${scriptId}/stop`)
      refresh()
    } catch (err) {
      alert(errorMessage(err))
    }
  }

  return (
    <div className="space-y-4">
      {/* Builder */}
      <div className="card">
        <h3 className="section-title mb-4">New Schedule</h3>
        {error && <p className="text-red-400 text-sm mb-2">{error}</p>}
        <div className="grid sm:grid-cols-2 gap-3">
          <div>
            <label className="label">Script</label>
            <select className="select" value={builder.scriptId}
              onChange={(e) => setBuilder({ ...builder, scriptId: e.target.value })}>
              <option value="">— select —</option>
              {scripts.map((s) => <option key={s.id} value={s.id}>{s.folder}/{s.filename}</option>)}
            </select>
          </div>
          <div>
            <label className="label">Frequency</label>
            <select className="select" value={builder.frequency}
              onChange={(e) => setBuilder({ ...builder, frequency: e.target.value })}>
              {FREQUENCIES.map((f) => <option key={f.key} value={f.key}>{f.label}</option>)}
            </select>
          </div>

          {builder.frequency === 'minutely' && (
            <div>
              <label className="label">Every N minutes</label>
              <input type="number" min="1" max="59" className="input" value={builder.interval}
                onChange={(e) => setBuilder({ ...builder, interval: e.target.value })} />
            </div>
          )}
          {['hourly', 'daily', 'weekly', 'monthly'].includes(builder.frequency) && (
            <div>
              <label className="label">Minute</label>
              <input type="number" min="0" max="59" className="input" value={builder.minute}
                onChange={(e) => setBuilder({ ...builder, minute: e.target.value })} />
            </div>
          )}
          {['daily', 'weekly', 'monthly'].includes(builder.frequency) && (
            <div>
              <label className="label">Hour (0-23)</label>
              <input type="number" min="0" max="23" className="input" value={builder.hour}
                onChange={(e) => setBuilder({ ...builder, hour: e.target.value })} />
            </div>
          )}
          {builder.frequency === 'weekly' && (
            <div>
              <label className="label">Day of week</label>
              <select className="select" value={builder.weekday}
                onChange={(e) => setBuilder({ ...builder, weekday: e.target.value })}>
                {DAYS.map((d, i) => <option key={d} value={i}>{d}</option>)}
              </select>
            </div>
          )}
          {builder.frequency === 'monthly' && (
            <div>
              <label className="label">Day of month</label>
              <input type="number" min="1" max="31" className="input" value={builder.day}
                onChange={(e) => setBuilder({ ...builder, day: e.target.value })} />
            </div>
          )}
          {builder.frequency === 'custom' && (
            <div className="sm:col-span-2">
              <label className="label">Cron expression</label>
              <input className="input font-mono" value={builder.custom}
                onChange={(e) => setBuilder({ ...builder, custom: e.target.value })} placeholder="0 9 * * 1-5" />
            </div>
          )}
        </div>
        <div className="mt-3 flex items-center gap-3">
          <span className="text-sm text-slate-500">Resulting cron:</span>
          <code className="text-sky-300 bg-slate-900 px-2 py-1 rounded">{cron}</code>
          <button className="btn-primary ml-auto" onClick={create}><Icon name="plus" size={15} />Add schedule</button>
        </div>
      </div>

      {/* Existing schedules */}
      <div className="card">
        <h3 className="section-title mb-4">Scheduled Scripts</h3>
        {schedules.length === 0 ? (
          <p className="text-slate-600 text-sm py-4 text-center">No schedules for this project yet.</p>
        ) : (
          <table className="w-full text-sm">
            <thead>
              <tr className="text-left text-xs uppercase text-slate-500 border-b border-panel-border">
                <th className="py-2">Script</th><th>Cron</th><th>Next run</th><th>Last run</th><th>Active</th><th></th>
              </tr>
            </thead>
            <tbody className="divide-y divide-panel-border">
              {schedules.map((s) => (
                <tr key={s.id}>
                  <td className="py-2 font-mono">{s.script_name}</td>
                  <td><code className="text-xs text-slate-400">{s.cron_expression}</code></td>
                  <td className="text-slate-400">{formatTime(s.next_run)}</td>
                  <td className="text-slate-400">{s.last_run ? formatTime(s.last_run + 'Z') : '—'}</td>
                  <td>
                    <button onClick={() => toggle(s.id)}
                      className={`badge ${s.is_active ? 'bg-green-500/15 text-green-400' : 'bg-slate-500/20 text-slate-400'}`}>
                      {s.is_active ? 'ON' : 'OFF'}
                    </button>
                  </td>
                  <td className="text-right space-x-2 whitespace-nowrap">
                    {s.last_status === 'RUNNING' && (
                      <button onClick={() => stopRun(s.script_id)}
                        className="inline-flex items-center gap-1.5 text-red-400 hover:underline">
                        <Icon name="stop" size={13} />stop
                      </button>
                    )}
                    <button onClick={() => remove(s.id)} className="text-red-400 hover:underline">delete</button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
    </div>
  )
}
