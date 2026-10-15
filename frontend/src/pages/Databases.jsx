import { useCallback, useEffect, useRef, useState } from 'react'
import api, { errorMessage } from '../api/client'
import DataTable, { NameCell, RowActions } from '../components/ui/DataTable'
import Icon from '../components/ui/Icon'
import Modal from '../components/ui/Modal'
import PageHeader from '../components/ui/PageHeader'
import Tabs from '../components/ui/Tabs'
import PostgresDatabases from '../components/PostgresDatabases'

const ENGINES = [{ key: 'mysql', label: 'MySQL' }, { key: 'postgres', label: 'PostgreSQL' }]

/** Databases section: a MySQL tab and a PostgreSQL tab. */
export default function Databases() {
  const [engine, setEngine] = useState(() => {
    try { return localStorage.getItem('db-engine') || 'mysql' } catch { return 'mysql' }
  })
  const pick = (key) => { setEngine(key); try { localStorage.setItem('db-engine', key) } catch { /* private mode */ } }
  const tabs = <Tabs tabs={ENGINES} active={engine} onChange={pick} />
  return engine === 'postgres' ? <PostgresDatabases tabs={tabs} /> : <MysqlDatabases tabs={tabs} />
}

/** MySQL manager: list/create/drop databases, import/export, query runner. */
function MysqlDatabases({ tabs }) {
  const [databases, setDatabases] = useState([])
  const [showCreate, setShowCreate] = useState(false)
  const [form, setForm] = useState({ name: '', user: '', password: '' })
  const [queryDb, setQueryDb] = useState('')
  const [sql, setSql] = useState('')
  const [result, setResult] = useState(null)
  const [error, setError] = useState('')
  const importRef = useRef(null)
  const [importTarget, setImportTarget] = useState(null)
  const [browseDb, setBrowseDb] = useState('')

  const refresh = useCallback(() => {
    api.get('/databases').then((res) => setDatabases(res.data)).catch((err) => setError(errorMessage(err)))
  }, [])

  useEffect(() => {
    refresh()
  }, [refresh])

  async function create(e) {
    e.preventDefault()
    try {
      await api.post('/databases', form)
      setShowCreate(false)
      setForm({ name: '', user: '', password: '' })
      refresh()
    } catch (err) {
      alert(errorMessage(err))
    }
  }

  async function drop(name) {
    if (!window.confirm(`DROP DATABASE ${name}? This permanently deletes all its data.`)) return
    if (!window.confirm(`Really drop "${name}"? This cannot be undone.`)) return
    try {
      await api.delete(`/databases/${name}`)
      refresh()
    } catch (err) {
      alert(errorMessage(err))
    }
  }

  async function runQuery() {
    setError('')
    setResult(null)
    try {
      const res = await api.post('/databases/query', { database: queryDb, sql })
      setResult(res.data)
    } catch (err) {
      setError(errorMessage(err))
    }
  }

  function exportDb(name) {
    api
      .get(`/databases/${name}/export`, { responseType: 'blob' })
      .then((res) => {
        const url = URL.createObjectURL(res.data)
        const a = document.createElement('a')
        a.href = url
        a.download = `${name}.sql`
        a.click()
        URL.revokeObjectURL(url)
      })
      .catch((err) => alert(errorMessage(err)))
  }

  async function importDb(file) {
    if (!file || !importTarget) return
    const form = new FormData()
    form.append('file', file)
    try {
      await api.post(`/databases/${importTarget}/import`, form)
      alert(`Imported into ${importTarget}`)
    } catch (err) {
      alert(errorMessage(err))
    }
  }

  const columns = [
    {
      key: 'name',
      label: 'Database',
      render: (d) => <NameCell icon="database" tint="mint" title={d.name} onClick={() => setBrowseDb(d.name)} />,
    },
    {
      key: 'linked_website',
      label: 'Linked website',
      render: (d) =>
        d.linked_website ? (
          <span className="badge-muted">{d.linked_website}</span>
        ) : (
          <span className="text-slate-600">—</span>
        ),
    },
    {
      key: 'actions',
      label: 'Actions',
      align: 'right',
      width: '14rem',
      render: (d) => (
        <RowActions>
          <button className="btn-icon" onClick={() => setBrowseDb(d.name)} title="Browse tables">
            <Icon name="layers" size={15} />
          </button>
          <button className="btn-icon" onClick={() => setQueryDb(d.name)} title="Query this database">
            <Icon name="terminal" size={15} />
          </button>
          <button className="btn-icon" onClick={() => exportDb(d.name)} title="Export .sql">
            <Icon name="download" size={15} />
          </button>
          <button
            className="btn-icon"
            onClick={() => { setImportTarget(d.name); importRef.current?.click() }}
            title="Import .sql"
          >
            <Icon name="upload" size={15} />
          </button>
          <button className="btn-icon-danger" onClick={() => drop(d.name)} title="Drop database">
            <Icon name="trash" size={15} />
          </button>
        </RowActions>
      ),
    },
  ]

  return (
    <div className="space-y-6">
      <PageHeader
        title="Databases"
        crumbs={[{ label: 'Data' }, { label: 'MySQL' }]}
        actions={
          <>
            <button className="btn-secondary" onClick={refresh}>
              <Icon name="refresh" size={15} />
              Refresh
            </button>
            <button className="btn-primary" onClick={() => setShowCreate(true)}>
              <Icon name="plus" size={15} />
              New Database
            </button>
          </>
        }
      />
      {tabs}

      {error && (
        <div className="flex items-start gap-2 rounded-lg border border-red-500/30 bg-red-500/10 px-3 py-2 text-sm text-red-300">
          <Icon name="warning" size={15} className="mt-0.5" />
          {error}
        </div>
      )}

      {/* DB list */}
      <DataTable columns={columns} rows={databases} rowKey={(d) => d.name} empty="No databases yet." />
      <input
        ref={importRef}
        type="file"
        accept=".sql"
        className="hidden"
        onChange={(e) => { importDb(e.target.files[0]); e.target.value = '' }}
      />

      {/* Database browser */}
      <DbBrowser databases={databases} db={browseDb} setDb={setBrowseDb} />

      {/* Query runner */}
      <div className="card">
        <div className="mb-4 flex flex-wrap items-center gap-2">
          <h3 className="flex items-center gap-2 font-semibold text-slate-100">
            <Icon name="terminal" size={16} className="text-mint-400" />
            Query Runner
          </h3>
          <select
            className="select ml-auto max-w-xs"
            value={queryDb}
            onChange={(e) => setQueryDb(e.target.value)}
          >
            <option value="">— select database —</option>
            {databases.map((d) => <option key={d.name} value={d.name}>{d.name}</option>)}
          </select>
          <button className="btn-primary" onClick={runQuery} disabled={!queryDb || !sql.trim()}>
            <Icon name="play" size={14} />
            Run
          </button>
        </div>

        <textarea
          className="textarea h-28"
          placeholder="SELECT * FROM users LIMIT 10;"
          value={sql}
          onChange={(e) => setSql(e.target.value)}
        />

        {result && (
          <div className="mt-4">
            <p className="mb-2 text-xs text-slate-500">{result.message}</p>
            {result.columns?.length > 0 && (
              <div className="table-wrap max-h-[50vh] overflow-auto">
                <table className="table">
                  <thead className="sticky top-0 bg-panel-card">
                    <tr>
                      {result.columns.map((c) => <th key={c}>{c}</th>)}
                    </tr>
                  </thead>
                  <tbody>
                    {result.rows.map((row, i) => (
                      <tr key={i}>
                        {row.map((cell, j) => (
                          <td key={j} className="whitespace-nowrap font-mono text-xs">{cell}</td>
                        ))}
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </div>
        )}
      </div>

      {/* Create modal */}
      {showCreate && (
        <Modal
          as="form"
          onSubmit={create}
          title="New Database"
          subtitle="Creates the schema, and optionally a dedicated user with full access to it."
          onClose={() => setShowCreate(false)}
          footer={
            <>
              <button type="button" className="btn-secondary" onClick={() => setShowCreate(false)}>Cancel</button>
              <button type="submit" className="btn-primary">Create database</button>
            </>
          }
        >
          <div>
            <label className="label">Database name</label>
            <input className="input" placeholder="database name" value={form.name}
              onChange={(e) => setForm({ ...form, name: e.target.value })} autoFocus required />
          </div>
          <div>
            <label className="label">User (optional)</label>
            <input className="input" placeholder="username" value={form.user}
              onChange={(e) => setForm({ ...form, user: e.target.value })} />
          </div>
          <div>
            <label className="label">Password (optional)</label>
            <input className="input" type="password" placeholder="password" value={form.password}
              onChange={(e) => setForm({ ...form, password: e.target.value })} />
          </div>
        </Modal>
      )}
    </div>
  )
}

/**
 * Visual database browser: pick a database → see its tables → click a table to
 * see its columns and a preview of its rows.
 */
function DbBrowser({ databases, db, setDb }) {
  const [tables, setTables] = useState([])
  const [table, setTable] = useState(null)
  const [info, setInfo] = useState(null)
  const [view, setView] = useState('columns') // 'columns' | 'data'
  const [error, setError] = useState('')
  const [editIdx, setEditIdx] = useState(-1)   // which data row is being edited
  const [editVals, setEditVals] = useState([]) // working copy of that row's cells

  // The primary-key column lets us safely UPDATE/DELETE a specific row
  const pkColumn = info?.columns?.find((c) => c.key === 'PRI')?.name || null
  const pkIndex = pkColumn ? (info?.preview?.columns?.indexOf(pkColumn) ?? -1) : -1

  function startEdit(rowIdx, row) {
    setEditIdx(rowIdx)
    setEditVals([...row])
  }

  function cancelEdit() {
    setEditIdx(-1)
    setEditVals([])
  }

  async function saveEdit(originalRow) {
    const cols = info.preview.columns
    const changes = {}
    cols.forEach((c, i) => {
      if (editVals[i] !== originalRow[i]) changes[c] = editVals[i]
    })
    if (Object.keys(changes).length === 0) { cancelEdit(); return }
    try {
      await api.post(`/databases/${db}/tables/${table}/update-row`, {
        pk_column: pkColumn,
        pk_value: originalRow[pkIndex],
        changes,
      })
      cancelEdit()
      openTable(table) // reload fresh data
    } catch (err) {
      alert(errorMessage(err))
    }
  }

  async function deleteRow(originalRow) {
    if (!window.confirm('Delete this row? This cannot be undone.')) return
    try {
      await api.post(`/databases/${db}/tables/${table}/delete-row`, {
        pk_column: pkColumn,
        pk_value: originalRow[pkIndex],
      })
      openTable(table)
    } catch (err) {
      alert(errorMessage(err))
    }
  }

  // Load tables when the selected database changes
  useEffect(() => {
    setTable(null)
    setInfo(null)
    if (!db) {
      setTables([])
      return
    }
    setError('')
    api.get(`/databases/${db}/tables`)
      .then((res) => setTables(res.data))
      .catch((err) => setError(errorMessage(err)))
  }, [db])

  function openTable(name) {
    setTable(name)
    setInfo(null)
    setEditIdx(-1)
    api.get(`/databases/${db}/tables/${name}`, { params: { limit: 100 } })
      .then((res) => setInfo(res.data))
      .catch((err) => setError(errorMessage(err)))
  }

  return (
    <div className="card">
      <div className="mb-4 flex flex-wrap items-center gap-3">
        <h3 className="flex items-center gap-2 font-semibold text-slate-100">
          <Icon name="layers" size={16} className="text-mint-400" />
          Database Browser
        </h3>
        <select className="select ml-auto max-w-xs" value={db} onChange={(e) => setDb(e.target.value)}>
          <option value="">— select database —</option>
          {databases.map((d) => <option key={d.name} value={d.name}>{d.name}</option>)}
        </select>
        {error && <span className="text-sm text-red-400">{error}</span>}
      </div>

      {!db ? (
        <p className="text-sm text-slate-500">
          Pick a database (or hit the browse action above) to explore its tables.
        </p>
      ) : (
        <div className="flex flex-col gap-4 md:flex-row" style={{ minHeight: '40vh' }}>
          {/* Tables list */}
          <aside
            className="w-full shrink-0 overflow-y-auto rounded-xl border border-panel-border/70
                       bg-panel-bg/50 p-2 md:w-60"
            style={{ maxHeight: '60vh' }}
          >
            <p className="px-2 py-1.5 text-[11px] font-semibold uppercase tracking-wider text-slate-500">
              Tables ({tables.length})
            </p>
            <ul className="space-y-0.5">
              {tables.map((t) => (
                <li key={t.name}>
                  <button
                    onClick={() => openTable(t.name)}
                    className={`flex w-full items-center justify-between gap-2 rounded-lg px-2.5 py-2
                                text-left text-sm transition-colors ${
                                  table === t.name
                                    ? 'bg-mint-400/[0.12] text-mint-300'
                                    : 'text-slate-300 hover:bg-panel-raise'
                                }`}
                  >
                    <span className="flex min-w-0 items-center gap-2">
                      <Icon name="grid" size={13} className="text-slate-500" />
                      <span className="truncate font-mono">{t.name}</span>
                    </span>
                    <span className="count-chip shrink-0">{t.rows ?? '?'}</span>
                  </button>
                </li>
              ))}
              {tables.length === 0 && <li className="px-2.5 py-2 text-xs text-slate-600">No tables</li>}
            </ul>
          </aside>

          {/* Table detail */}
          <div className="min-w-0 flex-1">
            {!table ? (
              <p className="text-sm text-slate-500">Select a table on the left.</p>
            ) : !info ? (
              <p className="text-sm text-slate-500">Loading {table}…</p>
            ) : (
              <>
                <div className="mb-3 flex flex-wrap items-center gap-3">
                  <span className="font-mono text-mint-300">{table}</span>
                  <span className="text-xs text-slate-500">
                    {info.columns.length} columns · {info.row_count} rows
                  </span>
                  {/* Segmented view switch */}
                  <div className="ml-auto flex rounded-lg border border-panel-border bg-panel-bg/60 p-0.5">
                    {['columns', 'data'].map((v) => (
                      <button
                        key={v}
                        onClick={() => setView(v)}
                        className={`rounded-md px-3 py-1.5 text-xs font-medium capitalize transition-colors ${
                          view === v ? 'bg-mint-grad text-[#04231a]' : 'text-slate-400 hover:text-slate-100'
                        }`}
                      >
                        {v}
                      </button>
                    ))}
                  </div>
                </div>

                <div className="table-wrap overflow-auto" style={{ maxHeight: '55vh' }}>
                  {view === 'columns' ? (
                    <table className="table">
                      <thead className="sticky top-0 bg-panel-card">
                        <tr>
                          {['Column', 'Type', 'Null', 'Key', 'Default', 'Extra'].map((h) => (
                            <th key={h}>{h}</th>
                          ))}
                        </tr>
                      </thead>
                      <tbody>
                        {info.columns.map((c) => (
                          <tr key={c.name}>
                            <td className="font-mono text-mint-300">{c.name}</td>
                            <td className="font-mono text-xs">{c.type}</td>
                            <td className="text-xs">{c.null}</td>
                            <td>
                              {c.key === 'PRI' ? <span className="badge-warn">PRIMARY</span> : (
                                <span className="text-xs text-slate-500">{c.key || '—'}</span>
                              )}
                            </td>
                            <td className="text-xs text-slate-400">{c.default}</td>
                            <td className="text-xs text-slate-400">{c.extra}</td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  ) : (
                    <table className="table">
                      <thead className="sticky top-0 bg-panel-card">
                        <tr>
                          {info.preview.columns.map((c) => (
                            <th key={c} className="font-mono">
                              {c}{c === pkColumn && <span className="ml-1 text-amber-300">PK</span>}
                            </th>
                          ))}
                          <th className="w-px text-right">Actions</th>
                        </tr>
                      </thead>
                      <tbody>
                        {info.preview.rows.map((row, i) => (
                          <tr key={i}>
                            {row.map((cell, j) => (
                              <td key={j} className="whitespace-nowrap font-mono text-xs">
                                {editIdx === i ? (
                                  <input
                                    className="w-full min-w-[6rem] rounded border border-panel-border
                                               bg-panel-bg px-1.5 py-1 text-slate-100
                                               focus:border-mint-400/70 focus:outline-none"
                                    value={editVals[j] ?? ''}
                                    onChange={(e) => {
                                      const v = [...editVals]; v[j] = e.target.value; setEditVals(v)
                                    }}
                                  />
                                ) : cell === 'NULL' ? (
                                  <span className="italic text-slate-600">NULL</span>
                                ) : cell}
                              </td>
                            ))}
                            <td className="whitespace-nowrap text-right">
                              {!pkColumn ? (
                                <span className="text-slate-600" title="Editing needs a single primary-key column">—</span>
                              ) : editIdx === i ? (
                                <RowActions>
                                  <button className="btn-icon hover:text-mint-300" onClick={() => saveEdit(row)} title="Save">
                                    <Icon name="check" size={15} />
                                  </button>
                                  <button className="btn-icon" onClick={cancelEdit} title="Cancel">
                                    <Icon name="x" size={15} />
                                  </button>
                                </RowActions>
                              ) : (
                                <RowActions>
                                  <button className="btn-icon" onClick={() => startEdit(i, row)} title="Edit row">
                                    <Icon name="pencil" size={15} />
                                  </button>
                                  <button className="btn-icon-danger" onClick={() => deleteRow(row)} title="Delete row">
                                    <Icon name="trash" size={15} />
                                  </button>
                                </RowActions>
                              )}
                            </td>
                          </tr>
                        ))}
                        {info.preview.rows.length === 0 && (
                          <tr>
                            <td className="py-6 text-center text-slate-600" colSpan={(info.preview.columns.length || 1) + 1}>
                              (no rows)
                            </td>
                          </tr>
                        )}
                      </tbody>
                    </table>
                  )}
                </div>

                {view === 'data' && !pkColumn && info.preview.rows.length > 0 && (
                  <p className="mt-2 text-xs text-amber-400/80">
                    This table has no single primary key — rows can&apos;t be safely edited here. Use the Query Runner.
                  </p>
                )}
                {view === 'data' && info.row_count > info.preview.rows.length && (
                  <p className="mt-2 text-xs text-slate-500">
                    Showing first {info.preview.rows.length} of {info.row_count} rows. Use the Query Runner for more.
                  </p>
                )}
              </>
            )}
          </div>
        </div>
      )}
    </div>
  )
}
