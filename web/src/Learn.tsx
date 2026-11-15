import { useCallback, useEffect, useRef, useState } from 'react'
import type { RefObject, SyntheticEvent } from 'react'
import { getLesson, lessonUrl, listLessons, toSeconds } from './api'
import type { AdvanceMsg, CheckOfflineReason, Lesson, LessonSummary, Mistake, MistakeMsg, NextClip, StateMsg, Step } from './api'
import { playChime, unlockAudio } from './chime'
import { TopBar } from './TopBar'
import { useClipPair } from './useClipPair'
import { ConnectCamera } from './ConnectCamera'
import { useLiveCanvas } from './useLiveCanvas'
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
  no_key: 'No API key',
  rate_limited: 'Rate limited',
  errors: 'Check errors',
  budget: 'AI budget reached',
}

// Sources that are a live camera. Anything else (a replay file, an unknown
// sender) gets the Recording banner so it never passes for a live view.
const LIVE_SOURCES = ['phone', 'glasses', 'browser']

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
  // True while the "End this lesson?" card is open.
  const [confirmEnd, setConfirmEnd] = useState(false)
  // True between re-sending select_lesson after a reconnect and the server's answer.
  const [resuming, setResuming] = useState(false)
  const resumingRef = useRef(false)
  resumingRef.current = resuming

  const liveRef = useRef<HTMLCanvasElement>(null)
  const hasFrameRef = useRef(false)
  const staleRef = useRef(false)
  staleRef.current = stale
  // The live panel hugs the camera's real shape (glasses and replays are landscape,
  // a phone held upright is portrait). Null until the first frame decodes.
  const liveCellRef = useRef<HTMLElement>(null)
  const [liveAspect, setLiveAspect] = useState<number | null>(null)
  const liveBox = useFitBox(liveCellRef, liveAspect ?? 1)
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
  const onLiveSize = useCallback((w: number, h: number) => {
    const next = w / h
    setLiveAspect((prev) => (prev !== null && Math.abs(prev - next) < 0.01 ? prev : next))
  }, [])
  const drawFrame = useLiveCanvas(liveRef, onLiveSize)

  // Live frames go straight to the canvas so React does not re-render per frame.
  const onFrame = useCallback(
    (jpeg: Blob) => {
      drawFrame(jpeg)
      if (!hasFrameRef.current) {
        hasFrameRef.current = true
        setHasFrame(true)
      }
      if (staleRef.current) setStale(false)
    },
    [drawFrame],
  )

  // For the done screen: when this run began, and how each step was finished.
  const runStart = useRef(0)
  const advancedBy = useRef(new Map<number, AdvanceMsg['reason']>())
  // Time spent on each step (summed if revisited), counted from position
  // changes so next, back, goto and camera advances are all covered. Advance
  // messages count too: the hub may skip states for a slow client, but never
  // an advance (it always comes before its state).
  const spentMs = useRef(new Map<number, number>())
  const lastPos = useRef(0)
  const lastPosAt = useRef(0)
  // Each mistake once, however often the hub repeats it (message and state).
  const mistakeKeys = useRef(new Set<string>())
  const resetRun = () => {
    const now = performance.now()
    runStart.current = now
    advancedBy.current = new Map()
    spentMs.current = new Map()
    lastPos.current = 0
    lastPosAt.current = now
    mistakeKeys.current = new Set()
    setMistake(null)
    // A Verified flash from the previous run should not carry into the new one.
    window.clearTimeout(flashTimer.current)
    setFlashVerified(false)
  }

  // The clip pair: a step change to the buffered next clip is a swap, not a load.
  const clips = useClipPair((v) => {
    if (v.videoWidth && v.videoHeight) setAspect(v.videoWidth / v.videoHeight)
  })
  const lessonRef = useRef<Lesson | null>(null)
  const revRef = useRef(0)

  // Charge the time since the last change to the step we left. `pos` is the
  // step, or `total` when done.
  const moveTo = (pos: number, total: number) => {
    if (!runStart.current || pos === lastPos.current) return
    const now = performance.now()
    if (lastPos.current < total) {
      const spent = spentMs.current
      spent.set(lastPos.current, (spent.get(lastPos.current) ?? 0) + now - lastPosAt.current)
    }
    lastPos.current = pos
    lastPosAt.current = now
  }

  const onAdvance = useCallback((msg: AdvanceMsg) => {
    if (msg.to > msg.from) advancedBy.current.set(msg.from, msg.reason)
    const total = lessonRef.current?.steps.length
    if (total) moveTo(Math.min(msg.to, total), total)
    // Show the next clip now rather than after the state message and a render.
    const l = lessonRef.current
    const s = l?.steps[msg.to]
    if (l && s && startedRef.current) {
      clips.show(lessonUrl(l.id, s.clip, revRef.current), lessonUrl(l.id, s.captions, revRef.current), true)
    }
    if (msg.reason !== 'camera') return
    playChime()
    setFlashVerified(true)
    window.clearTimeout(flashTimer.current)
    flashTimer.current = window.setTimeout(() => setFlashVerified(false), 1800)
  }, [])

  // If the server restarts mid lesson it comes back with no lesson; pick ours
  // again, once per connection. `resumeId` is the lesson the learner started.
  const resumeId = useRef<string | null>(null)
  // The position to return to after the hub comes back (it restarts at step 0).
  const resumeStep = useRef(0)
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
    if (msg.lesson_id === null) {
      // The hub restarted (or lost the lesson): pick ours again and remember
      // where the learner was. The run and its times carry on.
      if (resumeId.current && !resentThisConnection.current) {
        resentThisConnection.current = true
        resumingRef.current = true
        setResuming(true)
        resumeStep.current = lastPos.current
        setMistake(null)
        sendRef.current({ type: 'select_lesson', id: resumeId.current })
      } else if (!resumingRef.current) setResuming(false)
      return
    }
    if (resumingRef.current) {
      resumingRef.current = false
      setResuming(false)
      const to = resumeStep.current
      // select_lesson starts at step 0; go back to the learner's step.
      if (to > 0 && to < msg.total && msg.step !== to) {
        sendRef.current({ type: 'goto', step: to })
        return
      }
    }
    moveTo(msg.status === 'done' ? msg.total : msg.step, msg.total)
    // Older servers omit `mistake`; only an explicit value replaces ours.
    if (msg.mistake !== undefined) {
      setMistake(msg.mistake)
      if (msg.mistake) countMistake(msg.mistake)
    }
  }, [])

  // True the first time this mistake is seen in the run.
  const countMistake = (m: Mistake) => {
    if (!startedRef.current) return false
    const key = `${m.step}:${m.kind}:${m.looks_like ?? ''}`
    if (mistakeKeys.current.has(key)) return false
    mistakeKeys.current.add(key)
    return true
  }

  // The catch: show the banner and say the message once.
  const onMistake = useCallback((msg: MistakeMsg) => {
    const { type: _type, ...m } = msg
    setMistake(m)
    if (!startedRef.current) return
    if (!countMistake(m)) return // already shown and spoken
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
  lessonRef.current = lesson
  revRef.current = rev
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
    if (state && !state.camera_connected) {
      staleRef.current = true
      setStale(true)
    }
  }, [state?.camera_connected])

  const steps = lesson?.steps ?? []
  const total = steps.length || state?.total || 0
  const isDone = state?.status === 'done'
  const idx = Math.max(0, Math.min(state?.step ?? 0, steps.length - 1))
  const step = steps.length ? steps[idx] : null

  // Show the clip and its captions on every step change. Done imperatively
  // so the <video> elements stay put (no layout jump) and the caption track
  // is guaranteed to reload. Acts only when the clip URL (path or rev)
  // changes, never on other re-renders, so playback is not reset under the
  // learner. An advance usually swapped the clip in already (onAdvance).
  const clipKey = lesson && step ? lessonUrl(lesson.id, step.clip, rev) : ''
  const captionsKey = lesson && step ? lessonUrl(lesson.id, step.captions, rev) : ''
  useEffect(() => {
    if (clipKey) clips.show(clipKey, captionsKey, started && !isDone)
  }, [clipKey, started, isDone])

  // Buffer the next clip in the standby element once the current one can play,
  // so the two downloads never compete.
  const upcoming = isDone ? null : nextClipFor(lesson, steps, idx, rev, state?.next_clip)
  const upClip = upcoming?.clip ?? ''
  const upCaptions = upcoming?.captions ?? ''
  useEffect(() => {
    const video = clips.active()
    if (!upClip || !video) return
    const go = () => clips.preload(upClip, upCaptions)
    if (video.readyState >= HTMLMediaElement.HAVE_FUTURE_DATA) return go()
    video.addEventListener('canplay', go, { once: true })
    return () => video.removeEventListener('canplay', go)
  }, [upClip, upCaptions, clipKey])

  // Play once started, and stop the last clip looping on the done screen.
  useEffect(() => {
    const video = clips.active()
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
  // Only the clip on screen sets the shape; the standby reports on swap.
  const onClipMetadata = (e: SyntheticEvent<HTMLVideoElement>) => {
    const v = e.currentTarget
    if (v === clips.active() && v.videoWidth && v.videoHeight) setAspect(v.videoWidth / v.videoHeight)
  }

  const clipAudible = useCallback(() => {
    const v = clips.active()
    return !!v && !v.paused && !v.muted && v.volume > 0
  }, [])
  const { listening } = useVoice(started && voiceOn, (cmd) => (cmd === 'next' ? next('voice') : back()), clipAudible)
  const voiceAvailable = started && voiceSupported()

  // Keyboard: Right or Space for next, Left for back.
  useEffect(() => {
    if (!started || confirmEnd) return
    const onKey = (e: KeyboardEvent) => {
      const t = e.target instanceof Element ? e.target : null
      if (t?.closest('input, select, textarea, [contenteditable="true"]')) return
      // Space belongs to the focused control (the mic, Show step, OK), not to Next.
      if (e.key === ' ' && t?.closest('button, a, summary, [role="button"]')) return
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
  }, [started, confirmEnd, next, back])

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

  // A fresh select_lesson, not goto 0, so the hub starts a new run (with its
  // own run id in Databricks) for the second attempt.
  const restart = () => {
    const id = lessonId ?? resumeId.current
    if (!id) return
    resetRun()
    send({ type: 'select_lesson', id })
  }

  // End: back to the lesson list. Asks first unless the lesson is finished.
  const endLesson = () => {
    setConfirmEnd(false)
    resumeId.current = null
    clips.active()?.pause()
    if ('speechSynthesis' in window) window.speechSynthesis.cancel()
    setVoiceOn(false)
    setMistake(null)
    setStarted(false)
    send({ type: 'end_lesson' }) // the hub stops the run and unloads the lesson (older hubs ignore it)
  }
  const askEnd = () => (isDone ? endLesson() : setConfirmEnd(true))
  useEffect(() => {
    if (!confirmEnd) return
    const onKey = (e: KeyboardEvent) => e.key === 'Escape' && setConfirmEnd(false)
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [confirmEnd])

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
      mistakes: mistakeKeys.current.size,
      rows,
    })
  }, [isDone])

  // Mock checks pass on a timer and never look at the camera; say so.
  const mockChecks = state?.check_mode === 'mock'
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

  // What to do now, one line under the step title. Always a line, so the layout never moves.
  let doNow = '\u00a0'
  if (step && !isDone) {
    const autoChecks = cameraStep && badge !== 'manual' && !!state?.camera_connected && !offline
    if (!autoChecks) doNow = 'Do this step, then press Next.'
    else if (mockChecks) doNow = 'Do this step. Mock checks move on after a short wait.'
    else doNow = 'Do this step. HandOver moves on when it sees it done.'
  }

  // A frozen frame while the socket is down would mislead, so show the placeholder.
  // A camera that drops after sending frames leaves its last frame, dimmed.
  const showLive = !down && hasFrame && (!!state?.camera_connected || stale)
  const cameraLost = showLive && (stale || !state?.camera_connected)
  const source = state?.camera?.source
  const recording = showLive && !cameraLost && !!source && !LIVE_SOURCES.includes(source)
  const cameraName = !down && state?.camera_connected ? state?.camera?.name : undefined

  // Before start, or when the server has no lesson (restart, lesson gone) and
  // no resume is in flight, the learner picks one.
  const showPicker = !started || (!!state && !state.lesson_id && !resuming)

  return (
    <div className="page learn">
      <div className="progress" role="progressbar" aria-valuemin={0} aria-valuemax={total} aria-valuenow={isDone ? total : idx}>
        {Array.from({ length: Math.max(total, 1) }, (_, i) => {
          let cls = !total ? 'upcoming' : isDone || i < idx ? 'done' : i === idx ? 'current' : 'upcoming'
          if (i === idx && activeMistake && activeMistake.kind !== 'ahead') cls = 'mistake'
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
        {started && !showPicker && (
          <button type="button" className="ghost end-button" onClick={askEnd}>
            End lesson
          </button>
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
        <section className="live-cell" ref={liveCellRef} aria-label="You, live camera">
          <div className="panel live" style={showLive && liveAspect && liveBox ? { width: liveBox.w, height: liveBox.h } : undefined}>
            <canvas ref={liveRef} role="img" aria-label="Live camera" className={showLive ? (cameraLost ? 'lost' : '') : 'hidden'} />
            {showLive && <span className="pane-label">You</span>}
            {cameraLost && (
              <p className="live-note" role="status">
                Camera lost. Keep going with Next.
              </p>
            )}
            {recording && (
              <span
                className="rec"
                title={source === 'file' ? 'Frames come from a recorded video, not a live camera' : `Camera source "${source}" is not a known live camera`}
              >
                <span className="rec-dot" />
                Recording
              </span>
            )}
            {!showLive &&
              (down ? (
                <div className="placeholder">
                  <CameraIcon />
                  <p className="placeholder-title">Reconnecting to HandOver</p>
                  <p className="placeholder-hint">Your camera shows here again once it is back.</p>
                </div>
              ) : state?.camera_connected ? (
                <div className="placeholder">
                  <CameraIcon />
                  <p className="placeholder-title">Camera connected</p>
                  <p className="placeholder-hint">Waiting for its first picture.</p>
                </div>
              ) : (
                <ConnectCamera />
              ))}
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
                  <p className="mistake-text">
                    {activeMistake.label && <span className="mistake-label">{activeMistake.label}</span>}
                    {activeMistake.message}
                  </p>
                  <div className="mistake-actions">
                    {activeMistake.kind === 'behind' && typeof activeMistake.looks_like === 'number' ? (
                      <>
                        <button type="button" className="ghost small" onClick={() => showStep(activeMistake.looks_like as number)}>
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
              {step && !isDone && <span className="pane-label">Expert</span>}
              <div className={`clip-media ${step && !isDone ? '' : 'hidden'}`}>
                <video ref={clips.refA} data-slot="a" loop playsInline preload="auto" onLoadedMetadata={onClipMetadata} />
                <video ref={clips.refB} data-slot="b" loop playsInline preload="auto" muted className="standby" onLoadedMetadata={onClipMetadata} />
              </div>
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
                      <dt>{mockChecks ? 'By timer (mock)' : 'By camera'}</dt>
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
                              {r.how === 'camera' && mockChecks ? (
                                <span title="Mock checks pass on a timer and do not look at the camera">Timer (mock)</span>
                              ) : r.how === 'camera' ? (
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
              {!isDone && <p className="step-do">{doNow}</p>}
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
              {mockChecks && (
                <span className="mode-pill" title="Steps pass on a timer. The camera is not checked.">
                  Mock checks
                </span>
              )}
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
            <h2>Pick a lesson</h2>
            <p className="start-how">The expert shows each step. You do it in front of a camera, and HandOver moves on when it sees it done.</p>
            {lessons && lessons.length > 0 ? (
              <ul className="lesson-picker" role="radiogroup" aria-label="Lessons">
                {lessons.map((l) => (
                  <li key={l.id}>
                    <button
                      type="button"
                      role="radio"
                      aria-checked={picked === l.id}
                      data-id={l.id}
                      className={`lesson-option ${picked === l.id ? 'on' : ''}`}
                      onClick={() => setPicked(l.id)}
                      onDoubleClick={() => {
                        setPicked(l.id)
                        if (picked === l.id) start()
                      }}
                    >
                      <span className="lesson-option-title">{l.title}</span>
                      <span className="lesson-option-meta">
                        {l.steps} {l.steps === 1 ? 'step' : 'steps'}
                      </span>
                    </button>
                  </li>
                ))}
              </ul>
            ) : (
              <p className="lesson-picker-empty">
                {lessons === null ? (
                  'Loading lessons'
                ) : (
                  <>
                    No lessons yet. Make one in <a href="#/teach">Teach</a>.
                  </>
                )}
              </p>
            )}
            <button className="primary" onClick={start} disabled={!picked}>
              Start lesson
            </button>
            {!!lessons?.length && <p className="start-hint">Turns on sound. Voice commands stay off until you click the mic.</p>}
          </div>
        </div>
      )}

      {confirmEnd && !showPicker && (
        <div className="overlay" onClick={(e) => e.target === e.currentTarget && setConfirmEnd(false)}>
          <div className="start-card confirm-card" role="alertdialog" aria-modal="true" aria-labelledby="end-title">
            <h2 id="end-title">End this lesson?</h2>
            <p className="start-how">You go back to the lesson list.</p>
            <div className="confirm-actions">
              <button type="button" className="secondary" onClick={() => setConfirmEnd(false)} autoFocus>
                Keep going
              </button>
              <button type="button" className="primary danger" onClick={endLesson}>
                End lesson
              </button>
            </div>
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

/**
 * The clip to buffer next, as URLs: the hub's `next_clip` when it sends one
 * (null = nothing next), else the following step's clip.
 */
function nextClipFor(lesson: Lesson | null, steps: Step[], idx: number, rev: number, hint: NextClip | null | undefined) {
  if (!lesson) return null
  const clean = (p: string) => p.replace(/[?#].*$/, '').replace(`/lessons/${encodeURIComponent(lesson.id)}/`, '').replace(/^\/+/, '')
  let clip: string
  let captions: string | null | undefined
  if (hint === undefined) {
    const s = steps[idx + 1]
    if (!s) return null
    clip = s.clip
    captions = s.captions
  } else {
    if (!hint) return null
    clip = clean(typeof hint === 'string' ? hint : hint.clip)
    captions = typeof hint === 'string' ? undefined : hint.captions
    captions ??= steps.find((s) => clean(s.clip) === clip)?.captions
  }
  return { clip: lessonUrl(lesson.id, clip, rev), captions: captions ? lessonUrl(lesson.id, clean(captions), rev) : '' }
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
