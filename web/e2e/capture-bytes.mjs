// Measures what capture.html sends: frames per second, bytes per frame and
// frame size, using Chrome's fake camera fed from a video file.
//
//   ffmpeg -f lavfi -i testsrc2=size=1280x720:rate=10 -vf noise=alls=12:allf=t -t 4 -pix_fmt yuv420p /tmp/cam.y4m
//   PORT=8013 node mock/mock-server.mjs
//   MOCK=http://localhost:8013 CAM=/tmp/cam.y4m node e2e/capture-bytes.mjs
//
// The mock serves server/static/capture.html at /capture and counts frames on /ws/camera.

import { chromium } from 'playwright'

const MOCK = process.env.MOCK || 'http://localhost:8010'
const CAM = process.env.CAM || '/tmp/cam.y4m'
const SECONDS = Number(process.env.SECONDS || 10)

const browser = await chromium.launch({
  channel: process.env.SHOTS_CHANNEL === 'chromium' ? undefined : 'chrome',
  args: ['--use-fake-ui-for-media-stream', '--use-fake-device-for-media-stream', `--use-file-for-fake-video-capture=${CAM}`],
})
const stats = (q = '') => fetch(`${MOCK}/mock/camera_stats${q}`).then((r) => r.json())
const page = await browser.newPage()
await page.goto(`${MOCK}/capture`)
await page.click('#start')
await page.waitForFunction(() => document.getElementById('conn').textContent === 'Connected', null, { timeout: 10000 })
await page.waitForTimeout(1500)
await stats('?reset=1')
await page.waitForTimeout(SECONDS * 1000)
const s = await stats()
const shown = await page.locator('#stats').innerText()
await browser.close()

const kb = (n) => (n / 1024).toFixed(1)
const sorted = [...s.sizes].sort((a, b) => a - b)
console.log(`frames ${s.frames} in ${SECONDS} s (${(s.frames / SECONDS).toFixed(2)} fps)`)
console.log(`bytes per frame: mean ${kb(s.bytes / Math.max(1, s.frames))} KB, median ${kb(sorted[Math.floor(sorted.length / 2)] ?? 0)} KB`)
console.log(`frame size ${s.last}`)
console.log(`page says: ${shown}`)
