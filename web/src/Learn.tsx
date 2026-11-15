import './learn.css'
import { useCallback, useEffect, useRef, useState } from 'react'
import type { RefObject, SyntheticEvent } from 'react'
import { getLesson, lessonUrl, toSeconds } from './api'
import type { AdvanceMsg, CheckOfflineReason, Lesson, Mistake, MistakeMsg, NextClip, StateMsg, Step } from './api'
import { go, useRoute } from './App'
import { playChime, unlockAudio } from './chime'
import * as cues from './cues'
import { ConnectCamera } from './ConnectCamera'
import { Done } from './Done'
import type { DoneSummary } from './Done'
import { CloseIcon, SoundIcon } from './icons'
import { Caps, emptyRun, pad2, StepList } from './StepList'
import type { StepRun } from './StepList'
import { TopBar } from './TopBar'
import { useClipPair } from './useClipPair'
import { useLiveCanvas } from './useLiveCanvas'
import { useUiSocket } from './useUiSocket'

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

// Choices for how often the vision model is offered a frame (set_check_interval, CONTRACT.md 7).
const CHECK_INTERVALS = [0.5, 1, 2]

// The chime's two notes last about this long; a spoken cue after it waits this much so they never overlap.
const CHIME_MS = 700

export function Learn() {
  const { lessonId: routeId } = useRoute()
  const [state, setState] = useState<StateMsg | null>(null)
  const [lesson, setLesson] = useState<Lesson | null>(null)
  const [hasFrame, setHasFrame] = useState(false)
  // True after the camera drops, until its next frame: the last frame stays, dimmed.
  const [stale, setStale] = useState(false)
  // The mistake on screen, from a `mistake` message or state.mistake.
  const [mistake, setMistake] = useState<Mistake | null>(null)
  const [flashVerified, setFlashVerified] = useState(false)
  // True while the "End this lesson?" card is open.
  const [confirmEnd, setConfirmEnd] = useState(false)
  // The steps sheet (narrow windows) or the check-rate popover.
  const [popup, setPopup] = useState<'none' | 'steps' | 'more'>('none')
  // True between re-sending select_lesson after a reconnect and the server's answer.
  const [resuming, setResuming] = useState(false)
  const resumingRef = useRef(false)
  resumingRef.current = resuming
  // The lesson this page asked the hub for, until the hub answers.
  const [pending, setPending] = useState<string | null>(null)
  const pendingRef = useRef<string | null>(null)
  const setPendingId = (id: string | null) => {
    pendingRef.current = id
    setPending(id)
  }
  // The browser refused to play the clip with sound: it plays muted until the learner turns sound on.
  const [soundBlocked, setSoundBlocked] = useState(false)
  const soundBlockedRef = useRef(false)
  // Re-render after run bookkeeping changes (it lives in refs).
  const [, setTick] = useState(0)
  // Spoken cues (cues.ts), on unless turned off in the popover; remembered in this browser.
  const [voiceCues, setVoiceCues] = useState(cues.cuesEnabled)
  const toggleVoiceCues = () => {
    const on = !voiceCues
    cues.setCuesEnabled(on)
    setVoiceCues(on)
  }
  // When the chime last played, so a cue right after waits for it to finish.
  const chimeAt = useRef(-Infinity)
  const afterChime = () => Math.max(0, CHIME_MS - (performance.now() - chimeAt.current))

  const liveRef = useRef<HTMLCanvasElement>(null)
  const hasFrameRef = useRef(false)
  const staleRef = useRef(false)
  staleRef.current = stale
  const [aspect, setAspect] = useState(16 / 9)
  const stageRef = useRef<HTMLElement>(null)
  const underRef = useRef<HTMLDivElement>(null)
  const sideLayout = aspect < 1 // portrait take: title and controls beside the panes, panes full height
  const pane = usePaneBox(stageRef, underRef, aspect, sideLayout)
  const flashTimer = useRef<number | undefined>(undefined)
  const [serverError, setServerError] = useState('')
  const errorTimer = useRef<number | undefined>(undefined)

  // Live frames keep their own shape inside the pane (object-fit), so their size needs no state.
  const drawFrame = useLiveCanvas(liveRef, () => {})

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

  // The run, for the step list and the done screen. Time on each step is
  // summed over visits and counted from position changes, so next, back,
  // goto and camera advances are all covered. Advance messages count too: the
  // hub may skip states for a slow client, but never an advance (it always
  // comes before its state).
  const runStart = useRef(0)
  // True when this page joined a run already under way, so its total time is unknown.
  const joined = useRef(false)
  const runs = useRef<StepRun[]>([])
  const lastPos = useRef(0)
  const lastPosAt = useRef(0)
  // The lesson the run belongs to; a different lesson in state starts a new run.
  const runLesson = useRef<string | null>(null)
  // Each mistake once, however often the hub repeats it (message and state).
  const mistakeKeys = useRef(new Set<string>())
  const run = (i: number) => (runs.current[i] ??= emptyRun())
  const resetRun = (startPos = 0, join = false) => {
    const now = performance.now()
    runStart.current = now
    joined.current = join
    runs.current = []
    lastPos.current = startPos
    lastPosAt.current = now
    mistakeKeys.current = new Set()
    setMistake(null)
    // A Verified flash from the previous run should not carry into the new one.
    window.clearTimeout(flashTimer.current)
    setFlashVerified(false)
    setTick((t) => t + 1)
  }

  // The clip pair: a step change to the buffered next clip is a swap, not a load.
  const clips = useClipPair((v) => {
    if (v.videoWidth && v.videoHeight) setAspect(v.videoWidth / v.videoHeight)
  })
  // A cue turns the expert clip down; both elements, so a swap during the cue stays quiet.
  cues.setDuckTargets(() => [clips.refA.current, clips.refB.current])
  const lessonRef = useRef<Lesson | null>(null)
  const revRef = useRef(0)

  // Plays the clip on screen with sound; if the browser refuses sound, muted,
  // and the Turn on sound button shows.
  const playActive = useCallback(() => {
    const v = clips.active()
    if (!v || !v.getAttribute('src')) return
    if (soundBlockedRef.current) v.muted = true
    v.play().catch((e: unknown) => {
      if ((e as Error)?.name !== 'NotAllowedError' || v.muted) return
      soundBlockedRef.current = true
      setSoundBlocked(true)
      v.muted = true
      v.play().catch(() => {})
    })
  }, [])

  const turnOnSound = () => {
    unlockAudio()
    soundBlockedRef.current = false
    setSoundBlocked(false)
    const v = clips.active()
    if (!v) return
    v.muted = false
    if (state?.status !== 'done') v.play().catch(() => {})
  }

  // Charge the time since the last change to the step we left, and mark steps
  // passed over without being finished as skipped. `pos` is the step, or
  // `total` when done.
  const moveTo = (pos: number, total: number) => {
    if (!runStart.current || pos === lastPos.current) return
    const now = performance.now()
    if (lastPos.current < total) run(lastPos.current).ms += now - lastPosAt.current
    for (let k = lastPos.current; k < pos && k < total; k++) if (!run(k).how) run(k).how = 'skipped'
    lastPos.current = pos
    lastPosAt.current = now
  }

  const onAdvance = useCallback((msg: AdvanceMsg) => {
    const total = lessonRef.current?.steps.length
    if (msg.to > msg.from && runStart.current) {
      run(msg.from).how = msg.reason === 'camera' ? 'camera' : 'button'
      // An ahead advance (k to k+2) jumps over k+1.
      for (let k = msg.from + 1; k < msg.to && (!total || k < total); k++) if (!run(k).how) run(k).how = 'skipped'
    }
    if (total) moveTo(Math.min(msg.to, total), total)
    setTick((t) => t + 1)
    // Show the next clip now rather than after the state message and a render.
    const l = lessonRef.current
    const s = l?.steps[msg.to]
    if (l && s) {
      clips.show(lessonUrl(l.id, s.clip, revRef.current), lessonUrl(l.id, s.captions, revRef.current), false)
      playActive()
    }
    if (msg.reason !== 'camera') return
    playChime()
    chimeAt.current = performance.now()
    // The last step's advance ends the lesson: the done cue says so instead.
    if (!total || msg.to < total) cues.play('done-moving-on', CHIME_MS)
    setFlashVerified(true)
    window.clearTimeout(flashTimer.current)
    flashTimer.current = window.setTimeout(() => setFlashVerified(false), 1800)
  }, [])

  // If the hub restarts mid lesson it comes back with no lesson; pick ours
  // again, once per connection. `resumeId` is the lesson this page selected.
  const resumeId = useRef<string | null>(null)
  // The position to return to after the hub comes back (it restarts at step 0).
  const resumeStep = useRef(0)
  const resentThisConnection = useRef(false)
  // True until the first state of a connection: a hub that restarted says "no
  // lesson" first, while a lesson ended elsewhere arrives later on the same connection.
  const firstState = useRef(true)
  // Lessons this page already asked for on this connection.
  const selectedFor = useRef(new Set<string>())
  const sendRef = useRef<(m: object) => void>(() => {})

  // Server errors (bad lesson id, command with no lesson) show briefly in the top bar.
  const onError = useCallback((message: string) => {
    if (resumingRef.current) {
      resumeId.current = null
      setResuming(false)
    }
    setPendingId(null)
    setServerError(message || 'Something went wrong')
    window.clearTimeout(errorTimer.current)
    errorTimer.current = window.setTimeout(() => setServerError(''), 4000)
  }, [])

  // True the first time this mistake is seen in the run.
  const countMistake = (m: Mistake) => {
    if (!runStart.current) return false
    const key = `${m.step}:${m.kind}:${m.looks_like ?? ''}`
    if (mistakeKeys.current.has(key)) return false
    mistakeKeys.current.add(key)
    run(m.step).mistakes += 1
    return true
  }

  const onState = useCallback((msg: StateMsg) => {
    const first = firstState.current
    firstState.current = false
    setState(msg)
    if (msg.lesson_id === null) {
      if (first && resumeId.current && !resentThisConnection.current) {
        // The hub restarted: pick our lesson again and remember where the
        // learner was. The run and its times carry on.
        resentThisConnection.current = true
        selectedFor.current.add(resumeId.current)
        resumingRef.current = true
        setResuming(true)
        resumeStep.current = lastPos.current
        setMistake(null)
        sendRef.current({ type: 'select_lesson', id: resumeId.current })
      } else if (!resumingRef.current && !pendingRef.current) {
        // Ended here or elsewhere: no lesson, no run.
        runLesson.current = null
        resumeId.current = null
        runStart.current = 0
      }
      return
    }
    // While a lesson this page asked for is on its way, older states are not part of its run.
    if (pendingRef.current && msg.lesson_id !== pendingRef.current) return
    if (pendingRef.current) setPendingId(null)
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
    if (msg.lesson_id !== runLesson.current) {
      // A lesson this page did not start (a viewer, or started elsewhere): count from here.
      runLesson.current = msg.lesson_id
      resetRun(msg.status === 'done' ? msg.total : msg.step, true)
    }
    moveTo(msg.status === 'done' ? msg.total : msg.step, msg.total)
    // Older servers omit `mistake`; only an explicit value replaces ours.
    if (msg.mistake !== undefined) {
      setMistake(msg.mistake)
      if (msg.mistake) countMistake(msg.mistake)
    }
  }, [])

  // The catch: show the card and say the message once.
  const onMistake = useCallback((msg: MistakeMsg) => {
    const { type: _type, ...m } = msg
    setMistake(m)
    if (!countMistake(m)) return // already shown and spoken
    setTick((t) => t + 1)
    if (m.kind === 'ahead') cues.play('ahead')
    else if (m.message?.trim()) cues.say(m.message)
    else cues.play('still-step')
  }, [])

  const onOpen = useCallback(() => {
    resentThisConnection.current = false
    firstState.current = true
    selectedFor.current = new Set()
  }, [])

  const { down, send } = useUiSocket({ onFrame, onState, onAdvance, onError, onMistake, onOpen })
  sendRef.current = send

  useEffect(() => {
    // Any click or key on this page lets the chime and the spoken cues play later.
    const unlock = () => {
      unlockAudio()
      cues.unlockCues()
    }
    window.addEventListener('pointerdown', unlock)
    window.addEventListener('keydown', unlock)
    return () => {
      window.clearTimeout(flashTimer.current)
      window.clearTimeout(errorTimer.current)
      window.removeEventListener('pointerdown', unlock)
      window.removeEventListener('keydown', unlock)
      cues.stopCue()
    }
  }, [])

  // Starts lesson `id` from step 0: a new run on the hub and here.
  const selectLesson = (id: string) => {
    unlockAudio()
    selectedFor.current.add(id)
    resumeId.current = id
    runLesson.current = id
    resetRun()
    setPendingId(id)
    send({ type: 'select_lesson', id })
  }

  // The route names a lesson: ask the hub for it once per id per connection.
  // The Community card click that got us here is the gesture that allows sound.
  useEffect(() => {
    if (!routeId || !state || down || resumingRef.current) return
    if (state.lesson_id === routeId || selectedFor.current.has(routeId)) return
    selectLesson(routeId)
  }, [routeId, state, down])

  // Fetch the full lesson whenever the server switches lessons or recuts it.
  const lessonId = state?.lesson_id ?? null
  const rev = state?.rev ?? 0
  lessonRef.current = lesson
  revRef.current = rev
  useEffect(() => {
    if (!lessonId) {
      if (!resumingRef.current) setLesson(null)
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

  // What the page shows: the lesson, nothing running, or a wait.
  const view: 'lesson' | 'empty' | 'loading' =
    lesson && (lessonId === lesson.id || resuming) ? 'lesson' : state && !lessonId && !resuming && !pending ? 'empty' : 'loading'
  const showing = view === 'lesson'

  const steps = lesson?.steps ?? []
  const total = steps.length || state?.total || 0
  const isDone = showing && state?.status === 'done'
  const idx = Math.max(0, Math.min(state?.step ?? 0, steps.length - 1))
  const step = showing && steps.length ? steps[idx] : null

  // Show the clip and its captions on every step change. Done imperatively
  // so the <video> elements stay put (no layout jump) and the caption track
  // is guaranteed to reload. Acts only when the clip URL (path or rev)
  // changes, never on other re-renders, so playback is not reset under the
  // learner. An advance usually swapped the clip in already (onAdvance).
  const clipKey = lesson && step ? lessonUrl(lesson.id, step.clip, rev) : ''
  const captionsKey = lesson && step ? lessonUrl(lesson.id, step.captions, rev) : ''
  useEffect(() => {
    if (!clipKey) return
    clips.show(clipKey, captionsKey, false)
    if (!isDone) playActive()
  }, [clipKey])

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

  // Stop the last clip looping on the done screen and when nothing is running; play again after.
  useEffect(() => {
    const video = clips.active()
    if (!video || !video.getAttribute('src')) return
    if (isDone || !showing) video.pause()
    else playActive()
  }, [isDone, showing])

  // `from` is the step on screen, so the server drops a tap that races a
  // camera advance instead of skipping a step.
  const shownStep = state?.step ?? 0
  const next = useCallback(() => {
    if (lessonId && !isDone) send({ type: 'next', reason: 'button', from: shownStep })
  }, [send, lessonId, isDone, shownStep])
  const back = useCallback(() => {
    if (lessonId && shownStep > 0) send({ type: 'back', from: shownStep })
  }, [send, lessonId, shownStep])
  const gotoStep = (to: number) => {
    // Leave focus on the page, so Space and the arrows drive the lesson again.
    if (document.activeElement instanceof HTMLElement) document.activeElement.blur()
    setPopup('none')
    setMistake(null)
    send({ type: 'goto', step: to })
  }

  // Only the clip on screen sets the shape; the standby reports on swap.
  const onClipMetadata = (e: SyntheticEvent<HTMLVideoElement>) => {
    const v = e.currentTarget
    if (v === clips.active() && v.videoWidth && v.videoHeight) setAspect(v.videoWidth / v.videoHeight)
  }

  // Keyboard: Right or Space for next, Left for back, Escape closes what is open.
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') {
        setConfirmEnd(false)
        setPopup('none')
        return
      }
      if (!showing || isDone || confirmEnd) return
      const t = e.target instanceof Element ? e.target : null
      if (t?.closest('input, select, textarea, [contenteditable="true"]')) return
      // Space belongs to the focused control (a step row, OK, Show step), not to Next.
      if (e.key === ' ' && t?.closest('button, a, summary, [role="button"]')) return
      if (e.key === 'ArrowRight' || e.key === ' ') {
        e.preventDefault()
        next()
      } else if (e.key === 'ArrowLeft') {
        e.preventDefault()
        back()
      }
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [showing, isDone, confirmEnd, next, back])

  // A fresh select_lesson, not goto 0, so the hub starts a new run (with its
  // own run id in Databricks) for the second attempt.
  const restart = () => {
    const id = lessonId ?? resumeId.current
    if (id) selectLesson(id)
  }

  // Leave: the hub stops the run and unloads the lesson; the ids make it
  // ignore a stale End (older hubs ignore them). Then back to the lessons.
  const endLesson = () => {
    setConfirmEnd(false)
    resumeId.current = null
    clips.active()?.pause()
    cues.stopCue()
    if ('speechSynthesis' in window) window.speechSynthesis.cancel()
    setMistake(null)
    if (state?.lesson_id) send({ type: 'end_lesson', lesson_id: state.lesson_id, run_id: state.run_id ?? undefined })
    go('community')
  }
  const askEnd = () => (isDone ? endLesson() : setConfirmEnd(true))

  // A mistake belongs to one step; it never outlives that step or the lesson.
  const activeMistake = mistake && showing && !isDone && mistake.step === state?.step ? mistake : null
  const dismissMistake = () => {
    setMistake(null)
    send({ type: 'dismiss_mistake' })
  }

  // Snapshot the summary the moment the lesson finishes.
  const [summary, setSummary] = useState<DoneSummary | null>(null)
  useEffect(() => {
    if (!isDone) {
      setSummary(null)
      return
    }
    const rows = steps.map((s, i) => {
      const r = runs.current[i] ?? emptyRun()
      return {
        n: s.n || i + 1,
        title: s.title,
        expertS: Math.max(0, toSeconds(s.end) - toSeconds(s.start)),
        yourS: r.ms >= 500 ? r.ms / 1000 : null,
        how: r.how,
        mistakes: r.mistakes,
      }
    })
    setSummary({
      title: lesson?.title ?? '',
      ms: runStart.current && !joined.current ? performance.now() - runStart.current : 0,
      expertS: rows.reduce((a, r) => a + r.expertS, 0),
      camera: rows.filter((r) => r.how === 'camera').length,
      cameraSteps: steps.filter((s) => s.check_type !== 'manual').length,
      byButton: rows.filter((r) => r.how === 'button').length,
      skipped: rows.filter((r) => r.how === 'skipped').length,
      mistakes: mistakeKeys.current.size,
      mock: state?.check_mode === 'mock',
      rows,
    })
  }, [isDone])

  // Spoken cues for the lesson finishing, checks going off and the camera dropping, each once per change.
  // Only a change seen while the lesson is on screen speaks: a page that joins a finished run stays quiet.
  const wasRunning = useRef(false)
  useEffect(() => {
    if (isDone && wasRunning.current) cues.play('lesson-complete', afterChime())
    wasRunning.current = showing && !isDone
  }, [isDone, showing])
  const offlineSpoken = useRef(false)
  const checkOffline = !!state?.check_offline
  useEffect(() => {
    if (!checkOffline) offlineSpoken.current = false
    else if (showing && !isDone && !offlineSpoken.current) {
      offlineSpoken.current = true
      cues.play('checks-off')
    }
  }, [checkOffline, showing])
  const cameraWasOn = useRef(false)
  const cameraOn = !!state?.camera_connected
  useEffect(() => {
    if (cameraOn) cameraWasOn.current = true
    else if (cameraWasOn.current && state) {
      cameraWasOn.current = false
      if (showing && !isDone) cues.play('camera-lost')
    }
  }, [cameraOn])

  // Mock checks pass on a timer and never look at the camera; say so.
  const mockChecks = state?.check_mode === 'mock'
  const offline = !!state?.check_offline
  const offlineReason = state?.check_offline_reason ? OFFLINE_REASON[state.check_offline_reason] : ''
  let badge: Badge = 'watching'
  if (isDone) badge = 'done'
  else if (flashVerified || state?.status === 'verified') badge = 'verified'
  else if (state?.status === 'manual' || step?.check_type === 'manual') badge = 'manual'
  else if (offline) badge = 'offline'

  // Small text beside the badge: why checks are off, that checks are simulated,
  // or the last check's latency and reason.
  const cameraStep = !!step && step.check_type !== 'manual' && !isDone
  const lc = state?.last_check
  const latency = lc && cameraStep && state?.camera_connected ? `Last check ${(lc.latency_ms / 1000).toFixed(1)} s` : ''
  let metaTop = ''
  let metaBottom = ''
  if (badge === 'offline') metaTop = offlineReason
  else if (badge === 'watching' && mockChecks) {
    metaTop = 'Simulated checks'
    metaBottom = latency
  } else if (badge === 'watching' && latency && lc) {
    metaTop = latency
    if (lc.reason && lc.done === 'no' && lc.confidence >= REASON_MIN_CONF) metaBottom = lc.reason
  }

  // What to do now, one line under the step title. Always a line, so the layout never moves.
  let doNow = ' '
  if (step && !isDone) {
    const autoChecks = cameraStep && badge !== 'manual' && !!state?.camera_connected && !offline
    if (!autoChecks) doNow = 'Do this step, then press Next.'
    else if (mockChecks) doNow = 'Do this step. Simulated checks move on after a short wait.'
    else doNow = 'Do this step. HandOver moves on when it sees it done.'
  }

  // A frozen frame while the socket is down would mislead, so show the placeholder.
  // A camera that drops after sending frames leaves its last frame, dimmed.
  const showLive = !down && hasFrame && (!!state?.camera_connected || stale)
  const cameraLost = showLive && (stale || !state?.camera_connected)
  const source = state?.camera?.source
  const recording = showLive && !cameraLost && !!source && !LIVE_SOURCES.includes(source)
  const cameraName = !down && state?.camera_connected ? state?.camera?.name : undefined
  const checkInterval = state?.check_interval_s
  const paneStyle = pane ? { width: pane.w, height: pane.h } : undefined
  const runList = runs.current

  const showStep = activeMistake && typeof activeMistake.looks_like === 'number' && activeMistake.looks_like !== state?.step ? activeMistake.looks_like : null

  return (
    <div className={`page learn ${isDone ? 'is-done' : ''}`}>
      <div className="progress" role="progressbar" aria-valuemin={0} aria-valuemax={total} aria-valuenow={isDone ? total : idx}>
        {Array.from({ length: showing ? Math.max(total, 1) : 1 }, (_, i) => {
          let cls = !showing || !total ? 'upcoming' : isDone || i < idx ? 'done' : i === idx ? 'cur' : 'upcoming'
          if (i === idx && activeMistake && activeMistake.kind !== 'ahead') cls = 'mistake'
          return <span key={i} className={`seg ${cls}`} />
        })}
      </div>

      <TopBar route="learn" title={showing ? lesson?.title : undefined} camera={showing ? cameraName : undefined}>
        {serverError && !down && (
          <span className="note error" role="status">
            {serverError}
          </span>
        )}
        {down && <span className="note">Reconnecting</span>}
        {showing && !isDone && (
          <button type="button" className="btn small quiet steps-toggle" aria-expanded={popup === 'steps'} onClick={() => setPopup(popup === 'steps' ? 'none' : 'steps')}>
            Steps
          </button>
        )}
        {showing && !down && checkInterval !== undefined && (
          <span className="more-wrap">
            <button
              type="button"
              className="btn small quiet more-button"
              aria-label="Check settings"
              aria-expanded={popup === 'more'}
              title="Check settings"
              onClick={() => setPopup(popup === 'more' ? 'none' : 'more')}
            >
              <MoreIcon />
            </button>
            {popup === 'more' && (
              <div className="popover card" role="dialog" aria-label="Check settings">
                <p className="popover-label">Model sees one frame every</p>
                <div className="check-rate" role="group" aria-label="How often the model checks a frame">
                  {CHECK_INTERVALS.map((s) => {
                    const on = Math.abs(checkInterval - s) < 0.01
                    return (
                      <button
                        key={s}
                        type="button"
                        className={`btn small ${on ? 'ink on' : ''}`}
                        aria-pressed={on}
                        onClick={() => send({ type: 'set_check_interval', seconds: s })}
                      >
                        <Caps>{`${s} s`}</Caps>
                      </button>
                    )
                  })}
                </div>
                <label className="cue-toggle">
                  <input type="checkbox" checked={voiceCues} onChange={toggleVoiceCues} />
                  Voice cues
                </label>
              </div>
            )}
          </span>
        )}
        {showing && (
          <button type="button" className="btn small end-button" onClick={askEnd}>
            End lesson
          </button>
        )}
      </TopBar>

      {view === 'empty' && (
        <main className="learn-empty">
          <div className="empty-state">
            <p className="empty-title">No lesson running</p>
            <p className="empty-message">Pick a lesson from the list to start learning.</p>
            <button type="button" className="btn primary" onClick={() => go('community')}>
              Pick a lesson
            </button>
          </div>
        </main>
      )}
      {view === 'loading' && (
        <main className="learn-empty">
          <div className="empty-state" role="status">
            <span className="spinner large" />
            <p className="empty-message">{down ? 'Connecting to HandOver' : 'Loading lesson'}</p>
          </div>
        </main>
      )}

      {/* Always mounted, so the video and canvas elements (and the clip pair holding them) survive every state. */}
      <main className={`learn-body ${showing && !isDone ? '' : 'off'}`}>
        <aside className="steps-card" aria-label="Steps">
          <StepList steps={steps} runs={runList} current={isDone ? -1 : idx} onPick={gotoStep} />
          <div className="rail-status">
            <span
              className={`badge ${badge} ${state?.camera_connected ? 'live' : ''}`}
              aria-live="polite"
              title={badge === 'offline' && offlineReason ? offlineReason : undefined}
            >
              <i className="badge-dot" />
              <Caps>{BADGE_LABEL[badge]}</Caps>
            </span>
            <p className="check-meta">
              <span className={metaTop === 'Simulated checks' ? 'sim' : ''}>{metaTop}</span>
              <span className="check-reason">{metaBottom}</span>
            </p>
          </div>
        </aside>

        <section className={`learn-stage ${sideLayout ? 'side' : ''}`} ref={stageRef}>
          <div className="panes">
            <div className={`frame pane live ${showLive ? 'on' : ''}`} style={paneStyle} aria-label="You, live camera">
              <canvas ref={liveRef} role="img" aria-label="Live camera" className={showLive ? (cameraLost ? 'lost' : '') : 'hidden'} />
              {showLive && (
                <span className="tab cobalt pane-tab">
                  {!recording && !cameraLost && <i />}
                  You
                </span>
              )}
              {cameraLost && (
                <p className="live-note" role="status">
                  <span className="note-label">
                    <Caps>Camera lost</Caps>
                  </span>
                  <span className="note-line">Keep going with Next.</span>
                </p>
              )}
              {recording && (
                <span
                  className="tab rec"
                  title={source === 'file' ? 'Frames come from a recorded video, not a live camera' : `Camera source "${source}" is not a known live camera`}
                >
                  <i />
                  Recording
                </span>
              )}
              {!showLive &&
                (down ? (
                  <div className="placeholder">
                    <p className="placeholder-title">Reconnecting to HandOver</p>
                    <p className="placeholder-hint">Your camera shows here again once it is back.</p>
                  </div>
                ) : state?.camera_connected ? (
                  <div className="placeholder">
                    <p className="placeholder-title">Camera connected</p>
                    <p className="placeholder-hint">Waiting for its first picture.</p>
                  </div>
                ) : (
                  <ConnectCamera />
                ))}
            </div>

            <div className="frame pane clip" style={paneStyle}>
              {step && <span className="tab pane-tab">Expert · {clock(step.start)} to {clock(step.end)}</span>}
              <div className={`clip-media ${step ? '' : 'hidden'}`}>
                <video ref={clips.refA} data-slot="a" loop playsInline preload="auto" onLoadedMetadata={onClipMetadata} />
                <video ref={clips.refB} data-slot="b" loop playsInline preload="auto" muted className="standby" onLoadedMetadata={onClipMetadata} />
              </div>
              {soundBlocked && step && (
                <button type="button" className="unmute" onClick={turnOnSound}>
                  <SoundIcon size={14} />
                  Turn on sound
                </button>
              )}
            </div>
          </div>

          <div className="under" ref={underRef}>
            <div className="step-info">
              <p className="eyebrow step-count">{step ? <Caps show={`Step ${pad2(idx + 1)} of ${pad2(total)}`}>{`Step ${idx + 1} of ${total}`}</Caps> : ' '}</p>
              <h1 className="display step-title">{step ? step.title : ' '}</h1>
              <p className="step-do">{doNow}</p>
            </div>

            <div className="controls">
              {activeMistake && (
                <div className="card mistake-banner" role="alert">
                  <span className="mistake-label">
                    <Caps>{activeMistake.label ? `Mistake · ${activeMistake.label}` : 'Mistake'}</Caps>
                  </span>
                  <p className="mistake-text">{activeMistake.message}</p>
                  <div className="mistake-actions">
                    {showStep !== null && (
                      <button type="button" className="btn small" onClick={() => gotoStep(showStep)}>
                        <Caps>{`Show step ${showStep + 1}`}</Caps>
                      </button>
                    )}
                    <button type="button" className="btn small quiet" onClick={dismissMistake}>
                      OK
                    </button>
                  </div>
                </div>
              )}
              <div className="next-wrap">
                <button
                  type="button"
                  className={`btn back ${idx > 0 ? '' : 'hidden'}`}
                  onClick={back}
                  disabled={!step || idx === 0}
                  title="Back (Left Arrow)"
                >
                  Back
                </button>
                <button type="button" className="btn primary next" onClick={next} disabled={!step} title="Next (Right Arrow or Space)">
                  Next
                  <span className="key" aria-hidden="true">
                    Space
                  </span>
                </button>
                {/* The key chip shows the shortcut; this names it for screen readers (and the e2e). */}
                <span className="next-hint sr-only">or press {'→'}</span>
              </div>
            </div>
          </div>
        </section>
      </main>

      {isDone && summary && <Done summary={summary} onRestart={restart} onBack={endLesson} disabled={down} />}

      {popup !== 'none' && <div className="scrim clear" onClick={() => setPopup('none')} />}
      {popup === 'steps' && showing && !isDone && (
        <div className="steps-sheet card" role="dialog" aria-label="Steps">
          <button type="button" className="icon-button small sheet-close" aria-label="Close" onClick={() => setPopup('none')}>
            <CloseIcon />
          </button>
          <StepList steps={steps} runs={runList} current={idx} onPick={gotoStep} />
        </div>
      )}

      {confirmEnd && showing && (
        <div className="scrim" onClick={(e) => e.target === e.currentTarget && setConfirmEnd(false)}>
          <div className="card confirm-card" role="alertdialog" aria-modal="true" aria-labelledby="end-title">
            <h2 id="end-title">End this lesson?</h2>
            <p className="confirm-text">You go back to the lesson list.</p>
            <div className="confirm-actions">
              <button type="button" className="btn ink" onClick={endLesson}>
                End lesson
              </button>
              <button type="button" className="btn quiet" onClick={() => setConfirmEnd(false)} autoFocus>
                Keep going
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
// Gap between the panes and the step block under them, and between the two panes; match learn.css.
const UNDER_GAP = 22
const SIDE_MIN = 280 // .learn-stage.side .under min-width in learn.css
const PANE_GAP = 18

/** "0:31.5" or "31.5" to "00:31": the expert clip's span on the Expert tab. */
function clock(ts: string) {
  const t = Math.floor(toSeconds(ts))
  return `${pad2(Math.floor(t / 60))}:${pad2(t % 60)}`
}

/**
 * Size of each of the two equal panes (live and clip), at the clip's aspect:
 * as wide as half the stage, but never so tall that the step block and the
 * controls under them stop fitting. Portrait clips end up height-bound.
 */
function usePaneBox(stageRef: RefObject<HTMLElement | null>, underRef: RefObject<HTMLElement | null>, aspect: number, side: boolean) {
  const [box, setBox] = useState<{ w: number; h: number } | null>(null)
  useEffect(() => {
    const stage = stageRef.current
    if (!stage) return
    const measure = () => {
      const cs = getComputedStyle(stage)
      const width = stage.clientWidth - parseFloat(cs.paddingLeft) - parseFloat(cs.paddingRight)
      const height = stage.clientHeight - parseFloat(cs.paddingTop) - parseFloat(cs.paddingBottom)
      if (width <= 0 || height <= 0) return // hidden
      // Portrait clips: the step block and controls sit beside the panes (a side column of at least
      // SIDE_MIN px), so the panes take the whole stage height. Landscape: they sit under the panes.
      const room = side ? height : height - (underRef.current?.offsetHeight ?? 0) - UNDER_GAP
      if (room <= 0) return
      const paneWidth = side ? width - SIDE_MIN - UNDER_GAP : width
      const w = Math.min((paneWidth - PANE_GAP) / 2, room * aspect)
      setBox((prev) => {
        const next = { w: Math.floor(w), h: Math.floor(w / aspect) }
        return prev && prev.w === next.w && prev.h === next.h ? prev : next
      })
    }
    measure()
    const ro = new ResizeObserver(measure)
    ro.observe(stage)
    if (underRef.current) ro.observe(underRef.current)
    return () => ro.disconnect()
  }, [stageRef, underRef, aspect, side])
  return box
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

function MoreIcon() {
  return (
    <svg width="18" height="18" viewBox="0 0 24 24" fill="currentColor" aria-hidden="true">
      <circle cx="5.5" cy="12" r="1.7" />
      <circle cx="12" cy="12" r="1.7" />
      <circle cx="18.5" cy="12" r="1.7" />
    </svg>
  )
}
