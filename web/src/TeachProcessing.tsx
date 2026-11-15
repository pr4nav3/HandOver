import type { ReactNode } from 'react'
import type { JobStatus } from './api'
import { CheckFillIcon, CloseIcon, WarningIcon } from './icons'

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
  const failedAt = phase === 'error' ? (job ? at : 0) : -1
  const pct = total ? Math.floor((sent / total) * 100) : 0

  const rows = STAGES.filter((s) => s.key !== 'queued' || at === 1).map((s) => {
    const i = ORDER.indexOf(s.key)
    const state = i === failedAt ? 'bad' : i < at ? 'done' : i === at && phase !== 'error' ? 'active' : 'todo'
    const text = state === 'done' ? s.done || s.active : s.key === 'upload' && state === 'active' ? `Uploading ${pct}%` : s.active
    return (
      <li key={s.key} className={`stage ${state}`}>
        <span className="stage-mark">
          {state === 'done' ? (
            <CheckFillIcon size={20} />
          ) : state === 'active' ? (
            <span className="spinner" />
          ) : state === 'bad' ? (
            <span className="stage-bad">
              <CloseIcon size={11} />
            </span>
          ) : (
            <span className="stage-ring" />
          )}
        </span>
        <span className="stage-text">
          {text}
          {s.key === 'upload' && state === 'active' && (
            <span className="bar" role="progressbar" aria-valuenow={pct} aria-valuemin={0} aria-valuemax={100}>
              <span style={{ width: `${pct}%` }} />
            </span>
          )}
          {state === 'active' && s.key !== 'upload' && message && <span className="stage-note">{message}</span>}
        </span>
      </li>
    )
  })

  return (
    <section className={`panel process-card job ${phase}`} aria-live="polite">
      <div className="process-head">
        <p className="eyebrow">
          {phase === 'done' ? title : `${fileName}${fileSize ? `, ${sizeLabel(fileSize)}` : ''}`}
        </p>
        {phase === 'done' ? (
          <h2 className="ready-title">
            <CheckFillIcon size={22} />
            Your lesson is ready
          </h2>
        ) : (
          <h2>{title}</h2>
        )}
        {(phase === 'uploading' || phase === 'polling') && <p className="muted">HandOver is turning your video into steps.</p>}
      </div>
      {phase !== 'done' && <ul className="stages">{rows}</ul>}
      {phase === 'error' && (
        <p className="process-error" role="alert">
          <WarningIcon size={20} />
          <span>{error}</span>
        </p>
      )}
      {children}
    </section>
  )
}
