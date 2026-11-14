import { useCallback, useEffect, useRef, useState } from 'react'
import type { AdvanceMsg, StateMsg } from './api'

interface Handlers {
  onFrame: (jpeg: Blob) => void
  onState: (msg: StateMsg) => void
  onAdvance: (msg: AdvanceMsg) => void
  onError?: (message: string) => void
  /** Called each time a connection opens, before queued messages are sent. */
  onOpen?: () => void
}

// Messages sent while the socket is not open wait here, oldest dropped first.
const QUEUE_MAX = 20

/**
 * Keeps one /ws/ui connection open, reconnecting with backoff.
 * `down` only turns true after a short grace period, so a quick blip
 * or the first connect does not flash the "Reconnecting" note.
 * Messages sent while disconnected are queued and sent on the next open.
 */
export function useUiSocket(handlers: Handlers) {
  const handlersRef = useRef(handlers)
  handlersRef.current = handlers
  const wsRef = useRef<WebSocket | null>(null)
  const queueRef = useRef<string[]>([])
  const [down, setDown] = useState(false)

  useEffect(() => {
    let closed = false
    let retry = 0
    let retryTimer: number | undefined
    let downTimer: number | undefined

    const markDown = () => {
      if (downTimer === undefined) downTimer = window.setTimeout(() => setDown(true), 1500)
    }
    const markUp = () => {
      window.clearTimeout(downTimer)
      downTimer = undefined
      setDown(false)
    }

    const connect = () => {
      const proto = location.protocol === 'https:' ? 'wss' : 'ws'
      const ws = new WebSocket(`${proto}://${location.host}/ws/ui`)
      ws.binaryType = 'blob'
      wsRef.current = ws

      ws.onopen = () => {
        retry = 0
        markUp()
        handlersRef.current.onOpen?.()
        const queued = queueRef.current
        queueRef.current = []
        for (const text of queued) ws.send(text)
      }
      ws.onmessage = (ev) => {
        if (typeof ev.data !== 'string') {
          handlersRef.current.onFrame(ev.data as Blob)
          return
        }
        try {
          const msg = JSON.parse(ev.data)
          if (msg.type === 'state') handlersRef.current.onState(msg as StateMsg)
          else if (msg.type === 'advance') handlersRef.current.onAdvance(msg as AdvanceMsg)
          else if (msg.type === 'error') handlersRef.current.onError?.(String(msg.message ?? 'Server error'))
        } catch {
          // Ignore anything that is not valid JSON.
        }
      }
      ws.onclose = () => {
        if (wsRef.current === ws) wsRef.current = null
        if (closed) return
        markDown()
        const delay = Math.min(5000, 400 * 2 ** retry)
        retry += 1
        retryTimer = window.setTimeout(connect, delay)
      }
      ws.onerror = () => ws.close()
    }

    connect()
    markDown()
    return () => {
      closed = true
      window.clearTimeout(retryTimer)
      window.clearTimeout(downTimer)
      wsRef.current?.close()
      wsRef.current = null
    }
  }, [])

  const send = useCallback((msg: object) => {
    const text = JSON.stringify(msg)
    const ws = wsRef.current
    if (ws && ws.readyState === WebSocket.OPEN) {
      ws.send(text)
      return
    }
    const queue = queueRef.current
    queue.push(text)
    if (queue.length > QUEUE_MAX) queue.shift()
  }, [])

  return { down, send }
}
