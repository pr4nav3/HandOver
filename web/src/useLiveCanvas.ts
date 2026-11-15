import { useCallback, useEffect, useRef } from 'react'
import type { RefObject } from 'react'

/**
 * Draws live JPEG frames on a canvas. Only the newest frame is kept: a frame
 * that arrives while another decodes replaces the waiting one, and a decoded
 * frame not yet drawn is closed when a newer one is ready. Drawing happens on
 * the next animation frame, so a hidden tab does no work and nothing queues.
 * No object URLs are made, so none can leak.
 *
 * `onSize` runs when the frame size changes (and on the first frame).
 */
export function useLiveCanvas(canvasRef: RefObject<HTMLCanvasElement | null>, onSize: (w: number, h: number) => void) {
  const onSizeRef = useRef(onSize)
  onSizeRef.current = onSize
  const s = useRef({ alive: true, decoding: false, pending: null as Blob | null, ready: null as ImageBitmap | null, raf: 0 })

  useEffect(() => {
    const st = s.current
    st.alive = true
    return () => {
      st.alive = false
      cancelAnimationFrame(st.raf)
      st.raf = 0
      st.ready?.close()
      st.ready = null
      st.pending = null
    }
  }, [])

  const draw = useCallback(() => {
    const st = s.current
    st.raf = 0
    const bmp = st.ready
    st.ready = null
    if (!bmp) return
    const canvas = canvasRef.current
    if (canvas) {
      if (canvas.width !== bmp.width || canvas.height !== bmp.height) {
        canvas.width = bmp.width
        canvas.height = bmp.height
        onSizeRef.current(bmp.width, bmp.height)
      }
      canvas.getContext('2d', { alpha: false })?.drawImage(bmp, 0, 0)
    }
    bmp.close()
  }, [canvasRef])

  const decode = useCallback(async () => {
    const st = s.current
    if (st.decoding) return
    st.decoding = true
    while (st.pending && st.alive) {
      const blob = st.pending
      st.pending = null
      let bmp: ImageBitmap
      try {
        bmp = await createImageBitmap(blob)
      } catch {
        continue // a broken frame; wait for the next one
      }
      if (!st.alive) {
        bmp.close()
        break
      }
      st.ready?.close()
      st.ready = bmp
      if (!st.raf) st.raf = requestAnimationFrame(draw)
    }
    st.decoding = false
  }, [draw])

  return useCallback(
    (jpeg: Blob) => {
      s.current.pending = jpeg
      void decode()
    },
    [decode],
  )
}
