import type { ReactNode } from 'react'

export type Route = 'community' | 'learn' | 'teach'

const MODES: { route: Route; label: string; href: string }[] = [
  { route: 'community', label: 'Lessons', href: '#/community' },
  { route: 'learn', label: 'Learn', href: '#/learn' },
  { route: 'teach', label: 'Teach', href: '#/teach' },
]

/**
 * 52px bar, hairline under it. Wordmark left; mode nav centered, followed by
 * the lesson title and camera when a screen passes them; `children` at right.
 */
export function TopBar({ route, title, camera, children }: { route: Route; title?: string; camera?: string; children?: ReactNode }) {
  return (
    <header className="topbar">
      <a className="brand" href="#/community">
        HandOver
      </a>
      <div className="topbar-mid">
        <nav className="modes" aria-label="Mode">
          {MODES.map((m) => (
            <a key={m.route} href={m.href} className={route === m.route ? 'on' : ''} aria-current={route === m.route ? 'page' : undefined}>
              {m.label}
            </a>
          ))}
        </nav>
        {(title || camera) && (
          <div className="topbar-meta">
            {title && <span className="topbar-title">{title}</span>}
            {camera && (
              <span className="topbar-camera" title="Active camera">
                {camera}
              </span>
            )}
          </div>
        )}
      </div>
      <div className="topbar-right">{children}</div>
    </header>
  )
}
