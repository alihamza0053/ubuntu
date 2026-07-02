import { useEffect, useRef, useState } from 'react'
import { wsUrl } from '../api/ws'

// Colour log lines: failures red, successes green, pipeline markers brighter.
function lineColor(line) {
  const l = line.toLowerCase()
  if (line.includes('✗') || l.includes('failed') || l.includes('error') || l.includes('traceback')) {
    return 'text-red-400'
  }
  if (line.includes('✓') || l.includes('status=success') || l.includes(' ok')) {
    return 'text-green-400'
  }
  if (line.includes('[pipeline]') || line.includes('[serverhub]')) {
    return 'text-sky-300'
  }
  return 'text-slate-300'
}

/**
 * Terminal-style live log panel fed by a WebSocket.
 *
 * Props:
 *   path     — backend WS path (e.g. /ws/script/3/run); null = idle
 *   onClose  — called when the socket closes (run finished)
 */
export default function LiveLog({ path, onClose }) {
  const [lines, setLines] = useState([])
  const [connected, setConnected] = useState(false)
  const boxRef = useRef(null)
  const socketRef = useRef(null)

  useEffect(() => {
    if (!path) return
    setLines([])
    const socket = new WebSocket(wsUrl(path))
    socketRef.current = socket

    socket.onopen = () => setConnected(true)
    socket.onmessage = (event) => setLines((prev) => [...prev, event.data])
    socket.onerror = () => setLines((prev) => [...prev, '[connection error]'])
    socket.onclose = () => {
      setConnected(false)
      onClose?.()
    }
    return () => socket.close()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [path])

  // Auto-scroll to bottom as lines arrive
  useEffect(() => {
    if (boxRef.current) boxRef.current.scrollTop = boxRef.current.scrollHeight
  }, [lines])

  if (!path) return null

  return (
    <div className="mt-3 rounded-lg border border-panel-border overflow-hidden">
      <div className="flex items-center justify-between bg-slate-900 px-3 py-1.5 text-xs">
        <span className={connected ? 'text-green-400' : 'text-slate-500'}>
          {connected ? '● live' : '○ closed'}
        </span>
        <button onClick={() => setLines([])} className="text-slate-500 hover:text-slate-300">
          clear
        </button>
      </div>
      <div
        ref={boxRef}
        className="bg-black text-green-300 text-xs font-mono p-3 h-64 overflow-y-auto whitespace-pre-wrap"
      >
        {lines.length
          ? lines.map((line, i) => (
              <div key={i} className={lineColor(line)}>{line || ' '}</div>
            ))
          : 'Waiting for output…'}
      </div>
    </div>
  )
}
