import { useCallback, useEffect, useRef, useState } from 'react'
import api, { errorMessage } from '../api/client'
import LiveLog from '../components/LiveLog'
import Backups from '../components/Backups'

/** Settings: change password, panel key/value settings, DB backup, self-update. */
export default function Settings() {
  const [pw, setPw] = useState({ current_password: '', new_password: '', confirm: '' })
  const [pwMsg, setPwMsg] = useState('')
  const [settings, setSettings] = useState({ panel_port: '', panel_subdomain: '' })
  const [setMsg, setSetMsg] = useState('')

  // Self-update
  const [upd, setUpd] = useState(null)        // /settings/update/info payload
  const [updLoading, setUpdLoading] = useState(false)
  const [updPath, setUpdPath] = useState(null) // WS path while updating
  const [restarting, setRestarting] = useState(false)
  const sawDown = useRef(false)

  useEffect(() => {
    api.get('/settings').then((res) => {
      setSettings((prev) => ({ ...prev, ...res.data }))
    }).catch(() => {})
  }, [])

  const checkUpdate = useCallback(() => {
    setUpdLoading(true)
    api.get('/settings/update/info')
      .then((res) => setUpd(res.data))
      .catch((err) => setUpd({ message: errorMessage(err), error: true }))
      .finally(() => setUpdLoading(false))
  }, [])

  useEffect(() => { checkUpdate() }, [checkUpdate])

  function startUpdate() {
    if (!window.confirm(
      'Update the panel now? It will pull the latest code, rebuild, and ' +
      'restart the panel. The page will reload when it is back.')) return
    setUpdPath(null)
    setTimeout(() => setUpdPath('/ws/settings/update'), 0)
  }

  // When the update WS closes, the panel is (probably) restarting — poll
  // /api/health and reload once it has gone down and come back up.
  function onUpdateClosed() {
    setRestarting(true)
    sawDown.current = false
    const t = setInterval(async () => {
      try {
        await api.get('/health', { timeout: 4000 })
        if (sawDown.current) { clearInterval(t); window.location.reload() }
      } catch {
        sawDown.current = true   // panel went down → restart in progress
      }
    }, 3000)
    // Give up after 3 min and just reload
    setTimeout(() => { clearInterval(t); window.location.reload() }, 180000)
  }

  async function changePassword(e) {
    e.preventDefault()
    setPwMsg('')
    if (pw.new_password !== pw.confirm) {
      setPwMsg('New passwords do not match')
      return
    }
    try {
      await api.post('/auth/change-password', {
        current_password: pw.current_password,
        new_password: pw.new_password,
      })
      setPwMsg('Password changed ✓')
      setPw({ current_password: '', new_password: '', confirm: '' })
    } catch (err) {
      setPwMsg(errorMessage(err))
    }
  }

  async function saveSettings(e) {
    e.preventDefault()
    setSetMsg('')
    try {
      await api.put('/settings', { values: settings })
      setSetMsg('Saved ✓')
    } catch (err) {
      setSetMsg(errorMessage(err))
    }
  }

  return (
    <div className="space-y-6 max-w-2xl">
      <h2 className="text-2xl font-bold">Settings</h2>

      {/* Change password */}
      <form onSubmit={changePassword} className="card space-y-3">
        <h3 className="font-semibold">Change Admin Password</h3>
        {pwMsg && <p className={`text-sm ${pwMsg.includes('✓') ? 'text-green-400' : 'text-red-400'}`}>{pwMsg}</p>}
        <input className="input" type="password" placeholder="Current password" value={pw.current_password}
          onChange={(e) => setPw({ ...pw, current_password: e.target.value })} required />
        <input className="input" type="password" placeholder="New password (min 8 chars)" value={pw.new_password}
          onChange={(e) => setPw({ ...pw, new_password: e.target.value })} required />
        <input className="input" type="password" placeholder="Confirm new password" value={pw.confirm}
          onChange={(e) => setPw({ ...pw, confirm: e.target.value })} required />
        <button className="btn-primary" type="submit">Change Password</button>
      </form>

      {/* Panel settings */}
      <form onSubmit={saveSettings} className="card space-y-3">
        <h3 className="font-semibold">Panel Configuration</h3>
        {setMsg && <p className="text-sm text-green-400">{setMsg}</p>}
        <div>
          <label className="block text-sm text-slate-400 mb-1">Panel port (informational)</label>
          <input className="input" value={settings.panel_port}
            onChange={(e) => setSettings({ ...settings, panel_port: e.target.value })} placeholder="8765" />
        </div>
        <div>
          <label className="block text-sm text-slate-400 mb-1">Panel subdomain</label>
          <input className="input" value={settings.panel_subdomain}
            onChange={(e) => setSettings({ ...settings, panel_subdomain: e.target.value })} placeholder="panel.yourdomain.com" />
        </div>
        <p className="text-xs text-slate-500">
          Changing the actual listen port requires updating the supervisor + nginx
          config on the server and restarting the panel.
        </p>
        <button className="btn-primary" type="submit">Save</button>
      </form>

      {/* Backup & Restore */}
      <Backups />

      {/* Updates */}
      <div className="card space-y-3">
        <div className="flex items-center justify-between">
          <h3 className="font-semibold">Updates</h3>
          <button className="text-xs text-slate-400 hover:text-slate-200"
            onClick={checkUpdate} disabled={updLoading || !!updPath}>
            {updLoading ? 'Checking…' : '↻ Check again'}
          </button>
        </div>

        {upd && (
          <p className={`text-sm ${
            upd.error ? 'text-red-400'
            : upd.behind > 0 ? 'text-yellow-300'
            : upd.behind === 0 ? 'text-green-400' : 'text-slate-400'}`}>
            {upd.message}
          </p>
        )}
        {upd?.current && (
          <p className="text-xs text-slate-500">Current: <code>{upd.current}</code></p>
        )}
        {upd?.src && (
          <p className="text-xs text-slate-600">Source: <code>{upd.src}</code></p>
        )}

        {restarting ? (
          <p className="text-sm text-sky-300">
            Panel is restarting to finish the update… this page will reload
            automatically when it's back.
          </p>
        ) : (
          <button className="btn-primary"
            onClick={startUpdate}
            disabled={!!updPath || (upd && upd.ready === false)}>
            {updPath ? 'Updating…' : '⬆ Update now'}
          </button>
        )}

        {upd && upd.ready === false && (
          <p className="text-xs text-slate-500">
            No source checkout found on the server. The update button redeploys
            from a git clone / uploaded bundle — set <code>UPDATE_SRC</code> in{' '}
            <code>backend/.env</code> (default <code>/opt/serverhub-src</code>),
            then re-run <code>sudo bash deploy/update.sh</code> once.
          </p>
        )}

        {updPath && <LiveLog path={updPath} onClose={onUpdateClosed} />}
      </div>
    </div>
  )
}
