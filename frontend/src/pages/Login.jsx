import { useState } from 'react'
import { Navigate, useNavigate } from 'react-router-dom'
import { errorMessage } from '../api/client'
import Icon from '../components/ui/Icon'
import { FormError } from '../components/ui/Modal'
import ThemeSwitcher from '../components/ui/ThemeSwitcher'
import { useAuth } from '../context/AuthContext'

const FEATURES = [
  { icon: 'code', title: 'Projects', text: 'Python pipelines and live dashboards' },
  { icon: 'globe', title: 'Websites', text: 'Static, React, PHP, Python and Node.js' },
  { icon: 'database', title: 'Databases', text: 'MySQL and PostgreSQL, isolated per app' },
  { icon: 'shield', title: 'Backups', text: 'Weekly snapshots, restore in a click' },
]

export default function Login() {
  const { user, login } = useAuth()
  const navigate = useNavigate()
  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')
  const [showPassword, setShowPassword] = useState(false)
  const [capsLock, setCapsLock] = useState(false)
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

  const trackCaps = (e) => setCapsLock(e.getModifierState?.('CapsLock') || false)

  return (
    <div className="relative z-10 flex min-h-screen flex-col px-4 py-5">
      <div className="flex justify-end">
        <ThemeSwitcher />
      </div>

      <main className="flex flex-1 items-center justify-center py-6">
        <div className="grid w-full max-w-5xl animate-fade-up gap-4 lg:grid-cols-12">
          {/* Brand + feature tiles: wide screens only, the form comes first on phones */}
          <section className="hidden gap-4 lg:col-span-7 lg:grid lg:grid-cols-2" aria-label="About ServerHub">
            <div className="col-span-2 flex min-h-[15rem] flex-col justify-between overflow-hidden rounded-tile
                            bg-mint-grad p-7 text-ink shadow-rail">
              <span className="flex h-12 w-12 items-center justify-center rounded-2xl bg-ink/10
                               text-base font-black tracking-tight">
                SH
              </span>
              <div>
                <h1 className="text-3xl font-semibold tracking-tight">ServerHub</h1>
                <p className="mt-2 max-w-sm text-sm text-ink/75">
                  One place to run your server: projects, websites, databases and backups.
                </p>
              </div>
            </div>
            {FEATURES.map((f) => (
              <div key={f.title} className="card">
                <span className="tile-icon mb-4">
                  <Icon name={f.icon} size={18} />
                </span>
                <p className="font-semibold text-slate-100">{f.title}</p>
                <p className="mt-1 text-sm text-slate-500">{f.text}</p>
              </div>
            ))}
          </section>

          {/* Sign-in tile */}
          <form onSubmit={handleSubmit}
            className="card mx-auto flex w-full max-w-md flex-col justify-center p-7 sm:p-9 lg:col-span-5 lg:max-w-none">
            <div className="mb-8">
              <span className="mb-5 flex h-12 w-12 items-center justify-center rounded-2xl bg-mint-grad
                               text-base font-black tracking-tight text-ink shadow-rail lg:hidden">
                SH
              </span>
              <h2 className="text-2xl font-semibold tracking-tight text-slate-100">Welcome back</h2>
              <p className="mt-1.5 text-sm text-slate-500">Sign in to manage your server.</p>
            </div>

            <div className="space-y-4">
              <FormError>{error}</FormError>

              <div>
                <label className="label" htmlFor="login-username">Username</label>
                <div className="relative">
                  <Icon name="user" size={16}
                    className="pointer-events-none absolute left-3.5 top-1/2 -translate-y-1/2 text-slate-500" />
                  <input
                    id="login-username"
                    className="input pl-10"
                    value={username}
                    onChange={(e) => setUsername(e.target.value)}
                    autoComplete="username"
                    autoCapitalize="none"
                    spellCheck={false}
                    autoFocus
                    required
                  />
                </div>
              </div>

              <div>
                <label className="label" htmlFor="login-password">Password</label>
                <div className="relative">
                  <Icon name="lock" size={16}
                    className="pointer-events-none absolute left-3.5 top-1/2 -translate-y-1/2 text-slate-500" />
                  <input
                    id="login-password"
                    className="input pl-10 pr-11"
                    type={showPassword ? 'text' : 'password'}
                    value={password}
                    onChange={(e) => setPassword(e.target.value)}
                    onKeyDown={trackCaps}
                    onKeyUp={trackCaps}
                    autoComplete="current-password"
                    aria-describedby={capsLock ? 'caps-warning' : undefined}
                    required
                  />
                  <button
                    type="button"
                    onClick={() => setShowPassword((s) => !s)}
                    className="absolute right-1.5 top-1/2 flex h-8 w-8 -translate-y-1/2 items-center justify-center
                               rounded-lg text-slate-500 transition-colors hover:bg-panel-raise hover:text-slate-200"
                    aria-label={showPassword ? 'Hide password' : 'Show password'}
                    aria-pressed={showPassword}
                  >
                    <Icon name={showPassword ? 'eye-off' : 'eye'} size={16} />
                  </button>
                </div>
                {capsLock && (
                  <p id="caps-warning" className="mt-1.5 flex items-center gap-1.5 text-xs text-amber-300">
                    <Icon name="warning" size={13} /> Caps Lock is on
                  </p>
                )}
              </div>

              <button type="submit" disabled={busy || !username || !password} className="btn-primary h-11 w-full text-[15px]">
                {busy ? 'Signing in…' : (
                  <>
                    Sign in
                    <Icon name="arrow-right" size={16} />
                  </>
                )}
              </button>
            </div>

            <p className="mt-8 text-center text-xs text-slate-500">ServerHub · VPS control panel</p>
          </form>
        </div>
      </main>
    </div>
  )
}
