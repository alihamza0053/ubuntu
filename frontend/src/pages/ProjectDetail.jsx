import { useCallback, useEffect, useState } from 'react'
import { Link, useParams, useSearchParams } from 'react-router-dom'
import api from '../api/client'
import StatusBadge from '../components/StatusBadge'
import DashboardTab from './project-tabs/DashboardTab'
import DataFilesTab from './project-tabs/DataFilesTab'
import EditorTab from './project-tabs/EditorTab'
import FilesTab from './project-tabs/FilesTab'
import OneDriveTab from './project-tabs/OneDriveTab'
import OverviewTab from './project-tabs/OverviewTab'
import PackagesTab from './project-tabs/PackagesTab'
import PipelineTab from './project-tabs/PipelineTab'
import SchedulerTab from './project-tabs/SchedulerTab'
import ScriptsTab from './project-tabs/ScriptsTab'
import UploadPortalTab from './project-tabs/UploadPortalTab'

const TABS = [
  { key: 'overview', label: 'Overview' },
  { key: 'files', label: 'Files' },
  { key: 'editor', label: 'Code Editor' },
  { key: 'scripts', label: 'Scripts' },
  { key: 'packages', label: 'Packages' },
  { key: 'pipeline', label: 'Pipeline' },
  { key: 'dashboard', label: 'Dashboard' },
  { key: 'scheduler', label: 'Scheduler' },
  { key: 'data', label: 'Data Files' },
  { key: 'onedrive', label: 'OneDrive' },
  { key: 'portal', label: 'Upload Portal' },
]

export default function ProjectDetail() {
  const { id } = useParams()
  const [searchParams, setSearchParams] = useSearchParams()
  const tab = searchParams.get('tab') || 'overview'

  const [project, setProject] = useState(null)
  const [files, setFiles] = useState(null) // { folders: { code: [...], ... } }
  // File selected from the Files tab to open in the editor
  const [editorFile, setEditorFile] = useState(null)

  const refresh = useCallback(() => {
    api.get(`/projects/${id}`).then((res) => setProject(res.data))
    api.get(`/projects/${id}/files`).then((res) => setFiles(res.data))
  }, [id])

  useEffect(() => {
    refresh()
  }, [refresh])

  function openInEditor(folder, filename) {
    setEditorFile({ folder, filename })
    setSearchParams({ tab: 'editor' })
  }

  if (!project) return <p className="text-slate-500">Loading…</p>

  return (
    <div className="space-y-4">
      {/* Header */}
      <div className="flex items-center gap-3 flex-wrap">
        <Link to="/projects" className="text-slate-500 hover:text-slate-300">←</Link>
        <h2 className="text-2xl font-bold">{project.name}</h2>
        <StatusBadge status={project.dashboard_status} />
        <span className="text-sm text-slate-500">port {project.dashboard_port}</span>
      </div>

      {/* Tab bar */}
      <div className="flex gap-1 border-b border-panel-border overflow-x-auto">
        {TABS.map((t) => (
          <button
            key={t.key}
            onClick={() => setSearchParams({ tab: t.key })}
            className={`px-4 py-2 text-sm whitespace-nowrap border-b-2 -mb-px transition-colors ${
              tab === t.key
                ? 'border-sky-400 text-sky-300'
                : 'border-transparent text-slate-400 hover:text-slate-200'
            }`}
          >
            {t.label}
          </button>
        ))}
      </div>

      {/* Active tab */}
      {tab === 'overview' && <OverviewTab project={project} files={files} />}
      {tab === 'files' && (
        <FilesTab project={project} files={files} onChanged={refresh} onOpenFile={openInEditor} />
      )}
      {tab === 'editor' && (
        <EditorTab project={project} files={files} initialFile={editorFile} />
      )}
      {tab === 'scripts' && <ScriptsTab project={project} onChanged={refresh} />}
      {tab === 'packages' && <PackagesTab project={project} />}
      {tab === 'pipeline' && <PipelineTab project={project} />}
      {tab === 'dashboard' && <DashboardTab project={project} onChanged={refresh} />}
      {tab === 'scheduler' && <SchedulerTab project={project} />}
      {tab === 'data' && <DataFilesTab project={project} files={files} onChanged={refresh} />}
      {tab === 'onedrive' && <OneDriveTab project={project} />}
      {tab === 'portal' && <UploadPortalTab project={project} onChanged={refresh} />}
    </div>
  )
}
