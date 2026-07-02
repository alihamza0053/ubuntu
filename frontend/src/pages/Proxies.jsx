import { useCallback, useEffect, useState } from 'react'
import api, { errorMessage } from '../api/client'

/**
 * Proxies: expose any local service (a Docker container, or a uvicorn/Flask/
 * Node app on 127.0.0.1:PORT) on a domain with SSL. The panel writes the nginx
 * reverse-proxy block; you keep running the service however you like.
 */
export default function Proxies() {
  const [proxies, setProxies] = useState([])
  const [loading, setLoading] = useState(true)
  const [showModal, setShowModal] = useState(false)
  const [form, setForm] = useState({ name: '', upstream_port: '' })
  const [error, setError] = useState('')

  const refresh = useCallback(() => {
    api.get('/proxies').then((res) => setProxies(res.data)).finally(() => setLoading(false))
  }, [])

  useEffect(() => { refresh() }, [refresh])

  async function create(e) {
    e.preventDefault()
    setError('')
    try {
      await api.post('/proxies', {
        name: form.name,
        upstream_port: parseInt(form.upstream_port, 10),
      })
      setShowModal(false)
      setForm({ name: '', upstream_port: '' })
      refresh()
    } catch (err) {
      setError(errorMessage(err))
    }
  }

  async function remove(p) {
    if (!window.confirm(`Remove proxy "${p.name}"? (your service keeps running; only the domain mapping is removed)`)) return
    try {
      await api.delete(`/proxies/${p.id}`)
      refresh()
    } catch (err) {
      alert(errorMessage(err))
    }
  }

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h2 className="text-2xl font-bold">Proxies</h2>
          <p className="text-sm text-slate-500">
            Put a domain + SSL in front of any local service (Docker container, uvicorn, Flask, Node…).
          </p>
        </div>
        <button className="btn-primary" onClick={() => setShowModal(true)}>＋ New Proxy</button>
      </div>

      {loading ? (
        <p className="text-slate-500">Loading…</p>
      ) : proxies.length === 0 ? (
        <div className="card text-center py-12 text-slate-500">
          No proxies yet. Run your app on a localhost port (e.g. a Docker container on
          <span className="font-mono"> 127.0.0.1:9100</span>), then create a proxy pointing at that port.
        </div>
      ) : (
        <div className="grid md:grid-cols-2 xl:grid-cols-3 gap-4">
          {proxies.map((p) => <ProxyCard key={p.id} proxy={p} onChanged={refresh} onDelete={remove} />)}
        </div>
      )}

      {showModal && (
        <div className="fixed inset-0 bg-black/60 flex items-center justify-center z-50 px-4">
          <form onSubmit={create} className="card w-full max-w-md space-y-3">
            <h3 className="text-lg font-semibold">New Proxy</h3>
            {error && <p className="text-red-400 text-sm">{error}</p>}
            <div>
              <label className="block text-sm text-slate-400 mb-1">Name</label>
              <input className="input" placeholder="browser-automation" value={form.name}
                onChange={(e) => setForm({ ...form, name: e.target.value })} required />
            </div>
            <div>
              <label className="block text-sm text-slate-400 mb-1">Local port (127.0.0.1)</label>
              <input className="input" type="number" placeholder="9100" value={form.upstream_port}
                onChange={(e) => setForm({ ...form, upstream_port: e.target.value })} required />
              <p className="text-xs text-slate-500 mt-1">
                The port your service listens on locally. Bind your app to 127.0.0.1, not 0.0.0.0.
              </p>
            </div>
            <div className="flex justify-end gap-2">
              <button type="button" className="btn-secondary" onClick={() => setShowModal(false)}>Cancel</button>
              <button type="submit" className="btn-primary">Create</button>
            </div>
          </form>
        </div>
      )}
    </div>
  )
}

function ProxyCard({ proxy, onChanged, onDelete }) {
  const [domain, setDomain] = useState(proxy.domain || '')
  const [msg, setMsg] = useState('')

  async function assignDomain() {
    setMsg('')
    try {
      const r = await api.post(`/proxies/${proxy.id}/assign-domain`, { domain })
      setMsg(r.data.detail)
      onChanged()
    } catch (err) {
      setMsg(errorMessage(err))
    }
  }

  async function requestSsl() {
    setMsg('')
    try {
      const r = await api.post(`/proxies/${proxy.id}/ssl`)
      setMsg(r.data.detail)
    } catch (err) {
      setMsg(errorMessage(err))
    }
  }

  return (
    <div className="card space-y-3">
      <div className="flex items-start justify-between gap-2">
        <span className="font-semibold truncate">🔀 {proxy.name}</span>
        <span className={`badge ${proxy.live ? 'bg-green-500/15 text-green-400' : 'bg-slate-500/15 text-slate-400'}`}>
          {proxy.live ? 'service up' : 'no service'}
        </span>
      </div>

      <dl className="space-y-1.5 text-sm">
        <div className="flex justify-between gap-2">
          <dt className="text-slate-500">Upstream</dt>
          <dd className="font-mono text-slate-300">127.0.0.1:{proxy.upstream_port}</dd>
        </div>
        <div className="flex justify-between gap-2">
          <dt className="text-slate-500">URL</dt>
          <dd className="text-right">
            {proxy.domain ? (
              <a href={`http://${proxy.domain}`} target="_blank" rel="noreferrer"
                 className="text-sky-400 hover:underline">{proxy.domain} ↗</a>
            ) : <span className="text-slate-500">no domain yet</span>}
          </dd>
        </div>
      </dl>

      <div className="flex gap-2 items-center flex-wrap">
        <input className="input max-w-[12rem] py-1" placeholder="app.example.com"
          value={domain} onChange={(e) => setDomain(e.target.value)} />
        <button className="btn-secondary" onClick={assignDomain} disabled={!domain}>Domain</button>
        <button className="btn-secondary" onClick={requestSsl} disabled={!proxy.domain}>🔒 SSL</button>
      </div>

      {!proxy.live && (
        <p className="text-xs text-yellow-500/80">
          Nothing is listening on this port yet — start your service first, or it’ll return 502.
        </p>
      )}
      {msg && <p className="text-xs text-slate-400 break-words">{msg}</p>}

      <div className="text-right">
        <button onClick={() => onDelete(proxy)} className="text-xs text-red-400 hover:underline">remove</button>
      </div>
    </div>
  )
}
