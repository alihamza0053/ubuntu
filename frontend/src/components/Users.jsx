import { useCallback, useEffect, useState } from 'react'
import api, { errorMessage } from '../api/client'
import Icon from './ui/Icon'
import { useAuth } from '../context/AuthContext'

/** What users did, newest first (one user, or everyone when userId is null). */
function ActivityList({ userId, showUser }) {
  const [rows, setRows] = useState(null)
  const [more, setMore] = useState(false)
  const [error, setError] = useState(null)
  const PAGE = 50

  const fetchPage = useCallback((beforeId) => {
    const params = { limit: PAGE }
    if (userId != null) params.user_id = userId
    if (beforeId) params.before_id = beforeId
    return api.get('/auth/activity', { params })
      .then((res) => {
        setRows((old) => (beforeId ? [...(old || []), ...res.data] : res.data))
        setMore(res.data.length === PAGE)
      })
      .catch((err) => setError(errorMessage(err)))
  }, [userId])

  useEffect(() => { setRows(null); fetchPage() }, [fetchPage])

  if (error) return <p className="text-xs text-red-400">{error}</p>
  if (rows === null) return <p className="text-xs text-slate-500">Loading activity…</p>
  if (rows.length === 0) return <p className="text-xs text-slate-500">No activity yet.</p>
  return (
    <div className="space-y-1">
      <div className="max-h-80 overflow-y-auto rounded-lg border border-panel-border divide-y divide-slate-800">
        {rows.map((r) => (
          <div key={r.id} className="flex items-start gap-3 px-3 py-1.5 text-xs">
            <span className="font-mono text-slate-500 shrink-0">{r.at.replace('T', ' ')}</span>
            {showUser && <span className="text-sky-300 shrink-0">{r.username}</span>}
            <span className={`flex-1 min-w-0 ${r.status >= 400 ? 'text-red-300' : 'text-slate-300'}`}>{r.action}</span>
            {r.ip && <span className="font-mono text-slate-600 shrink-0">{r.ip}</span>}
          </div>
        ))}
      </div>
      {more && (
        <button className="text-xs text-sky-400 hover:underline"
          onClick={() => fetchPage(rows[rows.length - 1].id)}>Load more</button>
      )}
    </div>
  )
}

