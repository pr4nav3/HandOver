import { CheckFillIcon, SkippedIcon, TapIcon } from './icons'
import type { StepHow } from './StepList'

export interface DoneRow {
  n: number
  title: string
  /** Length of the expert's clip for this step. */
  expertS: number
  /** Time this run spent on the step; null when it got none. */
  yourS: number | null
  how: StepHow | null
  mistakes: number
}

/** Frozen when the lesson finishes. Every number comes from this run's real events. */
export interface DoneSummary {
  title: string
  /** Run length, start to done; 0 when unknown (joined mid run). */
  ms: number
  expertS: number
  /** Steps finished by a camera check, and how many steps are camera steps. */
  camera: number
  cameraSteps: number
  byButton: number
  skipped: number
  mistakes: number
  /** Mock checks pass on a timer and never look at the camera. */
  mock: boolean
  rows: DoneRow[]
}

/** 75000 ms to "1:15", 3725000 ms to "1:02:05". */
export function formatDuration(ms: number) {
  const total = Math.round(ms / 1000)
  const h = Math.floor(total / 3600)
  const m = Math.floor((total % 3600) / 60)
  const sec = String(total % 60).padStart(2, '0')
  return h ? `${h}:${String(m).padStart(2, '0')}:${sec}` : `${m}:${sec}`
}

/** The Done screen (SCREENS 8, without the score and best and weakest cards). */
export function Done({ summary: s, onRestart, onBack, disabled }: { summary: DoneSummary; onRestart: () => void; onBack: () => void; disabled?: boolean }) {
  const maxT = Math.max(1, ...s.rows.map((r) => Math.max(r.expertS, r.yourS ?? 0)))
  const howWord = (how: StepHow | null) =>
    how === 'camera' ? (s.mock ? 'Timer (mock)' : 'Checked by camera') : how === 'button' ? 'Marked done' : how === 'skipped' ? 'Skipped' : 'Not finished in order'
  return (
    <div className="done-screen finish">
      <div className="done-left">
        <h1 className="done-title">Lesson complete</h1>
        {s.title && <p className="done-sub">{s.title}</p>}
        <dl className="done-stats finish-stats">
          <div>
            <dd>{s.ms > 0 ? formatDuration(s.ms) : <span className="faint">No time</span>}</dd>
            <dt>Your time</dt>
          </div>
          <div>
            <dd>{formatDuration(s.expertS * 1000)}</dd>
            <dt>Expert</dt>
          </div>
          <div>
            <dd>
              {s.camera} of {s.cameraSteps}
            </dd>
            <dt>{s.mock ? 'By timer (mock)' : 'Checked by camera'}</dt>
          </div>
          <div>
            <dd>{s.byButton}</dd>
            <dt>Marked done</dt>
          </div>
          <div>
            <dd className={s.mistakes ? 'caution' : ''}>{s.mistakes}</dd>
            <dt>Mistakes caught</dt>
          </div>
          {s.skipped > 0 && (
            <div>
              <dd>{s.skipped}</dd>
              <dt>Skipped</dt>
            </div>
          )}
        </dl>
        {s.mock && <p className="done-note">Simulated checks: camera steps passed on a timer.</p>}
        <div className="done-actions">
          <button type="button" className="primary large next" onClick={onRestart} disabled={disabled}>
            Start over
          </button>
          <button type="button" className="secondary large" onClick={onBack} disabled={disabled}>
            Back to lessons
          </button>
        </div>
      </div>

      <section className="done-right card" aria-label="Steps">
        <h2>Steps</h2>
        <ol className="breakdown finish-steps">
          {s.rows.map((r) => (
            <li key={r.n} className="bd-row">
              <span className="bd-num">{r.n}</span>
              <div className="bd-main">
                <p className="bd-title">
                  <span className="bd-name">{r.title}</span>
                  {r.mistakes > 0 && (
                    <span className="caution bd-mistakes">
                      {r.mistakes} {r.mistakes === 1 ? 'mistake' : 'mistakes'}
                    </span>
                  )}
                </p>
                <div className="bd-bars" aria-hidden="true">
                  <span className="tb exp" style={{ width: `${(r.expertS / maxT) * 100}%` }} />
                  {r.yourS !== null && <span className={`tb you ${r.how === 'camera' && !s.mock ? 'good' : ''}`} style={{ width: `${(r.yourS / maxT) * 100}%` }} />}
                </div>
                <p className={`bd-meta how ${r.how ?? 'none'} ${s.mock ? 'mock' : ''}`}>
                  {r.how === 'camera' && !s.mock ? (
                    <CheckFillIcon size={15} />
                  ) : r.how === 'button' ? (
                    <TapIcon size={15} />
                  ) : r.how === 'skipped' ? (
                    <SkippedIcon size={15} />
                  ) : null}
                  {howWord(r.how)}
                </p>
              </div>
              <span className="bd-times">
                <span title="You">{r.yourS === null ? 'No time' : formatDuration(r.yourS * 1000)}</span>
                <span className="faint" title="Expert">
                  {formatDuration(r.expertS * 1000)}
                </span>
              </span>
            </li>
          ))}
        </ol>
      </section>
    </div>
  )
}
