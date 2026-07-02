import { useCallback, useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import api, { errorMessage } from '../../api/client'

function formatSize(bytes) {
  if (bytes < 1024) return `${bytes} B`
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`
  return `${(bytes / 1024 / 1024).toFixed(1)} MB`
}

function formatTime(iso) {
  return new Date(iso + 'Z').toLocaleString()
}

/**
 * OneDrive tab: read-only view of the project's mapped OneDrive subfolder.
 * Files are kept fresh by the panel's OneDrive sync monitor (set up in Apps).
 */
export default function OneDriveTab({ project }) {
  const [status, setStatus] = useState(null) // { installed, authorized, monitor, sync_dir }
  const [listing, setListing] = useState(null) // { mapped, subpath, parent, available, entries }
  const [subpath, setSubpath] = useState('')
  const [msg, setMsg] = useState('')
  const [picker, setPicker] = useState(null) // { path, entries } when open

  const loadStatus = useCallback(() => {
    api.get('/onedrive/status').then((r) => setStatus(r.data)).catch(() => setStatus(null))
  }, [])

  const loadListing = useCallback(() => {
    api
      .get(`/projects/${project.id}/onedrive`, { params: { subpath } })
      .then((r) => setListing(r.data))
      .catch((err) => setMsg(errorMessage(err)))
  }, [project.id, subpath])

  useEffect(() => { loadStatus() }, [loadStatus])
  useEffect(() => { loadListing() }, [loadListing])

  async function syncNow() {
    setMsg('Syncing…')
    try {
      const r = await api.post('/onedrive/monitor/restart')
      setMsg(r.data.detail)
      setTimeout(loadListing, 1500)
    } catch (err) {
      setMsg(errorMessage(err))
    }
  }

  function download(rel, name) {
    api
      .get(`/projects/${project.id}/onedrive/download`, {
        params: { path: rel }, responseType: 'blob',
      })
      .then((res) => {
        const url = URL.createObjectURL(res.data)
        const a = document.createElement('a')
        a.href = url
        a.download = name
        a.click()
        URL.revokeObjectURL(url)
      })
      .catch((err) => alert(errorMessage(err)))
  }

  // ---- folder picker (browse the OneDrive root, pick a subfolder) ----
  function openPicker() {
    browseTo(status?.sync_dir || '')
  }

  function browseTo(path) {
    api
      .get('/files/browse', { params: { path } })
      .then((r) => setPicker({ path: r.data.path, parent: r.data.parent, entries: r.data.entries }))
      .catch((err) => alert(errorMessage(err)))
  }

  async function selectFolder(absPath) {
    const root = status?.sync_dir || ''
    let rel = absPath
    if (root && absPath.startsWith(root)) rel = absPath.slice(root.length).replace(/^[/\\]+/, '')
    if (absPath === root) rel = ''
    try {
      await api.put(`/projects/${project.id}/onedrive-path`, { path: rel })
      setPicker(null)
      setSubpath('')
      loadListing()
    } catch (err) {
      alert(errorMessage(err))
    }
  }

  // OneDrive not set up yet → guide the user to the Apps page.
  if (status && (!status.installed || !status.authorized)) {
    return (
      <div className="card">
        <h3 className="font-semibold mb-2">☁️ OneDrive</h3>
        <p className="text-sm text-slate-400">
          {!status.installed
            ? 'The OneDrive client isn’t installed on this server yet.'
            : 'OneDrive is installed but not authorized yet.'}
        </p>
        <p className="text-sm text-slate-400 mt-2">
          Set it up once in the{' '}
          <Link to="/apps" className="text-sky-400 hover:underline">Apps</Link> page
          (Files &amp; Sync → OneDrive), then map a folder here.
        </p>
      </div>
    )
  }

  const crumbs = subpath ? subpath.split('/') : []

  return (
    <div className="card">
      <div className="flex items-center justify-between mb-4 gap-3 flex-wrap">
        <div className="min-w-0">
          <h3 className="font-semibold">☁️ OneDrive files</h3>
          <p className="text-xs text-slate-500">
            Mapped folder:{' '}
            <span className="font-mono text-slate-300">
              {listing?.mapped || '(none selected)'}
            </span>
            {status?.monitor && (
              <span className="ml-2">· monitor: <span className="text-slate-300">{status.monitor}</span></span>
            )}
          </p>
        </div>
        <div className="flex gap-2">
          <button className="btn-secondary" onClick={openPicker}>📁 Change folder</button>
          <button className="btn-secondary" onClick={syncNow}>🔄 Sync now</button>
        </div>
      </div>

      {/* Breadcrumb within the mapped folder */}
      {listing?.mapped !== undefined && (
        <div className="flex items-center gap-1 text-xs text-slate-400 mb-3 flex-wrap">
          <button className="hover:text-sky-300" onClick={() => setSubpath('')}>root</button>
          {crumbs.map((c, i) => (
            <span key={i} className="flex items-center gap-1">
              <span>/</span>
              <button
                className="hover:text-sky-300"
                onClick={() => setSubpath(crumbs.slice(0, i + 1).join('/'))}
              >{c}</button>
            </span>
          ))}
        </div>
      )}

      {!listing?.available ? (
        <p className="text-center text-slate-600 py-8">
          {listing?.mapped == null
            ? 'No OneDrive folder mapped yet — click “Change folder”.'
            : 'Folder not synced yet. Click “Sync now”, then refresh.'}
        </p>
      ) : listing.entries.length === 0 ? (
        <p className="text-center text-slate-600 py-8">This folder is empty.</p>
      ) : (
        <table className="w-full text-sm">
          <thead>
            <tr className="text-left text-xs uppercase text-slate-500 border-b border-panel-border">
              <th className="py-2">Name</th>
              <th>Size</th>
              <th>Last modified</th>
              <th className="text-right">Actions</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-panel-border">
            {listing.entries.map((e) => (
              <tr key={e.rel}>
                <td className="py-2 font-mono">
                  {e.is_dir ? (
                    <button className="hover:text-sky-300" onClick={() => setSubpath(e.rel)}>
                      📁 {e.name}
                    </button>
                  ) : (
                    <span>📄 {e.name}</span>
                  )}
                </td>
                <td>{e.is_dir ? '—' : formatSize(e.size)}</td>
                <td className="text-slate-400">{formatTime(e.modified)}</td>
                <td className="text-right">
                  {!e.is_dir && (
                    <button onClick={() => download(e.rel, e.name)} className="text-sky-400 hover:underline">
                      Download
                    </button>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}

      {msg && <p className="mt-3 text-xs text-slate-400 break-words">{msg}</p>}

      {/* Folder picker modal */}
      {picker && (
        <div className="fixed inset-0 bg-black/60 flex items-center justify-center z-50 p-4"
             onClick={() => setPicker(null)}>
          <div className="card max-w-lg w-full max-h-[80vh] overflow-auto" onClick={(e) => e.stopPropagation()}>
            <div className="flex items-center justify-between mb-3">
              <h3 className="font-semibold">Pick a OneDrive folder</h3>
              <button className="text-slate-500 hover:text-slate-300" onClick={() => setPicker(null)}>✕</button>
            </div>
            <p className="text-xs font-mono text-slate-400 mb-2 break-all">{picker.path || '/'}</p>
            <div className="flex gap-2 mb-3">
              {picker.parent != null && (
                <button className="btn-secondary" onClick={() => browseTo(picker.parent)}>⬆ Up</button>
              )}
              <button className="btn-primary ml-auto" onClick={() => selectFolder(picker.path)}>
                ✓ Use this folder
              </button>
            </div>
            <ul className="divide-y divide-panel-border">
              {picker.entries.filter((e) => e.is_dir).map((e) => (
                <li key={e.path}>
                  <button className="w-full text-left py-2 font-mono hover:text-sky-300"
                          onClick={() => browseTo(e.path)}>
                    📁 {e.name}
                  </button>
                </li>
              ))}
              {picker.entries.filter((e) => e.is_dir).length === 0 && (
                <li className="py-2 text-slate-600 text-sm">No subfolders here.</li>
              )}
            </ul>
          </div>
        </div>
      )}
    </div>
  )
}
