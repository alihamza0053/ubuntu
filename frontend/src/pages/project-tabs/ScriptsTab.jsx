import { useCallback, useEffect, useState } from 'react'
import api, { errorMessage } from '../../api/client'
import LiveLog from '../../components/LiveLog'
import StatusBadge from '../../components/StatusBadge'

function formatTime(iso) {
  if (!iso) return 'never'
  return new Date(iso + 'Z').toLocaleString()
}

/** Scripts tab: run scripts with live output, view last run logs. */
export default function ScriptsTab({ project, onChanged }) {
  const [scripts, setScripts] = useState([])
  // Per-script expanded panel: { [id]: { mode: 'live' | 'log', content? } }
  const [panels, setPanels] = useState({})

  const refresh = useCallback(() => {
    api.get(`/projects/${project.id}/scripts`).then((res) => setScripts(res.data))
  }, [project.id])

  useEffect(() => {
    refresh()
  }, [refresh])

  // While a live run panel is open, poll so RUNNING/STOPPED status (and the
  // Stop button) stays current.
  useEffect(() => {
    const anyOpen = Object.values(panels).some((p) => p?.mode === 'live' || p?.mode === 'log')
    if (!anyOpen) return
    const t = setInterval(refresh, 3000)
    return () => clearInterval(t)
  }, [panels, refresh])

  function runLive(script) {
    // Open (or re-open) the live stream panel for this script
    setPanels((prev) => ({ ...prev, [script.id]: null }))
    setTimeout(
      () => setPanels((prev) => ({ ...prev, [script.id]: { mode: 'live' } })),
      0,
    )
  }

  async function stopScript(script) {
    try {
      await api.post(`/scripts/${script.id}/stop`)
      refresh()
    } catch (err) {
      alert(errorMessage(err))
    }
  }

  function viewLog(script) {
    // Live-tail the script's log file: shows the running script's output live,
    // or the last run's log when idle. Re-open to re-attach to the latest.
    setPanels((prev) => ({ ...prev, [script.id]: null }))
    setTimeout(
      () => setPanels((prev) => ({ ...prev, [script.id]: { mode: 'log' } })),
      0,
    )
  }

  function closePanel(id) {
    setPanels((prev) => ({ ...prev, [id]: undefined }))
  }

  if (scripts.length === 0) {
    return (
      <div className="card text-center py-10 text-slate-500">
        No scripts yet — upload .py files to code/ or allscripts/ on the Files tab.
      </div>
    )
  }

  return (
    <div className="space-y-3">
      {scripts.map((script) => {
        const panel = panels[script.id]
        return (
          <div key={script.id} className="card">
            <div className="flex items-center gap-3 flex-wrap">
              <span className="font-mono text-sm">
                <span className="text-slate-500">{script.folder}/</span>
                {script.filename}
              </span>
              {script.last_status && <StatusBadge status={script.last_status} />}
              <span className="text-xs text-slate-500">last run: {formatTime(script.last_run)}</span>

              <div className="ml-auto flex gap-2">
                {script.last_status === 'RUNNING' ? (
                  <button className="btn-danger" onClick={() => stopScript(script)}>
                    ⏹ Stop
                  </button>
                ) : (
                  <button className="btn-primary" onClick={() => runLive(script)}>
                    ▶ Run Now
                  </button>
                )}
                <button className="btn-secondary" onClick={() => viewLog(script)}>
                  📜 View Log
                </button>
                {panel && (
                  <button
                    className="btn-secondary"
                    onClick={() => closePanel(script.id)}
                    title="Close panel"
                  >
                    ✕
                  </button>
                )}
              </div>
            </div>

            {/* Expandable panel: live stream or last log */}
            {panel?.mode === 'live' && (
              <LiveLog
                path={`/ws/script/${script.id}/run`}
                onClose={() => {
                  refresh()
                  onChanged?.()
                }}
              />
            )}
            {panel?.mode === 'log' && (
              <LiveLog path={`/ws/script/${script.id}/logs`} />
            )}
          </div>
        )
      })}
    </div>
  )
}
