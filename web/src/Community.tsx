import { useCallback, useEffect, useState } from 'react'
import { listLessons, type LessonSummary } from './api'
import { go } from './App'
import { FilmIcon } from './icons'
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

  // The empty state carries the one primary button, so the head drops its own.
  const isEmpty = load.status === 'ready' && load.lessons.length === 0

  return (
    <div className="page community">
      <TopBar route="community" />
      <main className="page-body">
        <div className="page-inner">
          <header className="page-head">
            <div>
              <h1 className="display">Lessons</h1>
              <p className="page-sub">Recorded once by someone who knows how. Pick one, point a camera at your hands, and the lesson moves when you do.</p>
            </div>
            {!isEmpty && (
              <div className="page-actions">
                <button type="button" className="btn primary" onClick={() => go('teach')}>
                  + Teach a lesson
                </button>
              </div>
            )}
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
              <button type="button" className="btn" onClick={fetchLessons}>
                Retry
              </button>
            </div>
          )}

          {isEmpty && (
            <div className="empty-state">
              <p className="empty-title">No lessons yet</p>
              <p className="empty-message">Record a task once and HandOver cuts it into steps.</p>
              <button type="button" className="btn primary" onClick={() => go('teach')}>
                Teach one
              </button>
            </div>
          )}

          {load.status === 'ready' && load.lessons.length > 0 && (
            <ul className="card-grid" aria-label="Lessons">
              {load.lessons.map((l, i) => (
                <li key={l.id}>
                  <LessonCard lesson={l} index={i + 1} />
                </li>
              ))}
            </ul>
          )}
        </div>
      </main>
    </div>
  )
}

function LessonCard({ lesson, index }: { lesson: LessonSummary; index: number }) {
  const [broken, setBroken] = useState(false)
  const steps = lesson.steps
  const tab = <span className="tab cobalt">{String(index).padStart(2, '0')}</span>
  return (
    <button type="button" className="lesson-card" onClick={() => go('learn', lesson.id)}>
      {broken ? (
        <span className="cover empty-cover">
          <FilmIcon />
          {tab}
        </span>
      ) : (
        <span className="cover">
          <img src={coverUrl(lesson.id)} alt="" loading="lazy" onError={() => setBroken(true)} />
          {tab}
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
