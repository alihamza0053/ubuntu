import { useCallback, useEffect, useMemo, useState } from 'react'
import api, { errorMessage } from '../api/client'
import WebsiteCard from '../components/WebsiteCard'
import Icon from '../components/ui/Icon'
import Modal, { FormError } from '../components/ui/Modal'
import PageHeader from '../components/ui/PageHeader'
import Tabs from '../components/ui/Tabs'
import { useAuth } from '../context/AuthContext'

const FILTERS = [
  { key: 'all', label: 'All sites' },
  { key: 'html', label: 'Static' },
  { key: 'react', label: 'React' },
  { key: 'php', label: 'PHP' },
  { key: 'python', label: 'Python' },
]

export default function Websites() {
  const { isAdmin } = useAuth()
  const [sites, setSites] = useState([])
  const [loading, setLoading] = useState(true)
  const [showModal, setShowModal] = useState(false)
  const [form, setForm] = useState({ name: '', type: 'html', db_name: '', framework: '' })
  const [error, setError] = useState('')
  const [filter, setFilter] = useState('all')
  const [query, setQuery] = useState('')

  const refresh = useCallback(() => {
    api.get('/websites').then((res) => setSites(res.data)).finally(() => setLoading(false))
  }, [])

  useEffect(() => {
    refresh()
  }, [refresh])

  // Tab counts stay live as sites are added/removed.
  const tabs = useMemo(
    () =>
      FILTERS.map((f) => ({
        ...f,
        count: f.key === 'all' ? sites.length : sites.filter((s) => s.type === f.key).length,
      })),
    [sites],
  )

  const visible = useMemo(() => {
    const q = query.trim().toLowerCase()
    return sites.filter(
      (s) =>
        (filter === 'all' || s.type === filter) &&
        (!q || s.name.toLowerCase().includes(q) || (s.domain || '').toLowerCase().includes(q)),
    )
  }, [sites, filter, query])

  async function create(e) {
    e.preventDefault()
    setError('')
    try {
      await api.post('/websites', { ...form, framework: form.type === 'python' ? form.framework : null })
      setShowModal(false)
      setForm({ name: '', type: 'html', db_name: '', framework: '' })
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
      <PageHeader
        title="Websites"
        crumbs={[{ label: 'Hosting' }, { label: 'Websites' }]}
        actions={
          <>
            <div className="search-pill w-52">
              <Icon name="search" size={15} className="text-slate-500" />
              <input
                value={query}
                placeholder="Search name or domain…"
                onChange={(e) => setQuery(e.target.value)}
              />
            </div>
            <button className="btn-secondary" onClick={refresh}>
              <Icon name="refresh" size={15} />
              Refresh
            </button>
            <button className="btn-primary" onClick={() => setShowModal(true)}>
              <Icon name="plus" size={15} />
              New Website
            </button>
          </>
        }
      />

      <Tabs tabs={tabs} active={filter} onChange={setFilter} />

      {loading ? (
        <div className="empty-state">Loading…</div>
      ) : visible.length === 0 ? (
        <div className="empty-state">
          <Icon name="globe" size={26} className="text-slate-600" />
          {sites.length === 0 ? (
            <>
              <p className="text-slate-400">No websites yet</p>
              <p className="max-w-md text-sm">
                Create one, then upload a .zip of your Flask/FastAPI app, React build, PHP or
                static HTML site.
              </p>
              <button className="btn-primary mt-2" onClick={() => setShowModal(true)}>
                <Icon name="plus" size={15} />
                New Website
              </button>
            </>
          ) : (
            <p>No website matches this filter.</p>
          )}
        </div>
      ) : (
        <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
          {visible.map((s) => (
            <WebsiteCard
              key={s.id}
              site={s}
              onDelete={remove}
              onToggleHidden={isAdmin ? toggleHidden : undefined}
            />
          ))}
        </div>
      )}

      {showModal && (
        <Modal
          as="form"
          onSubmit={create}
          title="New Website"
          subtitle="Sets up the folder, supervisor entry and nginx config for a new site."
          onClose={() => setShowModal(false)}
          footer={
            <>
              <button type="button" className="btn-secondary" onClick={() => setShowModal(false)}>
                Cancel
              </button>
              <button type="submit" className="btn-primary">Create website</button>
            </>
          }
        >
          <FormError>{error}</FormError>

          <div>
            <label className="label">Site name</label>
            <input
              className="input"
              placeholder="site-name"
              value={form.name}
              onChange={(e) => setForm({ ...form, name: e.target.value })}
              autoFocus
              required
            />
          </div>

          <div>
            <label className="label">Type</label>
            <select
              className="select"
              value={form.type}
              onChange={(e) =>
                setForm({
                  ...form,
                  type: e.target.value,
                  // Flask is the common case for "I wrote a Python web app".
                  framework: e.target.value === 'python' ? form.framework || 'flask' : '',
                })
              }
            >
              <option value="html">Static HTML/CSS/JS</option>
              <option value="react">React (build → dist/)</option>
              <option value="php">PHP</option>
              <option value="python">Python app — upload &amp; run</option>
            </select>
          </div>

          {form.type === 'python' && (
            <div>
              <label className="label">Framework</label>
              <select
                className="select"
                value={form.framework}
                onChange={(e) => setForm({ ...form, framework: e.target.value })}
              >
                <option value="flask">Flask — served by gunicorn</option>
                <option value="fastapi">FastAPI — served by uvicorn</option>
                <option value="other">Other — I&apos;ll write the run command</option>
              </select>
              <p className="mt-1.5 text-xs text-slate-500">
                Sets the default run command and installs the right server. After you upload your
                zip the panel reads your code and adjusts this automatically.
              </p>
            </div>
          )}

          <div>
            <label className="label">Linked database (optional)</label>
            <input
              className="input"
              placeholder="database name"
              value={form.db_name}
              onChange={(e) => setForm({ ...form, db_name: e.target.value })}
            />
          </div>
        </Modal>
      )}
    </div>
  )
}
