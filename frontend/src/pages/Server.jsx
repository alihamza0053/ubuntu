import { useCallback, useEffect, useState } from 'react'
import {
  Area, AreaChart, ResponsiveContainer, Tooltip, XAxis, YAxis,
} from 'recharts'
import api, { errorMessage } from '../api/client'
import LiveLog from '../components/LiveLog'

const MAX_POINTS = 30

/** Server tools: live CPU/RAM/disk graphs, supervisor + system processes, apt. */
export default function Server() {
  const [history, setHistory] = useState([]) // [{t, cpu, ram, disk}]
  const [processes, setProcesses] = useState({ supervisor: [], system: [] })
  const [aptQuery, setAptQuery] = useState('')
  const [aptResults, setAptResults] = useState([])
  const [aptWsPath, setAptWsPath] = useState(null)

  const loadStats = useCallback(() => {
    api.get('/server/stats').then((res) => {
      const s = res.data
      setHistory((prev) => [
        ...prev.slice(-(MAX_POINTS - 1)),
        {
          t: new Date().toLocaleTimeString(),
          cpu: s.cpu_percent,
          ram: s.memory.percent,
          disk: s.disk.percent,
        },
      ])
    }).catch(() => {})
  }, [])

  const loadProcesses = useCallback(() => {
    api.get('/server/processes').then((res) => setProcesses(res.data)).catch(() => {})
  }, [])

  useEffect(() => {
    loadStats()
    loadProcesses()
    const a = setInterval(loadStats, 3000)
    const b = setInterval(loadProcesses, 8000)
    return () => { clearInterval(a); clearInterval(b) }
  }, [loadStats, loadProcesses])

  async function supervisorAction(name, action) {
    try {
      await api.post(`/server/supervisor/${name}/${action}`)
      loadProcesses()
    } catch (err) {
      alert(errorMessage(err))
    }
  }

  async function searchApt() {
    try {
      const res = await api.get('/server/apt/search', { params: { q: aptQuery } })
      setAptResults(res.data)
    } catch (err) {
      alert(errorMessage(err))
    }
  }

  function aptAction(action, pkg) {
    // Reconnect each time so re-running streams fresh
    setAptWsPath(null)
    const qs = pkg ? `?package=${encodeURIComponent(pkg)}` : ''
    setTimeout(() => setAptWsPath(`/ws/apt/${action}${qs}`), 0)
  }

  const latest = history[history.length - 1]

  return (
    <div className="space-y-6">
      <h2 className="text-2xl font-bold">Server Tools</h2>

      {/* Live graphs */}
      <div className="grid lg:grid-cols-3 gap-4">
        {[
          { key: 'cpu', label: 'CPU %', color: '#38bdf8' },
          { key: 'ram', label: 'RAM %', color: '#a78bfa' },
          { key: 'disk', label: 'Disk %', color: '#fb923c' },
        ].map((m) => (
          <div key={m.key} className="card">
            <div className="flex justify-between items-baseline mb-2">
              <span className="text-sm text-slate-400">{m.label}</span>
              <span className="text-xl font-bold">{latest ? `${latest[m.key]}%` : '…'}</span>
            </div>
            <ResponsiveContainer width="100%" height={120}>
              <AreaChart data={history}>
                <defs>
                  <linearGradient id={m.key} x1="0" y1="0" x2="0" y2="1">
                    <stop offset="5%" stopColor={m.color} stopOpacity={0.5} />
                    <stop offset="95%" stopColor={m.color} stopOpacity={0} />
                  </linearGradient>
                </defs>
                <XAxis dataKey="t" hide />
                <YAxis domain={[0, 100]} hide />
                <Tooltip contentStyle={{ background: '#1e293b', border: 'none', fontSize: 12 }} />
                <Area type="monotone" dataKey={m.key} stroke={m.color} fill={`url(#${m.key})`} />
              </AreaChart>
            </ResponsiveContainer>
          </div>
        ))}
      </div>

      {/* Supervisor processes */}
      <div className="card">
        <h3 className="font-semibold mb-3">Supervisor Programs</h3>
        <table className="w-full text-sm">
          <tbody className="divide-y divide-panel-border">
            {processes.supervisor.map((p) => (
              <tr key={p.name}>
                <td className="py-2 font-mono">{p.name}</td>
                <td>
                  <span className={`badge ${
                    p.state === 'RUNNING' ? 'bg-green-500/15 text-green-400' : 'bg-slate-500/20 text-slate-400'
                  }`}>{p.state}</span>
                </td>
                <td className="text-xs text-slate-500">{p.detail}</td>
                <td className="text-right space-x-2 whitespace-nowrap">
                  <button onClick={() => supervisorAction(p.name, 'start')} className="text-green-400 hover:underline">start</button>
                  <button onClick={() => supervisorAction(p.name, 'stop')} className="text-slate-400 hover:underline">stop</button>
                  <button onClick={() => supervisorAction(p.name, 'restart')} className="text-sky-400 hover:underline">restart</button>
                </td>
              </tr>
            ))}
            {processes.supervisor.length === 0 && (
              <tr><td className="py-4 text-center text-slate-600">No supervisor programs</td></tr>
            )}
          </tbody>
        </table>
      </div>

      {/* APT package manager */}
      <div className="card">
        <h3 className="font-semibold mb-3">APT Package Manager</h3>
        <div className="flex gap-2 mb-3 flex-wrap">
          <input
            className="input max-w-xs"
            placeholder="search packages…"
            value={aptQuery}
            onChange={(e) => setAptQuery(e.target.value)}
            onKeyDown={(e) => e.key === 'Enter' && searchApt()}
          />
          <button className="btn-secondary" onClick={searchApt}>🔍 Search</button>
          <button className="btn-secondary" onClick={() => aptAction('update')}>apt update</button>
          <button className="btn-secondary" onClick={() => aptAction('upgrade')}>apt upgrade</button>
        </div>

        {aptResults.length > 0 && (
          <ul className="max-h-52 overflow-y-auto divide-y divide-panel-border mb-3">
            {aptResults.map((pkg) => (
              <li key={pkg.name} className="flex items-center gap-2 py-1.5 text-sm">
                <span className="font-mono text-sky-300">{pkg.name}</span>
                <span className="text-xs text-slate-500 truncate">{pkg.description}</span>
                <div className="ml-auto flex gap-2 shrink-0">
                  <button onClick={() => aptAction('install', pkg.name)} className="text-green-400 hover:underline">install</button>
                  <button onClick={() => aptAction('remove', pkg.name)} className="text-red-400 hover:underline">remove</button>
                </div>
              </li>
            ))}
          </ul>
        )}

        <LiveLog path={aptWsPath} />
      </div>
    </div>
  )
}
