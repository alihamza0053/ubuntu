import { useEffect, useState } from 'react'
import api, { errorMessage } from '../api/client'

/** Settings: change password, panel key/value settings, DB backup download. */
export default function Settings() {
  const [pw, setPw] = useState({ current_password: '', new_password: '', confirm: '' })
  const [pwMsg, setPwMsg] = useState('')
  const [settings, setSettings] = useState({ panel_port: '', panel_subdomain: '' })
  const [setMsg, setSetMsg] = useState('')

  useEffect(() => {
    api.get('/settings').then((res) => {
      setSettings((prev) => ({ ...prev, ...res.data }))
    }).catch(() => {})
  }, [])

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

  function backupDb() {
    api.post('/settings/backup-db', null, { responseType: 'blob' })
      .then((res) => {
        const url = URL.createObjectURL(res.data)
        const a = document.createElement('a')
        a.href = url
        a.download = 'serverhub-backup.db'
        a.click()
        URL.revokeObjectURL(url)
      })
      .catch((err) => alert(errorMessage(err)))
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

      {/* Backup */}
      <div className="card space-y-3">
        <h3 className="font-semibold">Backup</h3>
        <p className="text-sm text-slate-500">
          Download the panel's SQLite database (projects, scripts, websites,
          schedules, users).
        </p>
        <button className="btn-secondary" onClick={backupDb}>⬇ Download database backup</button>
      </div>
    </div>
  )
}
