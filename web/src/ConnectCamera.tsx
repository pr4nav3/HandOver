import { useEffect, useMemo, useState } from 'react'
import { encode } from 'uqr'
import { CameraIcon } from './icons'

// Hosts a phone cannot reach: a QR code would point it at itself.
const LOCAL_HOST = /^(localhost|127\.\d+\.\d+\.\d+|\[::1\]|::1|0\.0\.0\.0)$/i

// The hub serves https on this port when it has certificates (scripts/run_server.sh).
// Phone browsers only give a page the camera over https.
const HTTPS_PORT = 8443

/** The capture page a phone can open on this hub, or null when the page is on localhost. */
export function captureAddress(loc: Pick<Location, 'protocol' | 'host' | 'hostname'> = location) {
  if (LOCAL_HOST.test(loc.hostname)) return null
  return loc.protocol === 'https:' ? `${loc.protocol}//${loc.host}/capture` : `https://${loc.hostname}:${HTTPS_PORT}/capture`
}

/** On localhost, the hub's own capture URL (GET /api/hub-info) so the QR code still works; null if unknown. */
function useHubCapture() {
  const [url, setUrl] = useState<string | null>(null)
  useEffect(() => {
    if (!LOCAL_HOST.test(location.hostname)) return
    let live = true
    fetch('/api/hub-info')
      .then((r) => (r.ok ? r.json() : null))
      .then((j: { capture_url?: string | null } | null) => live && j?.capture_url && setUrl(j.capture_url))
      .catch(() => {})
    return () => {
      live = false
    }
  }, [])
  return url
}

/** The live pane before any camera is connected: how to connect one. */
export function ConnectCamera() {
  const hubCapture = useHubCapture()
  const capture = useMemo(() => captureAddress() ?? hubCapture, [hubCapture])
  const port = location.port || (location.protocol === 'https:' ? '443' : '80')
  return (
    <div className="connect">
      <div className="connect-text">
        <CameraIcon size={32} className="connect-icon" />
        <p className="connect-title">Connect a camera</p>
        <p className="connect-copy">
          {capture ? 'Scan with a phone to use it as the camera.' : `A phone cannot reach localhost. Open this page at the computer's network address, like 192.168.1.20:${port}.`}
        </p>
        <a className="quiet connect-local" href="/capture" target="_blank" rel="noopener">
          Use this computer's camera
        </a>
      </div>
      {capture && (
        <figure className="connect-qr">
          <QrCode text={capture} label="QR code for the camera page" />
          <figcaption>
            <code>{capture.replace(/^https?:\/\//, '')}</code>
          </figcaption>
        </figure>
      )}
    </div>
  )
}

/** A QR code drawn locally as one SVG path. Dark modules on white, with a quiet border. */
function QrCode({ text, label }: { text: string; label: string }) {
  const { size, d } = useMemo(() => {
    const qr = encode(text, { ecc: 'M', border: 2 })
    let path = ''
    qr.data.forEach((row, y) =>
      row.forEach((on, x) => {
        if (on) path += `M${x} ${y}h1v1h-1z`
      }),
    )
    return { size: qr.size, d: path }
  }, [text])
  return (
    <svg className="qr" viewBox={`0 0 ${size} ${size}`} role="img" aria-label={label} shapeRendering="crispEdges">
      <title>{text}</title>
      <rect width={size} height={size} fill="#fff" />
      <path d={d} fill="#000" />
    </svg>
  )
}
