import { useCallback, useEffect, useRef, useState } from 'react'
import type { RefObject } from 'react'
import { getLesson, lessonUrl, listLessons } from './api'
import type { AdvanceMsg, Lesson, LessonSummary, StateMsg } from './api'
import { playChime, unlockAudio } from './chime'
import { TopBar } from './TopBar'
import { useFitBox } from './useFitBox'
import { useUiSocket } from './useUiSocket'
import { useVoice, voiceSupported } from './useVoice'

// Checking shows as Watching: the server flips between the two often, and
// one visual state keeps the badge calm.
type Badge = 'watching' | 'verified' | 'manual' | 'done'

const BADGE_LABEL: Record<Badge, string> = {
  watching: 'Watching',
  verified: 'Verified',
  manual: 'Manual step',
  done: 'Done',
}

export function Learn() {
  const [lessons, setLessons] = useState<LessonSummary[] | null>(null)
  const [picked, setPicked] = useState('')
  const [started, setStarted] = useState(false)
  const [state, setState] = useState<StateMsg | null>(null)
  const [lesson, setLesson] = useState<Lesson | null>(null)
  const [hasFrame, setHasFrame] = useState(false)
  const [flashVerified, setFlashVerified] = useState(false)
  // Voice is off until the learner turns it on (quiet rooms only, see docs/SCOPE.md).
  const [voiceOn, setVoiceOn] = useState(false)
  // True between re-sending select_lesson after a reconnect and the server's answer.
  const [resuming, setResuming] = useState(false)
  const resumingRef = useRef(false)
  resumingRef.current = resuming

  const liveRef = useRef<HTMLImageElement>(null)
  const frameUrl = useRef<string | null>(null)
  const videoRef = useRef<HTMLVideoElement>(null)
  const clipAreaRef = useRef<HTMLDivElement>(null)
  const [aspect, setAspect] = useState(16 / 9)
  const infoRef = useRef<HTMLDivElement>(null)
  const gridRef = useRef<HTMLElement>(null)
  const controlsRef = useRef<HTMLDivElement>(null)
  const sideWidth = useSideWidth(gridRef, aspect, infoRef, controlsRef)
  const clipBox = useFitBox(clipAreaRef, aspect, infoRef, CLIP_GAP)
  const flashTimer = useRef<number | undefined>(undefined)
  const [serverError, setServerError] = useState('')
  const errorTimer = useRef<number | undefined>(undefined)

  // Live frames go straight to the <img> so React does not re-render per frame.
  const onFrame = useCallback((jpeg: Blob) => {
    const url = URL.createObjectURL(jpeg)
    const img = liveRef.current
    if (img) img.src = url
    if (frameUrl.current) URL.revokeObjectURL(frameUrl.current)
    frameUrl.current = url
    setHasFrame(true)
  }, [])

  // For the done screen: when this run began, and how each step was finished.
  const runStart = useRef(0)
  const advancedBy = useRef(new Map<number, AdvanceMsg['reason']>())
  const resetRun = () => {
    runStart.current = performance.now()
    advancedBy.current = new Map()
    // A Verified flash from the previous run should not carry into the new one.
    window.clearTimeout(flashTimer.current)
    setFlashVerified(false)
  }

  const onAdvance = useCallback((msg: AdvanceMsg) => {
    if (msg.to > msg.from) advancedBy.current.set(msg.from, msg.reason)
    if (msg.reason !== 'camera') return
    playChime()
    setFlashVerified(true)
    window.clearTimeout(flashTimer.current)
    flashTimer.current = window.setTimeout(() => setFlashVerified(false), 1800)
  }, [])

  // If the server restarts mid lesson it comes back with no lesson; pick ours
  // again, once per connection. `resumeId` is the lesson the learner started.
  const resumeId = useRef<string | null>(null)
  const resentThisConnection = useRef(false)
  const sendRef = useRef<(m: object) => void>(() => {})

  // Server errors (bad lesson id, command with no lesson) show briefly in the top bar.
  const onError = useCallback((message: string) => {
    // A failed resume (lesson gone) falls back to the picker.
    if (resumingRef.current) {
      resumeId.current = null
      setResuming(false)
    }
    setServerError(message || 'Something went wrong')
    window.clearTimeout(errorTimer.current)
    errorTimer.current = window.setTimeout(() => setServerError(''), 4000)
  }, [])

  const onState = useCallback((msg: StateMsg) => {
    setState(msg)
    if (msg.lesson_id !== null) setResuming(false)
    else if (resumeId.current && !resentThisConnection.current) {
      resentThisConnection.current = true
      resumingRef.current = true
      setResuming(true)
      resetRun()
      sendRef.current({ type: 'select_lesson', id: resumeId.current })
    } else setResuming(false)
  }, [])

  const onOpen = useCallback(() => {
    resentThisConnection.current = false
  }, [])

  const { down, send } = useUiSocket({ onFrame, onState, onAdvance, onError, onOpen })
  sendRef.current = send

  useEffect(
    () => () => {
      window.clearTimeout(flashTimer.current)
      window.clearTimeout(errorTimer.current)
      if (frameUrl.current) URL.revokeObjectURL(frameUrl.current)
    },
    [],
  )

  // Lesson list for the picker.
  useEffect(() => {
    listLessons()
      .then(setLessons)
      .catch(() => setLessons([]))
  }, [])

  // Default the picker to the server's lesson, else the first one.
  useEffect(() => {
    if (picked || !lessons?.length) return
    const current = state?.lesson_id && lessons.find((l) => l.id === state.lesson_id)
    setPicked(current ? current.id : lessons[0].id)
  }, [lessons, state?.lesson_id, picked])

  // Fetch the full lesson whenever the server switches lessons or recuts it.
  const lessonId = state?.lesson_id ?? null
  const rev = state?.rev ?? 0
  useEffect(() => {
    if (!lessonId) {
      setLesson(null)
      return
    }
    let live = true
    getLesson(lessonId)
      .then((l) => live && setLesson(l))
      .catch(() => live && setLesson(null))
    return () => {
      live = false
    }
  }, [lessonId, rev])

  useEffect(() => {
    if (state && !state.camera_connected) setHasFrame(false)
  }, [state?.camera_connected])

  const steps = lesson?.steps ?? []
  const total = steps.length || state?.total || 0
  const isDone = state?.status === 'done'
  const idx = Math.max(0, Math.min(state?.step ?? 0, steps.length - 1))
  const step = steps.length ? steps[idx] : null

  // Load the clip and its captions on every step change. Done imperatively
  // so the <video> element stays put (no layout jump) and the caption track
  // is guaranteed to reload.
  // Reloads only when the clip URL (path or rev) changes, never on other
  // re-renders, so playback position is not reset under the learner.
  const clipKey = lesson && step ? lessonUrl(lesson.id, step.clip, rev) : ''
  const loadedClip = useRef('')
  useEffect(() => {
    const video = videoRef.current
    if (!video || !lesson || !step || loadedClip.current === clipKey) return
    loadedClip.current = clipKey
    // Disable the old track first so its last cue does not linger over the new clip.
    video.querySelectorAll('track').forEach((t) => {
      t.track.mode = 'disabled'
      t.remove()
    })
    const track = document.createElement('track')
    track.kind = 'captions'
    track.srclang = 'en'
    track.label = 'English'
    track.default = true
    track.src = lessonUrl(lesson.id, step.captions, rev)
    video.appendChild(track)
    track.track.mode = 'showing'
    video.src = clipKey
    video.load()
    if (started && !isDone) video.play().catch(() => {})
  }, [clipKey, started, isDone])

  // Play once started, and stop the last clip looping on the done screen.
  useEffect(() => {
    const video = videoRef.current
    if (!video || !started || !video.src) return
    if (isDone) video.pause()
    else video.play().catch(() => {})
  }, [started, isDone])

  // `from` is the step on screen, so the server drops a tap or "next" that
  // races a camera advance instead of skipping a step.
  const shownStep = state?.step ?? 0
  const next = useCallback(
    (reason: 'button' | 'voice') => {
      if (lessonId && !isDone) send({ type: 'next', reason, from: shownStep })
    },
    [send, lessonId, isDone, shownStep],
  )
  const back = useCallback(() => {
    if (lessonId) send({ type: 'back', from: shownStep })
  }, [send, lessonId, shownStep])

  // The expert's narration through the speakers can sound like a command.
  const clipAudible = useCallback(() => {
    const v = videoRef.current
    return !!v && !v.paused && !v.muted && v.volume > 0
  }, [])
  const { listening } = useVoice(started && voiceOn, (cmd) => (cmd === 'next' ? next('voice') : back()), clipAudible)
  const voiceAvailable = started && voiceSupported()

  // Keyboard: Right or Space for next, Left for back.
  useEffect(() => {
    if (!started) return
    const onKey = (e: KeyboardEvent) => {
      if (e.target instanceof HTMLInputElement || e.target instanceof HTMLSelectElement) return
      if (e.key === 'ArrowRight' || e.key === ' ') {
        e.preventDefault()
        next('button')
      } else if (e.key === 'ArrowLeft') {
        e.preventDefault()
        back()
      }
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [started, next, back])

  const start = () => {
    unlockAudio()
    if (picked) {
      send({ type: 'select_lesson', id: picked })
      resumeId.current = picked
      resentThisConnection.current = false
      resetRun()
    }
    setStarted(true)
  }

  const restart = () => {
    resetRun()
    send({ type: 'goto', step: 0 })
  }

  // Freeze the summary the moment the lesson finishes.
  const [summary, setSummary] = useState<{ ms: number; camera: number; byHand: number } | null>(null)
  useEffect(() => {
    if (!isDone) {
      setSummary(null)
      return
    }
    const reasons = [...advancedBy.current.values()]
    const camera = reasons.filter((r) => r === 'camera').length
    setSummary({ ms: runStart.current ? performance.now() - runStart.current : 0, camera, byHand: reasons.length - camera })
  }, [isDone])

  let badge: Badge = 'watching'
  if (isDone) badge = 'done'
  else if (flashVerified || state?.status === 'verified') badge = 'verified'
  else if (state?.status === 'manual' || step?.check_type === 'manual') badge = 'manual'

  // A frozen frame while the socket is down would mislead, so show the placeholder.
  const showLive = !down && !!state?.camera_connected && hasFrame

  // Before start, or when the server has no lesson (restart, lesson gone) and
  // no resume is in flight, the learner picks one.
  const showPicker = !started || (!!state && !state.lesson_id && !resuming)

  return (
    <div className="page learn">
      <div className="progress" role="progressbar" aria-valuemin={0} aria-valuemax={total} aria-valuenow={isDone ? total : idx}>
        {Array.from({ length: Math.max(total, 1) }, (_, i) => {
          const cls = !total ? 'upcoming' : isDone || i < idx ? 'done' : i === idx ? 'current' : 'upcoming'
          return <span key={i} className={`seg ${cls}`} />
        })}
      </div>

      <TopBar route="learn" title={lesson?.title}>
        {serverError && !down && (
          <span className="note error" role="status">
            {serverError}
          </span>
        )}
        {down && <span className="note">Reconnecting</span>}
        {voiceAvailable && (
          <button
            type="button"
            className={`mic ${voiceOn ? 'armed' : ''} ${listening ? 'on' : ''}`}
            onClick={() => setVoiceOn((v) => !v)}
            aria-pressed={voiceOn}
            aria-label="Voice commands"
            title={voiceOn ? (listening ? 'Listening for "next" and "back". Click to turn off.' : 'Starting microphone') : 'Voice off. Click to listen for "next" and "back".'}
          >
            <MicIcon />
          </button>
        )}
      </TopBar>

      <main className="learn-grid" ref={gridRef} style={sideWidth ? { gridTemplateColumns: `minmax(0, 1fr) ${sideWidth}px` } : undefined}>
        <section className="panel live" aria-label="Live camera">
          <img ref={liveRef} alt="Live camera" className={showLive ? '' : 'hidden'} />
          {!showLive && (
            <div className="placeholder">
              <CameraIcon />
              <p className="placeholder-title">Waiting for camera</p>
              <p className="placeholder-hint">
                Open <code>/capture</code> on the phone
              </p>
            </div>
          )}
        </section>

        <section className="side">
          <div className="clip-area" ref={clipAreaRef}>
            <div className="panel clip" style={clipBox ? { width: clipBox.w, height: clipBox.h } : undefined}>
              <video
                ref={videoRef}
                loop
                playsInline
                preload="auto"
                className={step && !isDone ? '' : 'hidden'}
                onLoadedMetadata={(e) => {
                  const v = e.currentTarget
                  if (v.videoWidth && v.videoHeight) setAspect(v.videoWidth / v.videoHeight)
                }}
              />
              {isDone && summary && (
                <div className="finish">
                  <CheckIcon />
                  <p className="finish-title">Lesson complete</p>
                  <dl className="finish-stats">
                    {summary.ms > 0 && (
                      <div>
                        <dt>Time</dt>
                        <dd>{formatDuration(summary.ms)}</dd>
                      </div>
                    )}
                    <div>
                      <dt>Checked by camera</dt>
                      <dd>{summary.camera}</dd>
                    </div>
                    <div>
                      <dt>Marked done</dt>
                      <dd>{summary.byHand}</dd>
                    </div>
                  </dl>
                  <button type="button" className="ghost restart" onClick={restart}>
                    Start over
                  </button>
                </div>
              )}
              {!step && (
                <div className="placeholder">
                  <p className="placeholder-title">{lessons?.length === 0 ? 'No lessons yet' : 'No lesson selected'}</p>
                </div>
              )}
            </div>

            <div className="step-info" ref={infoRef}>
              <p className="step-count">{step ? (isDone ? 'All steps complete' : `Step ${idx + 1} of ${total}`) : ' '}</p>
              <h1 className="step-title">{step ? (isDone ? lesson?.title : step.title) : ' '}</h1>
            </div>
          </div>

          <div className="controls" ref={controlsRef}>
            <span className={`badge ${badge} ${state?.camera_connected ? 'live' : ''}`} aria-live="polite">
              <span className="badge-dot" />
              {BADGE_LABEL[badge]}
            </span>
            <div className="next-wrap">
              <button className="next" onClick={() => next('button')} disabled={!step || isDone}>
                Next
              </button>
              {!isDone && <span className="next-hint">{voiceOn && listening ? 'or say next' : 'or press \u2192'}</span>}
            </div>
          </div>
        </section>
      </main>

      {showPicker && (
        <div className="overlay">
          <div className="start-card">
            <p className="start-eyebrow">HandOver</p>
            <h2>{started ? 'Pick a lesson' : 'Ready when you are'}</h2>
            <label className="field">
              <span>Lesson</span>
              <select value={picked} onChange={(e) => setPicked(e.target.value)} disabled={!lessons?.length}>
                {lessons === null && <option value="">Loading</option>}
                {lessons?.length === 0 && <option value="">No lessons yet</option>}
                {lessons?.map((l) => (
                  <option key={l.id} value={l.id}>
                    {l.title} ({l.steps} steps)
                  </option>
                ))}
              </select>
            </label>
            <button className="primary" onClick={start} disabled={!picked}>
              Start lesson
            </button>
            <p className="start-hint">
              {lessons?.length === 0 ? (
                <>
                  Create one in <a href="#/teach">Teach</a>.
                </>
              ) : (
                'Turns on sound. Voice commands are off until you click the mic.'
              )}
            </p>
          </div>
        </div>
      )}
    </div>
  )
}

// Gap between the clip and the step title; matches .clip-area in styles.css.
const CLIP_GAP = 18
// Gap between the clip area and the controls; matches .side in styles.css.
const SIDE_GAP = 18
// Share of the grid width the right column may take.
const MIN_SIDE = 0.4
const MAX_SIDE = 0.55

/**
 * Width of the right column so the clip, at its aspect ratio, uses the
 * height left after the title and controls, within MIN_SIDE and MAX_SIDE of
 * the grid width so the live camera keeps a fair share.
 */
function useSideWidth(
  gridRef: RefObject<HTMLElement | null>,
  aspect: number,
  infoRef: RefObject<HTMLElement | null>,
  controlsRef: RefObject<HTMLElement | null>,
) {
  const [width, setWidth] = useState<number | null>(null)
  useEffect(() => {
    const grid = gridRef.current
    if (!grid) return
    const measure = () => {
      const { width: w, height: h } = grid.getBoundingClientRect()
      const colGap = parseFloat(getComputedStyle(grid).columnGap) || 0
      const room = w - colGap
      const reserved = (infoRef.current?.offsetHeight ?? 0) + CLIP_GAP + SIDE_GAP + (controlsRef.current?.offsetHeight ?? 0)
      const wanted = (h - reserved) * aspect
      if (!room || h <= reserved) return
      setWidth(Math.round(Math.min(room * MAX_SIDE, Math.max(room * MIN_SIDE, wanted))))
    }
    measure()
    const ro = new ResizeObserver(measure)
    ro.observe(grid)
    if (infoRef.current) ro.observe(infoRef.current)
    return () => ro.disconnect()
  }, [gridRef, aspect, infoRef, controlsRef])
  return width
}

/** 75000 ms to "1:15", 3725000 ms to "1:02:05". */
function formatDuration(ms: number) {
  const total = Math.round(ms / 1000)
  const h = Math.floor(total / 3600)
  const m = Math.floor((total % 3600) / 60)
  const sec = String(total % 60).padStart(2, '0')
  return h ? `${h}:${String(m).padStart(2, '0')}:${sec}` : `${m}:${sec}`
}

function CheckIcon() {
  return (
    <svg width="36" height="36" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
      <circle cx="12" cy="12" r="9.5" />
      <path d="m7.8 12.3 2.8 2.8 5.6-5.8" />
    </svg>
  )
}

function CameraIcon() {
  return (
    <svg width="40" height="40" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.4" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
      <path d="M3 8.5A2.5 2.5 0 0 1 5.5 6h1.3l1.4-2h7.6l1.4 2h1.3A2.5 2.5 0 0 1 21 8.5v9a2.5 2.5 0 0 1-2.5 2.5h-13A2.5 2.5 0 0 1 3 17.5z" />
      <circle cx="12" cy="13" r="3.6" />
    </svg>
  )
}

function MicIcon() {
  return (
    <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
      <rect x="9" y="3" width="6" height="11" rx="3" />
      <path d="M5 11a7 7 0 0 0 14 0M12 18v3" />
    </svg>
  )
}
