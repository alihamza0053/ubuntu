import { useCallback, useEffect, useRef, useState } from 'react'
import api, { errorMessage } from '../api/client'

/** MySQL manager: list/create/drop databases, import/export, query runner. */
export default function Databases() {
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

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <h2 className="text-2xl font-bold">Databases (MySQL)</h2>
        <button className="btn-primary" onClick={() => setShowCreate(true)}>＋ New Database</button>
      </div>

      {error && <p className="text-red-400 text-sm">{error}</p>}

      {/* DB list */}
      <div className="card">
        <table className="w-full text-sm">
          <thead>
            <tr className="text-left text-xs uppercase text-slate-500 border-b border-panel-border">
              <th className="py-2">Database</th>
              <th>Linked website</th>
              <th className="text-right">Actions</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-panel-border">
            {databases.map((d) => (
              <tr key={d.name}>
                <td className="py-2 font-mono">🗄 {d.name}</td>
                <td className="text-slate-400">{d.linked_website || '—'}</td>
                <td className="text-right space-x-2 whitespace-nowrap">
                  <button onClick={() => setBrowseDb(d.name)} className="text-sky-400 hover:underline">Browse</button>
                  <button onClick={() => { setQueryDb(d.name); }} className="text-sky-400 hover:underline">Query</button>
                  <button onClick={() => exportDb(d.name)} className="text-sky-400 hover:underline">Export</button>
                  <button
                    onClick={() => { setImportTarget(d.name); importRef.current?.click() }}
                    className="text-sky-400 hover:underline"
                  >
                    Import
                  </button>
                  <button onClick={() => drop(d.name)} className="text-red-400 hover:underline">Drop</button>
                </td>
              </tr>
            ))}
            {databases.length === 0 && (
              <tr><td colSpan={3} className="py-6 text-center text-slate-600">No databases</td></tr>
            )}
          </tbody>
        </table>
        <input
          ref={importRef}
          type="file"
          accept=".sql"
          className="hidden"
          onChange={(e) => { importDb(e.target.files[0]); e.target.value = '' }}
        />
      </div>

      {/* Database browser */}
      <DbBrowser databases={databases} db={browseDb} setDb={setBrowseDb} />

      {/* Query runner */}
      <div className="card">
        <h3 className="font-semibold mb-2">Query Runner</h3>
        <div className="flex gap-2 mb-2">
          <select className="input max-w-xs" value={queryDb} onChange={(e) => setQueryDb(e.target.value)}>
            <option value="">— select database —</option>
            {databases.map((d) => <option key={d.name} value={d.name}>{d.name}</option>)}
          </select>
          <button className="btn-primary" onClick={runQuery} disabled={!queryDb || !sql.trim()}>Run</button>
        </div>
        <textarea
          className="input font-mono h-28"
          placeholder="SELECT * FROM users LIMIT 10;"
          value={sql}
          onChange={(e) => setSql(e.target.value)}
        />
        {result && (
          <div className="mt-3 overflow-auto">
            <p className="text-xs text-slate-500 mb-1">{result.message}</p>
            {result.columns?.length > 0 && (
              <table className="w-full text-xs border border-panel-border">
                <thead>
                  <tr className="bg-slate-800">
                    {result.columns.map((c) => <th key={c} className="px-2 py-1 text-left border border-panel-border">{c}</th>)}
                  </tr>
                </thead>
                <tbody>
                  {result.rows.map((row, i) => (
                    <tr key={i}>
                      {row.map((cell, j) => <td key={j} className="px-2 py-1 border border-panel-border font-mono">{cell}</td>)}
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </div>
        )}
      </div>

      {/* Create modal */}
      {showCreate && (
        <div className="fixed inset-0 bg-black/60 flex items-center justify-center z-50 px-4">
          <form onSubmit={create} className="card w-full max-w-md space-y-3">
            <h3 className="text-lg font-semibold">New Database</h3>
            <input className="input" placeholder="database name" value={form.name}
              onChange={(e) => setForm({ ...form, name: e.target.value })} required />
            <p className="text-xs text-slate-500">Optionally create a dedicated user with full access:</p>
            <input className="input" placeholder="username (optional)" value={form.user}
              onChange={(e) => setForm({ ...form, user: e.target.value })} />
            <input className="input" type="password" placeholder="password (optional)" value={form.password}
              onChange={(e) => setForm({ ...form, password: e.target.value })} />
            <div className="flex justify-end gap-2">
              <button type="button" className="btn-secondary" onClick={() => setShowCreate(false)}>Cancel</button>
              <button type="submit" className="btn-primary">Create</button>
            </div>
          </form>
        </div>
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
      <div className="flex items-center gap-3 flex-wrap mb-3">
        <h3 className="font-semibold">Database Browser</h3>
        <select className="input max-w-xs" value={db} onChange={(e) => setDb(e.target.value)}>
          <option value="">— select database —</option>
          {databases.map((d) => <option key={d.name} value={d.name}>{d.name}</option>)}
        </select>
        {error && <span className="text-red-400 text-sm">{error}</span>}
      </div>

      {!db ? (
        <p className="text-slate-600 text-sm">Pick a database (or click “Browse” above) to explore its tables.</p>
      ) : (
        <div className="flex gap-4" style={{ minHeight: '40vh' }}>
          {/* Tables list */}
          <aside className="w-60 shrink-0 border-r border-panel-border pr-3 overflow-y-auto" style={{ maxHeight: '60vh' }}>
            <p className="text-xs uppercase tracking-wide text-slate-500 mb-2">
              Tables ({tables.length})
            </p>
            <ul className="space-y-0.5">
              {tables.map((t) => (
                <li key={t.name}>
                  <button
                    onClick={() => openTable(t.name)}
                    className={`w-full text-left px-2 py-1.5 rounded text-sm flex justify-between gap-2 ${
                      table === t.name ? 'bg-sky-600/20 text-sky-300' : 'text-slate-300 hover:bg-slate-700/50'
                    }`}
                  >
                    <span className="truncate font-mono">📋 {t.name}</span>
                    <span className="text-xs text-slate-500 shrink-0">{t.rows ?? '?'}</span>
                  </button>
                </li>
              ))}
              {tables.length === 0 && <li className="text-xs text-slate-600 px-2">No tables</li>}
            </ul>
          </aside>

          {/* Table detail */}
          <div className="flex-1 min-w-0">
            {!table ? (
              <p className="text-slate-600 text-sm">Select a table on the left.</p>
            ) : !info ? (
              <p className="text-slate-500 text-sm">Loading {table}…</p>
            ) : (
              <>
                <div className="flex items-center gap-3 mb-3 flex-wrap">
                  <span className="font-mono text-sky-300">{table}</span>
                  <span className="text-xs text-slate-500">
                    {info.columns.length} columns · {info.row_count} rows
                  </span>
                  <div className="ml-auto flex gap-1">
                    <button className={view === 'columns' ? 'btn-primary' : 'btn-secondary'} onClick={() => setView('columns')}>
                      Columns
                    </button>
                    <button className={view === 'data' ? 'btn-primary' : 'btn-secondary'} onClick={() => setView('data')}>
                      Data
                    </button>
                  </div>
                </div>

                <div className="overflow-auto" style={{ maxHeight: '55vh' }}>
                  {view === 'columns' ? (
                    <table className="w-full text-xs border border-panel-border">
                      <thead>
                        <tr className="bg-slate-800 text-left">
                          {['Column', 'Type', 'Null', 'Key', 'Default', 'Extra'].map((h) => (
                            <th key={h} className="px-2 py-1 border border-panel-border">{h}</th>
                          ))}
                        </tr>
                      </thead>
                      <tbody>
                        {info.columns.map((c) => (
                          <tr key={c.name}>
                            <td className="px-2 py-1 border border-panel-border font-mono text-sky-300">{c.name}</td>
                            <td className="px-2 py-1 border border-panel-border font-mono">{c.type}</td>
                            <td className="px-2 py-1 border border-panel-border">{c.null}</td>
                            <td className="px-2 py-1 border border-panel-border">
                              {c.key === 'PRI' ? <span className="text-yellow-400">🔑 PRI</span> : c.key}
                            </td>
                            <td className="px-2 py-1 border border-panel-border text-slate-400">{c.default}</td>
                            <td className="px-2 py-1 border border-panel-border text-slate-400">{c.extra}</td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  ) : (
                    <table className="w-full text-xs border border-panel-border">
                      <thead>
                        <tr className="bg-slate-800 text-left">
                          {info.preview.columns.map((c) => (
                            <th key={c} className="px-2 py-1 border border-panel-border font-mono">
                              {c}{c === pkColumn && <span className="text-yellow-400"> 🔑</span>}
                            </th>
                          ))}
                          <th className="px-2 py-1 border border-panel-border w-px">Actions</th>
                        </tr>
                      </thead>
                      <tbody>
                        {info.preview.rows.map((row, i) => (
                          <tr key={i}>
                            {row.map((cell, j) => (
                              <td key={j} className="px-2 py-1 border border-panel-border font-mono whitespace-nowrap">
                                {editIdx === i ? (
                                  <input
                                    className="bg-slate-900 border border-panel-border rounded px-1 py-0.5 w-full min-w-[6rem]"
                                    value={editVals[j] ?? ''}
                                    onChange={(e) => {
                                      const v = [...editVals]; v[j] = e.target.value; setEditVals(v)
                                    }}
                                  />
                                ) : cell === 'NULL' ? (
                                  <span className="text-slate-600 italic">NULL</span>
                                ) : cell}
                              </td>
                            ))}
                            <td className="px-2 py-1 border border-panel-border whitespace-nowrap text-right space-x-2">
                              {!pkColumn ? (
                                <span className="text-slate-600" title="Editing needs a single primary-key column">—</span>
                              ) : editIdx === i ? (
                                <>
                                  <button className="text-green-400 hover:underline" onClick={() => saveEdit(row)}>save</button>
                                  <button className="text-slate-400 hover:underline" onClick={cancelEdit}>cancel</button>
                                </>
                              ) : (
                                <>
                                  <button className="text-sky-400 hover:underline" onClick={() => startEdit(i, row)}>✎ edit</button>
                                  <button className="text-red-400 hover:underline" onClick={() => deleteRow(row)}>🗑</button>
                                </>
                              )}
                            </td>
                          </tr>
                        ))}
                        {info.preview.rows.length === 0 && (
                          <tr><td className="px-2 py-3 text-center text-slate-600" colSpan={(info.preview.columns.length || 1) + 1}>
                            (no rows)
                          </td></tr>
                        )}
                      </tbody>
                    </table>
                  )}
                </div>
                {view === 'data' && !pkColumn && info.preview.rows.length > 0 && (
                  <p className="text-xs text-yellow-500/80 mt-2">
                    This table has no single primary key — rows can't be safely edited here. Use the Query Runner.
                  </p>
                )}
                {view === 'data' && info.row_count > info.preview.rows.length && (
                  <p className="text-xs text-slate-500 mt-2">
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
