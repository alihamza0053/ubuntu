import FolderBrowser from '../../components/FolderBrowser'

/**
 * Data Files tab: browse the project's data/ folder and its subfolders — open
 * folders and spreadsheets, and upload (button or drag-and-drop) / download /
 * delete files at any level.
 */
export default function DataFilesTab({ project }) {
  return (
    <div className="card">
      <div className="mb-3">
        <h3 className="font-semibold">Data Files</h3>
        <p className="text-xs text-slate-500">
          Files in the project’s <span className="font-mono">data/</span> folder — used by your scripts.
          Click a spreadsheet to open it.
        </p>
      </div>
      <FolderBrowser
        rootPath={`${project.folder_path}/data`}
        accept=".xlsx,.xls,.csv"
        emptyHint="No data files yet"
      />
    </div>
  )
}
