import { useCallback, useEffect, useRef, useState } from 'react'
import api, { errorMessage } from '../../api/client'
import SpreadsheetModal from '../../components/SpreadsheetModal'

const SPREADSHEET_EXT = ['.csv', '.xlsx', '.xls']
function isSpreadsheet(name) {
  const n = name.toLowerCase()
  return SPREADSHEET_EXT.some((ext) => n.endsWith(ext))
}

function formatSize(bytes) {
  if (bytes < 1024) return `${bytes} B`
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`
  return `${(bytes / 1024 / 1024).toFixed(1)} MB`
}

function formatTime(iso) {
  return iso ? new Date(iso + 'Z').toLocaleString() : '—'
}

/**
 * Data Files tab: browse the project's data/ folder AND its subfolders — open
 * folders, and upload / download / delete files at any level.
 */
export default function DataFilesTab({ project }) {
  const dataRoot = `${project.folder_path}/data`
  const [data, setData] = useState({ path: dataRoot, parent: null, entries: [] })
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState('')
  const [viewing, setViewing] = useState(null)
  const inputRef = useRef(null)

  const path = data.path
  const atRoot = path === dataRoot
  const rel = path.startsWith(dataRoot) ? path.slice(dataRoot.length).replace(/^\/+/, '') : ''

  const browse = useCallback((target) => {
    setErr('')
    api.get('/files/browse', { params: { path: target } })
      .then((res) => setData(res.data))
      .catch((e) => setErr(errorMessage(e)))
  }, [])

  useEffect(() => { browse(dataRoot) }, [browse, dataRoot])

  async function upload(fileList) {
    if (!fileList.length) return
    const form = new FormData()
    for (const f of fileList) form.append('files', f)
    setBusy(true)
    try {
      await api.post('/files/upload', form, { params: { path } })
      browse(path)
    } catch (e) { alert(errorMessage(e)) } finally { setBusy(false) }
  }

  function download(entry) {
    api.get('/files/download', { params: { path: entry.path }, responseType: 'blob' })
      .then((res) => {
        const url = URL.createObjectURL(res.data)
        const a = document.createElement('a')
        a.href = url
        a.download = entry.name
        a.click()
        URL.revokeObjectURL(url)
      })
      .catch((e) => alert(errorMessage(e)))
  }

  async function remove(entry) {
    if (!window.confirm(`Delete ${entry.name}${entry.is_dir ? '/ and its contents' : ''}?`)) return
    try {
      await api.delete('/files/delete', { data: { path: entry.path } })
      browse(path)
    } catch (e) { alert(errorMessage(e)) }
  }

  async function mkdir() {
    const name = prompt('New folder name:')
    if (!name || !name.trim()) return
    try {
      await api.post('/files/mkdir', { path: `${path}/${name.trim()}` })
      browse(path)
    } catch (e) { alert(errorMessage(e)) }
  }

  function iconFor(entry) {
    if (entry.is_dir) return '📁'
    const n = entry.name.toLowerCase()
    if (n.endsWith('.csv')) return '📄'
    if (n.endsWith('.xlsx') || n.endsWith('.xls')) return '📊'
    return '📄'
  }

  return (
    <div className="card">
      <div className="flex items-center justify-between mb-3 gap-2 flex-wrap">
        <div>
          <h3 className="font-semibold">Data Files</h3>
          <p className="text-xs text-slate-500">
            <span className="font-mono">data/{rel}</span> — used by your scripts
          </p>
        </div>
        <div className="flex gap-2">
          <button className="btn-secondary" onClick={mkdir}>📁＋ New folder</button>
          <button className="btn-primary" disabled={busy} onClick={() => inputRef.current?.click()}>
            {busy ? 'Uploading…' : '⬆ Upload'}
          </button>
        </div>
        <input
          ref={inputRef}
          type="file"
          multiple
          accept=".xlsx,.xls,.csv"
          className="hidden"
          onChange={(e) => { upload([...e.target.files]); e.target.value = '' }}
        />
      </div>

      {/* Breadcrumb / Up */}
      <div className="flex items-center gap-2 mb-3 text-sm">
        <button className="btn-secondary py-1" onClick={() => browse(dataRoot)}>🏠 data</button>
        {!atRoot && (
          <button className="btn-secondary py-1" onClick={() => browse(data.parent)}>⬆ Up</button>
        )}
        {rel && <span className="font-mono text-slate-400 truncate">/{rel}</span>}
      </div>

      {err && <p className="text-red-400 text-sm mb-2">{err}</p>}

      {data.entries.length === 0 ? (
        <p className="text-center text-slate-600 py-8">This folder is empty</p>
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
                    <button className="hover:text-sky-400" onClick={() => browse(entry.path)}>
                      {iconFor(entry)} {entry.name}
                    </button>
                  ) : isSpreadsheet(entry.name) ? (
                    <button className="hover:text-sky-400" onClick={() => setViewing(entry)}>
                      {iconFor(entry)} {entry.name}
                    </button>
                  ) : (
                    <span>{iconFor(entry)} {entry.name}</span>
                  )}
                </td>
                <td>{entry.is_dir ? '—' : formatSize(entry.size)}</td>
                <td className="text-slate-400">{formatTime(entry.modified)}</td>
                <td className="text-right space-x-2">
                  {!entry.is_dir && isSpreadsheet(entry.name) && (
                    <button onClick={() => setViewing(entry)} className="text-emerald-400 hover:underline">
                      Open
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
      )}

      {viewing && <SpreadsheetModal entry={viewing} onClose={() => setViewing(null)} />}
    </div>
  )
}
