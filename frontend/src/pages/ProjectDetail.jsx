import { useCallback, useEffect, useState } from 'react'
import { Link, useParams, useSearchParams } from 'react-router-dom'
import api from '../api/client'
import StatusBadge from '../components/StatusBadge'
import Icon from '../components/ui/Icon'
import PageHeader from '../components/ui/PageHeader'
import Tabs from '../components/ui/Tabs'
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

  if (!project) return <div className="empty-state">Loading…</div>

  return (
    <div className="space-y-5">
      <PageHeader
        title={project.name}
        crumbs={[{ label: 'Projects', to: '/projects' }, { label: project.name }]}
        actions={
          <>
            <StatusBadge status={project.dashboard_status} />
            <span className="badge-muted">port {project.dashboard_port}</span>
            <Link to="/projects" className="btn-secondary">
              <Icon name="arrow-left" size={15} />
              All projects
            </Link>
          </>
        }
      />

      <Tabs tabs={TABS} active={tab} onChange={(key) => setSearchParams({ tab: key })} />

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