/** Admin-only: create panel users and grant per-tab access with checkboxes. */
export default function Users() {
  const { user: me } = useAuth()
  const [catalog, setCatalog] = useState([])     // [{key,label}]
  const [users, setUsers] = useState([])
  const [msg, setMsg] = useState(null)           // {text, error}
  const [creating, setCreating] = useState(false)
  const [form, setForm] = useState({ username: '', password: '', is_admin: false, permissions: [] })
  const [openActivity, setOpenActivity] = useState(null)   // user id whose activity is open
  const [showAll, setShowAll] = useState(false)

  const load = useCallback(() => {
    Promise.all([api.get('/auth/permissions'), api.get('/auth/users')])
      .then(([c, u]) => { setCatalog(c.data); setUsers(u.data) })
      .catch((err) => setMsg({ text: errorMessage(err), error: true }))
  }, [])

  useEffect(() => { load() }, [load])

  function toggle(list, key) {
    return list.includes(key) ? list.filter((k) => k !== key) : [...list, key]
  }

  async function createUser(e) {
    e.preventDefault()
    setCreating(true); setMsg(null)
    try {
      await api.post('/auth/users', form)
      setMsg({ text: `User “${form.username}” created` })
      setForm({ username: '', password: '', is_admin: false, permissions: [] })
      load()
    } catch (err) {
      setMsg({ text: errorMessage(err), error: true })
    } finally { setCreating(false) }
  }

  async function patch(u, body) {
    try {
      await api.put(`/auth/users/${u.id}`, body)
      load()
    } catch (err) { setMsg({ text: errorMessage(err), error: true }) }
  }

  async function resetPw(u) {
    const pw = window.prompt(`New password for “${u.username}” (min 8 chars):`, '')
    if (!pw) return
    try {
      await api.post(`/auth/users/${u.id}/password`, { new_password: pw })
      setMsg({ text: `Password reset for ${u.username}` })
    } catch (err) { setMsg({ text: errorMessage(err), error: true }) }
  }

  async function remove(u) {
    if (!window.confirm(`Delete user “${u.username}”?`)) return
    try {
      await api.delete(`/auth/users/${u.id}`)
      load()
    } catch (err) { setMsg({ text: errorMessage(err), error: true }) }
  }

  return (
    <div className="card space-y-4">
      <h3 className="section-title">Users &amp; Access</h3>
      <p className="text-sm text-slate-500">
        Create users and tick the tabs each one may see. Admins see everything.
      </p>
      {msg && <p className={`text-sm ${msg.error ? 'text-red-400' : 'text-green-400'}`}>{msg.text}</p>}

      {/* Create user */}
      <form onSubmit={createUser} className="p-3 rounded-lg bg-slate-900 border border-panel-border space-y-3">
        <p className="text-sm font-medium text-slate-300">Add a user</p>
        <div className="grid sm:grid-cols-2 gap-2">
          <input className="input" placeholder="Username" value={form.username}
            onChange={(e) => setForm({ ...form, username: e.target.value })} required />
          <input className="input" type="password" placeholder="Password (min 8)" value={form.password}
            onChange={(e) => setForm({ ...form, password: e.target.value })} required />
        </div>
        <label className="flex items-center gap-2 text-sm">
          <input type="checkbox" checked={form.is_admin}
            onChange={(e) => setForm({ ...form, is_admin: e.target.checked })} />
          Administrator (full access + can manage users)
        </label>
        {!form.is_admin && (
          <div>
            <p className="text-xs text-slate-500 mb-1">Allowed tabs:</p>
            <div className="grid grid-cols-2 sm:grid-cols-3 gap-1">
              {catalog.map((c) => (
                <label key={c.key} className="flex items-center gap-2 text-sm cursor-pointer">
                  <input type="checkbox" checked={form.permissions.includes(c.key)}
                    onChange={() => setForm({ ...form, permissions: toggle(form.permissions, c.key) })} />
                  {c.label}
                </label>
              ))}
            </div>
          </div>
        )}
        <button className="btn-primary" disabled={creating}>
          {creating ? 'Creating…' : <><Icon name="plus" size={15} />Create user</>}
        </button>
      </form>

      {/* Existing users */}
      <div className="space-y-3">
        {users.map((u) => {
          const self = u.id === me?.id
          return (
            <div key={u.id} className="p-3 rounded-lg border border-panel-border space-y-2">
              <div className="flex items-center justify-between gap-2 flex-wrap">
                <div>
                  <span className="text-slate-200">{u.username}</span>
                  {self && <span className="ml-1 text-[10px] text-slate-500">(you)</span>}
                  <span className={`ml-2 badge ${u.is_admin ? 'bg-amber-500/15 text-amber-300' : 'bg-slate-700 text-slate-400'}`}>
                    {u.is_admin ? 'admin' : 'user'}
                  </span>
                </div>
                <div className="flex items-center gap-2 text-xs">
                  <label className="flex items-center gap-1 text-slate-400">
                    <input type="checkbox" checked={u.is_admin} disabled={self}
                      onChange={(e) => patch(u, { is_admin: e.target.checked })} />
                    admin
                  </label>
                  {!self && (
                    <button className={`px-2 py-1 rounded ${openActivity === u.id ? 'bg-sky-700' : 'bg-slate-700 hover:bg-slate-600'}`}
                      onClick={() => setOpenActivity(openActivity === u.id ? null : u.id)}>Activity</button>
                  )}
                  <button className="px-2 py-1 rounded bg-slate-700 hover:bg-slate-600"
                    onClick={() => resetPw(u)}>Reset password</button>
                  <button className="px-2 py-1 rounded bg-red-800 hover:bg-red-700 disabled:opacity-40"
                    onClick={() => remove(u)} disabled={self}>Delete</button>
                </div>
              </div>

              {openActivity === u.id && <ActivityList userId={u.id} />}

              {!u.is_admin && (
                <div className="grid grid-cols-2 sm:grid-cols-4 gap-1">
                  {catalog.map((c) => (
                    <label key={c.key} className="flex items-center gap-2 text-sm cursor-pointer">
                      <input type="checkbox" checked={u.permissions.includes(c.key)}
                        onChange={() => patch(u, { permissions: toggle(u.permissions, c.key) })} />
                      {c.label}
                    </label>
                  ))}
                </div>
              )}
            </div>
          )
        })}
      </div>

      {/* Everyone's activity */}
      <div className="border-t border-panel-border pt-3 space-y-2">
        <div className="flex items-center justify-between">
          <p className="text-sm font-medium text-slate-300">User activity</p>
          <button className="text-xs px-2 py-1 rounded bg-slate-700 hover:bg-slate-600"
            onClick={() => setShowAll(!showAll)}>{showAll ? 'Hide' : 'Show all users'}</button>
        </div>
        <p className="text-xs text-slate-500">
          Logins and every change users make (dashboards, uploads, deletes, scripts, settings).
          Kept for 90 days.
        </p>
        {showAll && <ActivityList userId={null} showUser />}
      </div>
    </div>
  )
}
