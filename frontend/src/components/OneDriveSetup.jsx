import { useCallback, useEffect, useState } from 'react'
import api, { errorMessage } from '../api/client'

/**
 * OneDrive setup: authorize a Microsoft account, then start/stop the read-only
 * sync monitor. Files appear under /srv/onedrive and in each project's
 * OneDrive tab (where a folder is mapped per project).
 *
 * Lives in Settings — it used to sit on the (removed) Apps page, but projects
 * read their synced files through it, so it stays available here.
 */
export default function OneDriveSetup() {
  const [status, setStatus] = useState(null) // { installed, authorized, monitor, sync_dir }
  const [authUrl, setAuthUrl] = useState('')
  const [responseUrl, setResponseUrl] = useState('')
  const [msg, setMsg] = useState('')
  const [busy, setBusy] = useState(false)

  const refresh = useCallback(() => {
    api.get('/onedrive/status').then((r) => setStatus(r.data)).catch(() => {})
  }, [])

  useEffect(() => { refresh() }, [refresh])

  async function startAuth() {
    setMsg(''); setBusy(true)
    try {
      const r = await api.post('/onedrive/auth/start')
      setAuthUrl(r.data.auth_url)
    } catch (err) {
      setMsg(errorMessage(err))
    } finally {
      setBusy(false)
    }
  }

  async function completeAuth() {
    setMsg(''); setBusy(true)
    try {
      const r = await api.post('/onedrive/auth/complete', { response_url: responseUrl })
      setMsg(r.data.detail)
      setAuthUrl(''); setResponseUrl('')
      refresh()
    } catch (err) {
      setMsg(errorMessage(err))
    } finally {
      setBusy(false)
    }
  }

  async function monitor(action) {
    setMsg('')
    try {
      const r = await api.post(`/onedrive/monitor/${action}`)
      setMsg(r.data.detail)
      setTimeout(refresh, 1200)
    } catch (err) {
      setMsg(errorMessage(err))
    }
  }

  async function resync() {
    if (!window.confirm('Full resync re-checks the whole drive and pulls shared '
      + 'items. This can take a while. Continue?')) return
    setMsg('')
    try {
      const r = await api.post('/onedrive/resync')
      setMsg(r.data.detail)
      setTimeout(refresh, 1500)
    } catch (err) {
      setMsg(errorMessage(err))
    }
  }

  if (!status) return null   // OneDrive isn't set up on this server

  return (
    <div className="card space-y-3">
      <h3 className="font-semibold">☁️ OneDrive Sync</h3>
      <p className="text-xs text-slate-500">
        Keeps <code>/srv/onedrive</code> in sync (read-only). Each project can map
        a subfolder of it in its own OneDrive tab.
      </p>

      <dl className="space-y-1.5 text-sm">
        <div className="flex justify-between">
          <dt className="text-slate-500">Authorized</dt>
          <dd className={status.authorized ? 'text-green-400' : 'text-yellow-400'}>
            {status.authorized ? 'yes' : 'not yet'}
          </dd>
        </div>
        <div className="flex justify-between">
          <dt className="text-slate-500">Sync monitor</dt>
          <dd className="text-slate-200">{status.monitor}</dd>
        </div>
        <div className="flex justify-between gap-2">
          <dt className="text-slate-500">Folder</dt>
          <dd className="font-mono text-slate-300">{status.sync_dir}</dd>
        </div>
      </dl>

      {!status.authorized ? (
        <div className="space-y-2">
          {!authUrl ? (
            <button className="btn-primary" disabled={busy} onClick={startAuth}>
              {busy ? 'Starting…' : '🔑 Authorize OneDrive'}
            </button>
          ) : (
            <div className="space-y-2 rounded-lg border border-panel-border bg-slate-900 p-3">
              <p className="text-xs text-slate-400">
                1. Open this URL, sign in, and approve access:
              </p>
              <a href={authUrl} target="_blank" rel="noreferrer"
                 className="text-sky-400 hover:underline text-xs break-all block">
                {authUrl} ↗
              </a>
              <p className="text-xs text-slate-400">
                2. After approving, your browser lands on a blank page. Copy that page’s
                full URL from the address bar and paste it here:
              </p>
              <input
                className="input w-full font-mono text-xs"
                placeholder="https://login.microsoftonline.com/.../nativeclient?code=…"
                value={responseUrl}
                onChange={(e) => setResponseUrl(e.target.value)}
              />
              <button className="btn-primary" disabled={busy || !responseUrl} onClick={completeAuth}>
                {busy ? 'Finishing…' : '✓ Finish & start syncing'}
              </button>
            </div>
          )}
        </div>
      ) : (
        <div className="space-y-2">
          <div className="flex flex-wrap gap-2">
            <button className="btn-secondary" onClick={() => monitor('start')}>▶ Start</button>
            <button className="btn-secondary" onClick={() => monitor('stop')}>⏹ Stop</button>
            <button className="btn-secondary" onClick={() => monitor('restart')}>🔄 Sync now</button>
            <button className="btn-secondary" disabled={status.resyncing} onClick={resync}>
              {status.resyncing ? '⏳ Resyncing…' : '⬇ Pull shared items (resync)'}
            </button>
          </div>
          <p className="text-xs text-slate-500">
            Files others shared with you (Work/School) only appear after a one-time
            <b> resync</b>.
          </p>
        </div>
      )}

      {msg && <p className="text-xs text-slate-400 break-words">{msg}</p>}
    </div>
  )
}
