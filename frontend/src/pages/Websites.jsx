import { useCallback, useEffect, useState } from 'react'
import api, { errorMessage } from '../api/client'
import WebsiteCard from '../components/WebsiteCard'
import { useAuth } from '../context/AuthContext'

export default function Websites() {
  const { isAdmin } = useAuth()
  const [sites, setSites] = useState([])
  const [loading, setLoading] = useState(true)
  const [showModal, setShowModal] = useState(false)
  const [form, setForm] = useState({ name: '', type: 'html', db_name: '' })
  const [error, setError] = useState('')

  const refresh = useCallback(() => {
    api.get('/websites').then((res) => setSites(res.data)).finally(() => setLoading(false))
  }, [])

  useEffect(() => {
    refresh()
  }, [refresh])

  async function create(e) {
    e.preventDefault()
    setError('')
    try {
      await api.post('/websites', form)
      setShowModal(false)
      setForm({ name: '', type: 'html', db_name: '' })
      refresh()
    } catch (err) {
      setError(errorMessage(err))
    }
  }

  async function toggleHidden(site) {
    try {
      await api.put(`/websites/${site.id}/hidden`, { hidden: !site.hidden })
      refresh()
    } catch (err) {
      alert(errorMessage(err))
    }
  }

  async function remove(site) {
    const delFiles = window.confirm(
      `Delete website "${site.name}"?\n\nOK = also delete its files\nCancel = keep files (panel entry only)`,
    )
    try {
      await api.delete(`/websites/${site.id}`, { params: { delete_files: delFiles } })
      refresh()
    } catch (err) {
      alert(errorMessage(err))
    }
  }

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <h2 className="text-2xl font-bold">Websites</h2>
        <button className="btn-primary" onClick={() => setShowModal(true)}>＋ New Website</button>
      </div>

      {loading ? (
        <p className="text-slate-500">Loading…</p>
      ) : sites.length === 0 ? (
        <div className="card text-center py-12 text-slate-500">
          No websites yet — create one, then upload a .zip of your React build, PHP, or static HTML site.
        </div>
      ) : (
        <div className="grid md:grid-cols-2 xl:grid-cols-3 gap-4">
          {sites.map((s) => (
            <WebsiteCard key={s.id} site={s} onDelete={remove}
              onToggleHidden={isAdmin ? toggleHidden : undefined} />
          ))}
        </div>
      )}

      {showModal && (
        <div className="fixed inset-0 bg-black/60 flex items-center justify-center z-50 px-4">
          <form onSubmit={create} className="card w-full max-w-md space-y-3">
            <h3 className="text-lg font-semibold">New Website</h3>
            {error && <p className="text-red-400 text-sm">{error}</p>}
            <input className="input" placeholder="site-name" value={form.name}
              onChange={(e) => setForm({ ...form, name: e.target.value })} required />
            <div>
              <label className="block text-sm text-slate-400 mb-1">Type</label>
              <select className="input" value={form.type} onChange={(e) => setForm({ ...form, type: e.target.value })}>
                <option value="html">Static HTML/CSS/JS</option>
                <option value="react">React (build → dist/)</option>
                <option value="php">PHP</option>
                <option value="python">Python (FastAPI/Flask) — upload &amp; run</option>
              </select>
            </div>
            <input className="input" placeholder="linked database name (optional)" value={form.db_name}
              onChange={(e) => setForm({ ...form, db_name: e.target.value })} />
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
