import { useCallback, useEffect, useRef, useState } from 'react'
import api, { errorMessage } from '../api/client'
import ProgressBar from './ProgressBar'

const LABELS = {} // filled from catalog

function fmtDate(iso) {
  if (!iso) return ''
  const d = new Date(iso)
  return isNaN(d) ? iso : d.toLocaleString()
}

/** Backup & restore: choose what to back up, list/download/delete/restore, import. */
export default function Backups() {
  const [catalog, setCatalog] = useState([])
  const [backups, setBackups] = useState([])
  const [sel, setSel] = useState({})            // create selection
  const [creating, setCreating] = useState(false)
  const [msg, setMsg] = useState(null)          // { text, error }
  const [busy, setBusy] = useState('')          // backup name being acted on
  const [restore, setRestore] = useState(null)  // { name, sel } restore dialog
  const [restarting, setRestarting] = useState(false)
  const [transfer, setTransfer] = useState(null) // { dir, name, pct }
  const fileRef = useRef(null)

  const load = useCallback(() => {
    api.get('/settings/backups').then((res) => {
      setCatalog(res.data.components)
      setBackups(res.data.backups)
      setSel((prev) =>
        Object.keys(prev).length
          ? prev
          : Object.fromEntries(res.data.components.map((c) => [c.key, true])))
    }).catch((err) => setMsg({ text: errorMessage(err), error: true }))
  }, [])

  useEffect(() => { load() }, [load])

  for (const c of catalog) LABELS[c.key] = c.label

  async function createBackup() {
    const components = Object.keys(sel).filter((k) => sel[k])
    if (!components.length) { setMsg({ text: 'Select at least one thing to back up.', error: true }); return }
    setCreating(true); setMsg(null)
    try {
      const res = await api.post('/settings/backups', { components })
      setMsg({ text: `Backup created: ${res.data.name} (${res.data.size_human})` })
      load()
    } catch (err) {
      setMsg({ text: errorMessage(err), error: true })
    } finally {
      setCreating(false)
    }
  }

  function download(name) {
    setTransfer({ dir: 'down', name, pct: 0 })
    api.get(`/settings/backups/${encodeURIComponent(name)}/download`, {
      responseType: 'blob',
      onDownloadProgress: (e) => {
        if (e.total) setTransfer((t) => t && { ...t, pct: Math.round((e.loaded / e.total) * 100) })
      },
    })
      .then((res) => {
        const url = URL.createObjectURL(res.data)
        const a = document.createElement('a')
        a.href = url; a.download = name; a.click()
        URL.revokeObjectURL(url)
      })
      .catch((err) => setMsg({ text: errorMessage(err), error: true }))
      .finally(() => setTransfer(null))
  }

  async function remove(name) {
    if (!window.confirm(`Delete backup ${name}? This cannot be undone.`)) return
    setBusy(name)
    try {
      await api.delete(`/settings/backups/${encodeURIComponent(name)}`)
      load()
    } catch (err) {
      setMsg({ text: errorMessage(err), error: true })
    } finally { setBusy('') }
  }

  async function importFile(e) {
    const file = e.target.files?.[0]
    if (!file) return
    setBusy('import'); setMsg(null)
    setTransfer({ dir: 'up', name: file.name, pct: 0 })
    try {
      const fd = new FormData()
      fd.append('file', file)
      const res = await api.post('/settings/backups/import', fd, {
        onUploadProgress: (e) => {
          if (e.total) setTransfer((t) => t && { ...t, pct: Math.round((e.loaded / e.total) * 100) })
        },
      })
      setMsg({ text: `Imported ${res.data.name}` })
      load()
    } catch (err) {
      setMsg({ text: errorMessage(err), error: true })
    } finally {
      setBusy(''); setTransfer(null); if (fileRef.current) fileRef.current.value = ''
    }
  }

  function openRestore(b) {
    const keys = b.components?.length ? b.components : catalog.map((c) => c.key)
    setRestore({ name: b.name, sel: Object.fromEntries(keys.map((k) => [k, true])) })
  }

  async function doRestore() {
    const components = Object.keys(restore.sel).filter((k) => restore.sel[k])
    if (!components.length) return
    if (!window.confirm(
      `Restore ${components.map((k) => LABELS[k] || k).join(', ')} from ${restore.name}?\n\n` +
      'This OVERWRITES current data (the existing copy is moved aside for rollback). Continue?')) return
    setBusy(restore.name); setMsg(null)
    try {
      const res = await api.post(`/settings/backups/${encodeURIComponent(restore.name)}/restore`, { components })
      setRestore(null)
      if (res.data.restart) {
        setRestarting(true)
        pollHealthAndReload()
      } else {
        setMsg({ text: `Restored: ${res.data.restored.map((k) => LABELS[k] || k).join(', ')}` })
      }
    } catch (err) {
      setMsg({ text: errorMessage(err), error: true })
    } finally { setBusy('') }
  }

  function pollHealthAndReload() {
    let down = false
    const t = setInterval(async () => {
      try {
        await api.get('/health', { timeout: 4000 })
        if (down) { clearInterval(t); window.location.reload() }
      } catch { down = true }
    }, 3000)
    setTimeout(() => { clearInterval(t); window.location.reload() }, 120000)
  }

  const last = backups[0]

  return (
    <div className="card space-y-4">
      <h3 className="font-semibold">Backup &amp; Restore</h3>

      {msg && (
        <p className={`text-sm ${msg.error ? 'text-red-400' : 'text-green-400'}`}>{msg.text}</p>
      )}

      {transfer && <ProgressBar dir={transfer.dir} name={transfer.name} pct={transfer.pct} />}

      {restarting && (
        <p className="text-sm text-sky-300">
          Panel database restored — the panel is restarting. This page will
          reload automatically when it's back.
        </p>
      )}

      {/* What to back up */}
      <div>
        <p className="text-sm text-slate-400 mb-2">Choose what to include:</p>
        <div className="grid sm:grid-cols-2 gap-2">
          {catalog.map((c) => (
            <label key={c.key} className="flex items-start gap-2 text-sm cursor-pointer">
              <input type="checkbox" className="mt-1"
                checked={!!sel[c.key]}
                onChange={(e) => setSel({ ...sel, [c.key]: e.target.checked })} />
              <span>
                <span className="text-slate-200">{c.label}</span>
                <span className="block text-xs text-slate-500">{c.desc}</span>
              </span>
            </label>
          ))}
        </div>
        <div className="flex items-center gap-3 mt-3">
          <button className="btn-primary" onClick={createBackup} disabled={creating}>
            {creating ? 'Creating backup…' : '＋ Create backup'}
          </button>
          <label className="btn-secondary cursor-pointer">
            {busy === 'import' ? 'Importing…' : '⬆ Import backup'}
            <input ref={fileRef} type="file" accept=".tar.gz,.tgz" className="hidden"
              onChange={importFile} disabled={busy === 'import'} />
          </label>
        </div>
      </div>

      {/* Last backup */}
      <div className="text-xs text-slate-500">
        {last
          ? <>Last backup: <span className="text-slate-300">{last.name}</span> · {fmtDate(last.created)} · {last.size_human}</>
          : 'No backups yet.'}
      </div>

      {/* Existing backups */}
      {backups.length > 0 && (
        <div className="divide-y divide-panel-border border border-panel-border rounded-lg">
          {backups.map((b) => (
            <div key={b.name} className="p-3 space-y-2">
              <div className="flex items-center justify-between gap-2 flex-wrap">
                <div className="min-w-0">
                  <p className="text-sm text-slate-200 truncate">{b.name}</p>
                  <p className="text-xs text-slate-500">{fmtDate(b.created)} · {b.size_human}</p>
                </div>
                <div className="flex items-center gap-2 text-xs">
                  <button className="px-2 py-1 rounded bg-slate-700 hover:bg-slate-600"
                    onClick={() => download(b.name)}>Download</button>
                  <button className="px-2 py-1 rounded bg-sky-700 hover:bg-sky-600"
                    onClick={() => openRestore(b)} disabled={busy === b.name}>Restore</button>
                  <button className="px-2 py-1 rounded bg-red-800 hover:bg-red-700"
                    onClick={() => remove(b.name)} disabled={busy === b.name}>Delete</button>
                </div>
              </div>
              {b.components?.length > 0 && (
                <div className="flex flex-wrap gap-1">
                  {b.components.map((k) => (
                    <span key={k} className="text-[10px] px-1.5 py-0.5 rounded bg-slate-800 text-slate-400">
                      {LABELS[k] || k}
                    </span>
                  ))}
                </div>
              )}

              {/* Restore dialog for this backup */}
              {restore?.name === b.name && (
                <div className="mt-2 p-3 rounded bg-slate-900/70 border border-sky-800 space-y-2">
                  <p className="text-xs text-sky-300">Select what to restore (overwrites current):</p>
                  <div className="grid sm:grid-cols-2 gap-1">
                    {Object.keys(restore.sel).map((k) => (
                      <label key={k} className="flex items-center gap-2 text-sm cursor-pointer">
                        <input type="checkbox" checked={!!restore.sel[k]}
                          onChange={(e) => setRestore({ ...restore, sel: { ...restore.sel, [k]: e.target.checked } })} />
                        {LABELS[k] || k}
                      </label>
                    ))}
                  </div>
                  <div className="flex gap-2">
                    <button className="btn-primary text-xs py-1" onClick={doRestore} disabled={busy === b.name}>
                      {busy === b.name ? 'Restoring…' : 'Restore now'}
                    </button>
                    <button className="text-xs text-slate-400 hover:text-slate-200" onClick={() => setRestore(null)}>
                      Cancel
                    </button>
                  </div>
                </div>
              )}
            </div>
          ))}
        </div>
      )}
    </div>
  )
}
