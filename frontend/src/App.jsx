import { Navigate, Route, Routes } from 'react-router-dom'
import Layout from './components/Layout'
import { useAuth } from './context/AuthContext'
import Databases from './pages/Databases'
import Files from './pages/Files'
import Home from './pages/Home'
import Login from './pages/Login'
import Logs from './pages/Logs'
import Nginx from './pages/Nginx'
import ProjectDetail from './pages/ProjectDetail'
import Projects from './pages/Projects'
import Server from './pages/Server'
import Settings from './pages/Settings'
import Terminal from './pages/Terminal'
import WebsiteDetail from './pages/WebsiteDetail'
import Websites from './pages/Websites'

/** Gate: render children only when authenticated. */
function RequireAuth({ children }) {
  const { user, loading } = useAuth()
  if (loading) {
    return <div className="h-screen flex items-center justify-center text-slate-400">Loading…</div>
  }
  return user ? children : <Navigate to="/login" replace />
}

export default function App() {
  return (
    <Routes>
      <Route path="/login" element={<Login />} />
      <Route
        path="/"
        element={
          <RequireAuth>
            <Layout />
          </RequireAuth>
        }
      >
        <Route index element={<Navigate to="/dashboard" replace />} />
        <Route path="dashboard" element={<Home />} />
        <Route path="projects" element={<Projects />} />
        <Route path="projects/:id" element={<ProjectDetail />} />
        <Route path="websites" element={<Websites />} />
        <Route path="websites/:id" element={<WebsiteDetail />} />
        <Route path="terminal" element={<Terminal />} />
        <Route path="logs" element={<Logs />} />
        <Route path="files" element={<Files />} />
        <Route path="databases" element={<Databases />} />
        <Route path="nginx" element={<Nginx />} />
        <Route path="server" element={<Server />} />
        <Route path="settings" element={<Settings />} />
      </Route>
      <Route path="*" element={<Navigate to="/dashboard" replace />} />
    </Routes>
  )
}
