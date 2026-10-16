import { useCallback, useEffect, useRef, useState } from 'react'
import api, { errorMessage } from '../api/client'
import DataTable, { NameCell, RowActions } from './ui/DataTable'
import Icon from './ui/Icon'
import Modal from './ui/Modal'
import PageHeader from './ui/PageHeader'

function fmtBytes(n) {
  if (n == null) return '—'
  const u = ['B', 'KB', 'MB', 'GB', 'TB']
  let i = 0
  while (n >= 1024 && i < u.length - 1) { n /= 1024; i++ }
  return `${n.toFixed(i ? 1 : 0)} ${u[i]}`
}

function Copy({ text }) {
  const [done, setDone] = useState(false)
  return (
    <button type="button" className="btn-icon" title="Copy"
      onClick={() => { navigator.clipboard?.writeText(text); setDone(true); setTimeout(() => setDone(false), 1200) }}>
      <Icon name={done ? 'check' : 'copy'} size={14} />
    </button>
  )
}

/** Ready-to-paste code with this database's real values written in as constants. */
function snippets(c) {
  const settings = `# ============ DATABASE (PostgreSQL) ============
DB_HOST = "${c.host}"
DB_PORT = ${c.port}
DB_NAME = "${c.database}"
DB_USER = "${c.user}"
DB_PASSWORD = "${c.password}"
# ==============================================`
  return {
    'Python (psycopg)': `import psycopg

${settings}

def db():
    return psycopg.connect(host=DB_HOST, port=DB_PORT, dbname=DB_NAME,
                           user=DB_USER, password=DB_PASSWORD)

with db() as conn:
    conn.execute("CREATE TABLE IF NOT EXISTS orders (id serial PRIMARY KEY, customer text, qty int)")
    conn.execute("INSERT INTO orders (customer, qty) VALUES (%s, %s)", ("TAIGA", 120))
    rows = conn.execute("SELECT customer, qty FROM orders").fetchall()`,
    'pandas (read / write tables)': `import pandas as pd
from sqlalchemy import create_engine

${settings}

engine = create_engine(
    f"postgresql+psycopg://{DB_USER}:{DB_PASSWORD}@{DB_HOST}:{DB_PORT}/{DB_NAME}")

df = pd.read_sql("SELECT * FROM orders", engine)             # table -> DataFrame
df.to_sql("orders_copy", engine, if_exists="replace", index=False)   # DataFrame -> table`,
    'Streamlit dashboard': `import pandas as pd
import streamlit as st
from sqlalchemy import create_engine

${settings}

@st.cache_resource
def engine():
    return create_engine(
        f"postgresql+psycopg://{DB_USER}:{DB_PASSWORD}@{DB_HOST}:{DB_PORT}/{DB_NAME}",
        pool_size=3, max_overflow=2, pool_pre_ping=True)   # few connections, reused

@st.cache_data(ttl=60)
def load(query):
    return pd.read_sql(query, engine())

df = load("SELECT * FROM orders")
st.dataframe(df)`,
    'Realtime (LISTEN/NOTIFY)': `import psycopg

${settings}

# writer (any script):   conn.execute("NOTIFY changes, 'order 42 updated'")
with psycopg.connect(host=DB_HOST, port=DB_PORT, dbname=DB_NAME, user=DB_USER,
                     password=DB_PASSWORD, autocommit=True) as conn:
    conn.execute("LISTEN changes")
    for note in conn.notifies():          # waits, gets each message instantly
        print(note.channel, note.payload)`,
  }
}

