import { useRef, useState } from 'react'
import api, { errorMessage } from '../../api/client'

function formatSize(bytes) {
  if (bytes < 1024) return `${bytes} B`
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`
  return `${(bytes / 1024 / 1024).toFixed(1)} MB`
}

function formatTime(iso) {
  return new Date(iso + 'Z').toLocaleString()
}

/** Data Files tab: Excel/CSV files in data/ — upload, download, delete. */
export default function DataFilesTab({ project, files, onChanged }) {
  const inputRef = useRef(null)
  const [busy, setBusy] = useState(false)
  const dataFiles = files?.folders?.data || []

  async function upload(fileList) {
    if (!fileList.length) return
    const form = new FormData()
    for (const file of fileList) form.append('files', file)
    setBusy(true)
    try {
      await api.post(`/projects/${project.id}/upload-data`, form)
      onChanged()
    } catch (err) {
      alert(errorMessage(err))
    } finally {
      setBusy(false)
    }
  }

  function download(filename) {
    api
      .get(`/projects/${project.id}/download`, {
        params: { folder: 'data', filename },
        responseType: 'blob',
      })
      .then((res) => {
        const url = URL.createObjectURL(res.data)
        const a = document.createElement('a')
        a.href = url
        a.download = filename
        a.click()
        URL.revokeObjectURL(url)
      })
      .catch((err) => alert(errorMessage(err)))
  }

  async function remove(filename) {
    if (!window.confirm(`Delete data/${filename}?`)) return
    try {
      await api.delete(`/projects/${project.id}/files`, {
        params: { folder: 'data', filename },
      })
      onChanged()
    } catch (err) {
      alert(errorMessage(err))
    }
  }

  return (
    <div className="card">
      <div className="flex items-center justify-between mb-4">
        <div>
          <h3 className="font-semibold">Data Files</h3>
          <p className="text-xs text-slate-500">Excel / CSV files in data/ — used by your scripts</p>
        </div>
        <button className="btn-primary" disabled={busy} onClick={() => inputRef.current?.click()}>
          {busy ? 'Uploading…' : '⬆ Upload .xlsx'}
        </button>
        <input
          ref={inputRef}
          type="file"
          multiple
          accept=".xlsx,.xls,.csv"
          className="hidden"
          onChange={(e) => {
            upload([...e.target.files])
            e.target.value = ''
          }}
        />
      </div>

      {dataFiles.length === 0 ? (
        <p className="text-center text-slate-600 py-8">No data files yet</p>
      ) : (
        <table className="w-full text-sm">
          <thead>
            <tr className="text-left text-xs uppercase text-slate-500 border-b border-panel-border">
              <th className="py-2">File</th>
              <th>Size</th>
              <th>Last modified</th>
              <th className="text-right">Actions</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-panel-border">
            {dataFiles.map((file) => (
              <tr key={file.name}>
                <td className="py-2 font-mono">📊 {file.name}</td>
                <td>{formatSize(file.size)}</td>
                <td className="text-slate-400">{formatTime(file.modified)}</td>
                <td className="text-right space-x-2">
                  <button onClick={() => download(file.name)} className="text-sky-400 hover:underline">
                    Download
                  </button>
                  <button onClick={() => remove(file.name)} className="text-red-400 hover:underline">
                    Delete
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  )
}
