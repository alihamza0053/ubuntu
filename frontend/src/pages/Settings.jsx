import { useCallback, useEffect, useRef, useState } from 'react'
import api, { errorMessage } from '../api/client'
import LiveLog from '../components/LiveLog'
import Backups from '../components/Backups'
import Users from '../components/Users'
import { useAuth } from '../context/AuthContext'

/** Settings: change password, panel key/value settings, DB backup, self-update. */
export default function Settings() {
  const { isAdmin } = useAuth()
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

      {/* User management (admins only) */}
      {isAdmin && <Users />}

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

      {/* System cleanup: CPU / RAM / Disk cards (admins only) */}
      {isAdmin && <SystemCleanup />}


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

const DEFAULT_CLEAN = ['tmp', 'apt', 'journal', 'logs', 'pip']

function fmtSize(bytes) {
  if (bytes === null || bytes === undefined) return '—'
  if (bytes < 1024) return `${bytes} B`
  const units = ['KB', 'MB', 'GB', 'TB']
  let v = bytes
  let i = -1
  do { v /= 1024; i += 1 } while (v >= 1024 && i < units.length - 1)
  return `${v.toFixed(1)} ${units[i]}`
}

function StatBar({ label, percent, detail, color }) {
  return (
    <div className="flex-1 min-w-[10rem]">
      <div className="flex justify-between text-xs mb-1">
        <span className="text-slate-400">{label}</span>
        <span className="text-slate-300">{detail}</span>
      </div>
      <div className="h-2 rounded bg-slate-800 overflow-hidden">
        <div className={`h-full ${color}`} style={{ width: `${Math.min(percent || 0, 100)}%` }} />
      </div>
    </div>
  )
}

/** Compact process table used by the CPU and RAM cards. */
function ProcessTable({ rows, valueHeader, value }) {
  if (!rows?.length) return null
  return (
    <div className="overflow-x-auto">
      <table className="w-full text-xs">
        <thead>
          <tr className="text-slate-500 text-left">
            <th className="py-1 pr-2 font-normal">Process</th>
            <th className="py-1 pr-2 font-normal">User</th>
            <th className="py-1 pr-2 font-normal">PID</th>
            <th className="py-1 font-normal text-right">{valueHeader}</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((p) => (
            <tr key={p.pid} className="border-t border-slate-800">
              <td className="py-1 pr-2 text-slate-200 truncate max-w-[12rem]">{p.name}</td>
              <td className="py-1 pr-2 text-slate-500">{p.user}</td>
              <td className="py-1 pr-2 text-slate-500 font-mono">{p.pid}</td>
              <td className="py-1 font-mono text-right text-slate-300">{value(p)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

/**
 * System Cleanup: three cards — CPU (what's using it), RAM (top processes +
 * flush caches) and Disk (where the space went + cleanup tasks).
 */
function SystemCleanup() {
  const [info, setInfo] = useState(null)      // /settings/cleanup/preview payload
  const [loading, setLoading] = useState(true)
  const [selected, setSelected] = useState(new Set(DEFAULT_CLEAN))
  const [wsPath, setWsPath] = useState(null)  // LiveLog path while cleaning
  const [runningKind, setRunningKind] = useState(null)  // 'ram' | 'disk' | null

  const refresh = useCallback(() => {
    setLoading(true)
    api.get('/settings/cleanup/preview')
      .then((res) => setInfo(res.data))
      .catch(() => {})
      .finally(() => setLoading(false))
  }, [])

  useEffect(() => { refresh() }, [refresh])

  function toggle(key) {
    setSelected((prev) => {
      const next = new Set(prev)
      if (next.has(key)) next.delete(key)
      else next.add(key)
      return next
    })
  }

  function start(kind, tasks) {
    if (tasks.length === 0) return
    if (tasks.includes('trash') && !window.confirm(
      'Also empty the recycle bin? Deleted files in it can no longer be restored.')) {
      return
    }
    setRunningKind(kind)
    setWsPath(null)
    setTimeout(() => setWsPath(`/ws/settings/cleanup?tasks=${tasks.join(',')}`), 0)
  }

  function onCleanupClosed() {
    setRunningKind(null)
    setWsPath(null)
    refresh()   // show the freed space/RAM in the stats
  }

  const cpu = info?.cpu
  const mem = info?.memory
  const disk = info?.disk
  const ramTask = (info?.tasks || []).find((t) => t.key === 'ram')
  const diskTasks = (info?.tasks || []).filter((t) => t.key !== 'ram')
  const helperMissing = info && info.ready === false

  return (
    <>
      <div className="flex items-center justify-between">
        <h3 className="text-lg font-semibold">System Cleanup</h3>
        <button className="text-xs text-slate-400 hover:text-slate-200"
          onClick={refresh} disabled={loading}>
          {loading ? 'Loading…' : '↻ Refresh'}
        </button>
      </div>

      {helperMissing && (
        <p className="text-xs text-yellow-500 -mt-3">
          The cleanup helper isn't installed on this server yet — run{' '}
          <code>sudo bash deploy/update.sh</code> once, then the RAM/Disk
          cleanup buttons will work.
        </p>
      )}

      {/* ─── CPU ─── */}
      <div className="card space-y-3">
        <h3 className="font-semibold">⚙️ CPU</h3>
        {cpu && (
          <>
            <StatBar label={`CPU (${cpu.cores} core${cpu.cores > 1 ? 's' : ''})`}
              percent={cpu.percent} detail={`${cpu.percent}%`} color="bg-sky-500" />
            {cpu.load_avg && (
              <p className="text-xs text-slate-500">
                Load average (1 / 5 / 15 min):{' '}
                <span className="font-mono text-slate-300">{cpu.load_avg.join(' / ')}</span>
                {' '}— above {cpu.cores}.0 means the CPU is saturated.
              </p>
            )}
            <p className="text-xs text-slate-500">Top processes by CPU right now:</p>
            <ProcessTable rows={cpu.top} valueHeader="CPU %"
              value={(p) => `${p.cpu}%`} />
            <p className="text-xs text-slate-600">
              CPU load isn't "cleanable" — it's whatever is running. If something
              here shouldn't be running, stop it from the <b>Server</b> tab's
              process list (or stop that script/dashboard/app).
            </p>
          </>
        )}
      </div>

      {/* ─── RAM ─── */}
      <div className="card space-y-3">
        <h3 className="font-semibold">🧠 RAM</h3>
        {mem && (
          <>
            <StatBar label="RAM" percent={mem.percent}
              detail={`${mem.used_gb} / ${mem.total_gb} GB`} color="bg-violet-500" />
            <div className="flex flex-wrap gap-x-6 gap-y-1 text-xs text-slate-400">
              <span>Available: <b className="text-slate-200">{mem.available_gb} GB</b></span>
              <span>Disk cache: <b className="text-slate-200">{mem.cached_gb} GB</b></span>
            </div>
            <p className="text-xs text-slate-500">Top processes by memory:</p>
            <ProcessTable rows={mem.top} valueHeader="Memory"
              value={(p) => `${p.memory_mb} MB (${p.memory_percent}%)`} />
            <p className="text-xs text-slate-600">
              Linux keeps free RAM filled with disk cache on purpose — that part
              is released automatically when programs need it. Flushing it is
              safe but usually only worth it before starting something heavy.
            </p>
            <button className="btn-primary"
              onClick={() => start('ram', ['ram'])}
              disabled={!!runningKind || helperMissing}>
              {runningKind === 'ram' ? 'Flushing…' : '🧹 Flush RAM caches'}
              {ramTask?.size ? ` (~${fmtSize(ramTask.size)})` : ''}
            </button>
            {runningKind === 'ram' && wsPath && (
              <LiveLog path={wsPath} onClose={onCleanupClosed} />
            )}
          </>
        )}
      </div>

      {/* ─── Disk ─── */}
      <div className="card space-y-3">
        <h3 className="font-semibold">💾 Disk</h3>
        {disk && (
          <>
            <StatBar label="Disk (/)" percent={disk.percent}
              detail={`${disk.used_gb} / ${disk.total_gb} GB · ${disk.free_gb} GB free`}
              color="bg-emerald-500" />

            {disk.breakdown?.length > 0 && (
              <>
                <p className="text-xs text-slate-500">Where the space is going:</p>
                <div className="space-y-1">
                  {disk.breakdown.map((d) => (
                    <div key={d.path} className="flex items-center justify-between gap-2 text-xs">
                      <span className="text-slate-300">{d.label}
                        <span className="text-slate-600 font-mono ml-1.5">{d.path}</span>
                      </span>
                      <span className="font-mono text-slate-300 shrink-0">{fmtSize(d.size)}</span>
                    </div>
                  ))}
                </div>
              </>
            )}

            {disk.docker?.length > 0 && (
              <>
                <p className="text-xs text-slate-500 mt-1">Docker disk usage:</p>
                <div className="space-y-1">
                  {disk.docker.map((d) => (
                    <div key={d.type} className="flex items-center justify-between gap-2 text-xs">
                      <span className="text-slate-300">{d.type}
                        <span className="text-slate-600 ml-1.5">({d.count})</span>
                      </span>
                      <span className="font-mono text-slate-300 shrink-0">
                        {d.size} <span className="text-slate-500">· reclaimable {d.reclaimable}</span>
                      </span>
                    </div>
                  ))}
                </div>
              </>
            )}

            <p className="text-xs text-slate-500 border-t border-slate-800 pt-2">
              Safe to clean (nothing here touches your projects, websites, apps
              or databases):
            </p>
            <div className="space-y-1.5">
              {diskTasks.map((t) => (
                <label key={t.key}
                  className="flex items-start gap-2.5 rounded-lg px-2 py-1.5 hover:bg-slate-800/60 cursor-pointer">
                  <input type="checkbox" className="mt-1 accent-sky-500"
                    checked={selected.has(t.key)} onChange={() => toggle(t.key)} />
                  <span className="flex-1 min-w-0">
                    <span className="text-sm text-slate-200">{t.label}</span>
                    <span className="block text-xs text-slate-500">{t.description}</span>
                  </span>
                  <span className="text-xs text-slate-400 font-mono shrink-0">
                    {t.key === 'trash' && t.count ? `${t.count} item(s) · ` : ''}{fmtSize(t.size)}
                  </span>
                </label>
              ))}
            </div>

            <button className="btn-primary"
              onClick={() => start('disk', diskTasks.map((t) => t.key).filter((k) => selected.has(k)))}
              disabled={!!runningKind || helperMissing
                || diskTasks.every((t) => !selected.has(t.key))}>
              {runningKind === 'disk' ? 'Cleaning…' : '🧹 Clean disk now'}
            </button>
            {runningKind === 'disk' && wsPath && (
              <LiveLog path={wsPath} onClose={onCleanupClosed} />
            )}
          </>
        )}
      </div>
    </>
  )
}
