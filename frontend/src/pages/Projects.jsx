import { useCallback, useEffect, useMemo, useState } from 'react'
import api, { errorMessage } from '../api/client'
import ProjectCard from '../components/ProjectCard'
import Icon from '../components/ui/Icon'
import Modal, { FormError } from '../components/ui/Modal'
import PageHeader from '../components/ui/PageHeader'
import { useAuth } from '../context/AuthContext'

export default function Projects() {
  const { isAdmin } = useAuth()
  const [projects, setProjects] = useState([])
  const [loading, setLoading] = useState(true)
  const [showModal, setShowModal] = useState(false)
  const [newName, setNewName] = useState('')
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)
  const [query, setQuery] = useState('')

  const refresh = useCallback(() => {
    api
      .get('/projects', { params: { with_status: true } })
      .then((res) => setProjects(res.data))
      .finally(() => setLoading(false))
  }, [])

  useEffect(() => {
    refresh()
  }, [refresh])

  const visible = useMemo(() => {
    const q = query.trim().toLowerCase()
    return q ? projects.filter((p) => p.name.toLowerCase().includes(q)) : projects
  }, [projects, query])

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
      <PageHeader
        title="Python Projects"
        crumbs={[{ label: 'Workspaces' }, { label: 'Projects' }]}
        actions={
          <>
            <div className="search-pill w-52">
              <Icon name="search" size={15} className="text-slate-500" />
              <input
                value={query}
                placeholder="Filter projects…"
                onChange={(e) => setQuery(e.target.value)}
              />
            </div>
            <button className="btn-secondary" onClick={refresh}>
              <Icon name="refresh" size={15} />
              Refresh
            </button>
            <button className="btn-primary" onClick={() => setShowModal(true)}>
              <Icon name="plus" size={15} />
              New Project
            </button>
          </>
        }
      />

      {loading ? (
        <div className="empty-state">Loading…</div>
      ) : visible.length === 0 ? (
        <div className="empty-state">
          <Icon name="code" size={26} className="text-slate-600" />
          {projects.length === 0 ? (
            <>
              <p className="text-slate-400">No projects yet</p>
              <p className="max-w-md text-sm">
                Create one to get the standard workspace folders (code / allscripts / data / dashboard).
              </p>
              <button className="btn-primary mt-2" onClick={() => setShowModal(true)}>
                <Icon name="plus" size={15} />
                New Project
              </button>
            </>
          ) : (
            <p>No project matches “{query}”.</p>
          )}
        </div>
      ) : (
        <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
          {visible.map((p) => (
            <ProjectCard
              key={p.id}
              project={p}
              onChanged={refresh}
              onDelete={deleteProject}
              onToggleHidden={isAdmin ? toggleHidden : undefined}
            />
          ))}
        </div>
      )}

      {/* New Project modal */}
      {showModal && (
        <Modal
          as="form"
          onSubmit={createProject}
          title="New Project"
          subtitle="Creates /srv/projects/<name>/ with code, allscripts, data and dashboard folders, plus a supervisor entry for its dashboard."
          onClose={() => setShowModal(false)}
          footer={
            <>
              <button type="button" className="btn-secondary" onClick={() => setShowModal(false)}>
                Cancel
              </button>
              <button type="submit" className="btn-primary" disabled={busy}>
                {busy ? 'Creating…' : 'Create project'}
              </button>
            </>
          }
        >
          <FormError>{error}</FormError>
          <div>
            <label className="label">Project name</label>
            <input
              className="input"
              placeholder="project-name (letters, numbers, - _)"
              value={newName}
              onChange={(e) => setNewName(e.target.value)}
              autoFocus
              required
            />
          </div>
        </Modal>
      )}
    </div>
  )
}
