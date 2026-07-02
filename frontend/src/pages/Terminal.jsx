import { FitAddon } from '@xterm/addon-fit'
import { Terminal as XTerm } from '@xterm/xterm'
import '@xterm/xterm/css/xterm.css'
import { useEffect, useRef, useState } from 'react'
import { wsUrl } from '../api/ws'

/**
 * Full interactive terminal backed by a server-side PTY over WebSocket.
 *
 * Frame protocol (JSON):
 *   client → {type:'input', data} | {type:'resize', cols, rows}
 *   server → {type:'output', data}
 */
export default function Terminal() {
  const containerRef = useRef(null)
  const [status, setStatus] = useState('connecting')

  useEffect(() => {
    const term = new XTerm({
      fontSize: 13,
      fontFamily: 'monospace',
      theme: { background: '#000000', foreground: '#d1d5db' },
      cursorBlink: true,
    })
    const fit = new FitAddon()
    term.loadAddon(fit)
    term.open(containerRef.current)
    fit.fit()

    const socket = new WebSocket(wsUrl('/ws/terminal'))

    socket.onopen = () => {
      setStatus('connected')
      // Send initial size
      socket.send(JSON.stringify({ type: 'resize', cols: term.cols, rows: term.rows }))
      term.focus()
    }
    socket.onmessage = (event) => {
      try {
        const msg = JSON.parse(event.data)
        if (msg.type === 'output') term.write(msg.data)
      } catch {
        term.write(event.data)
      }
    }
    socket.onclose = () => {
      setStatus('disconnected')
      term.write('\r\n\x1b[31m[connection closed]\x1b[0m\r\n')
    }
    socket.onerror = () => setStatus('error')

    // Keystrokes → server
    term.onData((data) => {
      if (socket.readyState === WebSocket.OPEN) {
        socket.send(JSON.stringify({ type: 'input', data }))
      }
    })

    // Resize handling
    function handleResize() {
      fit.fit()
      if (socket.readyState === WebSocket.OPEN) {
        socket.send(JSON.stringify({ type: 'resize', cols: term.cols, rows: term.rows }))
      }
    }
    window.addEventListener('resize', handleResize)

    return () => {
      window.removeEventListener('resize', handleResize)
      socket.close()
      term.dispose()
    }
  }, [])

  return (
    <div className="space-y-4 h-full flex flex-col">
      <div className="flex items-center gap-3">
        <h2 className="text-2xl font-bold">Terminal</h2>
        <span
          className={`badge ${
            status === 'connected'
              ? 'bg-green-500/15 text-green-400'
              : status === 'connecting'
              ? 'bg-yellow-500/15 text-yellow-400'
              : 'bg-red-500/15 text-red-400'
          }`}
        >
          {status}
        </span>
        <span className="text-xs text-slate-500">
          Full bash session — run any command (apt, pip, nano, top…)
        </span>
      </div>

      <div className="card flex-1 p-2" style={{ minHeight: '70vh' }}>
        <div ref={containerRef} style={{ height: '70vh' }} />
      </div>
    </div>
  )
}
