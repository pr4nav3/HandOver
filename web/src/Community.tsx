import { useCallback, useEffect, useState } from 'react'
import { listLessons, type LessonSummary } from './api'
import { go } from './App'
import { FilmIcon, GridIcon } from './icons'
import { TopBar } from './TopBar'

/** The first step's still, which the hub writes for every lesson. */
const coverUrl = (id: string) => `/lessons/${encodeURIComponent(id)}/frames/01.jpg`

type Load = { status: 'loading' } | { status: 'error' } | { status: 'ready'; lessons: LessonSummary[] }

export function Community() {
  const [load, setLoad] = useState<Load>({ status: 'loading' })

  const fetchLessons = useCallback(() => {
    setLoad({ status: 'loading' })
    listLessons()
      .then((lessons) => setLoad({ status: 'ready', lessons }))
      .catch(() => setLoad({ status: 'error' }))
  }, [])

  useEffect(fetchLessons, [fetchLessons])

  return (
    <div className="page community">
      <TopBar route="community" />
      <main className="page-body">
        <div className="page-inner">
          <header className="page-head">
            <div>
              <h1>Lessons</h1>
              <p className="page-sub">Pick a lesson and follow along. The camera watches and moves you to the next step.</p>
            </div>
            <div className="page-actions">
              <button type="button" className="secondary" onClick={() => go('teach')}>
                Teach a lesson
              </button>
            </div>
          </header>

          {load.status === 'loading' && (
            <div className="empty-state" role="status">
              <span className="spinner" />
              <p className="empty-message">Loading lessons</p>
            </div>
          )}

          {load.status === 'error' && (
            <div className="empty-state" role="alert">
              <p className="empty-title">Could not load lessons</p>
              <p className="empty-message">HandOver did not answer. Check that it is running, then try again.</p>
              <button type="button" className="secondary" onClick={fetchLessons}>
                Retry
              </button>
            </div>
          )}

          {load.status === 'ready' && load.lessons.length === 0 && (
            <div className="empty-state">
              <span className="empty-symbol">
                <GridIcon size={40} />
              </span>
              <p className="empty-title">No lessons yet. Teach one.</p>
              <p className="empty-message">Record a task once and HandOver cuts it into steps.</p>
              <button type="button" className="primary" onClick={() => go('teach')}>
                Teach a lesson
              </button>
            </div>
          )}

          {load.status === 'ready' && load.lessons.length > 0 && (
            <ul className="card-grid" aria-label="Lessons">
              {load.lessons.map((l) => (
                <li key={l.id}>
                  <LessonCard lesson={l} />
                </li>
              ))}
            </ul>
          )}
        </div>
      </main>
    </div>
  )
}

function LessonCard({ lesson }: { lesson: LessonSummary }) {
  const [broken, setBroken] = useState(false)
  const steps = lesson.steps
  return (
    <button type="button" className="lesson-card" onClick={() => go('learn', lesson.id)}>
      {broken ? (
        <span className="cover empty-cover">
          <FilmIcon />
        </span>
      ) : (
        <span className="cover">
          <img src={coverUrl(lesson.id)} alt="" loading="lazy" onError={() => setBroken(true)} />
        </span>
      )}
      <span className="lesson-card-text">
        <span className="lesson-card-title">{lesson.title || lesson.id}</span>
        <span className="lesson-card-meta">
          {steps} {steps === 1 ? 'step' : 'steps'}
        </span>
      </span>
    </button>
  )
}
