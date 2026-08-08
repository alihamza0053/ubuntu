import { Link } from 'react-router-dom'
import Icon from './Icon'

/**
 * Page title block: big heading, mint breadcrumb trail underneath and an
 * optional action cluster pinned right.
 *
 * <PageHeader
 *   title="Settings"
 *   crumbs={[{ label: 'Platform Settings', to: '/settings' }, { label: 'Cloud Setting' }]}
 *   actions={<button className="btn-primary">…</button>}
 * />
 */
export default function PageHeader({ title, crumbs = [], actions, children }) {
  return (
    <header className="flex flex-wrap items-start justify-between gap-4">
      <div className="min-w-0">
        <h1 className="truncate text-2xl font-semibold tracking-tight text-slate-100">{title}</h1>

        {crumbs.length > 0 && (
          <nav aria-label="Breadcrumb" className="mt-1.5 flex flex-wrap items-center gap-1.5 text-xs">
            {crumbs.map((crumb, i) => (
              <span key={`${crumb.label}-${i}`} className="flex items-center gap-1.5">
                {i > 0 && <Icon name="chevron-right" size={11} className="text-slate-600" />}
                {crumb.to ? (
                  <Link to={crumb.to} className="text-mint-400 transition-colors hover:text-mint-300">
                    {crumb.label}
                  </Link>
                ) : (
                  <span className={i === crumbs.length - 1 ? 'text-slate-400' : 'text-mint-400'}>
                    {crumb.label}
                  </span>
                )}
              </span>
            ))}
          </nav>
        )}

        {children && <div className="mt-2">{children}</div>}
      </div>

      {actions && <div className="flex flex-wrap items-center gap-2">{actions}</div>}
    </header>
  )
}
