// Checks server/static/capture.html against the mock server with Chrome's fake camera:
// hello name, status words, the mistake card, camera revive after the track ends, and a
// failed revive that stops instead of claiming to run.
//
//   PORT=8013 MOCK_AUTO=0 node mock/mock-server.mjs
//   MOCK=http://localhost:8013 node e2e/capture.mjs

import { chromium } from 'playwright'

const MOCK = process.env.MOCK || 'http://localhost:8010'
const problems = []
const check = (ok, msg) => (ok ? console.log('ok  ', msg) : problems.push(msg))
const hook = (p) => fetch(MOCK + p).then((r) => r.json())

const browser = await chromium.launch({
  channel: process.env.SHOTS_CHANNEL === 'chromium' ? undefined : 'chrome',
  args: ['--use-fake-ui-for-media-stream', '--use-fake-device-for-media-stream'],
})
const page = await browser.newPage({ viewport: { width: 390, height: 844 }, userAgent: 'Mozilla/5.0 (iPhone; CPU iPhone OS 18_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/18.0 Mobile/15E148 Safari/604.1' })
page.on('pageerror', (e) => problems.push(`pageerror: ${e.message}`))
await page.addInitScript(() => localStorage.clear())
await hook('/mock/select?id=demo-v1')
await hook('/mock/goto?step=1')
await page.goto(`${MOCK}/capture`)
await page.click('#start')
await page.waitForFunction(() => document.getElementById('conn').textContent === 'Connected', null, { timeout: 10000 })
await page.waitForTimeout(800)

const stats = await hook('/mock/camera_stats')
check(stats.hello?.name === 'iPhone Safari' && stats.hello?.source === 'browser', `hello name from the device (${stats.hello?.name})`)
const sub = await page.locator('#step').innerText()
check(/^Step 2 of \d+ · Watching$/.test(sub), `status in words, not raw (${sub})`)

await hook('/mock/mistake?kind=behind')
await page.waitForSelector('#mistake:not([hidden])', { timeout: 3000 }).catch(() => {})
const card = await page.locator('#mistake').innerText().catch(() => '')
check(card.length > 0 && (await page.locator('#mistake').isVisible()), `mistake card shows (${card})`)
await hook('/mock/goto?step=2')
await page.waitForTimeout(400)
check(!(await page.locator('#mistake').isVisible()), 'mistake card clears on step change')

// The track ends (another app took the camera): a fresh one is opened and frames keep coming.
const before = await page.evaluate(() => document.getElementById('video').srcObject.id)
await page.evaluate(() => {
  const t = document.getElementById('video').srcObject.getVideoTracks()[0]
  t.stop()
  t.dispatchEvent(new Event('ended'))
})
await page.waitForFunction((id) => document.getElementById('video').srcObject?.id && document.getElementById('video').srcObject.id !== id, before, { timeout: 5000 }).catch(() => {})
await hook('/mock/camera_stats?reset=1')
await page.waitForTimeout(1500)
const after = await hook('/mock/camera_stats')
check(after.frames >= 2, `camera revives after the track ends (${after.frames} frames in 1.5 s)`)

// A revive that fails stops the page instead of leaving it "running" with no camera.
await page.evaluate(() => {
  navigator.mediaDevices.getUserMedia = () => Promise.reject(new DOMException('busy', 'NotReadableError'))
  const t = document.getElementById('video').srcObject.getVideoTracks()[0]
  t.stop()
  t.dispatchEvent(new Event('ended'))
})
await page.waitForTimeout(800)
const btn = await page.locator('#start').innerText()
const err = await page.locator('#err').innerText()
check(btn === 'Start camera' && err.includes('NotReadableError'), `failed revive stops and says why (${btn}; ${err})`)
await page.screenshot({ path: new URL('../screenshots/15-capture-revive-failed.png', import.meta.url).pathname })
await browser.close()

if (problems.length) {
  console.log('Problems:\n' + problems.join('\n'))
  process.exitCode = 1
} else {
  console.log('No problems found')
}
