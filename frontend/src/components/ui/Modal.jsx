import { useEffect } from 'react'
import Icon from './Icon'

/**
 * Centered dialog on a blurred scrim. Closes on Escape and on scrim click.
 *
 * <Modal title="New Project" onClose={…} footer={…}>…</Modal>
 */
export default function Modal({ title, subtitle, onClose, children, footer, size = 'md', as = 'div', onSubmit }) {
  useEffect(() => {
    const onKey = (e) => e.key === 'Escape' && onClose?.()
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [onClose])

  const widths = { sm: 'max-w-sm', md: 'max-w-md', lg: 'max-w-2xl', xl: 'max-w-4xl' }
  const Tag = as

  return (
    <div className="scrim" onMouseDown={(e) => e.target === e.currentTarget && onClose?.()}>
      <Tag
        onSubmit={onSubmit}
        className={`card w-full ${widths[size] || widths.md} animate-fade-up
                    max-h-[88vh] overflow-y-auto p-0 shadow-[0_24px_60px_-20px_rgba(0,0,0,0.9)]`}
      >
        <div className="flex items-start justify-between gap-4 border-b border-panel-border/70 px-5 py-4">
          <div className="min-w-0">
            <h3 className="truncate text-base font-semibold text-slate-100">{title}</h3>
            {subtitle && <p className="mt-0.5 text-xs text-slate-500">{subtitle}</p>}
          </div>
          {onClose && (
            <button type="button" onClick={onClose} className="btn-icon -mr-1" aria-label="Close">
              <Icon name="x" size={16} />
            </button>
          )}
        </div>

        <div className="space-y-4 px-5 py-5">{children}</div>

        {footer && (
          <div className="flex flex-wrap items-center justify-end gap-2 border-t border-panel-border/70 px-5 py-4">
            {footer}
          </div>
        )}
      </Tag>
    </div>
  )
}

/** Inline error strip used inside modals and forms. */
export function FormError({ children }) {
  if (!children) return null
  return (
    <div className="flex items-start gap-2 rounded-lg border border-red-500/30 bg-red-500/10 px-3 py-2 text-sm text-red-300">
      <Icon name="warning" size={15} className="mt-0.5" />
      <span className="min-w-0">{children}</span>
    </div>
  )
}
