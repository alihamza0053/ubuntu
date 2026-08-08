import { useCallback, useEffect, useState } from 'react'
import api, { errorMessage } from '../api/client'
import DataTable, { NameCell, RowActions } from '../components/ui/DataTable'
import Icon from '../components/ui/Icon'
import PageHeader from '../components/ui/PageHeader'
import { formatDateTime, parseServerDate } from '../lib/datetime'

function formatSize(bytes) {
  if (bytes == null) return '—'
  if (bytes < 1024) return `${bytes} B`
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`
  return `${(bytes / 1024 / 1024).toFixed(1)} MB`
}

const formatTime = (iso) => formatDateTime(iso)

/** "in 5h 12m" until the item is auto-purged (or "expired"). */
function timeLeft(expiresIso) {
  if (!expiresIso) return '—'
  const expiry = parseServerDate(expiresIso)
  if (!expiry) return '—'
  const ms = expiry.getTime() - Date.now()
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

  const columns = [
    {
      key: 'name',
      label: 'Name',
      render: (item) => (
        <NameCell
          icon={item.is_dir ? 'folder' : 'file'}
          tint={item.is_dir ? 'amber' : 'slate'}
          title={item.name}
          subtitle={item.origin}
        />
      ),
    },
    { key: 'size', label: 'Size', render: (item) => (item.is_dir ? '—' : formatSize(item.size)) },
    {
      key: 'deleted_at',
      label: 'Deleted',
      render: (item) => <span className="text-slate-400">{formatTime(item.deleted_at)}</span>,
    },
    {
      key: 'expires_at',
      label: 'Auto-removes',
      render: (item) => <span className="badge-warn">{timeLeft(item.expires_at)}</span>,
    },
    {
      key: 'actions',
      label: 'Actions',
      align: 'right',
      width: '9rem',
      render: (item) => (
        <RowActions>
          <button className="btn-icon" onClick={() => restore(item)} title="Restore">
            <Icon name="refresh" size={15} />
          </button>
          <button className="btn-icon-danger" onClick={() => remove(item)} title="Delete permanently">
            <Icon name="trash" size={15} />
          </button>
        </RowActions>
      ),
    },
  ]

  return (
    <div className="space-y-6">
      <PageHeader
        title="Recycle Bin"
        crumbs={[{ label: 'Storage' }, { label: 'Recycle Bin' }]}
        actions={
          <>
            <button className="btn-secondary" onClick={load}>
              <Icon name="refresh" size={15} />
              Refresh
            </button>
            <button className="btn-danger" disabled={!items.length} onClick={empty}>
              <Icon name="trash" size={15} />
              Empty bin
            </button>
          </>
        }
      >
        <p className="text-sm text-slate-500">
          Files deleted from Projects &amp; Websites in the last {retention} hours. Items are
          removed automatically {retention}h after deletion.
        </p>
      </PageHeader>

      {err && (
        <div className="flex items-start gap-2 rounded-lg border border-red-500/30 bg-red-500/10 px-3 py-2 text-sm text-red-300">
          <Icon name="warning" size={15} className="mt-0.5" />
          {err}
        </div>
      )}

      {loading ? (
        <div className="empty-state">Loading…</div>
      ) : (
        <DataTable
          columns={columns}
          rows={items}
          empty={`The recycle bin is empty. Deleted project & website files show up here for ${retention} hours.`}
        />
      )}
    </div>
  )
}
