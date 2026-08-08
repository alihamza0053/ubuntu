import Editor from '@monaco-editor/react'
import { useEffect, useState } from 'react'
import api, { errorMessage } from '../api/client'

// Map extension → Monaco language id
const LANGUAGES = {
  py: 'python', js: 'javascript', jsx: 'javascript', ts: 'typescript', tsx: 'typescript',
  json: 'json', yaml: 'yaml', yml: 'yaml', html: 'html', htm: 'html', css: 'css',
  md: 'markdown', sql: 'sql', php: 'php', sh: 'shell', toml: 'ini', cfg: 'ini',
  ini: 'ini', conf: 'ini', txt: 'plaintext', csv: 'plaintext', log: 'plaintext', xml: 'xml',
}

function languageFor(path) {
  const ext = (path.split('.').pop() || '').toLowerCase()
  return LANGUAGES[ext] || 'plaintext'
}

/**
 * Full-screen Monaco editor modal that reads/writes any server path via the
 * global file API. Reused by File manager and Nginx config editing.
 *
 * Props: path (absolute server path), onClose()
 */
export default function EditorModal({ path, onClose }) {
  const [content, setContent] = useState('')
  const [loading, setLoading] = useState(true)
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState('')

  useEffect(() => {
    if (!path) return
    setLoading(true)
    setError('')
    api
      .get('/files/read', { params: { path } })
      .then((res) => setContent(res.data.content))
      .catch((err) => setError(errorMessage(err)))
      .finally(() => setLoading(false))
  }, [path])

  async function save() {
    setSaving(true)
    try {
      await api.post('/files/write', { path, content })
      onClose(true)
    } catch (err) {
      setError(errorMessage(err))
    } finally {
      setSaving(false)
    }
  }

  // Ctrl+S to save
  useEffect(() => {
    function onKey(e) {
      if ((e.ctrlKey || e.metaKey) && e.key === 's') {
        e.preventDefault()
        save()
      }
      if (e.key === 'Escape') onClose(false)
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [content])

  if (!path) return null

  return (
    <div className="fixed inset-0 z-50 flex flex-col bg-[#03080b]/90 p-4 backdrop-blur-sm">
      <div className="mb-3 flex flex-wrap items-center gap-3">
        <span className="truncate font-mono text-sm text-slate-300">{path}</span>
        {error && <span className="text-xs text-red-400">{error}</span>}
        <div className="ml-auto flex gap-2">
          <button className="btn-primary" onClick={save} disabled={saving || loading}>
            {saving ? 'Saving…' : 'Save'}
            <span className="kbd ml-1">Ctrl S</span>
          </button>
          <button className="btn-secondary" onClick={() => onClose(false)}>
            Close
            <span className="kbd ml-1">Esc</span>
          </button>
        </div>
      </div>
      <div className="flex-1 overflow-hidden rounded-xl border border-panel-border">
        {loading ? (
          <div className="h-full flex items-center justify-center text-slate-500">Loading…</div>
        ) : (
          <Editor
            height="100%"
            theme="vs-dark"
            language={languageFor(path)}
            value={content}
            onChange={(v) => setContent(v ?? '')}
            options={{ minimap: { enabled: false }, fontSize: 13 }}
          />
        )}
      </div>
    </div>
  )
}
