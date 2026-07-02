import Editor from '@monaco-editor/react'
import { useEffect, useState } from 'react'
import api, { errorMessage } from '../../api/client'
import LiveLog from '../../components/LiveLog'

// Map file extension → Monaco language id
const LANGUAGES = {
  py: 'python', js: 'javascript', jsx: 'javascript', ts: 'typescript',
  json: 'json', yaml: 'yaml', yml: 'yaml', html: 'html', css: 'css',
  md: 'markdown', sql: 'sql', php: 'php', sh: 'shell', toml: 'ini',
  cfg: 'ini', ini: 'ini', conf: 'ini', txt: 'plaintext', csv: 'plaintext',
  log: 'plaintext',
}

function languageFor(filename) {
  const ext = filename.split('.').pop().toLowerCase()
  return LANGUAGES[ext] || 'plaintext'
}

/**
 * Code Editor tab: file tree (left) + Monaco (right) + Save / Run.
 *
 * initialFile: { folder, filename } passed when a file was clicked on the
 * Files tab so it opens immediately.
 */
export default function EditorTab({ project, files, initialFile }) {
  const [current, setCurrent] = useState(null) // { folder, filename, path }
  const [content, setContent] = useState('')
  const [dirty, setDirty] = useState(false)
  const [saving, setSaving] = useState(false)
  const [message, setMessage] = useState('')
  const [runWsPath, setRunWsPath] = useState(null)

  // Absolute path on the server (Linux-style; folder_path comes from the API)
  function absPath(folder, filename) {
    return `${project.folder_path}/${folder}/${filename}`
  }

  async function openFile(folder, filename) {
    if (dirty && !window.confirm('Discard unsaved changes?')) return
    try {
      const res = await api.get('/files/read', { params: { path: absPath(folder, filename) } })
      setCurrent({ folder, filename, path: res.data.path })
      setContent(res.data.content)
      setDirty(false)
      setMessage('')
    } catch (err) {
      alert(errorMessage(err))
    }
  }

  // Open the file handed over from the Files tab
  useEffect(() => {
    if (initialFile) openFile(initialFile.folder, initialFile.filename)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [initialFile])

  async function save() {
    if (!current) return
    setSaving(true)
    try {
      await api.post('/files/write', { path: current.path, content })
      setDirty(false)
      setMessage(`Saved ${current.filename} ✓`)
      setTimeout(() => setMessage(''), 3000)
    } catch (err) {
      alert(errorMessage(err))
    } finally {
      setSaving(false)
    }
  }

  async function runCurrent() {
    // Look up the script id, then stream the run over WebSocket
    try {
      const res = await api.get(`/projects/${project.id}/scripts`)
      const script = res.data.find(
        (s) => s.folder === current.folder && s.filename === current.filename,
      )
      if (!script) {
        alert('Only .py files in code/ or allscripts/ can be run')
        return
      }
      setRunWsPath(null) // reset so re-running the same script reconnects
      setTimeout(() => setRunWsPath(`/ws/script/${script.id}/run`), 0)
    } catch (err) {
      alert(errorMessage(err))
    }
  }

  // Ctrl+S to save
  useEffect(() => {
    function onKey(e) {
      if ((e.ctrlKey || e.metaKey) && e.key === 's') {
        e.preventDefault()
        save()
      }
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [current, content])

  const isPython = current?.filename.endsWith('.py')
  const canRun = isPython && ['code', 'allscripts'].includes(current?.folder)

  return (
    <div className="flex gap-4" style={{ minHeight: '60vh' }}>
      {/* File tree */}
      <aside className="w-56 shrink-0 card overflow-y-auto">
        <h4 className="text-xs uppercase tracking-wide text-slate-500 mb-2">Project files</h4>
        {files ? (
          Object.entries(files.folders).map(([folder, list]) => (
            <div key={folder} className="mb-3">
              <p className="font-mono text-xs text-slate-500">{folder}/</p>
              <ul>
                {list.map((file) => (
                  <li key={file.name}>
                    <button
                      onClick={() => openFile(folder, file.name)}
                      className={`w-full text-left px-2 py-1 rounded text-sm truncate ${
                        current?.folder === folder && current?.filename === file.name
                          ? 'bg-sky-600/20 text-sky-300'
                          : 'text-slate-300 hover:bg-slate-700/50'
                      }`}
                    >
                      {file.name}
                    </button>
                  </li>
                ))}
                {list.length === 0 && <li className="px-2 text-xs text-slate-700">empty</li>}
              </ul>
            </div>
          ))
        ) : (
          <p className="text-slate-500 text-sm">Loading…</p>
        )}
      </aside>

      {/* Editor area */}
      <div className="flex-1 min-w-0">
        <div className="flex items-center gap-2 mb-2">
          <span className="font-mono text-sm text-slate-400 truncate">
            {current ? `${current.folder}/${current.filename}${dirty ? ' •' : ''}` : 'No file open'}
          </span>
          {message && <span className="text-xs text-green-400">{message}</span>}
          <div className="ml-auto flex gap-2">
            {canRun && (
              <button className="btn-secondary" onClick={runCurrent}>▶ Run this file</button>
            )}
            <button className="btn-primary" onClick={save} disabled={!current || !dirty || saving}>
              {saving ? 'Saving…' : '💾 Save (Ctrl+S)'}
            </button>
          </div>
        </div>

        {current ? (
          <div className="border border-panel-border rounded-lg overflow-hidden">
            <Editor
              height="55vh"
              theme="vs-dark"
              language={languageFor(current.filename)}
              value={content}
              onChange={(value) => {
                setContent(value ?? '')
                setDirty(true)
              }}
              options={{ minimap: { enabled: false }, fontSize: 13 }}
            />
          </div>
        ) : (
          <div className="card h-[55vh] flex items-center justify-center text-slate-600">
            Select a file from the tree to start editing
          </div>
        )}

        {/* Live output when running the open .py file */}
        <LiveLog path={runWsPath} onClose={() => {}} />
      </div>
    </div>
  )
}