/** Connection details + ready-to-paste code. */
function ConnectionModal({ conn, note, onClose }) {
  const code = snippets(conn)
  const [tab, setTab] = useState(Object.keys(code)[0])
  const rows = [['Host', conn.host], ['Port', String(conn.port)], ['Database', conn.database],
    ['User', conn.user], ['Password', conn.password], ['DATABASE_URL', conn.url]]
  return (
    <Modal title={`Connect to “${conn.database}”`} size="lg" onClose={onClose}
      subtitle="Only reachable from this server (127.0.0.1). The user can open this database and nothing else.">
      {note && <p className="text-sm text-emerald-300">{note}</p>}
      <div className="space-y-1">
        {rows.map(([k, v]) => (
          <div key={k} className="flex items-center gap-2 text-sm">
            <span className="w-28 shrink-0 text-slate-500">{k}</span>
            <code className="flex-1 min-w-0 truncate rounded bg-slate-900 px-2 py-1 text-slate-200">{v}</code>
            <Copy text={v} />
          </div>
        ))}
      </div>
      <p className="text-xs text-slate-500">
        Copy the code below into your app.py / script — the settings block has this database's real values,
        nothing else to set up. (Linked projects also get them as DATABASE_URL / PG* environment variables, for
        code that prefers that.) Keep the password private: anyone with it can open this database.
      </p>
      <div className="flex flex-wrap gap-1">
        {Object.keys(code).map((k) => (
          <button key={k} type="button" onClick={() => setTab(k)}
            className={`rounded px-2 py-1 text-xs ${tab === k ? 'bg-sky-700 text-white' : 'bg-slate-800 text-slate-300'}`}>{k}</button>
        ))}
      </div>
      <div className="relative">
        <pre className="overflow-x-auto rounded-lg bg-slate-950 p-3 text-xs text-slate-300">{code[tab]}</pre>
        <div className="absolute right-1 top-1"><Copy text={code[tab]} /></div>
      </div>
    </Modal>
  )
}

/** Pick none / a project / a website. */
function LinkPicker({ targets, value, onChange }) {
  const options = [['', 'Not linked'],
    ...targets.projects.map((n) => [`project:${n}`, `Project · ${n}`]),
    ...targets.websites.map((n) => [`website:${n}`, `Website · ${n}`])]
  return (
    <select className="input" value={value} onChange={(e) => onChange(e.target.value)}>
      {options.map(([v, l]) => <option key={v} value={v}>{l}</option>)}
    </select>
  )
}

function splitLink(v) {
  if (!v) return { kind: null, name: null }
  const i = v.indexOf(':')
  return { kind: v.slice(0, i), name: v.slice(i + 1) }
}

