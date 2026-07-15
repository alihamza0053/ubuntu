import { Navigate, Route, Routes } from 'react-router-dom'
import Layout from './components/Layout'
import { useAuth } from './context/AuthContext'
import { firstAllowed } from './nav'
import Apps from './pages/Apps'
import Databases from './pages/Databases'
import Docker from './pages/Docker'
import Files from './pages/Files'
import Home from './pages/Home'
import Login from './pages/Login'
import Logs from './pages/Logs'
import Nginx from './pages/Nginx'
import ProjectDetail from './pages/ProjectDetail'
import Projects from './pages/Projects'
import Proxies from './pages/Proxies'
import RecycleBin from './pages/RecycleBin'
import Server from './pages/Server'
import Settings from './pages/Settings'
import ShopifyApps from './pages/ShopifyApps'
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

/** Per-tab gate: redirect to the user's first allowed tab if not permitted. */
function Guard({ perm, children }) {
  const { can } = useAuth()
  return can(perm) ? children : <Navigate to={firstAllowed(can)} replace />
}

export default function App() {
  const { can } = useAuth()
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
        <Route index element={<Navigate to={firstAllowed(can)} replace />} />
        <Route path="dashboard" element={<Guard perm="dashboard"><Home /></Guard>} />
        <Route path="projects" element={<Guard perm="projects"><Projects /></Guard>} />
        <Route path="projects/:id" element={<Guard perm="projects"><ProjectDetail /></Guard>} />
        <Route path="websites" element={<Guard perm="websites"><Websites /></Guard>} />
        <Route path="websites/:id" element={<Guard perm="websites"><WebsiteDetail /></Guard>} />
        <Route path="proxies" element={<Guard perm="proxies"><Proxies /></Guard>} />
        <Route path="apps" element={<Guard perm="apps"><Apps /></Guard>} />
        <Route path="shopify-apps" element={<Guard perm="shopify"><ShopifyApps /></Guard>} />
        <Route path="docker" element={<Guard perm="docker"><Docker /></Guard>} />
        <Route path="terminal" element={<Guard perm="terminal"><Terminal /></Guard>} />
        <Route path="logs" element={<Guard perm="logs"><Logs /></Guard>} />
        <Route path="files" element={<Guard perm="files"><Files /></Guard>} />
        <Route path="recycle-bin" element={<Guard perm="files"><RecycleBin /></Guard>} />
        <Route path="databases" element={<Guard perm="databases"><Databases /></Guard>} />
        <Route path="nginx" element={<Guard perm="nginx"><Nginx /></Guard>} />
        <Route path="server" element={<Guard perm="server"><Server /></Guard>} />
        <Route path="settings" element={<Guard perm="settings"><Settings /></Guard>} />
      </Route>
      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
  )
}
