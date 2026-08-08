import { useState } from 'react'
import { Navigate, useNavigate } from 'react-router-dom'
import { errorMessage } from '../api/client'
import Icon from '../components/ui/Icon'
import { FormError } from '../components/ui/Modal'
import { useAuth } from '../context/AuthContext'

export default function Login() {
  const { user, login } = useAuth()
  const navigate = useNavigate()
  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)

  // Already logged in → go straight to the dashboard
  if (user) return <Navigate to="/dashboard" replace />

  async function handleSubmit(event) {
    event.preventDefault()
    setError('')
    setBusy(true)
    try {
      await login(username, password)
      navigate('/dashboard')
    } catch (err) {
      setError(errorMessage(err))
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="relative z-10 flex min-h-screen items-center justify-center px-4">
      <form onSubmit={handleSubmit} className="card w-full max-w-sm animate-fade-up p-7">
        {/* Brand */}
        <div className="mb-7 flex flex-col items-center text-center">
          <span
            className="mb-4 flex h-12 w-12 items-center justify-center rounded-2xl bg-mint-grad
                       text-base font-black tracking-tight text-[#04231a] shadow-rail"
          >
            SH
          </span>
          <h1 className="text-xl font-semibold tracking-tight text-slate-100">ServerHub</h1>
          <p className="mt-1 text-sm text-slate-500">Sign in to manage your server</p>
        </div>

        <div className="space-y-4">
          <FormError>{error}</FormError>

          <div>
            <label className="label">Username</label>
            <input
              className="input"
              value={username}
              onChange={(e) => setUsername(e.target.value)}
              autoFocus
              required
            />
          </div>
          <div>
            <label className="label">Password</label>
            <input
              className="input"
              type="password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              required
            />
          </div>

          <button type="submit" disabled={busy} className="btn-primary w-full">
            {busy ? 'Signing in…' : (
              <>
                <Icon name="login" size={15} />
                Sign in
              </>
            )}
          </button>
        </div>

        <p className="mt-6 text-center text-xs text-slate-600">VPS control panel</p>
      </form>
    </div>
  )
}
