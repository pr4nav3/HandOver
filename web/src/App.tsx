import { useEffect, useState } from 'react'
import { Community } from './Community'
import { Learn } from './Learn'
import { Teach } from './Teach'
import type { Route } from './TopBar'

/*
 * Hash router, three modes:
 *   #/community          the lesson grid (also the default for an empty or unknown hash)
 *   #/learn              the learn screen, learner picks a lesson there
 *   #/learn/<lessonId>   the learn screen for that lesson
 *   #/teach              upload a take
 *
 * Contract for Learn.tsx: call `useRoute()` and read `lessonId` (undefined on
 * plain #/learn). It is URL-decoded. Learn renders for both forms; App does not
 * remount Learn when only the lesson id changes, so Learn should react to
 * `lessonId` changing (an effect on it). Use `go('learn', id)` to switch lessons
 * and `go('community')` to leave.
 */

export type RouteState = { name: Route; lessonId?: string }

export function parseRoute(hash: string = location.hash): RouteState {
  const parts = hash.replace(/^#\/?/, '').split('/')
  const head = parts[0]
  if (head === 'teach') return { name: 'teach' }
  if (head === 'learn') {
    const id = parts.slice(1).join('/')
    if (!id) return { name: 'learn' }
    try {
      return { name: 'learn', lessonId: decodeURIComponent(id) }
    } catch {
      return { name: 'learn', lessonId: id }
    }
  }
  return { name: 'community' }
}

export function routeHash(name: Route, lessonId?: string): string {
  return name === 'learn' && lessonId ? `#/learn/${encodeURIComponent(lessonId)}` : `#/${name}`
}

/** Navigate: sets location.hash; every useRoute() re-renders from the hashchange. */
export function go(name: Route, lessonId?: string) {
  const next = routeHash(name, lessonId)
  if (location.hash !== next) location.hash = next
}

export function useRoute(): RouteState {
  const [route, setRoute] = useState<RouteState>(() => parseRoute())
  useEffect(() => {
    const onHash = () =>
      setRoute((prev) => {
        const next = parseRoute()
        return prev.name === next.name && prev.lessonId === next.lessonId ? prev : next
      })
    window.addEventListener('hashchange', onHash)
    return () => window.removeEventListener('hashchange', onHash)
  }, [])
  return route
}

export function App() {
  const route = useRoute()
  if (route.name === 'teach') return <Teach />
  if (route.name === 'learn') return <Learn />
  return <Community />
}
