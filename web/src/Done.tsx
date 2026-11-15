import { Caps, pad2 } from './StepList'
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

/** The Done screen (SCREENS 8): a printed result sheet. Totals on the left, the step table on the right. */
export function Done({ summary: s, onRestart, onBack, disabled }: { summary: DoneSummary; onRestart: () => void; onBack: () => void; disabled?: boolean }) {
  const maxT = Math.max(1, ...s.rows.map((r) => Math.max(r.expertS, r.yourS ?? 0)))
  const howWord = (how: StepHow | null) =>
    how === 'camera' ? (s.mock ? 'Timer (mock)' : 'Checked by camera') : how === 'button' ? 'Marked done' : how === 'skipped' ? 'Skipped' : 'Not finished in order'
  return (
    <div className="done-screen finish">
      <div className="done-left">
        <h1 className="display done-title">
          <Caps>Lesson complete</Caps>
        </h1>
        {s.title && <p className="done-sub">{s.title}</p>}
        <dl className="card done-stats finish-stats">
          <div>
            <dd>{s.ms > 0 ? formatDuration(s.ms) : <span className="faint">None</span>}</dd>
            <dt>Your time</dt>
          </div>
          <div>
            <dd>{formatDuration(s.expertS * 1000)}</dd>
            <dt>Expert</dt>
          </div>
          <div>
            <dd>
              {s.camera}
              <span className="of"> of {s.cameraSteps}</span>
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
              <dd className="caution">{s.skipped}</dd>
              <dt>Skipped</dt>
            </div>
          )}
        </dl>
        {s.mock && <p className="done-note">Simulated checks: camera steps passed on a timer.</p>}
        <div className="done-actions">
          <button type="button" className="btn primary next" onClick={onRestart} disabled={disabled}>
            <Caps>Start over</Caps>
          </button>
          <button type="button" className="btn" onClick={onBack} disabled={disabled}>
            Back to lessons
          </button>
        </div>
      </div>

      <section className="done-right" aria-label="Steps">
        <h2 className="rule-head">
          <span>Steps</span>
          <span className="bd-legend" aria-hidden="true">
            <span className="key-exp">Expert</span>
            <span className="key-you">You</span>
          </span>
        </h2>
        <ol className="breakdown finish-steps">
          {s.rows.map((r) => (
            <li key={r.n} className="bd-row">
              <span className="bd-num">{pad2(r.n)}</span>
              <div className="bd-main">
                <p className="bd-title">
                  <span className="bd-name">{r.title}</span>
                  {r.mistakes > 0 && (
                    <span className="caution bd-mistakes">
                      {r.mistakes} {r.mistakes === 1 ? 'mistake' : 'mistakes'}
                    </span>
                  )}
                </p>
                <p className={`bd-meta how ${r.how ?? 'none'} ${s.mock ? 'mock' : ''}`}>{howWord(r.how)}</p>
              </div>
              <div className="bd-bars" aria-hidden="true">
                <span className="tb exp" style={{ width: `${(r.expertS / maxT) * 100}%` }} />
                <span
                  className={`tb you ${r.how === 'camera' && !s.mock ? 'good' : ''}`}
                  style={{ width: r.yourS === null ? 0 : `${(r.yourS / maxT) * 100}%` }}
                />
              </div>
              <span className="bd-times">
                <span title="Expert" className="exp">
                  {formatDuration(r.expertS * 1000)}
                </span>
                <span title="You" className="you">
                  {r.yourS === null ? 'None' : formatDuration(r.yourS * 1000)}
                </span>
              </span>
            </li>
          ))}
        </ol>
      </section>
    </div>
  )
}
