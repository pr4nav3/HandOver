import type { ReactNode } from 'react'
import { MarkIcon } from './icons'

export type Route = 'community' | 'learn' | 'teach'

const MODES: { route: Route; label: string; href: string }[] = [
  { route: 'community', label: 'Community', href: '#/community' },
  { route: 'learn', label: 'Learn', href: '#/learn' },
  { route: 'teach', label: 'Teach', href: '#/teach' },
]

export function TopBar({ route, title, camera, children }: { route: Route; title?: string; camera?: string; children?: ReactNode }) {
  return (
    <header className="topbar">
      <div className="topbar-left">
        <a className="brand" href="#/community">
          <MarkIcon />
          HandOver
        </a>
        <nav className="modes" aria-label="Mode">
          {MODES.map((m) => (
            <a key={m.route} href={m.href} className={route === m.route ? 'on' : ''} aria-current={route === m.route ? 'page' : undefined}>
              {m.label}
            </a>
          ))}
        </nav>
        {title && <span className="topbar-title">{title}</span>}
      </div>
      <div className="topbar-right">
        {camera && (
          <span className="topbar-camera" title="Active camera">
            {camera}
          </span>
        )}
        {children}
      </div>
    </header>
  )
}
