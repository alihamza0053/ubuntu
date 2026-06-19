import { useRef, useState } from 'react'
import api, { errorMessage } from '../../api/client'

// Map each project folder to its upload endpoint + query params
const FOLDERS = [
  { name: 'code', endpoint: 'upload-script', params: { folder: 'code' }, hint: 'Python scripts' },
  { name: 'allscripts', endpoint: 'upload-script', params: { folder: 'allscripts' }, hint: 'Helper scripts' },
  { name: 'data', endpoint: 'upload-data', params: {}, hint: 'Excel / CSV data' },
  { name: 'dashboard', endpoint: 'upload-dashboard', params: {}, hint: 'Streamlit app (app.py)' },
  { name: 'onedrivefiles', readOnly: true, hint: 'Uploaded via the upload portal' },
]

// Extensions that open in the Monaco editor on click
const EDITABLE = ['.py', '.txt', '.json', '.yaml', '.yml', '.csv', '.md', '.toml', '.cfg', '.ini', '.log']

function isEditable(name) {
  return EDITABLE.some((ext) => name.toLowerCase().endsWith(ext))
}

function formatSize(bytes) {
  if (bytes < 1024) return `${bytes} B`
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`
  return `${(bytes / 1024 / 1024).toFixed(1)} MB`
}

/** One folder panel: upload (button + drag-drop), list, download, delete. */
function FolderPanel({ project, folder, files, onChanged, onOpenFile }) {
  const inputRef = useRef(null)
  const [dragOver, setDragOver] = useState(false)
  const [busy, setBusy] = useState(false)

  async function upload(fileList) {
    if (!fileList.length) return
    const form = new FormData()
    for (const file of fileList) form.append('files', file)
    setBusy(true)
    try {
      await api.post(`/projects/${project.id}/${folder.endpoint}`, form, {
        params: folder.params,
      })
      onChanged()
    } catch (err) {
      alert(errorMessage(err))
    } finally {
      setBusy(false)
    }
  }

  async function remove(filename) {
    if (!window.confirm(`Delete ${folder.name}/${filename}?`)) return
    try {
      await api.delete(`/projects/${project.id}/files`, {
        params: { folder: folder.name, filename },
      })
      onChanged()
    } catch (err) {
      alert(errorMessage(err))
    }
  }

  function download(filename) {
    // Token-authenticated download via a temporary blob link
    api
      .get(`/projects/${project.id}/download`, {
        params: { folder: folder.name, filename },
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

  const readOnly = folder.readOnly
  return (
    <div
      className={`card ${dragOver ? 'border-sky-500 bg-sky-500/5' : ''}`}
      onDragOver={(e) => {
        if (readOnly) return
        e.preventDefault()
        setDragOver(true)
      }}
      onDragLeave={() => setDragOver(false)}
      onDrop={(e) => {
        if (readOnly) return
        e.preventDefault()
        setDragOver(false)
        upload([...e.dataTransfer.files])
      }}
    >
      <div className="flex items-center justify-between mb-2">
        <div>
          <h4 className="font-mono font-semibold text-sky-300">{folder.name}/</h4>
          <p className="text-xs text-slate-500">{folder.hint}</p>
        </div>
        {!readOnly && (
          <>
            <button className="btn-secondary" disabled={busy} onClick={() => inputRef.current?.click()}>
              {busy ? 'Uploading…' : '⬆ Upload'}
            </button>
            <input
              ref={inputRef}
              type="file"
              multiple
              className="hidden"
              onChange={(e) => {
                upload([...e.target.files])
                e.target.value = ''
              }}
            />
          </>
        )}
      </div>

      {files.length === 0 ? (
        <p className="text-sm text-slate-600 py-3 text-center">
          {readOnly ? 'no files uploaded yet' : 'empty — drop files here'}
        </p>
      ) : (
        <ul className="divide-y divide-panel-border">
          {files.map((file) => (
            <li key={file.name} className="flex items-center gap-2 py-1.5 text-sm">
              {isEditable(file.name) ? (
                <button
                  className="text-sky-400 hover:underline truncate"
                  onClick={() => onOpenFile(folder.name, file.name)}
                  title="Open in editor"
                >
                  {file.name}
                </button>
              ) : (
                <span className="truncate" title={`${file.name} (${formatSize(file.size)})`}>
                  {file.name}
                </span>
              )}
              <span className="ml-auto text-xs text-slate-600 shrink-0">{formatSize(file.size)}</span>
              <button onClick={() => download(file.name)} className="text-slate-500 hover:text-sky-400" title="Download">
                ⬇
              </button>
              <button onClick={() => remove(file.name)} className="text-slate-500 hover:text-red-400" title="Delete">
                🗑
              </button>
            </li>
          ))}
        </ul>
      )}
    </div>
  )
}

/** Files tab: four folder panels with upload / download / delete / edit. */
export default function FilesTab({ project, files, onChanged, onOpenFile }) {
  if (!files) return <p className="text-slate-500">Loading…</p>
  return (
    <div className="grid lg:grid-cols-2 gap-4">
      {FOLDERS.map((folder) => (
        <FolderPanel
          key={folder.name}
          project={project}
          folder={folder}
          files={files.folders[folder.name] || []}
          onChanged={onChanged}
          onOpenFile={onOpenFile}
        />
      ))}
    </div>
  )
}
