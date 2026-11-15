import type { Step } from './api'
import { CheckFillIcon, PlayIcon, Ring0Icon, SkippedIcon, TapIcon } from './icons'

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

function Glyph({ how, current }: { how: StepHow | null; current: boolean }) {
  const kind = current ? 'current' : (how ?? 'idle')
  return (
    <span className={`st ${kind}`} title={STATUS[kind]} aria-label={STATUS[kind]} role="img">
      {kind === 'current' ? (
        <PlayIcon size={20} />
      ) : kind === 'camera' ? (
        <CheckFillIcon size={20} />
      ) : kind === 'button' ? (
        <TapIcon size={20} />
      ) : kind === 'skipped' ? (
        <SkippedIcon size={20} />
      ) : (
        <Ring0Icon size={20} />
      )}
    </span>
  )
}

/** A small ring for "k of n done". */
function Ring({ done, total }: { done: number; total: number }) {
  const r = 8
  const c = 2 * Math.PI * r
  const f = total ? Math.min(1, done / total) : 0
  return (
    <svg className="steps-ring" width="22" height="22" viewBox="0 0 22 22" aria-hidden="true">
      <circle cx="11" cy="11" r={r} fill="none" stroke="var(--panel-2)" strokeWidth="3" />
      <circle
        cx="11"
        cy="11"
        r={r}
        fill="none"
        stroke={f >= 1 ? 'var(--green)' : 'var(--accent)'}
        strokeWidth="3"
        strokeLinecap="round"
        strokeDasharray={`${c * f} ${c}`}
        transform="rotate(-90 11 11)"
      />
    </svg>
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
      <div className="sl-head">
        <span className="sl-title">Steps</span>
        {steps.length > 0 && (
          <span className="sl-count">
            <Ring done={done} total={steps.length} />
            {done} of {steps.length} done
          </span>
        )}
      </div>
      <ol className="sl-rows">
        {steps.map((s, i) => (
          <li key={i}>
            <button
              type="button"
              className={`sl-row ${i === current ? 'current' : ''}`}
              aria-current={i === current ? 'step' : undefined}
              onClick={() => onPick(i)}
            >
              <Glyph how={runs[i]?.how ?? null} current={i === current} />
              <span className="sl-num">{i + 1}</span>
              <span className="sl-name">{s.title}</span>
            </button>
          </li>
        ))}
      </ol>
    </div>
  )
}