/** Databases → PostgreSQL tab. */
export default function PostgresDatabases({ tabs }) {
  const [status, setStatus] = useState(null)
  const [dbs, setDbs] = useState([])
  const [targets, setTargets] = useState({ projects: [], websites: [] })
  const [error, setError] = useState('')
  const [busy, setBusy] = useState('')
  const [create, setCreate] = useState(null)        // form or null
  const [linking, setLinking] = useState(null)      // {db, value}
  const [conn, setConn] = useState(null)            // {conn, note}
  const [browse, setBrowse] = useState('')
  const [queryDb, setQueryDb] = useState('')
  const importRef = useRef(null)
  const [importTarget, setImportTarget] = useState(null)

  const refresh = useCallback(() => {
    setError('')
    api.get('/postgres/status').then((res) => {
      setStatus(res.data)
      if (res.data.running) {
        api.get('/postgres').then((r) => setDbs(r.data)).catch((err) => setError(errorMessage(err)))
        api.get('/postgres/link-targets').then((r) => setTargets(r.data)).catch(() => {})
      }
    }).catch((err) => setError(errorMessage(err)))
  }, [])

  useEffect(() => { refresh() }, [refresh])

  async function act(label, fn) {
    setBusy(label); setError('')
    try { return await fn() } catch (err) { setError(errorMessage(err)) } finally { setBusy('') }
  }

  const install = () => act('install', async () => {
    await api.post('/postgres/install'); refresh()
  })

  const submitCreate = (e) => {
    e.preventDefault()
    act('create', async () => {
      const { kind, name } = splitLink(create.link)
      const res = await api.post('/postgres', { name: create.name, conn_limit: Number(create.conn_limit) || 20,
        link_kind: kind, link_name: name })
      setCreate(null)
      setConn({ conn: res.data.connection, note: res.data.linked
        ? `Created and linked to ${res.data.linked}. Restart its dashboard/app to use it.` : 'Created.' })
      refresh()
    })
  }

  const submitLink = (e) => {
    e.preventDefault()
    act('link', async () => {
      const { kind, name } = splitLink(linking.value)
      const res = await api.post(`/postgres/${linking.db}/link`, { kind, name })
      setLinking(null)
      if (res.data.connection) setConn({ conn: res.data.connection, note: res.data.detail })
      else alert(res.data.detail)
      refresh()
    })
  }

  const showConnection = (d) => act('conn', async () => {
    const res = await api.get(`/postgres/${d.name}/connection`)
    if (res.data.connection) { setConn({ conn: res.data.connection }); return }
    if (window.confirm(`“${d.name}” isn't linked, so its password isn't stored anywhere.\n\nSet a new password and show it?`)) {
      const r = await api.post(`/postgres/${d.name}/password`)
      setConn({ conn: r.data.connection, note: r.data.detail })
    }
  })

  const resetPassword = (d) => {
    if (!window.confirm(`Set a new password for “${d.name}”? Code with the old password pasted in stops connecting until you paste the new one` +
      (d.linked_name ? ` (the linked ${d.linked_kind} gets the new one — restart it).` : '.'))) return
    act('pw', async () => {
      const r = await api.post(`/postgres/${d.name}/password`)
      setConn({ conn: r.data.connection, note: r.data.detail })
      refresh()
    })
  }

  const drop = (d) => {
    if (!window.confirm(`Delete PostgreSQL database “${d.name}” and its user?\nA backup is saved first.`)) return
    if (window.prompt(`Type the name to confirm:`) !== d.name) return
    act('drop', async () => { const r = await api.delete(`/postgres/${d.name}`); alert(r.data.detail); refresh() })
  }

  const exportDb = (name) => act('export', async () => {
    const res = await api.get(`/postgres/${name}/export`, { responseType: 'blob' })
    const url = URL.createObjectURL(res.data)
    const a = document.createElement('a'); a.href = url; a.download = `${name}.sql`; a.click()
    URL.revokeObjectURL(url)
  })

  const exportExcel = (name) => act(`xlsx-${name}`, async () => {
    const res = await api.get(`/postgres/${name}/xlsx`, { responseType: 'blob' })
    const url = URL.createObjectURL(res.data)
    const a = document.createElement('a'); a.href = url; a.download = `${name}.xlsx`; a.click()
    URL.revokeObjectURL(url)
  })

  const importDb = (file) => {
    if (!file || !importTarget) return
    const form = new FormData(); form.append('file', file)
    act('import', async () => { await api.post(`/postgres/${importTarget}/import`, form); alert(`Imported into ${importTarget}`); refresh() })
  }

  const columns = [
    { key: 'name', label: 'Database', render: (d) => (
      <NameCell icon="database" tint="mint" title={d.name} subtitle={`user: ${d.name}`} onClick={() => setBrowse(d.name)} />) },
    { key: 'size', label: 'Size', render: (d) => <span className="font-mono text-xs">{fmtBytes(d.size)}</span> },
    { key: 'connections', label: 'Connections', render: (d) => (
      <span className="font-mono text-xs">{d.connections} / {d.conn_limit > 0 ? d.conn_limit : '∞'}</span>) },
    { key: 'linked', label: 'Used by', render: (d) => d.linked_name
      ? <span className="badge-muted">{d.linked_kind} · {d.linked_name}</span>
      : <span className="text-slate-600">—</span> },
    { key: 'actions', label: 'Actions', align: 'right', width: '21rem', render: (d) => (
      <RowActions>
        <button className="btn-icon" title="Connection details" onClick={() => showConnection(d)}><Icon name="plug" size={15} /></button>
        <button className="btn-icon" title="Link to a project / website"
          onClick={() => setLinking({ db: d.name, value: d.linked_name ? `${d.linked_kind}:${d.linked_name}` : '' })}>
          <Icon name="link" size={15} /></button>
        <button className="btn-icon" title="Browse tables" onClick={() => setBrowse(d.name)}><Icon name="layers" size={15} /></button>
        <button className="btn-icon" title="Query" onClick={() => setQueryDb(d.name)}><Icon name="terminal" size={15} /></button>
        <button className="btn-icon" title="New password" onClick={() => resetPassword(d)}><Icon name="shield" size={15} /></button>
        <button className="btn-icon" title="Export whole database to Excel (one sheet per table)"
          onClick={() => exportExcel(d.name)} disabled={busy === `xlsx-${d.name}`}>
          {busy === `xlsx-${d.name}` ? <span className="text-[10px]">…</span> : <Icon name="chart" size={15} />}</button>
        <button className="btn-icon" title="Export .sql (backup)" onClick={() => exportDb(d.name)}><Icon name="download" size={15} /></button>
        <button className="btn-icon" title="Import .sql" onClick={() => { setImportTarget(d.name); importRef.current?.click() }}>
          <Icon name="upload" size={15} /></button>
        <button className="btn-icon-danger" title="Delete" onClick={() => drop(d)}><Icon name="trash" size={15} /></button>
      </RowActions>) },
  ]

  return (
    <div className="space-y-6">
      <PageHeader title="Databases" crumbs={[{ label: 'Data' }, { label: 'PostgreSQL' }]}
        actions={status?.running && (
          <>
            <button className="btn-secondary" onClick={refresh}><Icon name="refresh" size={15} />Refresh</button>
            <button className="btn-primary" onClick={() => setCreate({ name: '', conn_limit: 20, link: '' })}>
              <Icon name="plus" size={15} />New Database</button>
          </>
        )} />
      {tabs}

      {error && (
        <div className="flex items-start gap-2 rounded-lg border border-red-500/30 bg-red-500/10 px-3 py-2 text-sm text-red-300">
          <Icon name="warning" size={15} className="mt-0.5" />{error}
        </div>
      )}

      {status === null && <p className="text-sm text-slate-500">Checking PostgreSQL…</p>}

      {status && !status.installed && (
        <div className="card space-y-3">
          <h3 className="section-title">PostgreSQL isn't installed</h3>
          <p className="text-sm text-slate-400">
            Installs PostgreSQL locked down for this server: it listens on 127.0.0.1 only, every database gets its
            own user that can open that database and nothing else, and memory and connections are capped to this
            machine's RAM so it can't slow the dashboards down.
          </p>
          {status.error && <p className="text-xs text-amber-300">{status.error}</p>}
          <button className="btn-primary" onClick={install} disabled={busy === 'install'}>
            {busy === 'install' ? 'Installing… (a minute or two)' : <><Icon name="download" size={15} />Install PostgreSQL</>}
          </button>
        </div>
      )}

      {status?.installed && !status.running && (
        <div className="card space-y-3">
          <h3 className="section-title">PostgreSQL is installed but not running</h3>
          {status.error && <p className="text-xs text-amber-300">{status.error}</p>}
          <button className="btn-primary" disabled={busy === 'cfg'}
            onClick={() => act('cfg', async () => { await api.post('/postgres/configure'); refresh() })}>
            {busy === 'cfg' ? 'Starting…' : 'Re-apply config & start'}</button>
        </div>
      )}

      {status?.running && (
        <>
          <div className="flex flex-wrap gap-x-6 gap-y-1 text-xs text-slate-400">
            <span>PostgreSQL {status.server_version} · port {status.port}</span>
            <span>Connections {status.connections} / {status.max_connections}</span>
            <span>Memory (shared_buffers) {status.shared_buffers}</span>
            <span className="text-emerald-400">● localhost only · one user per database · password required</span>
          </div>
          <DataTable columns={columns} rows={dbs} rowKey={(d) => d.name}
            empty="No PostgreSQL databases yet — create one and link it to a project or website." />
          <input ref={importRef} type="file" accept=".sql" className="hidden"
            onChange={(e) => { importDb(e.target.files[0]); e.target.value = '' }} />
          {browse && <PgBrowser db={browse} onClose={() => setBrowse('')} />}
          <PgQuery dbs={dbs} db={queryDb} setDb={setQueryDb} />
        </>
      )}

      {create && (
        <Modal title="New PostgreSQL database" onClose={() => setCreate(null)} as="form" onSubmit={submitCreate}
          subtitle="A user with the same name is created; it can only open this database."
          footer={<button className="btn-primary" disabled={busy === 'create'}>{busy === 'create' ? 'Creating…' : 'Create'}</button>}>
          <label className="block space-y-1 text-sm">
            <span className="text-slate-400">Name (lowercase letters, numbers, _)</span>
            <input className="input" value={create.name} required pattern="[a-z][a-z0-9_]{2,62}"
              placeholder="mga_ops" onChange={(e) => setCreate({ ...create, name: e.target.value.toLowerCase() })} />
          </label>
          <label className="block space-y-1 text-sm">
            <span className="text-slate-400">Use it in (gets DATABASE_URL automatically)</span>
            <LinkPicker targets={targets} value={create.link} onChange={(v) => setCreate({ ...create, link: v })} />
          </label>
          <label className="block space-y-1 text-sm">
            <span className="text-slate-400">Max connections (1–50) — keeps one project from using them all</span>
            <input className="input" type="number" min="1" max="50" value={create.conn_limit}
              onChange={(e) => setCreate({ ...create, conn_limit: e.target.value })} />
          </label>
        </Modal>
      )}

      {linking && (
        <Modal title={`Link “${linking.db}”`} onClose={() => setLinking(null)} as="form" onSubmit={submitLink}
          subtitle="Sets a NEW password (shown next, with ready code). Update any code where you pasted the old one."
          footer={<button className="btn-primary" disabled={busy === 'link'}>{busy === 'link' ? 'Saving…' : 'Save'}</button>}>
          <LinkPicker targets={targets} value={linking.value} onChange={(v) => setLinking({ ...linking, value: v })} />
          <p className="text-xs text-slate-500">One database per project/website — linking here unlinks whatever that
            project/website used before. Restart its dashboard/app afterwards; scripts pick it up on their next run.</p>
        </Modal>
      )}

      {conn && <ConnectionModal conn={conn.conn} note={conn.note} onClose={() => setConn(null)} />}
    </div>
  )
}

