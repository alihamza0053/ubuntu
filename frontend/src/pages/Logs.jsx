import { useEffect, useMemo, useRef, useState } from 'react'
import api, { errorMessage } from '../api/client'
import { wsUrl } from '../api/ws'
import LiveLog from '../components/LiveLog'

/**
 * Always-on global activity feed — streams everything the panel is doing right
 * now (scripts running, pipelines, dashboard actions), failures in red.
 */
function LiveActivity() {
  const [open, setOpen] = useState(true)
  return (
    <div className="card">
      <div className="flex items-center gap-2">
        <h3 className="font-semibold">⚡ Live Activity</h3>
        <span className="text-xs text-slate-500">scripts, pipelines &amp; dashboard actions as they happen</span>
        <button className="ml-auto text-xs text-slate-400 hover:text-slate-200" onClick={() => setOpen((o) => !o)}>
          {open ? 'hide' : 'show'}
        </button>
      </div>
      {open && <LiveLog path="/ws/logs/activity/all" />}
    </div>
  )
}

/**
 * Log viewer: sidebar of sources, main panel showing content, a Live toggle
 * that streams via WebSocket, search filter, and download.
 */
export default function Logs() {
  const [sources, setSources] = useState([])
  const [selected, setSelected] = useState(null) // {type, name, label}
  const [lines, setLines] = useState([])
  const [live, setLive] = useState(false)
  const [filter, setFilter] = useState('')
  const boxRef = useRef(null)
  const socketRef = useRef(null)

  useEffect(() => {
    api.get('/logs/sources').then((res) => setSources(res.data)).catch(() => {})
  }, [])

  // Build the REST URL for a static (non-live) fetch of a source
  function restPath(src) {
    if (src.type === 'nginx') return `/logs/nginx/${src.name}`
    if (src.type === 'system') return '/logs/system'
    if (src.type === 'supervisor') return `/logs/supervisor/${src.name}`
    if (src.type === 'pipeline') return `/logs/pipeline/${src.name}`
    if (src.type === 'script') return `/logs/script/${src.name}`
    return null
  }

  async function loadStatic(src) {
    try {
      const res = await api.get(restPath(src))
      setLines(res.data.content.split('\n'))
    } catch (err) {
      setLines([errorMessage(err)])
    }
  }

  // Switch source / toggle live
  useEffect(() => {
    if (socketRef.current) {
      socketRef.current.close()
      socketRef.current = null
    }
    if (!selected) return

    if (live) {
      setLines([])
      const socket = new WebSocket(wsUrl(`/ws/logs/${selected.type}/${selected.name}`))
      socket.onmessage = (e) => setLines((prev) => [...prev, e.data])
      socket.onclose = () => {}
      socketRef.current = socket
      return () => socket.close()
    } else {
      loadStatic(selected)
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [selected, live])

  useEffect(() => {
    if (boxRef.current) boxRef.current.scrollTop = boxRef.current.scrollHeight
  }, [lines])

  const filtered = useMemo(
    () => (filter ? lines.filter((l) => l.toLowerCase().includes(filter.toLowerCase())) : lines),
    [lines, filter],
  )

  function download() {
    if (!selected) return
    api
      .get('/logs/download', {
        params: { log_type: selected.type, name: selected.name },
        responseType: 'blob',
      })
      .then((res) => {
        const url = URL.createObjectURL(res.data)
        const a = document.createElement('a')
        a.href = url
        a.download = `${selected.type}-${selected.name}.txt`
        a.click()
        URL.revokeObjectURL(url)
      })
      .catch((err) => alert(errorMessage(err)))
  }

  return (
    <div className="space-y-4">
      <h2 className="text-2xl font-bold">Logs</h2>

      {/* Always-on global activity feed */}
      <LiveActivity />

      <div className="flex gap-4" style={{ minHeight: '70vh' }}>
        {/* Sidebar */}
        <aside className="w-64 shrink-0 card overflow-y-auto">
          <h4 className="text-xs uppercase tracking-wide text-slate-500 mb-2">Sources</h4>
          <ul className="space-y-0.5">
            {sources.map((src) => (
              <li key={`${src.type}-${src.name}`}>
                <button
                  onClick={() => setSelected(src)}
                  className={`w-full text-left px-2 py-1.5 rounded text-sm truncate ${
                    selected?.type === src.type && selected?.name === src.name
                      ? 'bg-sky-600/20 text-sky-300'
                      : 'text-slate-300 hover:bg-slate-700/50'
                  }`}
                >
                  {src.label}
                </button>
              </li>
            ))}
            {sources.length === 0 && <li className="text-xs text-slate-600 px-2">No sources</li>}
          </ul>
        </aside>

        {/* Main panel */}
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2 mb-2 flex-wrap">
            <span className="font-mono text-sm text-slate-400">{selected?.label || 'Select a log'}</span>
            <div className="ml-auto flex items-center gap-2">
              <input
                className="input max-w-xs py-1"
                placeholder="filter…"
                value={filter}
                onChange={(e) => setFilter(e.target.value)}
              />
              <button
                className={live ? 'btn-primary' : 'btn-secondary'}
                onClick={() => setLive((v) => !v)}
                disabled={!selected}
              >
                {live ? '● Live' : '○ Live'}
              </button>
              <button className="btn-secondary" onClick={download} disabled={!selected}>
                ⬇ Download
              </button>
            </div>
          </div>

          <pre
            ref={boxRef}
            className="bg-black text-slate-300 text-xs font-mono p-3 rounded-lg overflow-auto whitespace-pre-wrap"
            style={{ height: '65vh' }}
          >
            {selected ? filtered.join('\n') || '(empty)' : 'Pick a log source from the left.'}
          </pre>
        </div>
      </div>
    </div>
  )
}
