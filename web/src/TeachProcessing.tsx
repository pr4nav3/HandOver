import type { ReactNode } from 'react'
import type { JobStatus } from './api'

/*
 * Make lesson, processing (SCREENS 13), ported from the desktop teach view:
 * honest per-stage progress. A stage is done only when the hub says so; the
 * only percentage is the upload's own bytes sent.
 */

export type UploadPhase = 'uploading' | 'polling' | 'done' | 'error'

const STAGES: { key: string; active: string; done: string }[] = [
  { key: 'upload', active: 'Uploading', done: 'Uploaded' },
  { key: 'queued', active: 'Waiting for the hub', done: '' },
  { key: 'normalizing', active: 'Preparing video', done: 'Video prepared' },
  { key: 'extracting', active: 'Finding steps', done: 'Steps found' },
  { key: 'cutting', active: 'Cutting clips', done: 'Clips cut' },
]
const ORDER = ['upload', 'queued', 'normalizing', 'extracting', 'cutting', 'done']

export const sizeLabel = (b: number) => (b >= 1e6 ? `${(b / 1e6).toFixed(1)} MB` : `${Math.max(1, Math.round(b / 1e3))} KB`)

/** Two-digit numeral, the way the printed sheet numbers things. */
export const nn = (n: number) => String(n).padStart(2, '0')

/** Done: a small ink square with a white check. */
function DoneMark() {
  return (
    <svg className="stage-done" width="18" height="18" viewBox="0 0 18 18" aria-hidden="true">
      <rect width="18" height="18" rx="2" fill="currentColor" />
      <path d="m4.6 9.3 2.9 2.8 5.9-6" fill="none" stroke="#fff" strokeWidth="1.9" strokeLinecap="square" />
    </svg>
  )
}

export function ProcessCard({
  phase,
  title,
  fileName,
  fileSize,
  sent,
  total,
  job,
  status,
  message,
  error,
  children,
}: {
  phase: UploadPhase
  title: string
  fileName: string
  fileSize: number
  /** Upload bytes sent and total. */
  sent: number
  total: number
  /** The hub's job id; empty while uploading or when the upload itself failed. */
  job: string
  /** Last status the hub reported other than error. */
  status: JobStatus | null
  /** The hub's free text for the active stage. */
  message: string
  error: string
  children?: ReactNode
}) {
  const at = phase === 'uploading' ? 0 : phase === 'done' ? 5 : Math.max(1, ORDER.indexOf(status ?? 'queued'))
  const pct = total ? Math.floor((sent / total) * 100) : 0
  const fileLine = `${fileName}${fileSize ? `, ${sizeLabel(fileSize)}` : ''}`

  if (phase === 'error') {
    // No job id means the upload itself failed.
    const stopped = STAGES.find((s) => ORDER.indexOf(s.key) === (job ? at : 0))
    return (
      <section className="card teach-card process-card job error" aria-live="polite">
        <div className="process-head">
          <p className="process-eyebrow">{stopped ? `Stopped at ${stopped.active}` : 'Stopped'}</p>
          <h2 className="process-title">Could not make the lesson</h2>
        </div>
        <p className="process-error" role="alert">
          {error}
        </p>
        <p className="process-file">{fileLine}</p>
        {children}
      </section>
    )
  }

  if (phase === 'done') {
    return (
      <section className="card teach-card process-card job done" aria-live="polite">
        <div className="process-head">
          <p className="process-eyebrow">{title}</p>
          <h2 className="process-title">Your lesson is ready</h2>
        </div>
        {children}
      </section>
    )
  }

  const rows = STAGES.filter((s) => s.key !== 'queued' || at === 1).map((s, n) => {
    const i = ORDER.indexOf(s.key)
    const state = i < at ? 'done' : i === at ? 'active' : 'todo'
    const upload = s.key === 'upload' && state === 'active'
    return (
      <li key={s.key} className={`stage ${state}`}>
        <span className="stage-num">{nn(n + 1)}</span>
        <span className="stage-text">
          <span className="stage-name">{state === 'done' ? s.done || s.active : s.active}</span>
          {upload && (
            <span className="stage-upload">
              <span className="bar" role="progressbar" aria-valuenow={pct} aria-valuemin={0} aria-valuemax={100}>
                <span style={{ width: `${pct}%` }} />
              </span>
              <span className="stage-pct">{pct}%</span>
            </span>
          )}
          {state === 'active' && !upload && message && <span className="stage-note">{message}</span>}
        </span>
        <span className="stage-mark">
          {state === 'done' ? <DoneMark /> : state === 'active' ? <span className="spinner" /> : <span className="stage-ring" />}
        </span>
      </li>
    )
  })

  return (
    <section className={`card teach-card process-card job ${phase}`} aria-live="polite">
      <div className="process-head">
        <p className="process-eyebrow">Making your lesson</p>
        <h2 className="process-title">{title}</h2>
        <p className="process-file">{fileLine}</p>
      </div>
      <ol className="stages">{rows}</ol>
      {children}
    </section>
  )
}