function PgBrowser({ db, onClose }) {
  const [tables, setTables] = useState(null)
  const [table, setTable] = useState(null)
  const [error, setError] = useState('')
  useEffect(() => {
    setTables(null); setTable(null)
    api.get(`/postgres/${db}/tables`).then((r) => setTables(r.data)).catch((err) => setError(errorMessage(err)))
  }, [db])
  return (
    <div className="card space-y-3">
      <div className="flex items-center justify-between">
        <h3 className="section-title">Tables in {db}</h3>
        <button className="btn-icon" onClick={onClose}><Icon name="x" size={15} /></button>
      </div>
      {error && <p className="text-sm text-red-400">{error}</p>}
      {tables === null ? <p className="text-sm text-slate-500">Loading…</p> : tables.length === 0
        ? <p className="text-sm text-slate-500">No tables yet.</p> : (
          <div className="flex flex-wrap gap-2">
            {tables.map((t) => (
              <button key={t.name} onClick={() => setTable(t.name)}
                className={`rounded-lg border px-2 py-1 text-xs ${table === t.name ? 'border-sky-500 text-sky-300' : 'border-panel-border text-slate-300'}`}>
                {t.name} <span className="text-slate-500">~{t.rows.toLocaleString()} rows · {fmtBytes(t.size)}</span>
              </button>
            ))}
          </div>
        )}
      {table && <TableViewer key={table} db={db} table={table} />}
    </div>
  )
}

