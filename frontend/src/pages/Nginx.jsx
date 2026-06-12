import { useCallback, useEffect, useState } from 'react'
import api, { errorMessage } from '../api/client'
import EditorModal from '../components/EditorModal'

/** Nginx config manager: list managed blocks, edit in Monaco, reload, delete. */
export default function Nginx() {
  const [configs, setConfigs] = useState([])
  const [editorPath, setEditorPath] = useState(null)
  const [message, setMessage] = useState('')

  const refresh = useCallback(() => {
    api.get('/nginx/configs').then((res) => setConfigs(res.data)).catch(() => {})
  }, [])

  useEffect(() => {
    refresh()
  }, [refresh])

  async function reload() {
    setMessage('')
    try {
      const res = await api.post('/nginx/reload')
      setMessage(res.data.detail)
    } catch (err) {
      setMessage(errorMessage(err))
    }
  }

  async function remove(cfg) {
    if (!window.confirm(`Delete nginx config for ${cfg.domain}? This unlinks and reloads nginx.`)) return
    try {
      await api.delete(`/nginx/configs/${cfg.id}`)
      refresh()
    } catch (err) {
      alert(errorMessage(err))
    }
  }

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <h2 className="text-2xl font-bold">Nginx Configs</h2>
        <button className="btn-primary" onClick={reload}>↻ Reload Nginx</button>
      </div>

      {message && <p className="text-sm text-slate-400">{message}</p>}

      <div className="card">
        <table className="w-full text-sm">
          <thead>
            <tr className="text-left text-xs uppercase text-slate-500 border-b border-panel-border">
              <th className="py-2">Domain</th>
              <th>Type</th>
              <th>Path</th>
              <th className="text-right">Actions</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-panel-border">
            {configs.map((cfg) => (
              <tr key={cfg.id}>
                <td className="py-2 font-mono text-sky-300">{cfg.domain}</td>
                <td className="text-slate-400">{cfg.entity_type}</td>
                <td className="font-mono text-xs text-slate-500 truncate max-w-xs">{cfg.config_path}</td>
                <td className="text-right space-x-2 whitespace-nowrap">
                  <button onClick={() => setEditorPath(cfg.config_path)} className="text-sky-400 hover:underline">Edit</button>
                  <button onClick={() => remove(cfg)} className="text-red-400 hover:underline">Delete</button>
                </td>
              </tr>
            ))}
            {configs.length === 0 && (
              <tr><td colSpan={4} className="py-6 text-center text-slate-600">
                No managed configs yet — assign a domain to a project or website to create one.
              </td></tr>
            )}
          </tbody>
        </table>
      </div>

      <EditorModal
        path={editorPath}
        onClose={(saved) => {
          setEditorPath(null)
          if (saved) reload()
        }}
      />
    </div>
  )
}
