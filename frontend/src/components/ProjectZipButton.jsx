import { useRef, useState } from 'react'
import api, { errorMessage, isCancel } from '../api/client'
import Icon from './ui/Icon'

/**
 * Download a whole project as a .zip. The server zips it first (no progress to
 * show yet), then the file comes down with a percentage. Clicking again cancels.
 * compact: an icon button for the project card; otherwise a labelled button.
 */
export default function ProjectZipButton({ project, compact = false }) {
  const [state, setState] = useState(null)        // null | 'zipping' | 0-100
  const controllerRef = useRef(null)

  function start() {
    if (controllerRef.current) {
      controllerRef.current.abort()
      return
    }
    const controller = new AbortController()
    controllerRef.current = controller
    setState('zipping')
    api.get(`/projects/${project.id}/zip`, {
      responseType: 'blob',
      signal: controller.signal,
      timeout: 0,
      onDownloadProgress: (e) => {
        if (e.total) setState(Math.round((e.loaded / e.total) * 100))
      },
    })
      .then((res) => {
        const match = /filename="?([^";]+)"?/.exec(res.headers['content-disposition'] || '')
        const url = URL.createObjectURL(res.data)
        const a = document.createElement('a')
        a.href = url
        a.download = match ? match[1] : `${project.name}.zip`
        a.click()
        URL.revokeObjectURL(url)
      })
      .catch(async (err) => {
        if (isCancel(err)) return
        // A blob response hides the server's JSON error message: read it out.
        let message = errorMessage(err)
        try {
          const detail = JSON.parse(await err.response.data.text()).detail
          if (typeof detail === 'string') message = detail
        } catch { /* not JSON */ }
        alert(`Couldn't download ${project.name}: ${message}`)
      })
      .finally(() => { controllerRef.current = null; setState(null) })
  }

  const busy = state !== null
  const progress = state === 'zipping' ? 'Zipping…' : `${state}%`
  const title = busy ? `${progress} Click to cancel.` : 'Download the whole project as a .zip'

  if (compact) {
    return (
      <button className="btn-icon" onClick={start} title={title} aria-label={title}>
        {busy
          ? <span className="text-[10px] font-medium text-mint-300">{state === 'zipping' ? '…' : `${state}%`}</span>
          : <Icon name="download" size={15} />}
      </button>
    )
  }
  return (
    <button className="btn-secondary" onClick={start} title={title}>
      <Icon name={busy ? 'x' : 'download'} size={15} />
      {busy ? progress : 'Export .zip'}
    </button>
  )
}

// nginx's limit for the panel, and Cloudflare free's (see WebsiteDetail).
const MAX_UPLOAD_BYTES = 200 * 1024 * 1024
const CLOUDFLARE_FREE_LIMIT = 100 * 1024 * 1024

/**
 * Import a .zip (e.g. one exported above) into a project. Files in the zip are
 * added or replaced; replaced files go to the recycle bin; nothing else changes.
 */
export function ProjectImportButton({ project, compact = false, onDone }) {
  const [state, setState] = useState(null)        // null | 0-100 | 'unpacking'
  const controllerRef = useRef(null)
  const inputRef = useRef(null)

  function pick() {
    if (controllerRef.current) {
      if (state !== 'unpacking') controllerRef.current.abort()
      return
    }
    inputRef.current?.click()
  }

  async function upload(file) {
    if (!file) return
    const mb = (file.size / 1024 / 1024).toFixed(1)
    if (file.size > MAX_UPLOAD_BYTES) {
      alert(`${file.name} is ${mb} MB; the limit is 200 MB. Leave out venv and other generated folders.`)
      return
    }
    if (!window.confirm(
      `Import ${file.name} (${mb} MB) into “${project.name}”?\n\n` +
      'Files in the zip are added; files with the same name are replaced (the old versions go to ' +
      'the recycle bin for 24 hours). Files not in the zip are left as they are.' +
      (file.size > CLOUDFLARE_FREE_LIMIT
        ? '\n\nThis is over 100 MB: if the panel is behind Cloudflare, the upload will be refused.' : ''))) return

    const form = new FormData()
    form.append('file', file)
    const controller = new AbortController()
    controllerRef.current = controller
    setState(0)
    try {
      const res = await api.post(`/projects/${project.id}/import`, form, {
        signal: controller.signal,
        timeout: 0,
        onUploadProgress: (e) => {
          if (!e.total) return
          const pct = Math.round((e.loaded / e.total) * 100)
          setState(pct >= 100 ? 'unpacking' : pct)
        },
      })
      alert(res.data.detail)
      onDone && onDone()
    } catch (err) {
      if (!isCancel(err)) alert(`Couldn't import into ${project.name}: ${errorMessage(err)}`)
    } finally {
      controllerRef.current = null
      setState(null)
    }
  }

  const busy = state !== null
  const progress = state === 'unpacking' ? 'Unpacking…' : `${state}%`
  const title = busy
    ? (state === 'unpacking' ? 'Unpacking on the server…' : `Uploading ${state}%. Click to cancel.`)
    : 'Import a .zip into this project'
  const input = (
    <input ref={inputRef} type="file" accept=".zip" className="hidden"
      onChange={(e) => { upload(e.target.files[0]); e.target.value = '' }} />
  )

  // The input sits beside the button, not inside it: a click on it would bubble
  // up to the button and open the file picker a second time.
  if (compact) {
    return (
      <>
        <button className="btn-icon" onClick={pick} title={title} aria-label={title}>
          {busy
            ? <span className="text-[10px] font-medium text-mint-300">{state === 'unpacking' ? '…' : `${state}%`}</span>
            : <Icon name="upload" size={15} />}
        </button>
        {input}
      </>
    )
  }
  return (
    <>
      <button className="btn-secondary" onClick={pick} title={title}>
        <Icon name={busy && state !== 'unpacking' ? 'x' : 'upload'} size={15} />
        {busy ? progress : 'Import .zip'}
      </button>
      {input}
    </>
  )
}
