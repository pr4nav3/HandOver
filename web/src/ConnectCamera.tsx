import { useMemo } from 'react'
import { encode } from 'uqr'

// Hosts a phone cannot reach: the QR codes would point it at itself.
const LOCAL_HOST = /^(localhost|127\.\d+\.\d+\.\d+|\[::1\]|::1|0\.0\.0\.0)$/i

// The hub serves https on this port when it has certificates (scripts/run_server.sh).
// Phone browsers only give a page the camera over https.
const HTTPS_PORT = 8443

/** Addresses a phone can use to reach this hub, or null when the page is on localhost. */
export function phoneAddresses(loc: Pick<Location, 'protocol' | 'host' | 'hostname'> = location) {
  if (LOCAL_HOST.test(loc.hostname)) return null
  const hub = `${loc.protocol}//${loc.host}`
  const capture = loc.protocol === 'https:' ? `${hub}/capture` : `https://${loc.hostname}:${HTTPS_PORT}/capture`
  return { hub, app: `handover://connect?hub=${encodeURIComponent(hub)}`, capture }
}

/** The live pane before any camera is connected: how to connect one. */
export function ConnectCamera() {
  const addr = useMemo(() => phoneAddresses(), [])
  const port = location.port || (location.protocol === 'https:' ? '443' : '80')
  return (
    <div className="connect">
      <p className="connect-title">Connect a camera</p>
      <p className="connect-text">Open HandOver on your phone and tap Be the Camera, or use this computer's camera.</p>
      {addr ? (
        <div className="connect-codes">
          <figure>
            <QrCode text={addr.app} label="QR code for the HandOver app" />
            <figcaption>HandOver app</figcaption>
          </figure>
          <figure>
            <QrCode text={addr.capture} label="QR code for the phone browser" />
            <figcaption>
              Phone browser
              <code>{addr.capture.replace(/^https?:\/\//, '')}</code>
            </figcaption>
          </figure>
        </div>
      ) : (
        <p className="connect-hint">
          This page is on localhost, so a phone cannot reach it. Open HandOver at this computer's network address, like{' '}
          <code>192.168.1.20:{port}</code>, to see QR codes.
        </p>
      )}
      <a className="primary connect-button" href="/capture" target="_blank" rel="noopener">
        Use this computer's camera
      </a>
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
