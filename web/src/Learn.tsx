import { useCallback, useEffect, useRef, useState } from 'react'
import type { RefObject } from 'react'
import { getLesson, lessonUrl, listLessons, toSeconds } from './api'
import type { AdvanceMsg, CheckOfflineReason, Lesson, LessonSummary, Mistake, MistakeMsg, StateMsg } from './api'
import { playChime, unlockAudio } from './chime'
import { TopBar } from './TopBar'
import { useFitBox } from './useFitBox'
import { useUiSocket } from './useUiSocket'
import { useVoice, voiceSupported } from './useVoice'

// Checking shows as Watching: the server flips between the two often, and
// one visual state keeps the badge calm.
type Badge = 'watching' | 'verified' | 'manual' | 'done' | 'offline'

const BADGE_LABEL: Record<Badge, string> = {
  watching: 'Watching',
  verified: 'Verified',
  manual: 'Manual step',
  done: 'Done',
  offline: 'Checks off, use Next',
}

const OFFLINE_REASON: Record<CheckOfflineReason, string> = {
  no_key: 'No Gemini key',
  rate_limited: 'Rate limited',
  errors: 'Check errors',
}

// A check reason is shown only when the model was at least this sure (CONTRACT.md 7).
const REASON_MIN_CONF = 0.7

interface StepRow {
  n: number
  title: string
  expertS: number
  yourS: number | null
  how: 'camera' | 'hand' | null
}

interface Summary {
  ms: number
  expertS: number
  camera: number
  byHand: number
  mistakes: number
  rows: StepRow[]
}

