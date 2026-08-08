import { useCallback, useEffect, useRef, useState } from 'react'
import api, { errorMessage } from '../api/client'
import EditorModal from '../components/EditorModal'
import DataTable, { NameCell, RowActions } from '../components/ui/DataTable'
import Icon from '../components/ui/Icon'
import PageHeader from '../components/ui/PageHeader'
import { formatDateTime } from '../lib/datetime'

const EDITABLE = ['.py', '.txt', '.json', '.yaml', '.yml', '.csv', '.md', '.html', '.htm',
  '.css', '.js', '.jsx', '.ts', '.tsx', '.php', '.sql', '.conf', '.cfg', '.ini', '.toml',
  '.env', '.sh', '.log', '.xml']

function isEditable(name) {
  return EDITABLE.some((ext) => name.toLowerCase().endsWith(ext))
}

function formatSize(bytes) {
  if (bytes < 1024) return `${bytes} B`
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`
  return `${(bytes / 1024 / 1024).toFixed(1)} MB`
}

const formatDate = (iso) => formatDateTime(iso)

/** Global server file manager confined to the panel-managed roots under /srv. */
export default function Files() {
  const [path, setPath] = useState('') // '' = roots listing
  const [data, setData] = useState({ entries: [], parent: null })
  const [editorPath, setEditorPath] = useState(null)
  const [error, setError] = useState('')
  const inputRef = useRef(null)
  const browseRequest = useRef(0)

  const browse = useCallback((target) => {
    const requestId = ++browseRequest.current
    setError('')
    api
      .get('/files/browse', { params: { path: target } })
      .then((res) => {
        if (requestId !== browseRequest.current) return
        setData(res.data)
        setPath(res.data.path)
      })
      .catch((err) => {
        // Ignore an older request that finished after the user navigated away.
        if (requestId === browseRequest.current) setError(errorMessage(err))
      })
  }, [])

  useEffect(() => {
    browse('')
  }, [browse])

  function open(entry) {
    if (entry.is_dir) browse(entry.path)
    else if (isEditable(entry.name)) setEditorPath(entry.path)
  }

  async function upload(files) {
    if (!path) {
      alert('Open a folder first')
      return
    }
    const form = new FormData()
    for (const f of files) form.append('files', f)
    try {
      await api.post('/files/upload', form, { params: { path } })
      browse(path)
    } catch (err) {
      alert(errorMessage(err))
    }
  }

  async function mkdir() {
    const name = prompt('New folder name:')
    if (!name) return
    try {
      await api.post('/files/mkdir', { path: `${path}/${name}` })
      browse(path)
    } catch (err) {
      alert(errorMessage(err))
    }
  }

  async function rename(entry) {
    const newName = prompt('Rename to:', entry.name)
    if (!newName || newName === entry.name) return
    try {
      await api.post('/files/rename', { path: entry.path, new_name: newName })
      browse(path)
    } catch (err) {
      alert(errorMessage(err))
    }
  }

  async function remove(entry) {
    if (!window.confirm(`Delete ${entry.name}${entry.is_dir ? '/ (and contents)' : ''}?`)) return
    try {
      await api.delete('/files/delete', { data: { path: entry.path } })
      browse(path)
    } catch (err) {
      alert(errorMessage(err))
    }
  }

  function download(entry) {
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
      .catch((err) => alert(errorMessage(err)))
  }

  const columns = [
    {
      key: 'name',
      label: 'Name',
      render: (entry) => (
        <NameCell
          icon={entry.is_dir ? 'folder' : isEditable(entry.name) ? 'pencil' : 'file'}
          tint={entry.is_dir ? 'amber' : isEditable(entry.name) ? 'mint' : 'slate'}
          title={entry.name}
          onClick={() => open(entry)}
        />
      ),
    },
    {
      key: 'size',
      label: 'Size',
      width: '8rem',
      render: (entry) => (
        <span className="text-slate-500">{entry.is_dir ? '—' : formatSize(entry.size)}</span>
      ),
    },
    {
      key: 'modified',
      label: 'Modified',
      width: '12rem',
      render: (entry) => <span className="whitespace-nowrap text-slate-400">{formatDate(entry.modified)}</span>,
    },
    {
      key: 'actions',
      label: 'Actions',
      align: 'right',
      width: '9rem',
      render: (entry) => (
        <RowActions>
          {!entry.is_dir && (
            <button className="btn-icon" onClick={() => download(entry)} title="Download">
              <Icon name="download" size={15} />
            </button>
          )}
          <button className="btn-icon" onClick={() => rename(entry)} title="Rename">
            <Icon name="pencil" size={15} />
          </button>
          <button className="btn-icon-danger" onClick={() => remove(entry)} title="Delete">
            <Icon name="trash" size={15} />
          </button>
        </RowActions>
      ),
    },
  ]

  return (
    <div className="space-y-6">
      <PageHeader
        title="File Manager"
        crumbs={[{ label: 'Storage' }, { label: 'Files' }]}
        actions={
          <>
            {path && (
              <button className="btn-secondary" onClick={mkdir}>
                <Icon name="plus" size={15} />
                New folder
              </button>
            )}
            {path && (
              <button className="btn-primary" onClick={() => inputRef.current?.click()}>
                <Icon name="upload" size={15} />
                Upload
              </button>
            )}
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
        }
      />

      {/* Path bar */}
      <div className="flex flex-wrap items-center gap-2 rounded-xl border border-panel-border/70 bg-panel-card/60 px-3 py-2">
        <button className="btn-icon" onClick={() => browse('')} title="Managed roots">
          <Icon name="server" size={15} />
        </button>
        {data.parent !== null && (
          <button className="btn-icon" onClick={() => browse(data.parent)} title="Up one level">
            <Icon name="chevron-up" size={15} />
          </button>
        )}
        <span className="mx-1 h-5 w-px bg-panel-border" />
        <span className="truncate font-mono text-sm text-slate-400">
          {path || '/srv (managed roots)'}
        </span>
      </div>

      {error && (
        <div className="flex items-start gap-2 rounded-lg border border-red-500/30 bg-red-500/10 px-3 py-2 text-sm text-red-300">
          <Icon name="warning" size={15} className="mt-0.5" />
          {error}
        </div>
      )}

      <DataTable columns={columns} rows={data.entries} rowKey={(e) => e.path} empty="This folder is empty." />

      <EditorModal
        path={editorPath}
        onClose={() => {
          setEditorPath(null)
        }}
      />
    </div>
  )
}
