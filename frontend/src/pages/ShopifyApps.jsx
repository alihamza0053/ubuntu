import { useCallback, useEffect, useRef, useState } from 'react'
import api, { errorMessage } from '../api/client'
import FolderBrowser from '../components/FolderBrowser'

export default function ShopifyApps() {
  const [apps, setApps] = useState([])
  const [name, setName] = useState('')
  const [message, setMessage] = useState('')
  const [uploadTarget, setUploadTarget] = useState(null)
  const inputRef = useRef(null)
  const refresh = useCallback(() => {
    api.get('/shopify-apps').then((res) => setApps(res.data)).catch((err) => setMessage(errorMessage(err)))
  }, [])
  useEffect(() => { refresh() }, [refresh])

  async function createWorkspace(e) {
    e.preventDefault()
    if (!name.trim()) return
    try {
      const res = await api.post('/shopify-apps', { name })
      setMessage(res.data.detail); setName(''); refresh()
    } catch (err) { setMessage(errorMessage(err)) }
  }
  function chooseArchive(appName) { setUploadTarget(appName); inputRef.current?.click() }
  async function uploadArchive(file) {
    if (!file || !uploadTarget) return
    setMessage('Uploading source archive...')
    const form = new FormData(); form.append('file', file)
    try {
      const res = await api.post(`/shopify-apps/${encodeURIComponent(uploadTarget)}/archive`, form)
      setMessage(res.data.detail); refresh()
    } catch (err) { setMessage(errorMessage(err)) }
    finally { setUploadTarget(null) }
  }

  return <div className="space-y-4">
    <div><h2 className="text-2xl font-bold">Shopify Apps</h2>
      <p className="text-sm text-slate-500 mt-1">Panel-managed local source storage. Upload a ZIP without node_modules, then deploy its Dockerfile on this VPS.</p>
    </div>
    <form onSubmit={createWorkspace} className="card flex gap-2 items-center flex-wrap">
      <input className="input max-w-sm" placeholder="app name, e.g. size-chart" value={name} onChange={(e) => setName(e.target.value)} />
      <button className="btn-primary" type="submit" disabled={!name.trim()}>+ New Shopify app</button>
      {message && <span className="text-sm text-slate-400 break-all">{message}</span>}
    </form>
    <input ref={inputRef} type="file" accept=".zip,application/zip" className="hidden" onChange={(e) => { uploadArchive(e.target.files?.[0]); e.target.value = '' }} />
    {apps.length === 0 ? <div className="card text-center py-10 text-slate-500">No Shopify app workspaces yet.</div> : apps.map((app) => <div key={app.path} className="card">
      <div className="flex items-center gap-3 flex-wrap mb-3"><div><h3 className="font-mono font-semibold text-sky-300">{app.name}</h3><p className="text-xs text-slate-500">{app.has_dockerfile ? 'Dockerfile found — ready to build.' : 'Upload source containing a Dockerfile.'}</p></div>
        <button className="btn-secondary ml-auto" onClick={() => chooseArchive(app.name)}>Upload source ZIP</button></div>
      <FolderBrowser rootPath={app.path} editable viewer={false} emptyHint="Upload a source ZIP or add files here" />
    </div>)}
  </div>
}
