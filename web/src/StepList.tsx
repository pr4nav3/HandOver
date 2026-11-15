import type { Step } from './api'

/** How a step was finished in this run: by a camera check, by Next, or passed over. */
export type StepHow = 'camera' | 'button' | 'skipped'

/** One step of the current run, kept by Learn.tsx from advance and state messages. */
export interface StepRun {
  how: StepHow | null
  /** Time spent on the step, summed over visits. */
  ms: number
  /** Distinct mistakes caught on the step. */
  mistakes: number
}

export const emptyRun = (): StepRun => ({ how: null, ms: 0, mistakes: 0 })

const STATUS: Record<StepHow | 'current' | 'idle', string> = {
  current: 'Current',
  camera: 'Checked by camera',
  button: 'Marked done',
  skipped: 'Skipped',
  idle: 'Not started',
}

/** 4 to "04": step numbers read like a printed procedure. */
export const pad2 = (n: number) => String(n).padStart(2, '0')

/**
 * Text drawn in capitals while the DOM keeps its sentence case, so innerText,
 * copy and paste, screen readers and the e2e checks all see "Start over", not
 * "START OVER" (Chromium's innerText applies text-transform). The capitals come
 * from `data-caps` in a ::before (learn.css); the real text sits visually
 * hidden beside it. `show` draws a different string (e.g. zero padded).
 */
export function Caps({ children, show }: { children: string; show?: string }) {
  return (
    <span className="caps" data-caps={show ?? children}>
      <span className="caps-src">{children}</span>
    </span>
  )
}

/**
 * The lesson's steps with this run's status (DESIGN 3.20). `current` is the
 * 0-based step on screen, or -1 when none is. Clicking a row calls `onPick`.
 */
export function StepList({
  steps,
  runs,
  current,
  onPick,
}: {
  steps: Step[]
  runs: StepRun[]
  current: number
  onPick: (i: number) => void
}) {
  const done = runs.filter((r) => r && (r.how === 'camera' || r.how === 'button')).length
  return (
    <div className="sl">
      <div className="rule-head sl-head">
        <span className="sl-title">Steps</span>
        {steps.length > 0 && (
          <span className="sl-count" aria-label={`${done} of ${steps.length} done`}>
            {done} / {steps.length}
          </span>
        )}
      </div>
      <ol className="sl-rows">
        {steps.map((s, i) => {
          const how = runs[i]?.how ?? null
          const kind = i === current ? 'current' : (how ?? 'idle')
          const state = kind === 'camera' || kind === 'button' ? 'done' : kind
          return (
            <li key={i}>
              <button
                type="button"
                className={`sl-row ${state}`}
                aria-current={i === current ? 'step' : undefined}
                title={STATUS[kind]}
                onClick={() => onPick(i)}
              >
                <span className="sl-num">{pad2(i + 1)}</span>
                <span className="sl-name">{s.title}</span>
                <span className="sr-only"> ({STATUS[kind]})</span>
              </button>
            </li>
          )
        })}
      </ol>
    </div>
  )
}
