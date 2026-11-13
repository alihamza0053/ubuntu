import Icon from '../components/ui/Icon'
import PageHeader from '../components/ui/PageHeader'
import { STYLES, THEME_MODES, useTheme } from '../context/ThemeContext'

const STYLE_INFO = {
  bento: { name: 'Bento', text: 'Solid rounded tiles in a clean grid. The default, and the clearest to read.' },
  glass: { name: 'Glassmorphism', text: 'Frosted, see-through tiles over a soft colour glow.' },
  neu: { name: 'Neumorphism', text: 'Soft raised tiles shaped by light and shadow, with pressed-in fields.' },
}

const MODE_INFO = {
  system: { icon: 'monitor', name: 'System', text: 'Follows your device' },
  light: { icon: 'sun', name: 'Light', text: 'Bright background' },
  dark: { icon: 'moon', name: 'Dark', text: 'Dark background' },
}

/** One selectable option tile: a real radio button underneath, so keyboards
 *  and screen readers get the usual arrow-key behaviour for free. */
function Option({ name, value, checked, onChange, children }) {
  return (
    <label className={`group relative block cursor-pointer rounded-2xl border-2 p-3 transition-colors
                       ${checked ? 'border-mint-400 bg-mint-400/[0.06]' : 'border-panel-border hover:border-mint-400/40'}`}>
      <input type="radio" name={name} value={value} checked={checked} onChange={() => onChange(value)}
        className="peer sr-only" />
      {children}
      {checked && (
        <span className="absolute right-3 top-3 flex h-6 w-6 items-center justify-center rounded-full bg-mint-grad text-ink">
          <Icon name="check" size={14} />
        </span>
      )}
      {/* Visible keyboard focus for the hidden radio */}
      <span className="pointer-events-none absolute -inset-1 rounded-[1.15rem] ring-2 ring-mint-400/70 opacity-0
                       peer-focus-visible:opacity-100" />
    </label>
  )
}

export default function Appearance() {
  const { mode, setMode, style, setStyle } = useTheme()

  return (
    <div className="space-y-6">
      <PageHeader title="Appearance" crumbs={[{ label: 'ServerHub' }, { label: 'Appearance' }]}>
        <p className="text-sm text-slate-500">
          Saved in this browser only, so everyone can pick their own. Changes apply instantly.
        </p>
      </PageHeader>

      <section className="card">
        <h2 className="section-title">Style</h2>
        <p className="mt-1 text-sm text-slate-500">How the tiles and controls look.</p>
        <div className="mt-4 grid gap-4 md:grid-cols-3" role="radiogroup" aria-label="Style">
          {STYLES.map((key) => (
            <Option key={key} name="panel-style" value={key} checked={style === key} onChange={setStyle}>
              <div className={`style-preview style-preview-${key}`} aria-hidden="true">
                <span /><span /><span />
              </div>
              <p className="mt-3 font-semibold text-slate-100">{STYLE_INFO[key].name}</p>
              <p className="mt-0.5 text-sm text-slate-500">{STYLE_INFO[key].text}</p>
            </Option>
          ))}
        </div>
      </section>

      <section className="card">
        <h2 className="section-title">Colour mode</h2>
        <p className="mt-1 text-sm text-slate-500">Works with every style.</p>
        <div className="mt-4 grid gap-4 sm:grid-cols-3" role="radiogroup" aria-label="Colour mode">
          {THEME_MODES.map((key) => (
            <Option key={key} name="panel-mode" value={key} checked={mode === key} onChange={setMode}>
              <div className="flex items-center gap-3">
                <span className="tile-icon"><Icon name={MODE_INFO[key].icon} size={18} /></span>
                <span>
                  <span className="block font-semibold text-slate-100">{MODE_INFO[key].name}</span>
                  <span className="block text-sm text-slate-500">{MODE_INFO[key].text}</span>
                </span>
              </div>
            </Option>
          ))}
        </div>
      </section>
    </div>
  )
}
