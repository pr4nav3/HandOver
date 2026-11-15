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

// Choices for how often the vision model is offered a frame (set_check_interval, CONTRACT.md 7).
const CHECK_INTERVALS = [0.5, 1, 2]

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

  // Two stacked <img>s: a new frame decodes in the hidden one, then the two swap, so
  // the picture never blanks between frames. Only the front one is visible.
  const liveRef = useRef<HTMLImageElement>(null)
  const liveBackRef = useRef<HTMLImageElement>(null)
  const frontIsA = useRef(true)
  const frameUrl = useRef<string | null>(null)
  const decoding = useRef(false)
  const pendingFrame = useRef<Blob | null>(null)
  const mounted = useRef(true)
  // The live panel hugs the camera's real shape (glasses and replays are landscape,
  // a phone held upright is portrait). Null until the first frame decodes.
  const liveCellRef = useRef<HTMLElement>(null)
  const [liveAspect, setLiveAspect] = useState<number | null>(null)
  const liveBox = useFitBox(liveCellRef, liveAspect ?? 1)
  const videoRef = useRef<HTMLVideoElement>(null)
  const clipAreaRef = useRef<HTMLDivElement>(null)
  const [aspect, setAspect] = useState(16 / 9)
  const infoRef = useRef<HTMLDivElement>(null)
  const gridRef = useRef<HTMLElement>(null)
  const controlsRef = useRef<HTMLDivElement>(null)
  const sideWidth = useSideWidth(gridRef, aspect, infoRef, controlsRef, liveAspect)
  const clipBox = useFitBox(clipAreaRef, aspect, infoRef, CLIP_GAP)
  const flashTimer = useRef<number | undefined>(undefined)
  const [serverError, setServerError] = useState('')
  const errorTimer = useRef<number | undefined>(undefined)

  // Sets state only when the shape changes, so frames of the same size never
  // re-render or move the layout.
  const noteAspect = useCallback((img: HTMLImageElement) => {
    if (!img.naturalWidth || !img.naturalHeight) return
    const next = img.naturalWidth / img.naturalHeight
    setLiveAspect((prev) => (prev !== null && Math.abs(prev - next) < 0.01 ? prev : next))
  }, [])

  // Live frames go straight to the <img>s so React does not re-render per frame.
  // One decode at a time; frames arriving meanwhile keep only the newest, so a
  // slow decode drops frames instead of building up delay.
  const showFrame = useCallback(
    (jpeg: Blob) => {
      const front = frontIsA.current ? liveRef.current : liveBackRef.current
      const back = frontIsA.current ? liveBackRef.current : liveRef.current
      if (!front || !back) return
      decoding.current = true
      const url = URL.createObjectURL(jpeg)
      back.src = url
      const finish = (ok: boolean) => {
        decoding.current = false
        if (!mounted.current) {
          URL.revokeObjectURL(url)
          return
        }
        if (ok) {
          back.style.opacity = '1'
          front.style.opacity = '0'
          frontIsA.current = !frontIsA.current
          // The old frame is off screen now, so its URL can go.
          if (frameUrl.current) URL.revokeObjectURL(frameUrl.current)
          frameUrl.current = url
          noteAspect(back)
          setHasFrame(true)
          setStale(false)
        } else URL.revokeObjectURL(url) // a bad JPEG: keep showing the last good frame
        const pending = pendingFrame.current
        pendingFrame.current = null
        if (pending) showFrame(pending)
      }
      back.decode().then(
        () => finish(true),
        () => finish(false),
      )
    },
    [noteAspect],
  )
  const onFrame = useCallback(
    (jpeg: Blob) => {
      if (decoding.current) pendingFrame.current = jpeg
      else showFrame(jpeg)
    },
    [showFrame],
  )

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

  useEffect(() => {
    mounted.current = true
    return () => {
      mounted.current = false
      pendingFrame.current = null
      window.clearTimeout(flashTimer.current)
      window.clearTimeout(errorTimer.current)
      if (frameUrl.current) URL.revokeObjectURL(frameUrl.current)
      frameUrl.current = null
    }
  }, [])

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
  const checkInterval = state?.check_interval_s
  const setCheckInterval = (seconds: number) => send({ type: 'set_check_interval', seconds })

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
        {started && !down && checkInterval !== undefined && (
          <span className="check-rate" role="group" aria-label="How often the model checks a frame">
            <span>Model sees: every</span>
            {CHECK_INTERVALS.map((s, i) => {
              const on = Math.abs(checkInterval - s) < 0.01
              return (
                <span key={s} className="check-rate-item">
                  {i > 0 && <span className="check-rate-sep">/</span>}
                  <button type="button" className={on ? 'on' : ''} aria-pressed={on} onClick={() => setCheckInterval(s)}>
                    {s} s
                  </button>
                </span>
              )
            })}
          </span>
        )}
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
        <section className="live-cell" ref={liveCellRef} aria-label="Live camera">
          <div className="panel live" style={liveAspect && liveBox ? { width: liveBox.w, height: liveBox.h } : undefined}>
            <img ref={liveRef} alt="Live camera" style={FRONT_STYLE} className={showLive ? (cameraLost ? 'lost' : '') : 'hidden'} />
            <img ref={liveBackRef} alt="" aria-hidden="true" style={BACK_STYLE} className={showLive ? (cameraLost ? 'lost' : '') : 'hidden'} />
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
          </div>
        </section>

        <section className="side">
          <div className="clip-area" ref={clipAreaRef}>
            <div
              className={`panel clip ${isDone ? 'finished' : ''}`}
              style={clipBox ? (isDone ? { width: clipBox.w, minHeight: clipBox.h } : { width: clipBox.w, height: clipBox.h }) : undefined}
            >
              {activeMistake && (
                <div className="mistake-banner" role="alert">
                  <WarningIcon />
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
                      <dt>By camera</dt>
                      <dd>{summary.camera}</dd>
                    </div>
                    <div>
                      <dt>By hand</dt>
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
                          <th>Step</th>
                          <th>Checked</th>
                          <th>Expert</th>
                          <th>You</th>
                        </tr>
                      </thead>
                      <tbody>
                        {summary.rows.map((r) => (
                          <tr key={r.n}>
                            <td className="name">
                              <span className="num">{r.n}</span>
                              {r.title}
                            </td>
                            <td className="how">
                              {r.how === 'camera' ? (
                                <>
                                  <SmallCameraIcon />
                                  Camera
                                </>
                              ) : r.how === 'hand' ? (
                                <>
                                  <HandIcon />
                                  By hand
                                </>
                              ) : (
                                <span className="faint" title="Left by a jump or Back, not by a check">
                                  Not checked
                                </span>
                              )}
                            </td>
                            <td className="muted">{formatSecs(r.expertS)}</td>
                            <td>{r.yourS === null ? <span className="faint">Skipped</span> : formatSecs(r.yourS)}</td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  )}
                </div>
              )}
              {!step && (
                <div className="placeholder">
                  <p className="placeholder-title">{lessons?.length === 0 ? 'No lessons yet' : 'No lesson selected'}</p>
                </div>
              )}
            </div>

            <div className="step-info" ref={infoRef}>
              <p className="step-count">{step ? (isDone ? `All ${total} steps done` : `Step ${idx + 1} of ${total}`) : ' '}</p>
              {/* The lesson title is already in the top bar, so the done screen does not repeat it. */}
              <h1 className="step-title">{step ? (isDone ? 'Lesson complete' : step.title) : ' '}</h1>
            </div>
          </div>

          <div className="controls" ref={controlsRef}>
            <div className="badge-wrap">
              <span
                className={`badge ${badge} ${state?.camera_connected ? 'live' : ''}`}
                aria-live="polite"
                title={badge === 'offline' && offlineReason ? offlineReason : undefined}
              >
                {badge === 'verified' ? <BadgeCheckIcon /> : <span className="badge-dot" />}
                {BADGE_LABEL[badge]}
              </span>
              <span className="check-meta">
                <span>{metaTop}</span>
                <span className="check-reason">{metaBottom}</span>
              </span>
            </div>
            <div className="next-wrap">
              {isDone ? (
                <button type="button" className="next" onClick={restart}>
                  Start over
                </button>
              ) : (
                <>
                  <button type="button" className="next" onClick={() => next('button')} disabled={!step}>
                    Next
                  </button>
                  <span className="next-hint">{voiceOn && listening ? 'or say next' : 'or press \u2192'}</span>
                </>
              )}
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

// Initial opacity of the two live <img>s; showFrame flips them from then on. Constant
// objects, so React sets them once at mount and never overwrites the flips.
const FRONT_STYLE = { opacity: 1 } as const
const BACK_STYLE = { opacity: 0 } as const

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
 * the grid width so the live camera keeps a fair share. With a landscape live
 * camera the clip is also kept no taller than the live panel, so the two line
 * up as one row instead of leaving the live panel short.
 */
function useSideWidth(
  gridRef: RefObject<HTMLElement | null>,
  aspect: number,
  infoRef: RefObject<HTMLElement | null>,
  controlsRef: RefObject<HTMLElement | null>,
  liveAspect: number | null,
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
      let wanted = (h - reserved) * aspect
      // Equal heights: clip width / aspect == live width / liveAspect.
      if (liveAspect && liveAspect > 1) wanted = Math.min(wanted, (room * aspect) / (aspect + liveAspect))
      if (!room || h <= reserved) return
      setWidth(Math.round(Math.min(room * MAX_SIDE, Math.max(room * MIN_SIDE, wanted))))
    }
    measure()
    const ro = new ResizeObserver(measure)
    ro.observe(grid)
    if (infoRef.current) ro.observe(infoRef.current)
    return () => ro.disconnect()
  }, [gridRef, aspect, infoRef, controlsRef, liveAspect])
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

// Filled check in the Verified badge, so it never reads as the grey Watching dot.
function BadgeCheckIcon() {
  return (
    <svg className="badge-check" width="16" height="16" viewBox="0 0 24 24" aria-hidden="true">
      <circle cx="12" cy="12" r="11" fill="currentColor" />
      <path d="m7.5 12.4 3 3 6-6.2" fill="none" stroke="#000" strokeWidth="2.4" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  )
}

function WarningIcon() {
  return (
    <svg className="mistake-icon" width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.9" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
      <path d="M10.3 4.2a2 2 0 0 1 3.4 0l7.6 13A2 2 0 0 1 19.6 20H4.4a2 2 0 0 1-1.7-2.8z" />
      <path d="M12 9.5v4M12 16.8v.2" />
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
