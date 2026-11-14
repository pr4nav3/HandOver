import { useEffect, useState } from 'react'
import { Learn } from './Learn'
import { Teach } from './Teach'
import type { Route } from './TopBar'

function readRoute(): Route {
  return location.hash.startsWith('#/teach') ? 'teach' : 'learn'
}

export function App() {
  const [route, setRoute] = useState<Route>(readRoute)
  useEffect(() => {
    const onHash = () => setRoute(readRoute())
    window.addEventListener('hashchange', onHash)
    return () => window.removeEventListener('hashchange', onHash)
  }, [])
  return route === 'teach' ? <Teach /> : <Learn />
}
