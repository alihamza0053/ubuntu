import { useCallback, useEffect, useRef, useState } from 'react'
import api, { errorMessage, isCancel } from '../api/client'
import SpreadsheetModal from './SpreadsheetModal'
import EditorModal from './EditorModal'
import ProgressBar from './ProgressBar'
import { formatDateTime } from '../lib/datetime'
import Icon from './ui/Icon'

const EDITABLE_EXT = ['.py', '.txt', '.json', '.yaml', '.yml', '.md', '.toml', '.cfg', '.ini', '.log', '.sh', '.js', '.html', '.css', '.xml', '.sql', '.php', '.conf']
function isEditable(name) {
  const n = name.toLowerCase()
  return EDITABLE_EXT.some((ext) => n.endsWith(ext))
}

function formatSize(bytes) {
  if (bytes < 1024) return `${bytes} B`
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`
  return `${(bytes / 1024 / 1024).toFixed(1)} MB`
}

const formatTime = (iso) => formatDateTime(iso)

const SPREADSHEET_EXT = ['.csv', '.xlsx', '.xls']
function isSpreadsheet(name) {
  const n = name.toLowerCase()
  return SPREADSHEET_EXT.some((ext) => n.endsWith(ext))
}

/**
 * Reusable file browser rooted at a fixed server folder: navigate subfolders,
 * upload (button + drag-and-drop), make folders, download/delete, and open
 * spreadsheets in a viewer. Navigation is capped at rootPath (no climbing above).
 *
 * Props:
 *   rootPath  absolute server path this browser is rooted at
 *   accept    optional file-input accept filter (e.g. ".xlsx,.xls,.csv")
 *   viewer    open csv/xlsx/xls in the SpreadsheetModal (default true)
 *   emptyHint text shown when a folder is empty
 */
export default function FolderBrowser({ rootPath, accept, viewer = true, editable = false, onChanged, emptyHint = 'This folder is empty' }) {
  const [data, setData] = useState({ path: rootPath, parent: null, entries: [] })
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState('')
  const [viewing, setViewing] = useState(null)
  const [editing, setEditing] = useState(null)
  const [dragOver, setDragOver] = useState(false)
  const [transfer, setTransfer] = useState(null)   // { dir, name, pct }
  const transferRef = useRef(null)                 // AbortController for the above
  const inputRef = useRef(null)

  const path = data.path
  const atRoot = path === rootPath
  const rootName = rootPath.split('/').filter(Boolean).pop() || ''
  const rel = path.startsWith(rootPath) ? path.slice(rootPath.length).replace(/^\/+/, '') : ''

  const browse = useCallback((target) => {
    setErr('')
    api.get('/files/browse', { params: { path: target } })
      .then((res) => setData(res.data))
      .catch((e) => setErr(errorMessage(e)))
  }, [])

  // Ensure the root folder exists (portal/data folders may not yet), then browse.
  useEffect(() => {
    api.post('/files/mkdir', { path: rootPath })
      .catch(() => {})
      .finally(() => browse(rootPath))
  }, [browse, rootPath])

  async function upload(fileList) {
    if (!fileList.length) return
    const form = new FormData()
    for (const f of fileList) form.append('files', f)
    const name = fileList.length > 1 ? `${fileList.length} files` : fileList[0].name
    const controller = new AbortController()
    transferRef.current = controller
    setBusy(true)
    setTransfer({ dir: 'up', name, pct: 0 })
    try {
      await api.post('/files/upload', form, {
        params: { path },
        signal: controller.signal,
        onUploadProgress: (e) => {
          if (e.total) setTransfer((t) => t && { ...t, pct: Math.round((e.loaded / e.total) * 100) })
        },
      })
      browse(path)
      onChanged && onChanged()
    } catch (e) {
      // An aborted transfer is a deliberate user action, not an error to report.
      if (!isCancel(e)) alert(errorMessage(e))
      else browse(path)   // a cancelled upload may have landed partially
    } finally {
      setBusy(false); setTransfer(null); transferRef.current = null
    }
  }

  function download(entry) {
    const controller = new AbortController()
    transferRef.current = controller
    setTransfer({ dir: 'down', name: entry.name, pct: 0 })
    api.get('/files/download', {
      params: { path: entry.path },
      responseType: 'blob',
      signal: controller.signal,
      onDownloadProgress: (e) => {
        if (e.total) setTransfer((t) => t && { ...t, pct: Math.round((e.loaded / e.total) * 100) })
      },
    })
      .then((res) => {
        const url = URL.createObjectURL(res.data)
        const a = document.createElement('a')
        a.href = url
        a.download = entry.name
        a.click()
        URL.revokeObjectURL(url)
      })
      .catch((e) => { if (!isCancel(e)) alert(errorMessage(e)) })
      .finally(() => { setTransfer(null); transferRef.current = null })
  }

  /** Abort the in-flight upload/download behind the progress bar. */
  function cancelTransfer() {
    transferRef.current?.abort()
  }

  async function remove(entry) {
    if (!window.confirm(`Delete ${entry.name}${entry.is_dir ? '/ and its contents' : ''}?`)) return
    try {
      await api.delete('/files/delete', { data: { path: entry.path } })
      browse(path)
      onChanged && onChanged()
    } catch (e) { alert(errorMessage(e)) }
  }

  async function mkdir() {
    const name = prompt('New folder name:')
    if (!name || !name.trim()) return
    try {
      await api.post('/files/mkdir', { path: `${path}/${name.trim()}` })
      browse(path)
      onChanged && onChanged()
    } catch (e) { alert(errorMessage(e)) }
  }

  function onDrop(e) {
    e.preventDefault()
    setDragOver(false)
    const files = [...(e.dataTransfer?.files || [])]
    if (files.length) upload(files)
  }

  function iconFor(entry) {
    if (entry.is_dir) return 'folder'
    const n = entry.name.toLowerCase()
    if (n.endsWith('.xlsx') || n.endsWith('.xls')) return 'chart'
    return 'file'
  }

  return (
    <div>
      {/* Toolbar */}
      <div className="flex items-center gap-2 mb-3 text-sm flex-wrap">
        <button className="btn-secondary py-1" onClick={() => browse(rootPath)}><Icon name="server" size={15} />{rootName}</button>
        {!atRoot && (
          <button className="btn-secondary py-1" onClick={() => browse(data.parent)}><Icon name="chevron-up" size={15} />Up</button>
        )}
        {rel && <span className="font-mono text-slate-400 truncate">/{rel}</span>}
        <div className="ml-auto flex gap-2">
          <button className="btn-secondary py-1" onClick={mkdir}><Icon name="folder" size={15} />New folder</button>
          <button className="btn-primary py-1" disabled={busy} onClick={() => inputRef.current?.click()}>
            {busy ? 'Uploading…' : <><Icon name="upload" size={15} />Upload</>}
          </button>
        </div>
        <input
          ref={inputRef}
          type="file"
          multiple
          accept={accept}
          className="hidden"
          onChange={(e) => { upload([...e.target.files]); e.target.value = '' }}
        />
      </div>

      {err && <p className="text-red-400 text-sm mb-2">{err}</p>}

      {transfer && (
        <ProgressBar dir={transfer.dir} name={transfer.name} pct={transfer.pct}
                     onCancel={cancelTransfer} />
      )}

      {/* Drop zone wraps the listing */}
      <div
        onDragOver={(e) => { e.preventDefault(); setDragOver(true) }}
        onDragLeave={() => setDragOver(false)}
        onDrop={onDrop}
        className={`rounded-lg border-2 border-dashed transition-colors ${
          dragOver ? 'border-sky-500 bg-sky-500/10' : 'border-transparent'
        }`}
      >
        {dragOver && (
          <p className="text-center text-sky-400 py-6 text-sm">Drop files to upload to /{rel || rootName}</p>
        )}
        {!dragOver && (
          data.entries.length === 0 ? (
            <p className="text-center text-slate-600 py-8">
              {emptyHint}<br />
              <span className="text-xs text-slate-500">Drag files here or use the Upload button</span>
            </p>
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
                {data.entries.map((entry) => (
                  <tr key={entry.path}>
                    <td className="py-2 font-mono">
                      {entry.is_dir ? (
                        <button className="text-left transition-colors hover:text-mint-300" onClick={() => browse(entry.path)}>
                          <span className="inline-flex items-center gap-2"><Icon name={iconFor(entry)} size={15} className="text-slate-500" />{entry.name}</span>
                        </button>
                      ) : viewer && isSpreadsheet(entry.name) ? (
                        <button className="text-left transition-colors hover:text-mint-300" onClick={() => setViewing(entry)}>
                          <span className="inline-flex items-center gap-2"><Icon name={iconFor(entry)} size={15} className="text-slate-500" />{entry.name}</span>
                        </button>
                      ) : editable && isEditable(entry.name) ? (
                        <button className="text-left transition-colors hover:text-mint-300" onClick={() => setEditing(entry.path)}>
                          <span className="inline-flex items-center gap-2"><Icon name={iconFor(entry)} size={15} className="text-slate-500" />{entry.name}</span>
                        </button>
                      ) : (
                        <span><span className="inline-flex items-center gap-2"><Icon name={iconFor(entry)} size={15} className="text-slate-500" />{entry.name}</span></span>
                      )}
                    </td>
                    <td>{entry.is_dir ? '—' : formatSize(entry.size)}</td>
                    <td className="text-slate-400">{formatTime(entry.modified)}</td>
                    <td className="text-right space-x-2">
                      {viewer && !entry.is_dir && isSpreadsheet(entry.name) && (
                        <button onClick={() => setViewing(entry)} className="text-emerald-400 hover:underline">
                          Open
                        </button>
                      )}
                      {editable && !entry.is_dir && !isSpreadsheet(entry.name) && isEditable(entry.name) && (
                        <button onClick={() => setEditing(entry.path)} className="text-emerald-400 hover:underline">
                          Edit
                        </button>
                      )}
                      {!entry.is_dir && (
                        <button onClick={() => download(entry)} className="text-sky-400 hover:underline">
                          Download
                        </button>
                      )}
                      <button onClick={() => remove(entry)} className="text-red-400 hover:underline">
                        Delete
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )
        )}
      </div>

      {viewing && <SpreadsheetModal entry={viewing} onClose={() => setViewing(null)} />}
      {editing && (
        <EditorModal
          path={editing}
          onClose={() => { setEditing(null); browse(path); onChanged && onChanged() }}
        />
      )}
    </div>
  )
}
