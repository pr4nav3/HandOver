import { useEffect, useRef, useState } from 'react'

// Minimal typings for the Chrome Web Speech API.
interface RecognitionResult {
  isFinal: boolean
  0: { transcript: string; confidence?: number }
}
interface RecognitionEvent {
  resultIndex: number
  results: { length: number; [i: number]: RecognitionResult }
}
interface Recognition {
  continuous: boolean
  interimResults: boolean
  lang: string
  onresult: ((e: RecognitionEvent) => void) | null
  onend: (() => void) | null
  onerror: ((e: { error: string }) => void) | null
  onstart: (() => void) | null
  start(): void
  stop(): void
  abort(): void
}
type RecognitionCtor = new () => Recognition

function getCtor(): RecognitionCtor | undefined {
  const w = window as unknown as { SpeechRecognition?: RecognitionCtor; webkitSpeechRecognition?: RecognitionCtor }
  return w.SpeechRecognition ?? w.webkitSpeechRecognition
}

export const voiceSupported = () => getCtor() !== undefined

export type VoiceCommand = 'next' | 'back'

// Whole utterances that count. Anything longer or different is ignored, so
// the expert's narration ("next, fold it back...") cannot trigger a step.
const PHRASES = new Map<string, VoiceCommand>([
  ['next', 'next'],
  ['next step', 'next'],
  ['back', 'back'],
  ['go back', 'back'],
])
// While the clip is audible, also require the recognizer to be this sure.
const MIN_CONFIDENCE_WHILE_AUDIBLE = 0.6

/** The command for a final transcript, or null. At most two words. */
export function matchCommand(transcript: string): VoiceCommand | null {
  const words = transcript.toLowerCase().match(/[a-z]+/g) ?? []
  if (!words.length || words.length > 2) return null
  return PHRASES.get(words.join(' ')) ?? null
}

/**
 * Continuous listening for "next" and "back". Only short final utterances
 * that are exactly a command count. While `isAudible()` says the clip is
 * playing through the speakers, a confidence of at least 0.6 is required
 * too. Each utterance triggers at most once (tracked per result index), plus
 * a short cooldown so one spoken word cannot double fire. Restarts itself.
 */
export function useVoice(enabled: boolean, onCommand: (cmd: VoiceCommand) => void, isAudible: () => boolean = () => false) {
  const cbRef = useRef(onCommand)
  cbRef.current = onCommand
  const audibleRef = useRef(isAudible)
  audibleRef.current = isAudible
  const [listening, setListening] = useState(false)

  useEffect(() => {
    const Ctor = getCtor()
    if (!enabled || !Ctor) return

    let stopped = false
    let restartTimer: number | undefined
    let fired = new Set<number>()
    let lastFire = 0
    const rec = new Ctor()
    rec.continuous = true
    rec.interimResults = false
    rec.lang = 'en-US'

    rec.onstart = () => {
      fired = new Set()
      setListening(true)
    }
    rec.onresult = (e) => {
      for (let i = e.resultIndex; i < e.results.length; i++) {
        const result = e.results[i]
        if (fired.has(i) || !result.isFinal) continue
        fired.add(i)
        const cmd = matchCommand(result[0].transcript)
        if (!cmd) continue
        if (audibleRef.current()) {
          const confidence = result[0].confidence
          if (!confidence || confidence < MIN_CONFIDENCE_WHILE_AUDIBLE) continue
        }
        const now = performance.now()
        if (now - lastFire < 1200) continue
        lastFire = now
        cbRef.current(cmd)
      }
    }
    const restart = (delay: number) => {
      setListening(false)
      if (stopped) return
      window.clearTimeout(restartTimer)
      restartTimer = window.setTimeout(() => {
        try {
          rec.start()
        } catch {
          // Already started; ignore.
        }
      }, delay)
    }
    let nextDelay = 250
    rec.onend = () => {
      restart(nextDelay)
      nextDelay = 250
    }
    rec.onerror = (e) => {
      // Permission denied: stop trying, the browser will not ask again.
      if (e.error === 'not-allowed' || e.error === 'service-not-allowed') stopped = true
      // Silence is normal; anything else (network, audio) waits a bit longer.
      else if (e.error !== 'no-speech' && e.error !== 'aborted') nextDelay = 2000
    }

    try {
      rec.start()
    } catch {
      restart(1000)
    }
    return () => {
      stopped = true
      window.clearTimeout(restartTimer)
      rec.onend = null
      rec.abort()
      setListening(false)
    }
  }, [enabled])

  return { listening }
}
