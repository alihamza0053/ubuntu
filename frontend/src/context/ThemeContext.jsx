import { createContext, useCallback, useContext, useEffect, useMemo, useState } from 'react'

/**
 * Colour theme: "system" (follow the device), "dark" or "light".
 *
 * The choice is kept per browser in localStorage. <html data-theme> carries the
 * resolved theme ("dark" | "light"), which theme.css keys every colour on. The
 * inline script in index.html applies the same choice before the first paint,
 * so a light-theme user never sees a dark flash on load.
 */
const ThemeContext = createContext(null)

export const THEME_KEY = 'serverhub.theme'
export const THEME_MODES = ['system', 'light', 'dark']
// Surface style, independent of light/dark: <html data-style> (see styles.css).
export const STYLE_KEY = 'serverhub.style'
export const STYLES = ['bento', 'glass', 'neu']
const META_COLOR = { dark: '#060E13', light: '#EEF3F1' }

const media = typeof window !== 'undefined' && window.matchMedia
  ? window.matchMedia('(prefers-color-scheme: light)')
  : null

function readMode() {
  try {
    const stored = localStorage.getItem(THEME_KEY)
    return THEME_MODES.includes(stored) ? stored : 'system'
  } catch {
    return 'system'
  }
}

function readStyle() {
  try {
    const stored = localStorage.getItem(STYLE_KEY)
    return STYLES.includes(stored) ? stored : 'bento'
  } catch {
    return 'bento'
  }
}

function resolve(mode) {
  if (mode === 'light' || mode === 'dark') return mode
  return media?.matches ? 'light' : 'dark'
}

function apply(theme) {
  const root = document.documentElement
  root.dataset.theme = theme
  root.classList.toggle('dark', theme === 'dark')
  document.querySelector('meta[name="theme-color"]')?.setAttribute('content', META_COLOR[theme])
}

export function ThemeProvider({ children }) {
  const [mode, setModeState] = useState(readMode)
  const [theme, setTheme] = useState(() => resolve(readMode()))
  const [style, setStyleState] = useState(readStyle)

  useEffect(() => {
    document.documentElement.dataset.style = style
  }, [style])

  const setStyle = useCallback((next) => {
    if (!STYLES.includes(next)) return
    setStyleState(next)
    try { localStorage.setItem(STYLE_KEY, next) } catch { /* private mode */ }
  }, [])

  useEffect(() => {
    const next = resolve(mode)
    setTheme(next)
    apply(next)
    if (mode !== 'system' || !media) return undefined
    // Follow the device live while on "system" (e.g. an OS switch at sunset).
    const onChange = () => {
      const followed = resolve('system')
      setTheme(followed)
      apply(followed)
    }
    media.addEventListener('change', onChange)
    return () => media.removeEventListener('change', onChange)
  }, [mode])

  const setMode = useCallback((next) => {
    if (!THEME_MODES.includes(next)) return
    setModeState(next)
    try { localStorage.setItem(THEME_KEY, next) } catch { /* private mode */ }
  }, [])

  const value = useMemo(() => ({ mode, theme, setMode, style, setStyle }), [mode, theme, setMode, style, setStyle])
  return <ThemeContext.Provider value={value}>{children}</ThemeContext.Provider>
}

export function useTheme() {
  const ctx = useContext(ThemeContext)
  if (!ctx) throw new Error('useTheme must be used inside <ThemeProvider>')
  return ctx
}
