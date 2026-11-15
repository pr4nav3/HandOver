// Spoken cues for the Learn screen, in the lessons' own voice: small mp3 files
// rendered by `python -m server.voice --cues web/public/voice` and served at
// /voice/<name>.mp3. One shared audio element, so cues never overlap (a new cue
// stops the previous one), and browser speech as the fallback when a file is
// missing and for per-lesson text (a step's common mistake).
//
// While a cue plays the expert clip is ducked to DUCK_VOLUME and restored after.
// Playback errors are swallowed: headless runs have no audio output, and a
// refused play() must never surface.

export type CueName = 'done-moving-on' | 'lesson-complete' | 'checks-off' | 'camera-lost' | 'ahead' | 'still-step'

/** The line in each file, also what browser speech says if the file is missing. Matches APP_CUES in server/voice.py. */
const CUE_TEXT: Record<CueName, string> = {
  'done-moving-on': "That's it. Next step.",
  'lesson-complete': "That's the whole thing. Nicely done.",
  'checks-off': "I can't see well right now. Tap Next when you're done.",
  'camera-lost': 'I lost the camera. Keep going with Next.',
  ahead: "You're ahead of me. Let's go back one step.",
  'still-step': 'Not quite yet. Take another look at the clip.',
}

const STORAGE_KEY = 'handover.voiceCues'
const DUCK_VOLUME = 0.35
const SPEECH_RATE = 0.95
// A cue that never reports its end (no audio device, a stuck voice) still gives the clip its volume back.
const MAX_CUE_MS = 8000

let audio: HTMLAudioElement | null = null
const missing = new Set<string>()
// Bumped by every play, say and stop: callbacks from an older cue see a different number and do nothing.
let token = 0
let delayTimer: number | undefined
let safetyTimer: number | undefined
let duckTargets: () => (HTMLMediaElement | null | undefined)[] = () => []
// Elements turned down, with the volume to give back.
const ducked = new Map<HTMLMediaElement, number>()

function readEnabled(): boolean {
  try {
    return window.localStorage.getItem(STORAGE_KEY) !== '0'
  } catch {
    return true
  }
}

let enabled = readEnabled()

export function cuesEnabled() {
  return enabled
}

/** Turns cues on or off, remembered in this browser. Off also stops a cue that is playing. */
export function setCuesEnabled(on: boolean) {
  enabled = on
  try {
    window.localStorage.setItem(STORAGE_KEY, on ? '1' : '0')
  } catch {
    // private mode: the choice lasts for this page only
  }
  if (!on) stopCue()
}

/** The media to turn down while a cue plays (both clip elements, so a swap mid-cue stays ducked). */
export function setDuckTargets(get: () => (HTMLMediaElement | null | undefined)[]) {
  duckTargets = get
}

/** Call from a user gesture (like unlockAudio): makes the shared element and fetches every cue once. */
export function unlockCues() {
  if (audio || typeof Audio === 'undefined') return
  audio = new Audio()
  audio.preload = 'auto'
  audio.volume = 1
  for (const name of Object.keys(CUE_TEXT)) {
    // Warms the cache; a 404 (or an HTML fallback page) marks the cue for browser speech.
    fetch(cueUrl(name))
      .then((r) => {
        const type = r.headers.get('content-type') ?? ''
        if (!r.ok || !(type.startsWith('audio/') || type === 'application/octet-stream')) missing.add(name)
      })
      .catch(() => {})
  }
}

function cueUrl(name: string) {
  return `/voice/${name}.mp3`
}

function duck() {
  for (const el of duckTargets()) {
    if (!el || ducked.has(el)) continue
    ducked.set(el, el.volume)
    el.volume = Math.min(el.volume, DUCK_VOLUME)
  }
}

function unduck() {
  for (const [el, volume] of ducked) el.volume = volume
  ducked.clear()
}

function clearTimers() {
  window.clearTimeout(delayTimer)
  window.clearTimeout(safetyTimer)
}

/** Ends whatever cue is playing or waiting, and gives the clip its volume back. */
export function stopCue() {
  token++
  clearTimers()
  if (audio) {
    try {
      audio.pause()
    } catch {
      // nothing to stop
    }
  }
  if ('speechSynthesis' in window) window.speechSynthesis.cancel()
  unduck()
}

function finish(my: number) {
  if (my !== token) return
  window.clearTimeout(safetyTimer)
  unduck()
}

function armSafety(my: number, ms: number) {
  window.clearTimeout(safetyTimer)
  safetyTimer = window.setTimeout(() => finish(my), ms)
}

function speakNow(text: string, my: number) {
  if (!('speechSynthesis' in window) || typeof SpeechSynthesisUtterance === 'undefined') return finish(my)
  try {
    const u = new SpeechSynthesisUtterance(text)
    u.rate = SPEECH_RATE
    u.onend = () => finish(my)
    u.onerror = () => finish(my)
    window.speechSynthesis.cancel()
    duck()
    armSafety(my, Math.max(3000, text.split(/\s+/).length * 600 + 1500))
    window.speechSynthesis.speak(u)
  } catch {
    finish(my)
  }
}

function playNow(name: CueName, my: number) {
  if (!audio || missing.has(name)) return speakNow(CUE_TEXT[name], my)
  const el = audio
  el.onended = () => finish(my)
  el.onerror = () => {
    if (my !== token) return
    missing.add(name)
    speakNow(CUE_TEXT[name], my)
  }
  el.volume = 1
  el.src = cueUrl(name)
  duck()
  armSafety(my, MAX_CUE_MS)
  try {
    el.play().catch((e: unknown) => {
      if (my !== token) return
      // No permission to play sound yet: speech would be refused too, so just give the volume back.
      if ((e as Error)?.name === 'NotAllowedError' || (e as Error)?.name === 'AbortError') return finish(my)
      missing.add(name)
      speakNow(CUE_TEXT[name], my)
    })
  } catch {
    finish(my)
  }
}

function schedule(delayMs: number, run: (my: number) => void) {
  if (!enabled) return
  stopCue()
  const my = token
  if (delayMs > 0) delayTimer = window.setTimeout(() => my === token && run(my), delayMs)
  else run(my)
}

/** Plays /voice/<name>.mp3, after `delayMs` (to follow the chime). Stops any cue before it. */
export function play(name: CueName, delayMs = 0) {
  schedule(delayMs, (my) => playNow(name, my))
}

/** Says `text` with the browser's voice, calmly. For per-lesson lines such as a step's common mistake. */
export function say(text: string, delayMs = 0) {
  const t = text.trim()
  if (!t) return
  schedule(delayMs, (my) => speakNow(t, my))
}
