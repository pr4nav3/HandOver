import type { ReactNode } from 'react'

export type Route = 'learn' | 'teach'

export function TopBar({ route, title, children }: { route: Route; title?: string; children?: ReactNode }) {
  return (
    <header className="topbar">
      <div className="topbar-left">
        <span className="brand">HandOver</span>
        {title && <span className="topbar-title">{title}</span>}
      </div>
      <div className="topbar-right">
        {children}
        <nav className="switch" aria-label="Mode">
          <a href="#/learn" className={route === 'learn' ? 'on' : ''} aria-current={route === 'learn' ? 'page' : undefined}>
            Learn
          </a>
          <a href="#/teach" className={route === 'teach' ? 'on' : ''} aria-current={route === 'teach' ? 'page' : undefined}>
            Teach
          </a>
        </nav>
      </div>
    </header>
  )
}
