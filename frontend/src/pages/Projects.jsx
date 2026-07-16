import { useCallback, useEffect, useState } from 'react'
import api, { errorMessage } from '../api/client'
import ProjectCard from '../components/ProjectCard'
import { useAuth } from '../context/AuthContext'

export default function Projects() {
  const { isAdmin } = useAuth()
  const [projects, setProjects] = useState([])
  const [loading, setLoading] = useState(true)
  const [showModal, setShowModal] = useState(false)
  const [newName, setNewName] = useState('')
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)

  const refresh = useCallback(() => {
    api
      .get('/projects', { params: { with_status: true } })
      .then((res) => setProjects(res.data))
      .finally(() => setLoading(false))
  }, [])

  useEffect(() => {
    refresh()
  }, [refresh])

  async function createProject(event) {
    event.preventDefault()
    setError('')
    setBusy(true)
    try {
      await api.post('/projects', { name: newName })
      setShowModal(false)
      setNewName('')
      refresh()
    } catch (err) {
      setError(errorMessage(err))
    } finally {
      setBusy(false)
    }
  }

  async function toggleHidden(project) {
    try {
      await api.put(`/projects/${project.id}/hidden`, { hidden: !project.hidden })
      refresh()
    } catch (err) {
      alert(errorMessage(err))
    }
  }

  async function deleteProject(project) {
    const deleteFiles = window.confirm(
      `Delete project "${project.name}"?\n\nOK = also delete its files on disk\nCancel = keep going to next question`,
    )
    if (!deleteFiles && !window.confirm(`Delete only the panel entry for "${project.name}" (files stay on disk)?`)) {
      return
    }
    try {
      await api.delete(`/projects/${project.id}`, { params: { delete_files: deleteFiles } })
      refresh()
    } catch (err) {
      alert(errorMessage(err))
    }
  }

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <h2 className="text-2xl font-bold">Python Projects</h2>
        <button className="btn-primary" onClick={() => setShowModal(true)}>
          ＋ New Project
        </button>
      </div>

      {loading ? (
        <p className="text-slate-500">Loading…</p>
      ) : projects.length === 0 ? (
        <div className="card text-center py-12 text-slate-500">
          No projects yet — create one to get the standard workspace folders
          (code / allscripts / data / dashboard).
        </div>
      ) : (
        <div className="grid md:grid-cols-2 xl:grid-cols-3 gap-4">
          {projects.map((p) => (
            <div key={p.id} className="relative">
              <ProjectCard project={p} onChanged={refresh} />
              <button
                onClick={() => deleteProject(p)}
                className="absolute top-3 right-3 -translate-y-9 text-slate-600 hover:text-red-400 text-xs"
                title="Delete project"
              >
                🗑
              </button>
              {isAdmin && (
                <button
                  onClick={() => toggleHidden(p)}
                  className="absolute top-3 right-9 -translate-y-9 text-slate-600 hover:text-sky-400 text-xs"
                  title={p.hidden ? 'Hidden from non-admins — click to unhide' : 'Hide from non-admins'}
                >
                  {p.hidden ? '🙈' : '👁'}
                </button>
              )}
            </div>
          ))}
        </div>
      )}

      {/* New Project modal */}
      {showModal && (
        <div className="fixed inset-0 bg-black/60 flex items-center justify-center z-50 px-4">
          <form onSubmit={createProject} className="card w-full max-w-md space-y-4">
            <h3 className="text-lg font-semibold">New Project</h3>
            <p className="text-sm text-slate-500">
              Creates /srv/projects/&lt;name&gt;/ with code, allscripts, data and dashboard
              folders, plus a supervisor entry for its Streamlit dashboard.
            </p>
            {error && (
              <div className="rounded-lg bg-red-500/10 border border-red-500/30 text-red-400 text-sm px-3 py-2">
                {error}
              </div>
            )}
            <input
              className="input"
              placeholder="project-name (letters, numbers, - _)"
              value={newName}
              onChange={(e) => setNewName(e.target.value)}
              autoFocus
              required
            />
            <div className="flex justify-end gap-2">
              <button type="button" className="btn-secondary" onClick={() => setShowModal(false)}>
                Cancel
              </button>
              <button type="submit" className="btn-primary" disabled={busy}>
                {busy ? 'Creating…' : 'Create'}
              </button>
            </div>
          </form>
        </div>
      )}
    </div>
  )
}
