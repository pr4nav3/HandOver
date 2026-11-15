// Measures how fast the next clip shows after the hub decides, from the
// `advance` message reaching the page:
//   picture: the next step's clip is on screen with a decoded frame (the
//     earlier of a rAF check and requestVideoFrameCallback)
//   moving: the first new frame presented after that (requestVideoFrameCallback)
//
//   PORT=8013 MOCK_AUTO=0 node mock/mock-server.mjs
//   VITE_API_TARGET=http://localhost:8013 npx vite --port 5193
//   APP=http://localhost:5193 MOCK=http://localhost:8013 node e2e/latency.mjs
//
// RTT_MS=40 adds that round trip to every request (Chrome network emulation),
// closer to a phone hotspot than localhost. Prints each sample and the median. Uses installed Google Chrome like
// screenshots.mjs (bundled Chromium cannot decode H.264).

import { chromium } from 'playwright'

const APP = process.env.APP || 'http://localhost:5173'
const MOCK = process.env.MOCK || 'http://localhost:8010'
const LESSON = process.env.LESSON || 'demo-v1'
const ROUNDS = Number(process.env.ROUNDS || 3)
const RTT_MS = Number(process.env.RTT_MS || 0)

const channel = process.env.SHOTS_CHANNEL === 'chromium' ? undefined : 'chrome'
const browser = await chromium.launch({ channel, args: ['--autoplay-policy=no-user-gesture-required'] })
const hook = (p) => fetch(MOCK + p).then((r) => r.json())
const wait = (ms) => new Promise((r) => setTimeout(r, ms))

// Runs in the page before the app: timestamps each `advance` message, then
// records when a visible <video> first shows the target clip (a rAF check of
// its decoded frame, or a presented frame) and when a second, later frame of
// it is presented (the clip is moving).
function probe() {
  window.__lat = []
  const Orig = window.WebSocket
  window.WebSocket = class extends Orig {
    constructor(...args) {
      super(...args)
      // Registered before the app's onmessage, so it runs first.
      this.addEventListener('message', (e) => {
        if (typeof e.data !== 'string' || !e.data.includes('"advance"')) return
        const m = JSON.parse(e.data)
        if (m.type !== 'advance') return
        const t0 = performance.now()
        const target = `clips/${String(m.to + 1).padStart(2, '0')}.mp4`
        const onScreen = (v) => v.src.includes(target) && v.readyState >= 2 && v.checkVisibility({ visibilityProperty: true })
        let first = null // { ms, mediaTime }
        let done = false
        const seen = (mediaTime) => {
          const ms = performance.now() - t0
          if (!first) first = { ms, mediaTime }
          else if (!done && mediaTime > first.mediaTime + 0.01) {
            done = true
            window.__lat.push({ to: m.to, picture: first.ms, moving: ms })
          }
        }
        for (const v of document.querySelectorAll('.clip video')) {
          const cb = (_now, md) => {
            if (done || performance.now() - t0 > 5000) return
            if (onScreen(v)) seen(md.mediaTime)
            v.requestVideoFrameCallback(cb)
          }
          v.requestVideoFrameCallback(cb)
        }
        const poll = () => {
          if (done || performance.now() - t0 > 5000) return
          for (const v of document.querySelectorAll('.clip video')) if (onScreen(v)) seen(v.currentTime)
          requestAnimationFrame(poll)
        }
        poll()
      })
    }
  }
}

const page = await browser.newPage({ viewport: { width: 1440, height: 900 } })
if (RTT_MS) {
  const cdp = await page.context().newCDPSession(page)
  await cdp.send('Network.enable')
  await cdp.send('Network.emulateNetworkConditions', { offline: false, latency: RTT_MS, downloadThroughput: -1, uploadThroughput: -1 })
}
await page.addInitScript(probe)
await hook('/mock/camera?on=1')
await page.goto(`${APP}/#/learn`)
await page.waitForSelector(`.lesson-option[data-id="${LESSON}"]`)
await page.click(`.lesson-option[data-id="${LESSON}"]`)
await page.click('text=Start lesson')
await wait(1500)

const total = (await hook('/mock/goto?step=0')).total
for (let r = 0; r < ROUNDS; r++) {
  for (let s = 0; s < total - 1; s++) {
    await hook(`/mock/goto?step=${s}`)
    // Time to watch the step, as a learner would, so a preload can finish.
    await wait(2500)
    await hook('/mock/advance?reason=camera')
    await wait(1500)
  }
}
const samples = await page.evaluate(() => window.__lat)
await browser.close()

const stats = (name, list) => {
  const v = list.filter((x) => x !== null).sort((a, b) => a - b)
  const med = v.length ? v[Math.floor(v.length / 2)] : NaN
  console.log(`${name}: samples ${v.length}, median ${med.toFixed(1)} ms, min ${v[0]?.toFixed(1)} ms, max ${v.at(-1)?.toFixed(1)} ms`)
}
for (const x of samples) console.log(`advance to step ${x.to + 1}: picture ${x.picture.toFixed(1)} ms, moving ${x.moving.toFixed(1)} ms`)
console.log(`network: ${RTT_MS ? `${RTT_MS} ms added round trip` : 'localhost'}`)
stats('picture on screen', samples.map((x) => x.picture))
stats('first new frame presented', samples.map((x) => x.moving))
const ms = samples.map((x) => x.moving)
if (ms.length < ROUNDS * (total - 1)) {
  console.log(`missing samples: expected ${ROUNDS * (total - 1)}`)
  process.exitCode = 1
}
