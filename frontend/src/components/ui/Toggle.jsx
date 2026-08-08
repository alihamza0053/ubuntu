/** Pill switch — mint when on, muted when off. */
export default function Toggle({ checked, onChange, label, hint, disabled }) {
  const control = (
    <button
      type="button"
      role="switch"
      aria-checked={!!checked}
      disabled={disabled}
      onClick={() => onChange?.(!checked)}
      className={`relative h-5 w-9 shrink-0 rounded-full transition-colors duration-200
                  disabled:cursor-not-allowed disabled:opacity-50
                  ${checked ? 'bg-mint-grad' : 'border border-panel-border bg-panel-raise'}`}
    >
      {/* Knob: 2.25rem track − 1rem knob − 0.125rem inset = 1.125rem of travel. */}
      <span
        className={`absolute top-0.5 h-4 w-4 rounded-full shadow transition-transform duration-200
                    ${checked ? 'translate-x-[1.125rem] bg-white' : 'translate-x-0.5 bg-slate-400'}`}
      />
    </button>
  )

  if (!label) return control

  return (
    <label className="flex cursor-pointer items-center gap-3">
      {control}
      <span className="min-w-0">
        <span className="block text-sm text-slate-200">{label}</span>
        {hint && <span className="block text-xs text-slate-500">{hint}</span>}
      </span>
    </label>
  )
}
