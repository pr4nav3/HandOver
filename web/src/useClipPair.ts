import { useMemo, useRef } from 'react'

/**
 * Two stacked <video> elements for the learn clip: one on screen and a muted,
 * hidden standby that holds the next step's clip and captions, buffered and
 * paused on its first frame. A step change to the standby's clip is a swap:
 * show it and play, no load() and no network wait. Any other change loads into
 * the on-screen element as before.
 *
 * Measured with e2e/latency.mjs: the new clip's first frame is on screen within
 * one display frame of the advance message. Keeping the standby playing (and
 * rewinding it on swap) was tried; it was no faster and decodes two videos.
 *
 * The standby is marked with the `standby` class, set here and never by React.
 */
export function useClipPair(onSwap?: (video: HTMLVideoElement) => void) {
  const refA = useRef<HTMLVideoElement>(null)
  const refB = useRef<HTMLVideoElement>(null)
  const onSwapRef = useRef(onSwap)
  onSwapRef.current = onSwap

  return useMemo(() => {
    let active = 0
    // The clip URL each element holds, so a swap is only taken when it is the right one.
    const held = ['', '']
    const video = (i: number) => (i === 0 ? refA : refB).current

    const load = (i: number, clip: string, captions: string, onScreen: boolean) => {
      const v = video(i)
      if (!v) return
      held[i] = clip
      setTrack(v, captions, onScreen ? 'showing' : 'hidden')
      v.muted = !onScreen
      v.src = clip
      v.load()
    }

    return {
      refA,
      refB,
      /** The element on screen. */
      active: () => video(active),

      /** Puts `clip` on screen. Returns how: already there, swapped in, or loaded. */
      show(clip: string, captions: string, play: boolean): 'same' | 'swap' | 'load' {
        if (held[active] === clip) return 'same'
        const prev = video(active)
        const next = video(1 - active)
        if (!prev || !next) return 'same'
        if (held[1 - active] !== clip) {
          load(active, clip, captions, true)
          if (play) prev.play().catch(() => {})
          return 'load'
        }
        active = 1 - active
        // A buffered clip waits at 0; seek only if something moved it.
        if (next.currentTime !== 0) next.currentTime = 0
        next.muted = false
        for (const t of next.textTracks) t.mode = 'showing'
        for (const t of prev.textTracks) t.mode = 'disabled'
        next.classList.remove('standby')
        prev.classList.add('standby')
        if (play) next.play().catch(() => {})
        prev.pause()
        prev.muted = true
        // Rewind off screen so a later swap back (Back) needs no seek on screen.
        prev.currentTime = 0
        onSwapRef.current?.(next)
        return 'swap'
      },

      /** Buffers `clip` in the standby element, unless one of the two already holds it. */
      preload(clip: string, captions: string) {
        if (!clip || held[0] === clip || held[1] === clip) return
        load(1 - active, clip, captions, false)
      },
    }
  }, [])
}

/** Replaces a video's caption track. `hidden` loads the cues without drawing them. */
function setTrack(video: HTMLVideoElement, src: string, mode: TextTrackMode) {
  // Disable the old track first so its last cue does not linger over the new clip.
  video.querySelectorAll('track').forEach((t) => {
    t.track.mode = 'disabled'
    t.remove()
  })
  if (!src) return
  const track = document.createElement('track')
  track.kind = 'captions'
  track.srclang = 'en'
  track.label = 'English'
  track.src = src
  video.appendChild(track)
  track.track.mode = mode
}
