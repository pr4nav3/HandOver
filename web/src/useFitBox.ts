import { useEffect, useState } from 'react'
import type { RefObject } from 'react'

/**
 * Largest width and height with the given aspect ratio that fit inside the
 * container, after leaving room for an optional element below it (plus
 * `gap`). Lets a video box hug its content so captions sit on the picture
 * instead of in a letterbox.
 */
export function useFitBox(
  ref: RefObject<HTMLElement | null>,
  aspect: number,
  below?: RefObject<HTMLElement | null>,
  gap = 0,
) {
  const [box, setBox] = useState<{ w: number; h: number } | null>(null)
  useEffect(() => {
    const el = ref.current
    if (!el) return
    const measure = () => {
      const { width, height } = el.getBoundingClientRect()
      const room = height - (below?.current ? below.current.offsetHeight + gap : 0)
      if (!width || room <= 0) return
      const w = Math.min(width, room * aspect)
      setBox({ w: Math.floor(w), h: Math.floor(w / aspect) })
    }
    measure()
    const ro = new ResizeObserver(measure)
    ro.observe(el)
    if (below?.current) ro.observe(below.current)
    return () => ro.disconnect()
  }, [ref, aspect, below, gap])
  return box
}