/** Every row of a table: pages, search across all columns, sort by any column, CSV download. */
function TableViewer({ db, table }) {
  const [data, setData] = useState(null)
  const [page, setPage] = useState(0)
  const [size, setSize] = useState(100)
  const [search, setSearch] = useState('')
  const [applied, setApplied] = useState('')
  const [sort, setSort] = useState(null)       // {col, desc}
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')
  const [picked, setPicked] = useState(null)   // columns chosen for export (null = all)
  const [showCols, setShowCols] = useState(false)
  const [exporting, setExporting] = useState('')

  useEffect(() => {
    setLoading(true); setError('')
    const params = { limit: size, offset: page * size }
    if (applied) params.search = applied
    if (sort) { params.sort = sort.col; params.desc = sort.desc }
    api.get(`/postgres/${db}/tables/${encodeURIComponent(table)}`, { params })
      .then((r) => setData(r.data)).catch((err) => setError(errorMessage(err)))
      .finally(() => setLoading(false))
  }, [db, table, page, size, applied, sort])

  const total = data?.total ?? 0
  const pages = Math.max(1, Math.ceil(total / size))
  const from = total ? page * size + 1 : 0
  const to = Math.min(total, (page + 1) * size)

  function toggleSort(col) {
    setPage(0)
    setSort((s) => (!s || s.col !== col ? { col, desc: false } : s.desc ? null : { col, desc: true }))
  }

  const allCols = data ? data.columns.map((c) => c.name) : []
  const chosen = picked ?? allCols

  function download(kind) {
    const params = {}
    if (applied) params.search = applied
    if (sort) { params.sort = sort.col; params.desc = sort.desc }
    if (picked && picked.length && picked.length < allCols.length) params.columns = picked.join(',')
    setExporting(kind); setError('')
    api.get(`/postgres/${db}/tables/${encodeURIComponent(table)}/${kind}`, { params, responseType: 'blob' })
      .then((res) => {
        const url = URL.createObjectURL(res.data)
        const a = document.createElement('a'); a.href = url; a.download = `${table}.${kind}`; a.click()
        URL.revokeObjectURL(url)
      })
      .catch((err) => setError(errorMessage(err)))
      .finally(() => setExporting(''))
  }

  function toggleCol(c) {
    const next = chosen.includes(c) ? chosen.filter((x) => x !== c) : allCols.filter((x) => x === c || chosen.includes(x))
    setPicked(next)
  }

  return (
    <div className="space-y-2">
      <div className="flex flex-wrap items-center gap-2">
        <form className="flex gap-2" onSubmit={(e) => { e.preventDefault(); setPage(0); setApplied(search.trim()) }}>
          <input className="input w-64" placeholder="Search in all columns…" value={search}
            onChange={(e) => setSearch(e.target.value)} />
          <button className="btn-secondary"><Icon name="search" size={14} />Search</button>
          {applied && (
            <button type="button" className="btn-secondary"
              onClick={() => { setSearch(''); setApplied(''); setPage(0) }}>Clear</button>
          )}
        </form>
        <select className="input w-auto" value={size} onChange={(e) => { setSize(Number(e.target.value)); setPage(0) }}>
          {[100, 500, 1000].map((n) => <option key={n} value={n}>{n} rows / page</option>)}
        </select>
        <div className="ml-auto flex flex-wrap items-center gap-2">
          <button className="btn-secondary" onClick={() => setShowCols(!showCols)} title="Choose which columns to export">
            Columns {chosen.length < allCols.length ? `(${chosen.length}/${allCols.length})` : '(all)'}</button>
          <button className="btn-primary" onClick={() => download('xlsx')} disabled={!!exporting || chosen.length === 0}
            title="Excel file — chosen columns, current search and sort">
            <Icon name="download" size={14} />{exporting === 'xlsx' ? 'Preparing…' : 'Excel'}</button>
          <button className="btn-secondary" onClick={() => download('csv')} disabled={!!exporting || chosen.length === 0}
            title="CSV — chosen columns, current search and sort">
            <Icon name="download" size={14} />{exporting === 'csv' ? 'Preparing…' : 'CSV'}</button>
        </div>
      </div>

      {showCols && data && (
        <div className="rounded-lg border border-panel-border p-2 space-y-2">
          <div className="flex items-center gap-3 text-xs">
            <span className="text-slate-400">Export these columns:</span>
            <button className="text-sky-400 hover:underline" onClick={() => setPicked(null)}>All</button>
            <button className="text-sky-400 hover:underline" onClick={() => setPicked([])}>None</button>
          </div>
          <div className="grid grid-cols-2 sm:grid-cols-4 lg:grid-cols-6 gap-1">
            {allCols.map((c) => (
              <label key={c} className="flex items-center gap-1.5 text-xs text-slate-300 cursor-pointer">
                <input type="checkbox" checked={chosen.includes(c)} onChange={() => toggleCol(c)} />{c}
              </label>
            ))}
          </div>
          <p className="text-[11px] text-slate-500">The export uses these columns plus the current search and sort.
            Excel keeps numbers and dates as real numbers/dates; more than ~1 million rows continue on a second sheet.</p>
        </div>
      )}

      {data && (
        <p className="text-xs text-slate-500">
          {data.columns.length} columns: {data.columns.map((c) => `${c.name} (${c.type})`).join(' · ')}
        </p>
      )}
      {error && <p className="text-sm text-red-400">{error}</p>}

      {data && (
        <div className={`max-h-[65vh] overflow-auto rounded-lg border border-panel-border ${loading ? 'opacity-60' : ''}`}>
          <table className="min-w-full text-xs">
            <thead className="sticky top-0 z-10 bg-slate-900">
              <tr>
                <th className="px-2 py-1.5 text-right text-slate-600">#</th>
                {data.preview.columns.map((c) => (
                  <th key={c} onClick={() => toggleSort(c)} title="Sort"
                    className="cursor-pointer select-none whitespace-nowrap px-2 py-1.5 text-left text-slate-400 hover:text-slate-200">
                    {c}{sort?.col === c ? (sort.desc ? ' ▼' : ' ▲') : ''}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {data.preview.rows.map((r, i) => (
                <tr key={i} className="border-t border-slate-800 hover:bg-slate-800/40">
                  <td className="px-2 py-1 text-right font-mono text-slate-600">{from + i}</td>
                  {r.map((v, j) => (
                    <td key={j} className="whitespace-nowrap px-2 py-1 text-slate-300">
                      {v === null ? <span className="text-slate-600">NULL</span> : String(v)}
                    </td>
                  ))}
                </tr>
              ))}
              {data.preview.rows.length === 0 && (
                <tr>
                  <td colSpan={data.preview.columns.length + 1} className="px-2 py-4 text-center text-slate-500">
                    {applied ? 'Nothing matches that search.' : 'This table is empty.'}
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      )}

      {data && (
        <div className="flex flex-wrap items-center gap-2 text-xs text-slate-400">
          <span>
            Rows {from.toLocaleString()}–{to.toLocaleString()} of {data.total_exact ? '' : '~'}{total.toLocaleString()}
            {applied ? ` matching "${applied}"` : ''}
          </span>
          <div className="ml-auto flex items-center gap-1">
            <button className="btn-icon" disabled={page === 0} onClick={() => setPage(0)} title="First">«</button>
            <button className="btn-icon" disabled={page === 0} onClick={() => setPage(page - 1)} title="Previous">
              <Icon name="chevron-left" size={14} /></button>
            <span className="px-2">Page {page + 1} / {pages.toLocaleString()}</span>
            <button className="btn-icon" disabled={page + 1 >= pages} onClick={() => setPage(page + 1)} title="Next">
              <Icon name="chevron-right" size={14} /></button>
            <button className="btn-icon" disabled={page + 1 >= pages} onClick={() => setPage(pages - 1)} title="Last">»</button>
          </div>
        </div>
      )}
    </div>
  )
}

function ResultGrid({ result }) {
  if (!result?.columns?.length) return null
  return (
    <div className="max-h-96 overflow-auto rounded-lg border border-panel-border">
      <table className="w-full text-xs">
        <thead className="sticky top-0 bg-slate-900">
          <tr>{result.columns.map((c) => <th key={c} className="px-2 py-1 text-left text-slate-400">{c}</th>)}</tr>
        </thead>
        <tbody>
          {result.rows.map((r, i) => (
            <tr key={i} className="border-t border-slate-800">
              {r.map((v, j) => <td key={j} className="whitespace-nowrap px-2 py-1 text-slate-300">
                {v === null ? <span className="text-slate-600">NULL</span> : String(v)}</td>)}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

function PgQuery({ dbs, db, setDb }) {
  const [sql, setSql] = useState('')
  const [result, setResult] = useState(null)
  const [error, setError] = useState('')
  const [running, setRunning] = useState(false)
  async function run() {
    setError(''); setResult(null); setRunning(true)
    try { setResult((await api.post('/postgres/query', { database: db, sql })).data) }
    catch (err) { setError(errorMessage(err)) } finally { setRunning(false) }
  }
  return (
    <div className="card space-y-3">
      <h3 className="section-title">Query</h3>
      <p className="text-xs text-slate-500">Runs as the database's own user (60 s limit, first 1000 rows shown).</p>
      <div className="flex gap-2">
        <select className="input max-w-xs" value={db} onChange={(e) => setDb(e.target.value)}>
          <option value="">Choose a database…</option>
          {dbs.map((d) => <option key={d.name} value={d.name}>{d.name}</option>)}
        </select>
        <button className="btn-primary" onClick={run} disabled={!db || !sql.trim() || running}>
          <Icon name="play" size={15} />{running ? 'Running…' : 'Run'}</button>
      </div>
      <textarea className="input min-h-[120px] font-mono text-xs" value={sql} onChange={(e) => setSql(e.target.value)}
        placeholder="CREATE TABLE orders (id serial PRIMARY KEY, customer text, qty int, created_at timestamptz DEFAULT now());" />
      {error && <p className="text-sm text-red-400 whitespace-pre-wrap">{error}</p>}
      {result && <p className="text-xs text-slate-400">{result.message}</p>}
      <ResultGrid result={result} />
    </div>
  )
}
