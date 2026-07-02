import FolderBrowser from '../../components/FolderBrowser'

// Project folders shown in the Files tab. Each is now a full browser: navigate
// subfolders, upload (button + drag-and-drop), download, delete, open
// spreadsheets, and edit text files — including onedrivefiles/ (portal uploads).
const FOLDERS = [
  { name: 'code', hint: 'Python scripts' },
  { name: 'allscripts', hint: 'Helper scripts' },
  { name: 'data', hint: 'Excel / CSV data' },
  { name: 'dashboard', hint: 'Streamlit app (app.py)' },
  { name: 'onedrivefiles', hint: 'Uploaded via the upload portal' },
]

export default function FilesTab({ project, onChanged }) {
  return (
    <div className="grid lg:grid-cols-2 gap-4">
      {FOLDERS.map((folder) => (
        <div key={folder.name} className="card">
          <div className="mb-2">
            <h4 className="font-mono font-semibold text-sky-300">{folder.name}/</h4>
            <p className="text-xs text-slate-500">{folder.hint}</p>
          </div>
          <FolderBrowser
            rootPath={`${project.folder_path}/${folder.name}`}
            editable
            onChanged={onChanged}
            emptyHint="empty"
          />
        </div>
      ))}
    </div>
  )
}
