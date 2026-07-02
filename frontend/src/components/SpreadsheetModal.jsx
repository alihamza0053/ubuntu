import { useEffect, useMemo, useState } from 'react'
import api, { errorMessage } from '../api/client'

const MAX_ROWS = 2000 // cap rendered rows so huge sheets don't freeze the browser

// SheetJS is self-hosted (frontend/public/vendor/) and loaded on demand — no npm
// dependency and no CDN, so it works fully offline. Resolves window.XLSX.
let _xlsxPromise = null
function loadXLSX() {
  if (window.XLSX) return Promise.resolve(window.XLSX)
  if (_xlsxPromise) return _xlsxPromise
  _xlsxPromise = new Promise((resolve, reject) => {
    const s = document.createElement('script')
    s.src = '/vendor/xlsx.full.min.js'
    s.onload = () => resolve(window.XLSX)
    s.onerror = () => { _xlsxPromise = null; reject(new Error('Failed to load the spreadsheet viewer')) }
    document.head.appendChild(s)
  })
  return _xlsxPromise
}

/**
 * Read-only viewer for spreadsheet files (.csv, .xlsx, .xls). Downloads the file
 * bytes via the global file API and parses them in the browser with SheetJS, so
 * no server-side pandas/Excel dependency is needed.
 *
 * Props: entry ({ name, path }), onClose()
 */
export default function SpreadsheetModal({ entry, onClose }) {
  const [xlsx, setXlsx] = useState(null)
  const [workbook, setWorkbook] = useState(null)
  const [active, setActive] = useState('')
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')

  useEffect(() => {
    if (!entry) return
    setLoading(true)
    setError('')
    Promise.all([
      loadXLSX(),
      api.get('/files/download', { params: { path: entry.path }, responseType: 'arraybuffer' }),
    ])
      .then(([XLSX, res]) => {
        const wb = XLSX.read(new Uint8Array(res.data), { type: 'array' })
        setXlsx(XLSX)
        setWorkbook(wb)
        setActive(wb.SheetNames[0] || '')
      })
      .catch((err) => setError(errorMessage(err)))
      .finally(() => setLoading(false))
  }, [entry])

  useEffect(() => {
    function onKey(e) { if (e.key === 'Escape') onClose() }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [onClose])

  function download() {
    api
      .get('/files/download', { params: { path: entry.path }, responseType: 'blob' })
      .then((res) => {
        const url = URL.createObjectURL(res.data)
        const a = document.createElement('a')
        a.href = url
        a.download = entry.name
        a.click()
        URL.revokeObjectURL(url)
      })
      .catch((err) => setError(errorMessage(err)))
  }

  // Convert the active sheet to an array-of-arrays (header row + data rows).
  const rows = useMemo(() => {
    if (!xlsx || !workbook || !active) return []
    const sheet = workbook.Sheets[active]
    return xlsx.utils.sheet_to_json(sheet, { header: 1, blankrows: false, defval: '' })
  }, [xlsx, workbook, active])

  const truncated = rows.length > MAX_ROWS + 1
  const shown = truncated ? rows.slice(0, MAX_ROWS + 1) : rows
  const header = shown[0] || []
  const body = shown.slice(1)

  if (!entry) return null

  return (
    <div className="fixed inset-0 bg-black/70 z-50 flex flex-col p-4">
      <div className="flex items-center gap-3 mb-2">
        <span className="font-mono text-sm text-slate-300 truncate">📊 {entry.name}</span>
        {error && <span className="text-xs text-red-400">{error}</span>}
        <div className="ml-auto flex gap-2">
          <button className="btn-secondary" onClick={download}>⬇ Download</button>
          <button className="btn-secondary" onClick={onClose}>Close (Esc)</button>
        </div>
      </div>

      {/* Sheet tabs (multi-sheet workbooks) */}
      {workbook && workbook.SheetNames.length > 1 && (
        <div className="flex gap-1 mb-2 flex-wrap">
          {workbook.SheetNames.map((name) => (
            <button
              key={name}
              onClick={() => setActive(name)}
              className={`px-3 py-1 text-xs rounded ${
                name === active ? 'bg-sky-600 text-white' : 'bg-panel-border text-slate-300'
              }`}
            >
              {name}
            </button>
          ))}
        </div>
      )}

      <div className="flex-1 border border-panel-border rounded-lg overflow-auto bg-panel-card">
        {loading ? (
          <div className="h-full flex items-center justify-center text-slate-500">Loading…</div>
        ) : rows.length === 0 ? (
          <div className="h-full flex items-center justify-center text-slate-500">Empty sheet</div>
        ) : (
          <table className="text-xs border-collapse">
            <thead className="sticky top-0 bg-panel-card">
              <tr>
                <th className="border border-panel-border px-2 py-1 text-slate-500 bg-panel-bg">#</th>
                {header.map((cell, i) => (
                  <th key={i} className="border border-panel-border px-2 py-1 text-left font-semibold whitespace-nowrap">
                    {String(cell)}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {body.map((row, r) => (
                <tr key={r} className="hover:bg-panel-border/40">
                  <td className="border border-panel-border px-2 py-1 text-slate-500 bg-panel-bg">{r + 1}</td>
                  {header.map((_, c) => (
                    <td key={c} className="border border-panel-border px-2 py-1 whitespace-nowrap">
                      {row[c] !== undefined && row[c] !== null ? String(row[c]) : ''}
                    </td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>

      {truncated && (
        <p className="text-xs text-amber-400 mt-1">
          Showing first {MAX_ROWS.toLocaleString()} rows — download the file to see all of it.
        </p>
      )}
    </div>
  )
}