export function Learn() {
  const [lessons, setLessons] = useState<LessonSummary[] | null>(null)
  const [picked, setPicked] = useState('')
  const [started, setStarted] = useState(false)
  const [state, setState] = useState<StateMsg | null>(null)
  const [lesson, setLesson] = useState<Lesson | null>(null)
  const [hasFrame, setHasFrame] = useState(false)
  // True after the camera drops, until its next frame: the last frame stays, dimmed.
  const [stale, setStale] = useState(false)
  // The mistake on screen, from a `mistake` message or state.mistake.
  const [mistake, setMistake] = useState<Mistake | null>(null)
  const startedRef = useRef(false)
  startedRef.current = started
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
    setStale(false)
  }, [])

  // For the done screen: when this run began, and how each step was finished.
  const runStart = useRef(0)
  const advancedBy = useRef(new Map<number, AdvanceMsg['reason']>())
  // Time spent on each step (summed if revisited), counted from state changes
  // so next, back, goto and camera advances are all covered.
  const spentMs = useRef(new Map<number, number>())
  const lastPos = useRef(0)
  const lastPosAt = useRef(0)
  const mistakeCount = useRef(0)
  const resetRun = () => {
    const now = performance.now()
    runStart.current = now
    advancedBy.current = new Map()
    spentMs.current = new Map()
    lastPos.current = 0
    lastPosAt.current = now
    mistakeCount.current = 0
    setMistake(null)
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
    // Per-step time: charge the time since the last change to the step we left.
    const pos = msg.status === 'done' ? msg.total : msg.step
    if (runStart.current && pos !== lastPos.current) {
      const now = performance.now()
      if (lastPos.current < msg.total) {
        const spent = spentMs.current
        spent.set(lastPos.current, (spent.get(lastPos.current) ?? 0) + now - lastPosAt.current)
      }
      lastPos.current = pos
      lastPosAt.current = now
    }
    // Older servers omit `mistake`; only an explicit value replaces ours.
    if (msg.mistake !== undefined) setMistake(msg.mistake)
    if (msg.lesson_id !== null) setResuming(false)
    else if (resumeId.current && !resentThisConnection.current) {
      resentThisConnection.current = true
      resumingRef.current = true
      setResuming(true)
      resetRun()
      sendRef.current({ type: 'select_lesson', id: resumeId.current })
    } else setResuming(false)
  }, [])

  // The catch: show the banner and say the message once.
  const onMistake = useCallback((msg: MistakeMsg) => {
    const { type: _type, ...m } = msg
    setMistake(m)
    if (!startedRef.current) return
    mistakeCount.current += 1
    if ('speechSynthesis' in window) {
      window.speechSynthesis.cancel()
      window.speechSynthesis.speak(new SpeechSynthesisUtterance(m.message))
    }
  }, [])

  const onOpen = useCallback(() => {
    resentThisConnection.current = false
  }, [])

  const { down, send } = useUiSocket({ onFrame, onState, onAdvance, onError, onMistake, onOpen })
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
    if (state && !state.camera_connected) setStale(true)
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

  // A mistake belongs to one step; it never outlives that step or the lesson.
  const activeMistake = mistake && !isDone && mistake.step === state?.step ? mistake : null
  const dismissMistake = () => {
    setMistake(null)
    send({ type: 'dismiss_mistake' })
  }
  const showStep = (to: number) => {
    setMistake(null)
    send({ type: 'goto', step: to })
  }

  // Freeze the summary the moment the lesson finishes.
  const [summary, setSummary] = useState<Summary | null>(null)
  useEffect(() => {
    if (!isDone) {
      setSummary(null)
      return
    }
    const reasons = [...advancedBy.current.values()]
    const camera = reasons.filter((r) => r === 'camera').length
    const rows: StepRow[] = steps.map((s, i) => {
      const spent = spentMs.current.get(i)
      const by = advancedBy.current.get(i)
      return {
        n: s.n || i + 1,
        title: s.title,
        expertS: Math.max(0, toSeconds(s.end) - toSeconds(s.start)),
        yourS: spent === undefined ? null : spent / 1000,
        how: by === undefined ? null : by === 'camera' ? 'camera' : 'hand',
      }
    })
    setSummary({
      ms: runStart.current ? performance.now() - runStart.current : 0,
      expertS: rows.reduce((a, r) => a + r.expertS, 0),
      camera,
      byHand: reasons.length - camera,
      mistakes: mistakeCount.current,
      rows,
    })
  }, [isDone])

  const offline = !!state?.check_offline
  const offlineReason = state?.check_offline_reason ? OFFLINE_REASON[state.check_offline_reason] : ''
  let badge: Badge = 'watching'
  if (isDone) badge = 'done'
  else if (flashVerified || state?.status === 'verified') badge = 'verified'
  else if (state?.status === 'manual' || step?.check_type === 'manual') badge = 'manual'
  else if (offline) badge = 'offline'

  // Small text beside the badge: why checks are off, or the last check's latency and reason.
  const cameraStep = !!step && step.check_type !== 'manual' && !isDone
  const lc = state?.last_check
  let metaTop = ''
  let metaBottom = ''
  if (badge === 'offline') metaTop = offlineReason
  else if (badge === 'watching' && cameraStep && state?.camera_connected && lc) {
    metaTop = `last check ${(lc.latency_ms / 1000).toFixed(1)} s`
    if (lc.reason && lc.done === 'no' && lc.confidence >= REASON_MIN_CONF) metaBottom = lc.reason
  }

  // A frozen frame while the socket is down would mislead, so show the placeholder.
  // A camera that drops after sending frames leaves its last frame, dimmed.
  const showLive = !down && hasFrame && (!!state?.camera_connected || stale)
  const cameraLost = showLive && (stale || !state?.camera_connected)
  const recording = showLive && !cameraLost && state?.camera?.source === 'file'
  const cameraName = !down && state?.camera_connected ? state?.camera?.name : undefined

  // Before start, or when the server has no lesson (restart, lesson gone) and
  // no resume is in flight, the learner picks one.
  const showPicker = !started || (!!state && !state.lesson_id && !resuming)

  return (
    <div className="page learn">
      <div className="progress" role="progressbar" aria-valuemin={0} aria-valuemax={total} aria-valuenow={isDone ? total : idx}>
        {Array.from({ length: Math.max(total, 1) }, (_, i) => {
          let cls = !total ? 'upcoming' : isDone || i < idx ? 'done' : i === idx ? 'current' : 'upcoming'
          if (i === idx && activeMistake?.kind === 'behind') cls = 'mistake'
          return <span key={i} className={`seg ${cls}`} />
        })}
      </div>

      <TopBar route="learn" title={lesson?.title} camera={cameraName}>
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
          <img ref={liveRef} alt="Live camera" className={showLive ? (cameraLost ? 'lost' : '') : 'hidden'} />
          {cameraLost && (
            <p className="live-note" role="status">
              Camera lost. Keep going with Next.
            </p>
          )}
          {recording && (
            <span className="rec" title="Frames come from a recorded video, not a live camera">
              <span className="rec-dot" />
              Recording
            </span>
          )}
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
          {activeMistake && (
            <div className="mistake-banner" role="alert">
              <p className="mistake-text">{activeMistake.message}</p>
              <div className="mistake-actions">
                {activeMistake.kind === 'behind' ? (
                  <>
                    <button type="button" className="ghost small" onClick={() => showStep(activeMistake.looks_like)}>
                      Show step {activeMistake.looks_like + 1}
                    </button>
                    <button type="button" className="ghost small" onClick={dismissMistake}>
                      I'm fine
                    </button>
                  </>
                ) : (
                  <button type="button" className="ghost small" onClick={dismissMistake}>
                    OK
                  </button>
                )}
              </div>
            </div>
          )}
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
                        <dt>Your time</dt>
                        <dd>{formatDuration(summary.ms)}</dd>
                      </div>
                    )}
                    {summary.expertS > 0 && (
                      <div>
                        <dt>Expert</dt>
                        <dd className="muted">{formatDuration(summary.expertS * 1000)}</dd>
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
                    <div>
                      <dt>Mistakes caught</dt>
                      <dd>{summary.mistakes}</dd>
                    </div>
                  </dl>
                  {summary.rows.length > 0 && (
                    <table className="finish-steps">
                      <thead>
                        <tr>
                          <th />
                          <th>Step</th>
                          <th>Expert</th>
                          <th>You</th>
                        </tr>
                      </thead>
                      <tbody>
                        {summary.rows.map((r) => (
                          <tr key={r.n}>
                            <td className="how" title={r.how === 'camera' ? 'Checked by camera' : r.how === 'hand' ? 'Marked done' : 'Not finished in order'}>
                              {r.how === 'camera' ? <SmallCameraIcon /> : r.how === 'hand' ? <HandIcon /> : null}
                            </td>
                            <td className="name">
                              <span className="num">{r.n}</span> {r.title}
                            </td>
                            <td className="muted">{formatSecs(r.expertS)}</td>
                            <td>{r.yourS === null ? '\u2013' : formatSecs(r.yourS)}</td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  )}
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
            <div className="badge-wrap">
              <span
                className={`badge ${badge} ${state?.camera_connected ? 'live' : ''}`}
                aria-live="polite"
                title={badge === 'offline' && offlineReason ? offlineReason : undefined}
              >
                <span className="badge-dot" />
                {BADGE_LABEL[badge]}
              </span>
              <span className="check-meta">
                <span>{metaTop}</span>
                <span className="check-reason">{metaBottom}</span>
              </span>
            </div>
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

/** Seconds as "12 s" under a minute, else "1:05". */
function formatSecs(s: number) {
  return s < 59.5 ? `${Math.round(s)} s` : formatDuration(s * 1000)
}

function SmallCameraIcon() {
  return (
    <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" aria-label="Camera">
      <path d="M3 8.5A2.5 2.5 0 0 1 5.5 6h1.3l1.4-2h7.6l1.4 2h1.3A2.5 2.5 0 0 1 21 8.5v9a2.5 2.5 0 0 1-2.5 2.5h-13A2.5 2.5 0 0 1 3 17.5z" />
      <circle cx="12" cy="13" r="3.6" />
    </svg>
  )
}

function HandIcon() {
  return (
    <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" aria-label="By hand">
      <path d="M8 13V5.5a1.5 1.5 0 0 1 3 0V12m0-1.5v-6a1.5 1.5 0 0 1 3 0V12m0-5.5a1.5 1.5 0 0 1 3 0V14a7 7 0 0 1-7 7h-.5a6 6 0 0 1-4.9-2.5L3.3 15a1.5 1.5 0 0 1 2.4-1.8L8 15.5" />
    </svg>
  )
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
