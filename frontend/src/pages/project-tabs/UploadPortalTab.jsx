import { useState } from 'react'
import api, { errorMessage } from '../../api/client'
import FolderBrowser from '../../components/FolderBrowser'

/**
 * Upload Portal tab: a public, password-protected page at
 * <project-domain>/onedrivefiles/ where outside people upload files for this
 * project (instead of OneDrive). You set/change the username + password here.
 */
export default function UploadPortalTab({ project, onChanged }) {
  const [username, setUsername] = useState(project.portal_username || '')
  const [password, setPassword] = useState('')
  const [msg, setMsg] = useState('')
  const [busy, setBusy] = useState(false)

  const enabled = !!project.portal_username
  const portalUrl = project.domain ? `https://${project.domain}/onedrivefiles/` : null

  async function save() {
    setMsg(''); setBusy(true)
    try {
      const r = await api.put(`/projects/${project.id}/portal-auth`, { username, password })
      setMsg(r.data.detail)
      setPassword('')
      onChanged()
    } catch (err) {
      setMsg(errorMessage(err))
    } finally {
      setBusy(false)
    }
  }

  async function disable() {
    if (!window.confirm('Disable the upload portal? The page will stop accepting uploads.')) return
    setMsg('')
    try {
      const r = await api.delete(`/projects/${project.id}/portal-auth`)
      setMsg(r.data.detail)
      setPassword('')
      onChanged()
    } catch (err) {
      setMsg(errorMessage(err))
    }
  }

  return (
   <div className="space-y-4">
    <div className="card space-y-4 max-w-2xl">
      <div>
        <h3 className="font-semibold">📤 Upload Portal</h3>
        <p className="text-xs text-slate-500">
          A public page where people upload files for this project. Files land in the
          project’s <span className="font-mono">onedrivefiles/</span> folder; re-uploading the
          same name replaces it.
        </p>
      </div>

      {/* Portal URL + status */}
      <div className="rounded-lg border border-panel-border bg-slate-900 p-3 space-y-2 text-sm">
        <div className="flex justify-between gap-2">
          <span className="text-slate-500">Status</span>
          <span className={enabled ? 'text-green-400' : 'text-slate-400'}>
            {enabled ? 'enabled' : 'disabled'}
          </span>
        </div>
        <div className="flex justify-between gap-2">
          <span className="text-slate-500">URL</span>
          <span className="text-right">
            {portalUrl ? (
              <a href={portalUrl} target="_blank" rel="noreferrer" className="text-sky-400 hover:underline break-all">
                {portalUrl} ↗
              </a>
            ) : (
              <span className="text-yellow-500/80">Assign a domain to this project first (Dashboard tab → Domain)</span>
            )}
          </span>
        </div>
      </div>

      {/* Credentials form */}
      <div className="space-y-2">
        <label className="block text-sm text-slate-400">Username</label>
        <input className="input" placeholder="e.g. supplier" value={username}
          onChange={(e) => setUsername(e.target.value)} autoComplete="off" />
        <label className="block text-sm text-slate-400 mt-2">
          {enabled ? 'New password (leave blank to keep current — re-enter to change)' : 'Password'}
        </label>
        <input className="input" type="text" placeholder="set a password"
          value={password} onChange={(e) => setPassword(e.target.value)} autoComplete="off" />
        <p className="text-xs text-slate-500">
          Share these with the people who should upload. Anyone with the link + credentials can upload.
        </p>
        <div className="flex gap-2 pt-1">
          <button className="btn-primary" disabled={busy || !username || password.length < 4}
            onClick={save}>
            {busy ? 'Saving…' : enabled ? 'Update credentials' : 'Enable portal'}
          </button>
          {enabled && (
            <button className="btn-secondary" onClick={disable}>Disable</button>
          )}
        </div>
      </div>

      {msg && <p className="text-xs text-slate-400 break-words">{msg}</p>}
    </div>

    {/* Files uploaded via the portal — overview + upload from the panel */}
    <div className="card">
      <div className="mb-3">
        <h3 className="font-semibold">📁 Portal files</h3>
        <p className="text-xs text-slate-500">
          Everything uploaded through the portal lands in{' '}
          <span className="font-mono">onedrivefiles/</span>. You can also upload here directly
          (button or drag-and-drop) and open spreadsheets.
        </p>
      </div>
      <FolderBrowser
        rootPath={`${project.folder_path}/onedrivefiles`}
        emptyHint="No files uploaded yet"
      />
    </div>
   </div>
  )
}
