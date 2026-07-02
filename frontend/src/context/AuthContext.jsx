import { createContext, useContext, useEffect, useState } from 'react'
import api from '../api/client'

// Holds the logged-in user; the token itself lives in localStorage so the
// axios interceptor and WebSocket helper can read it without React context.
const AuthContext = createContext(null)

export function AuthProvider({ children }) {
  const [user, setUser] = useState(null)
  const [loading, setLoading] = useState(true) // true while validating stored token

  useEffect(() => {
    const token = localStorage.getItem('serverhub_token')
    if (!token) {
      setLoading(false)
      return
    }
    api.get('/auth/me')
      .then((res) => setUser(res.data))
      .catch(() => localStorage.removeItem('serverhub_token'))
      .finally(() => setLoading(false))
  }, [])

  async function login(username, password) {
    const res = await api.post('/auth/login', { username, password })
    localStorage.setItem('serverhub_token', res.data.access_token)
    const me = await api.get('/auth/me')
    setUser(me.data)
  }

  function logout() {
    localStorage.removeItem('serverhub_token')
    setUser(null)
  }

  const isAdmin = !!user?.is_admin
  // can(perm): admins can do everything; others only their granted tabs.
  function can(perm) {
    if (isAdmin) return true
    return (user?.permissions || []).includes(perm)
  }

  return (
    <AuthContext.Provider value={{ user, loading, login, logout, isAdmin, can }}>
      {children}
    </AuthContext.Provider>
  )
}

export function useAuth() {
  return useContext(AuthContext)
}
