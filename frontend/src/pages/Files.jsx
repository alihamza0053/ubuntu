import { useCallback, useEffect, useRef, useState } from 'react'
import api, { errorMessage } from '../api/client'
import EditorModal from '../components/EditorModal'

const EDITABLE = ['.py', '.txt', '.json', '.yaml', '.yml', '.csv', '.md', '.html', '.htm',
  '.css', '.js', '.jsx', '.ts', '.tsx', '.php', '.sql', '.conf', '.cfg', '.ini', '.toml',
  '.env', '.sh', '.log', '.xml']

function isEditable(name) {
  return EDITABLE.some((ext) => name.toLowerCase().endsWith(ext))
}

function formatSize(bytes) {
  if (bytes < 1024) return `${bytes} B`
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`
  return `${(bytes / 1024 / 1024).toFixed(1)} MB`
}

function formatDate(iso) {
  if (!iso) return '—'
  const d = new Date(iso.endsWith('Z') ? iso : iso + 'Z') // backend sends UTC
  return isNaN(d.getTime()) ? '—' : d.toLocaleString()
}

/** Global server file manager confined to the panel-managed roots under /srv. */
export default function Files() {
  const [path, setPath] = useState('') // '' = roots listing
  const [data, setData] = useState({ entries: [], parent: null })
  const [editorPath, setEditorPath] = useState(null)
  const [error, setError] = useState('')
  const inputRef = useRef(null)
  const browseRequest = useRef(0)

  const browse = useCallback((target) => {
    const requestId = ++browseRequest.current
    setError('')
    api
      .get('/files/browse', { params: { path: target } })
      .then((res) => {
        if (requestId !== browseRequest.current) return
        setData(res.data)
        setPath(res.data.path)
      })
      .catch((err) => {
        // Ignore an older request that finished after the user navigated away.
        if (requestId === browseRequest.current) setError(errorMessage(err))
      })
  }, [])

  useEffect(() => {
    browse('')
  }, [browse])

  function open(entry) {
    if (entry.is_dir) browse(entry.path)
    else if (isEditable(entry.name)) setEditorPath(entry.path)
  }

  async function upload(files) {
    if (!path) {
      alert('Open a folder first')
      return
    }
    const form = new FormData()
    for (const f of files) form.append('files', f)
    try {
      await api.post('/files/upload', form, { params: { path } })
      browse(path)
    } catch (err) {
      alert(errorMessage(err))
    }
  }

  async function mkdir() {
    const name = prompt('New folder name:')
    if (!name) return
    try {
      await api.post('/files/mkdir', { path: `${path}/${name}` })
      browse(path)
    } catch (err) {
      alert(errorMessage(err))
    }
  }

  async function rename(entry) {
    const newName = prompt('Rename to:', entry.name)
    if (!newName || newName === entry.name) return
    try {
      await api.post('/files/rename', { path: entry.path, new_name: newName })
      browse(path)
    } catch (err) {
      alert(errorMessage(err))
    }
  }

  async function remove(entry) {
    if (!window.confirm(`Delete ${entry.name}${entry.is_dir ? '/ (and contents)' : ''}?`)) return
    try {
      await api.delete('/files/delete', { data: { path: entry.path } })
      browse(path)
    } catch (err) {
      alert(errorMessage(err))
    }
  }

  function download(entry) {
    api
      .get('/files/download', { params: { path: entry.path }, responseType: 'blob' })
      .then((res) => {
        const url = URL.createObjectURL(res.data)
        const a = document.createElement('a')
        a.href = url
        a.download = entry.name
        a.click()
        URL.revokeObjectURL(url)
      })
      .catch((err) => alert(errorMessage(err)))
  }

  return (
    <div className="space-y-4">
      <h2 className="text-2xl font-bold">File Manager</h2>

      <div className="card">
        {/* Toolbar */}
        <div className="flex items-center gap-2 mb-3 flex-wrap">
          <button className="btn-secondary" onClick={() => browse('/opt')}>Open /opt</button>
          <button className="btn-secondary" onClick={() => browse('')}>🏠 Roots</button>
          {data.parent !== null && (
            <button className="btn-secondary" onClick={() => browse(data.parent)}>⬆ Up</button>
          )}
          <span className="font-mono text-sm text-slate-400 truncate">{path || '/srv (managed roots)'}</span>
          <div className="ml-auto flex gap-2">
            {path && <button className="btn-secondary" onClick={mkdir}>📁＋ New folder</button>}
            {path && (
              <button className="btn-primary" onClick={() => inputRef.current?.click()}>⬆ Upload</button>
            )}
            <input
              ref={inputRef}
              type="file"
              multiple
              className="hidden"
              onChange={(e) => {
                upload([...e.target.files])
                e.target.value = ''
              }}
            />
          </div>
        </div>

        {error && <p className="text-red-400 text-sm mb-2">{error}</p>}

        {/* Listing */}
        <table className="w-full text-sm">
          <thead>
            <tr className="text-left text-xs uppercase text-slate-500 border-b border-panel-border">
              <th className="py-2">Name</th>
              <th>Size</th>
              <th>Modified</th>
              <th className="text-right">Actions</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-panel-border">
            {data.entries.map((entry) => (
              <tr key={entry.path}>
                <td className="py-2">
                  <button onClick={() => open(entry)} className="hover:text-sky-400">
                    {entry.is_dir ? '📁' : isEditable(entry.name) ? '📝' : '📄'} {entry.name}
                  </button>
                </td>
                <td className="text-slate-500">{entry.is_dir ? '—' : formatSize(entry.size)}</td>
                <td className="text-slate-400 whitespace-nowrap">{formatDate(entry.modified)}</td>
                <td className="text-right space-x-2 whitespace-nowrap">
                  {!entry.is_dir && (
                    <button onClick={() => download(entry)} className="text-sky-400 hover:underline">⬇</button>
                  )}
                  <button onClick={() => rename(entry)} className="text-slate-400 hover:underline">✎</button>
                  <button onClick={() => remove(entry)} className="text-red-400 hover:underline">🗑</button>
                </td>
              </tr>
            ))}
            {data.entries.length === 0 && (
              <tr><td colSpan={4} className="py-6 text-center text-slate-600">empty</td></tr>
            )}
          </tbody>
        </table>
      </div>

      <EditorModal
        path={editorPath}
        onClose={() => {
          setEditorPath(null)
        }}
      />
    </div>
  )
}
