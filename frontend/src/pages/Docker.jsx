import { useCallback, useEffect, useState } from 'react'
import api, { errorMessage } from '../api/client'
import LiveLog from '../components/LiveLog'

/**
 * Docker manager: live view of all containers, images and volumes with
 * start/stop/restart/remove. Auto-refreshes to stay in sync with reality.
 */
export default function Docker() {
  const [data, setData] = useState({ ready: true, containers: [], images: [], volumes: [] })
  const [tab, setTab] = useState('containers')
  const [logId, setLogId] = useState(null) // container id whose logs are shown
  const [msg, setMsg] = useState('')

  const refresh = useCallback(() => {
    api.get('/docker').then((res) => setData(res.data)).catch((err) => setMsg(errorMessage(err)))
  }, [])

  useEffect(() => {
    refresh()
    const t = setInterval(refresh, 5000) // keep in sync
    return () => clearInterval(t)
  }, [refresh])

  async function containerAction(cid, action) {
    if (action === 'remove' && !window.confirm('Remove this container?')) return
    setMsg('')
    try {
      await api.post(`/docker/containers/${cid}/${action}`)
      refresh()
    } catch (err) { setMsg(errorMessage(err)) }
  }

  async function removeImage(id) {
    if (!window.confirm('Remove this image?')) return
    try { await api.delete(`/docker/images/${id}`); refresh() }
    catch (err) { alert(errorMessage(err)) }
  }

  async function removeVolume(name) {
    if (!window.confirm(`Remove volume ${name}? Its data is lost.`)) return
    try { await api.delete(`/docker/volumes/${name}`); refresh() }
    catch (err) { alert(errorMessage(err)) }
  }

  async function prune() {
    if (!window.confirm('Prune unused containers, networks and dangling images?')) return
    try { const r = await api.post('/docker/prune'); setMsg(r.data.detail); refresh() }
    catch (err) { setMsg(errorMessage(err)) }
  }

  if (!data.ready) {
    return (
      <div className="space-y-4">
        <h2 className="text-2xl font-bold">Docker</h2>
        <div className="card border-yellow-600/50 bg-yellow-500/5">
          <p className="text-sm text-yellow-300 font-semibold">Docker isn't installed</p>
          <p className="text-sm text-slate-400 mt-1">
            Install the <b>Docker Engine</b> app from the <a href="/apps" className="text-sky-400 hover:underline">Apps</a> page, then manage containers here.
          </p>
        </div>
      </div>
    )
  }

  const TABS = [
    ['containers', `Containers (${data.containers.length})`],
    ['images', `Images (${data.images.length})`],
    ['volumes', `Volumes (${data.volumes.length})`],
  ]

  return (
    <div className="space-y-4">
      <div className="flex items-center gap-3 flex-wrap">
        <h2 className="text-2xl font-bold">Docker</h2>
        <button className="btn-secondary ml-auto" onClick={refresh}>↻ Refresh</button>
        <button className="btn-secondary" onClick={prune}>🧹 Prune</button>
      </div>
      {msg && <p className="text-sm text-slate-400 break-words">{msg}</p>}

      <div className="flex gap-1 border-b border-panel-border">
        {TABS.map(([k, label]) => (
          <button key={k} onClick={() => setTab(k)}
            className={`px-4 py-2 text-sm border-b-2 -mb-px ${
              tab === k ? 'border-sky-400 text-sky-300' : 'border-transparent text-slate-400 hover:text-slate-200'
            }`}>{label}</button>
        ))}
      </div>

      {/* Containers */}
      {tab === 'containers' && (
        <div className="card overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="text-left text-xs uppercase text-slate-500 border-b border-panel-border">
                <th className="py-2">Name</th><th>Image</th><th>State</th><th>Ports</th><th className="text-right">Actions</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-panel-border">
              {data.containers.map((c) => (
                <tr key={c.id}>
                  <td className="py-2 font-mono">
                    {c.managed && <span title="Installed via the panel">🔗 </span>}{c.name}
                  </td>
                  <td className="text-slate-400 font-mono text-xs">{c.image}</td>
                  <td>
                    <span className={`badge ${c.state === 'running' ? 'bg-green-500/15 text-green-400' : 'bg-slate-500/20 text-slate-400'}`}>
                      {c.state}
                    </span>
                  </td>
                  <td className="text-xs text-slate-500 font-mono">{c.ports}</td>
                  <td className="text-right space-x-2 whitespace-nowrap">
                    {c.state === 'running'
                      ? <button onClick={() => containerAction(c.id, 'stop')} className="text-slate-400 hover:underline">stop</button>
                      : <button onClick={() => containerAction(c.id, 'start')} className="text-green-400 hover:underline">start</button>}
                    <button onClick={() => containerAction(c.id, 'restart')} className="text-sky-400 hover:underline">restart</button>
                    <button onClick={() => setLogId(logId === c.id ? null : c.id)} className="text-slate-400 hover:underline">logs</button>
                    <button onClick={() => containerAction(c.id, 'remove')} className="text-red-400 hover:underline">remove</button>
                  </td>
                </tr>
              ))}
              {data.containers.length === 0 && <tr><td colSpan={5} className="py-6 text-center text-slate-600">No containers</td></tr>}
            </tbody>
          </table>
          {logId && (
            <div className="mt-3">
              <p className="text-xs text-slate-500 mb-1">Logs — {logId.slice(0, 12)}</p>
              <LiveLog path={`/ws/docker/containers/${logId}/logs`} />
            </div>
          )}
        </div>
      )}

      {/* Images */}
      {tab === 'images' && (
        <div className="card overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="text-left text-xs uppercase text-slate-500 border-b border-panel-border">
                <th className="py-2">Image</th><th>Size</th><th>Created</th><th className="text-right">Actions</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-panel-border">
              {data.images.map((i) => (
                <tr key={i.id}>
                  <td className="py-2 font-mono text-xs">{i.name}</td>
                  <td className="text-slate-400">{i.size}</td>
                  <td className="text-slate-500 text-xs">{i.created}</td>
                  <td className="text-right">
                    <button onClick={() => removeImage(i.id)} className="text-red-400 hover:underline">remove</button>
                  </td>
                </tr>
              ))}
              {data.images.length === 0 && <tr><td colSpan={4} className="py-6 text-center text-slate-600">No images</td></tr>}
            </tbody>
          </table>
        </div>
      )}

      {/* Volumes */}
      {tab === 'volumes' && (
        <div className="card overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="text-left text-xs uppercase text-slate-500 border-b border-panel-border">
                <th className="py-2">Volume</th><th>Driver</th><th className="text-right">Actions</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-panel-border">
              {data.volumes.map((v) => (
                <tr key={v.name}>
                  <td className="py-2 font-mono text-xs">{v.name}</td>
                  <td className="text-slate-400">{v.driver}</td>
                  <td className="text-right">
                    <button onClick={() => removeVolume(v.name)} className="text-red-400 hover:underline">remove</button>
                  </td>
                </tr>
              ))}
              {data.volumes.length === 0 && <tr><td colSpan={3} className="py-6 text-center text-slate-600">No volumes</td></tr>}
            </tbody>
          </table>
        </div>
      )}
    </div>
  )
}
