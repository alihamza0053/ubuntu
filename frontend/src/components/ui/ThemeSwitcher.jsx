import { THEME_MODES, useTheme } from '../../context/ThemeContext'
import Icon from './Icon'

const OPTIONS = {
  system: { icon: 'monitor', label: 'System' },
  light: { icon: 'sun', label: 'Light' },
  dark: { icon: 'moon', label: 'Dark' },
}

/**
 * Three-way theme control: System / Light / Dark. A real radio group, so it is
 * reachable with Tab and switchable with the arrow keys.
 * showLabels: print the names beside the icons (Settings, wide screens).
 */
export default function ThemeSwitcher({ showLabels = false, className = '' }) {
  const { mode, setMode } = useTheme()

  function onKeyDown(e) {
    const step = { ArrowRight: 1, ArrowDown: 1, ArrowLeft: -1, ArrowUp: -1 }[e.key]
    if (!step) return
    e.preventDefault()
    const next = THEME_MODES[(THEME_MODES.indexOf(mode) + step + THEME_MODES.length) % THEME_MODES.length]
    setMode(next)
    e.currentTarget.querySelector(`[data-mode="${next}"]`)?.focus()
  }

  return (
    <div role="radiogroup" aria-label="Colour theme" onKeyDown={onKeyDown}
      className={`inline-flex items-center gap-0.5 rounded-xl border border-panel-border bg-panel-bg/70 p-0.5 ${className}`}>
      {THEME_MODES.map((key) => {
        const active = key === mode
        const { icon, label } = OPTIONS[key]
        return (
          <button
            key={key}
            type="button"
            role="radio"
            data-mode={key}
            aria-checked={active}
            tabIndex={active ? 0 : -1}
            title={`${label} theme`}
            onClick={() => setMode(key)}
            className={`inline-flex h-8 items-center justify-center gap-1.5 rounded-[0.6rem] text-xs font-medium
                        transition-colors ${showLabels ? 'flex-1 px-2.5' : 'w-8'}
                        ${active
                          ? 'bg-panel-card text-mint-300 shadow-card'
                          : 'text-slate-500 hover:text-slate-200'}`}
          >
            <Icon name={icon} size={15} />
            {showLabels ? label : <span className="sr-only">{label}</span>}
          </button>
        )
      })}
    </div>
  )
}
