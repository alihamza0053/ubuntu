import { useCallback, useEffect, useMemo, useState } from 'react'
import api, { errorMessage } from '../../api/client'
import LiveLog from '../../components/LiveLog'

/**
 * Packages tab: pip-install Python libraries into the same interpreter that
 * runs this project's scripts — so a `ModuleNotFoundError: No module named 'X'`
 * is fixed by typing `X` and clicking Install.
 */
export default function PackagesTab({ project }) {
  const [pkgs, setPkgs] = useState([])
  const [pyver, setPyver] = useState('')
  const [loading, setLoading] = useState(true)
  const [spec, setSpec] = useState('')
  const [installWs, setInstallWs] = useState(null)
  const [query, setQuery] = useState('')
  const [err, setErr] = useState('')

  const refresh = useCallback(() => {
    setLoading(true)
    api.get(`/projects/${project.id}/packages`)
      .then((res) => { setPkgs(res.data.packages || []); setPyver(res.data.python || '') })
      .catch((e) => setErr(errorMessage(e)))
      .finally(() => setLoading(false))
  }, [project.id])

  useEffect(() => { refresh() }, [refresh])

  function install(e) {
    e?.preventDefault()
    if (!spec.trim()) return
    const path = `/ws/projects/${project.id}/pip-install?spec=${encodeURIComponent(spec.trim())}`
    setInstallWs(null)
    setTimeout(() => setInstallWs(path), 0)
  }

  function installPlaywrightBrowsers() {
    const path = `/ws/projects/${project.id}/playwright-install`
    setInstallWs(null)
    setTimeout(() => setInstallWs(path), 0)
  }

  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase()
    return q ? pkgs.filter((p) => p.name.toLowerCase().includes(q)) : pkgs
  }, [pkgs, query])

  return (
    <div className="space-y-4">
      <div className="card">
        <h3 className="font-semibold">📦 Install a Python package</h3>
        <p className="text-xs text-slate-500 mt-1">
          Installs into the scripts' Python ({pyver || 'python3'}). When a script fails with
          <span className="font-mono"> ModuleNotFoundError: No module named 'X'</span>, type
          <span className="font-mono"> X</span> here and Install.
        </p>
        <form onSubmit={install} className="mt-3 flex gap-2 flex-wrap">
          <input
            className="input font-mono flex-1 min-w-[16rem]"
            placeholder="e.g. playwright   or   requests==2.31.0   (space-separate several)"
            value={spec}
            onChange={(e) => setSpec(e.target.value)}
          />
          <button type="submit" className="btn-primary" disabled={!spec.trim()}>⬇ Install</button>
        </form>
        <div className="text-xs text-slate-600 mt-2 flex items-center gap-2 flex-wrap">
          <span>
            Packages are shared by all projects' scripts (same interpreter). Using Playwright?
            After installing it, download its browser:
          </span>
          <button type="button" className="btn-secondary py-1" onClick={installPlaywrightBrowsers}>
            🎭 Install Playwright browsers
          </button>
        </div>
        {installWs && (
          <LiveLog path={installWs} onClose={refresh} />
        )}
      </div>

      <div className="card">
        <div className="flex items-center justify-between gap-2 mb-3 flex-wrap">
          <h3 className="font-semibold">Installed packages {!loading && `(${pkgs.length})`}</h3>
          <input
            className="input max-w-xs"
            placeholder="🔎 filter…"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
          />
        </div>
        {err && <p className="text-red-400 text-sm mb-2">{err}</p>}
        {loading ? (
          <p className="text-slate-500">Loading…</p>
        ) : (
          <table className="w-full text-sm">
            <thead>
              <tr className="text-left text-xs uppercase text-slate-500 border-b border-panel-border">
                <th className="py-2">Package</th>
                <th>Version</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-panel-border">
              {filtered.map((p) => (
                <tr key={p.name}>
                  <td className="py-1.5 font-mono">{p.name}</td>
                  <td className="text-slate-400 font-mono">{p.version}</td>
                </tr>
              ))}
              {filtered.length === 0 && (
                <tr><td colSpan={2} className="py-6 text-center text-slate-600">no matches</td></tr>
              )}
            </tbody>
          </table>
        )}
      </div>
    </div>
  )
}
