import { useCallback, useEffect, useState } from 'react'
import api, { errorMessage } from '../api/client'

function formatSize(bytes) {
  if (bytes == null) return '—'
  if (bytes < 1024) return `${bytes} B`
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`
  return `${(bytes / 1024 / 1024).toFixed(1)} MB`
}

function formatTime(iso) {
  return iso ? new Date(iso + (iso.endsWith('Z') ? '' : 'Z')).toLocaleString() : '—'
}

/** "in 5h 12m" until the item is auto-purged (or "expired"). */
function timeLeft(expiresIso) {
  if (!expiresIso) return '—'
  const ms = new Date(expiresIso + (expiresIso.endsWith('Z') ? '' : 'Z')).getTime() - Date.now()
  if (ms <= 0) return 'expiring…'
  const h = Math.floor(ms / 3_600_000)
  const m = Math.floor((ms % 3_600_000) / 60_000)
  return h > 0 ? `in ${h}h ${m}m` : `in ${m}m`
}

export default function RecycleBin() {
  const [items, setItems] = useState([])
  const [retention, setRetention] = useState(24)
  const [loading, setLoading] = useState(true)
  const [err, setErr] = useState('')

  const load = useCallback(() => {
    setErr('')
    api.get('/trash')
      .then((res) => {
        setItems(res.data.items || [])
        setRetention(res.data.retention_hours ?? 24)
      })
      .catch((e) => setErr(errorMessage(e)))
      .finally(() => setLoading(false))
  }, [])

  useEffect(() => { load() }, [load])

  async function restore(item) {
    try {
      const r = await api.post(`/trash/${item.id}/restore`)
      load()
      alert(r.data.detail)
    } catch (e) { alert(errorMessage(e)) }
  }

  async function remove(item) {
    if (!window.confirm(`Permanently delete "${item.name}"? This cannot be undone.`)) return
    try {
      await api.delete(`/trash/${item.id}`)
      load()
    } catch (e) { alert(errorMessage(e)) }
  }

  async function empty() {
    if (!items.length) return
    if (!window.confirm('Permanently delete everything in the recycle bin? This cannot be undone.')) return
    try {
      await api.post('/trash/empty')
      load()
    } catch (e) { alert(errorMessage(e)) }
  }

  return (
    <div className="max-w-5xl">
      <div className="flex items-center justify-between mb-4 gap-2 flex-wrap">
        <div>
          <h2 className="text-2xl font-bold">🗑️ Recycle Bin</h2>
          <p className="text-sm text-slate-500">
            Files deleted from Projects &amp; Websites in the last {retention} hours.
            Items are automatically removed {retention}h after deletion.
          </p>
        </div>
        <div className="flex gap-2">
          <button className="btn-secondary" onClick={load}>↻ Refresh</button>
          <button className="btn-secondary text-red-300" disabled={!items.length} onClick={empty}>
            Empty bin
          </button>
        </div>
      </div>

      {err && <p className="text-red-400 text-sm mb-3">{err}</p>}

      <div className="card">
        {loading ? (
          <p className="text-center text-slate-500 py-8">Loading…</p>
        ) : items.length === 0 ? (
          <p className="text-center text-slate-600 py-10">
            The recycle bin is empty.<br />
            <span className="text-xs text-slate-500">
              Deleted project &amp; website files show up here for {retention} hours.
            </span>
          </p>
        ) : (
          <table className="w-full text-sm">
            <thead>
              <tr className="text-left text-xs uppercase text-slate-500 border-b border-panel-border">
                <th className="py-2">Name</th>
                <th>Original location</th>
                <th>Size</th>
                <th>Deleted</th>
                <th>Auto-removes</th>
                <th className="text-right">Actions</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-panel-border">
              {items.map((item) => (
                <tr key={item.id}>
                  <td className="py-2 font-mono">
                    {item.is_dir ? '📁' : '📄'} {item.name}
                  </td>
                  <td className="text-slate-400 font-mono text-xs">{item.origin}</td>
                  <td>{item.is_dir ? '—' : formatSize(item.size)}</td>
                  <td className="text-slate-400">{formatTime(item.deleted_at)}</td>
                  <td className="text-amber-400 text-xs">{timeLeft(item.expires_at)}</td>
                  <td className="text-right space-x-2">
                    <button onClick={() => restore(item)} className="text-emerald-400 hover:underline">
                      Restore
                    </button>
                    <button onClick={() => remove(item)} className="text-red-400 hover:underline">
                      Delete
                    </button>
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
