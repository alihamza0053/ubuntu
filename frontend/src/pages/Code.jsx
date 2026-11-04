import { useCallback, useEffect, useState } from 'react'
import api, { errorMessage } from '../api/client'
import Icon from '../components/ui/Icon'
import PageHeader from '../components/ui/PageHeader'
import { useAuth } from '../context/AuthContext'
import { openInEditor } from '../lib/openEditor'

/** Sidebar → Code: VS Code in the browser (code-server), on any project or website. */
export default function Code() {
  const { isAdmin } = useAuth()
  const [deleteData, setDeleteData] = useState(false)
  const [status, setStatus] = useState(null)
  const [folders, setFolders] = useState({ projects: [], websites: [] })
  const [filter, setFilter] = useState('')
  const [busy, setBusy] = useState('')
  const [error, setError] = useState('')

  const refresh = useCallback(() => {
    setError('')
    api.get('/code/status').then((r) => setStatus(r.data)).catch((err) => setError(errorMessage(err)))
    api.get('/code/folders').then((r) => setFolders(r.data)).catch(() => {})
  }, [])

  useEffect(() => { refresh() }, [refresh])

  async function act(label, fn) {
    setBusy(label); setError('')
    try { await fn(); refresh() } catch (err) { setError(errorMessage(err)) } finally { setBusy('') }
  }

  const match = (n) => n.toLowerCase().includes(filter.trim().toLowerCase())
  const ready = status?.installed

  return (
    <div className="space-y-6">
      <PageHeader title="Code" crumbs={[{ label: 'Tools' }, { label: 'Code editor' }]}
        actions={ready && (
          <>
            <button className="btn-secondary" onClick={refresh}><Icon name="refresh" size={15} />Refresh</button>
            {status.running
              ? <button className="btn-secondary" disabled={busy === 'stop'}
                  onClick={() => act('stop', () => api.post('/code/stop'))}>
                  <Icon name="stop" size={15} />{busy === 'stop' ? 'Stopping…' : 'Stop editor'}</button>
              : <button className="btn-secondary" disabled={busy === 'start'}
                  onClick={() => act('start', () => api.post('/code/start'))}>
                  <Icon name="play" size={15} />{busy === 'start' ? 'Starting…' : 'Start editor'}</button>}
            <button className="btn-primary" onClick={() => openInEditor()}>
              <Icon name="external" size={15} />Open editor</button>
          </>
        )} />

      {error && (
        <div className="flex items-start gap-2 rounded-lg border border-red-500/30 bg-red-500/10 px-3 py-2 text-sm text-red-300">
          <Icon name="warning" size={15} className="mt-0.5" />{error}
        </div>
      )}

      {status === null && <p className="text-sm text-slate-500">Checking the editor…</p>}

      {status && !status.installed && (
        <div className="card space-y-3">
          <h3 className="section-title">Install the code editor</h3>
          <p className="text-sm text-slate-400">
            Installs <b>code-server</b> — VS Code in your browser (~150–300 MB of RAM while it runs). It opens at
            this panel's address under <code>/ide/</code>, only for people allowed to use it: nobody else can
            reach it, and there's no extra password to share.
          </p>
          {status.error && <p className="text-xs text-amber-300">{status.error}</p>}
          <button className="btn-primary" disabled={busy === 'install'}
            onClick={() => act('install', () => api.post('/code/install'))}>
            {busy === 'install' ? 'Installing… (a minute or two)' : <><Icon name="download" size={15} />Install code editor</>}
          </button>
        </div>
      )}

      {ready && (
        <>
          <div className="flex flex-wrap items-center gap-x-6 gap-y-1 text-xs text-slate-400">
            <span>code-server {status.version}</span>
            <span className={status.running ? 'text-emerald-400' : 'text-slate-500'}>
              ● {status.running ? 'running' : 'stopped (starts by itself when you open a folder)'}</span>
            <span>{status.owner_only ? 'Only you can use it' : 'Users with the Code permission can use it'}</span>
          </div>

          <div className="rounded-lg border border-amber-500/30 bg-amber-500/10 px-3 py-2 text-xs text-amber-200">
            The editor has a terminal that runs as the panel's server user, so anyone who can open it can control the
            server. Give the <b>Code editor</b> permission (Settings → Users &amp; Access) only to people you trust.
          </div>

          {status.can_set_owner_only && (
            <label className="card flex items-start gap-3 cursor-pointer">
              <input type="checkbox" className="mt-1" checked={status.owner_only}
                onChange={(e) => act('owner', () => api.put('/code/owner-only', { enabled: e.target.checked }))} />
              <span>
                <span className="text-sm text-slate-200">Only me</span>
                <span className="block text-xs text-slate-500">
                  Hide the editor from everyone else — other admins included. Only you see this switch.
                </span>
              </span>
            </label>
          )}

          <div className="card space-y-3">
            <div className="flex flex-wrap items-center justify-between gap-2">
              <h3 className="section-title">Open a folder</h3>
              <input className="input w-64" placeholder="Filter…" value={filter} onChange={(e) => setFilter(e.target.value)} />
            </div>
            <FolderGroup title="Projects" kind="project" items={folders.projects.filter((f) => match(f.name))}
              subs={[['', 'Whole project'], ['dashboard', 'Dashboard'], ['code', 'Code']]} />
            <FolderGroup title="Websites" kind="website" items={folders.websites.filter((f) => match(f.name))}
              subs={[['', 'Open']]} />
          </div>

          {isAdmin && (
            <div className="card space-y-2">
              <h3 className="section-title">Uninstall</h3>
              <p className="text-xs text-slate-500">
                Removes the editor from this server. Your projects, websites, dashboards and databases are not
                touched. You can install it again from this page at any time.
              </p>
              <label className="flex items-center gap-2 text-xs text-slate-400 cursor-pointer">
                <input type="checkbox" checked={deleteData} onChange={(e) => setDeleteData(e.target.checked)} />
                Also delete the editor's settings and installed extensions
              </label>
              <button className="btn-secondary text-red-300" disabled={busy === 'uninstall'}
                onClick={() => {
                  const what = deleteData ? "the editor, its settings and its extensions" : 'the editor (its settings are kept)'
                  if (!window.confirm(`Uninstall ${what}? Anyone using it now will be disconnected.`)) return
                  act('uninstall', () => api.post('/code/uninstall', null, { params: { delete_data: deleteData } }))
                }}>
                <Icon name="trash" size={15} />{busy === 'uninstall' ? 'Removing…' : 'Uninstall code editor'}</button>
            </div>
          )}
        </>
      )}
    </div>
  )
}

function FolderGroup({ title, kind, items, subs }) {
  if (!items.length) return null
  return (
    <div className="space-y-1">
      <p className="text-xs uppercase tracking-wide text-slate-500">{title}</p>
      <div className="divide-y divide-slate-800 rounded-lg border border-panel-border">
        {items.map((f) => (
          <div key={f.name} className="flex flex-wrap items-center gap-2 px-3 py-2">
            <Icon name={kind === 'project' ? 'code' : 'globe'} size={15} className="text-slate-500" />
            <span className="text-sm text-slate-200">{f.name}</span>
            <span className="font-mono text-xs text-slate-600">{f.path}</span>
            <div className="ml-auto flex gap-1">
              {subs.map(([sub, label]) => (
                <button key={sub} className={sub === '' ? 'btn-primary' : 'btn-secondary'}
                  onClick={() => openInEditor({ kind, name: f.name, sub })}>
                  {sub === '' && <Icon name="external" size={13} />}{label}
                </button>
              ))}
            </div>
          </div>
        ))}
      </div>
    </div>
  )
}
