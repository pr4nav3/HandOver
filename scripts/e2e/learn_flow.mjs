// Learn screen demo flow in real Chrome, driven by scripts/e2e_demo.py.
//
// Run it through the Python script, which builds the web app, starts a mock hub
// and the replay camera, and tears everything down:
//   .venv/bin/python scripts/e2e_demo.py
//
// Env (set by e2e_demo.py):
//   E2E_APP      app URL, e.g. http://localhost:8095
//   E2E_OUT      folder for screenshots and flow.json
//   E2E_WEB      web/ folder whose node_modules has Playwright
//   E2E_LESSON   lesson id (default demo-v1)
//   E2E_MISTAKE  common_mistake text expected on step 2
//   E2E_HEADED   1 = show the browser
//
// Protocol: prints "E2E_READY" once the page is up; the driver then starts the
// replay camera. Writes flow.json with one row per assertion and exits 1 on failure.
// Selectors use visible text and roles from web/src/Learn.tsx, not class names.

import { createRequire } from 'node:module'
import { mkdirSync, writeFileSync } from 'node:fs'
import { join } from 'node:path'

const APP = process.env.E2E_APP || 'http://localhost:8095'
const OUT = process.env.E2E_OUT || join(process.cwd(), 'e2e-out')
const WEB = process.env.E2E_WEB || join(process.cwd(), 'web')
const LESSON = process.env.E2E_LESSON || 'demo-v1'
const MISTAKE = process.env.E2E_MISTAKE || 'Flip it over first.'
mkdirSync(OUT, { recursive: true })

const { chromium } = createRequire(join(WEB, 'package.json'))('playwright')

const rows = []
const pageErrors = []
const consoleErrors = []
let t0 = 0 // performance.now() when Start lesson was clicked
let failed = false
let stats = {} // done screen numbers, for flow.json
const sleep = (ms) => new Promise((r) => setTimeout(r, ms))
const slug = (s) => s.toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/^-|-$/g, '')

// Runs one assertion. fn returns a detail string or throws. After the first
// failure the rest are recorded as SKIP, since each depends on the one before.
async function check(page, name, fn) {
  const n = String(rows.length + 1).padStart(2, '0')
  const row = { name, status: 'SKIP', ms: 0, at_s: null, detail: '', screenshot: null }
  rows.push(row)
  if (failed) {
    row.detail = 'skipped after an earlier failure'
    return
  }
  const started = performance.now()
  try {
    row.detail = (await fn()) || ''
    row.status = 'PASS'
  } catch (e) {
    row.status = 'FAIL'
    row.detail = String(e?.message || e).split('\n')[0].slice(0, 300)
    failed = true
  }
  row.ms = Math.round(performance.now() - started)
  row.at_s = t0 ? +((performance.now() - t0) / 1000).toFixed(1) : null
  const file = `${n}-${slug(name)}${row.status === 'FAIL' ? '-FAIL' : ''}.png`
  try {
    await page.screenshot({ path: join(OUT, file) })
    row.screenshot = file
  } catch {
    // The page may be gone; the row still counts.
  }
  console.log(`${row.status.padEnd(4)}  ${name}  (${row.ms} ms)  ${row.detail}`)
}

function watch(page, label) {
  page.on('pageerror', (e) => pageErrors.push(`${label}: ${e.message}`))
  page.on('console', (m) => {
    if (m.type() === 'error') consoleErrors.push(`${label}: ${m.text()}`)
  })
}

// Text of the step counter ("Step 2 of 5", "All steps complete").
const stepCount = (page) => page.getByText(/^(Step \d+ of \d+|All steps complete)$/).first()
const waitStep = (page, text, timeout) => page.getByText(text, { exact: true }).first().waitFor({ state: 'visible', timeout })

const browser = await chromium.launch({
  channel: 'chrome',
  headless: process.env.E2E_HEADED !== '1',
  args: ['--autoplay-policy=no-user-gesture-required'],
})

try {
  const ctx = await browser.newContext({ viewport: { width: 1440, height: 900 } })
  // Count chime notes: chime.ts makes one oscillator per note, two per chime.
  await ctx.addInitScript(() => {
    window.__chimeNotes = 0
    const AC = window.AudioContext
    if (AC) {
      const make = AC.prototype.createOscillator
      AC.prototype.createOscillator = function () {
        window.__chimeNotes += 1
        return make.call(this)
      }
    }
  })
  const page = await ctx.newPage()
  watch(page, 'learner')
  const chimes = () => page.evaluate(() => window.__chimeNotes)

  await check(page, 'learn screen opens', async () => {
    await page.goto(`${APP}/#/learn`)
    await page.getByRole('button', { name: 'Start lesson' }).waitFor({ timeout: 15000 })
    await page.locator(`option[value="${LESSON}"]`).waitFor({ state: 'attached', timeout: 10000 })
    return `${LESSON} is in the picker`
  })

  // The spectator is a second viewer in its own browser context. It never
  // clicks Start (that would select the lesson again), it only watches.
  const specCtx = await browser.newContext({ viewport: { width: 1440, height: 900 } })
  const spectator = await specCtx.newPage()
  watch(spectator, 'spectator')
  await spectator.goto(`${APP}/#/learn`)

  console.log('E2E_READY')

  await check(page, 'replay camera connects', async () => {
    // The top bar names the active camera ("Replay: norm.mp4").
    await page.getByTitle('Active camera').waitFor({ state: 'visible', timeout: 20000 })
    return `camera "${(await page.getByTitle('Active camera').innerText()).trim()}"`
  })

  await check(page, 'pick lesson and start', async () => {
    await page.getByRole('combobox').selectOption(LESSON)
    await page.getByRole('button', { name: 'Start lesson' }).click()
    t0 = performance.now()
    await page.getByRole('button', { name: 'Start lesson' }).waitFor({ state: 'detached', timeout: 5000 })
    await waitStep(page, 'Step 1 of 5', 5000)
    return 'picker closed, Step 1 of 5'
  })

  await check(page, 'live frame appears', async () => {
    const img = page.getByRole('img', { name: 'Live camera' })
    await img.waitFor({ state: 'visible', timeout: 10000 })
    await page.waitForFunction(
      () => {
        const i = document.querySelector('img[alt="Live camera"]')
        return !!i && i.src.startsWith('blob:') && i.complete && i.naturalWidth > 0
      },
      null,
      { timeout: 10000 },
    )
    const size = await img.evaluate((i) => `${i.naturalWidth}x${i.naturalHeight}`)
    return `live JPEG ${size}`
  })

  await check(page, 'Recording banner shows', async () => {
    await page.getByText('Recording', { exact: true }).waitFor({ state: 'visible', timeout: 5000 })
    return 'frames come from a file'
  })

  await check(page, 'step 1 clip plays with a caption', async () => {
    const cue = await page.waitForFunction(
      () => {
        const v = document.querySelector('video')
        if (!v || v.paused || v.currentTime <= 0) return false
        const t = [...v.textTracks].find((x) => x.mode === 'showing')
        const c = t?.activeCues?.[0]
        return c ? { text: c.text, src: v.currentSrc } : false
      },
      null,
      { timeout: 6000 },
    )
    const { text, src } = await cue.jsonValue()
    if ((await stepCount(page).innerText()).trim() !== 'Step 1 of 5') throw new Error('step moved before the caption showed')
    if (!/clips\/01\.mp4/.test(src)) throw new Error(`clip is ${src}, expected clips/01.mp4`)
    return `cue "${text}"`
  })

  const chimeBefore = await chimes()
  await check(page, 'camera advance to step 2 with chime', async () => {
    await page.getByText('Verified', { exact: true }).waitFor({ state: 'visible', timeout: 20000 })
    await waitStep(page, 'Step 2 of 5', 5000)
    const deadline = Date.now() + 2000
    let notes = 0
    while ((notes = (await chimes()) - chimeBefore) < 2 && Date.now() < deadline) await sleep(50)
    if (notes < 2) throw new Error(`no chime played (${notes} notes)`)
    return `Verified badge, Step 2 of 5, chime (${notes} notes)`
  })

  // The banner only lasts until the mock check says yes (about 2 s), so start
  // waiting for it now and check the spectator meanwhile.
  const banner = page.getByRole('alert').filter({ hasText: MISTAKE })
  const bannerSeen = banner.waitFor({ state: 'visible', timeout: 12000 }).then(
    () => performance.now(),
    (e) => e,
  )

  await check(spectator, 'spectator mirrors step 2', async () => {
    await waitStep(spectator, 'Step 2 of 5', 3000)
    return 'second viewer shows Step 2 of 5'
  })

  let mistakeAt = 0
  await check(page, 'mistake banner on step 2', async () => {
    const seen = await bannerSeen
    if (seen instanceof Error) throw seen
    mistakeAt = seen
    const step = (await stepCount(page).innerText()).trim()
    if (step !== 'Step 2 of 5') throw new Error(`banner showed on "${step}"`)
    return `"${(await banner.locator('p').first().innerText()).trim()}"`
  })

  await check(page, "I'm fine dismisses it", async () => {
    await page.getByRole('button', { name: "I'm fine" }).click({ timeout: 2000 })
    const clickedAfter = ((performance.now() - mistakeAt) / 1000).toFixed(1)
    await banner.waitFor({ state: 'hidden', timeout: 1500 })
    const step = (await stepCount(page).innerText()).trim()
    // If the step moved, the camera yes may have cleared the banner, not the click.
    if (step !== 'Step 2 of 5') throw new Error(`step moved to "${step}" before the dismissal could be confirmed`)
    return `banner gone, still Step 2 of 5 (clicked ${clickedAfter} s after it showed)`
  })

  await check(page, 'manual step shows manual badge', async () => {
    await waitStep(page, 'Step 3 of 5', 20000)
    await page.getByText('Manual step', { exact: true }).waitFor({ state: 'visible', timeout: 3000 })
    return 'Step 3 of 5, Manual step'
  })

  await check(page, 'Next advances the manual step', async () => {
    await page.getByRole('button', { name: 'Next', exact: true }).click()
    await waitStep(page, 'Step 4 of 5', 3000)
    return 'Step 4 of 5'
  })

  await check(page, 'Done shows real stats', async () => {
    await page.getByText('Lesson complete', { exact: true }).waitFor({ state: 'visible', timeout: 45000 })
    await waitStep(page, 'All steps complete', 2000)
    stats = await page.evaluate(() => {
      const out = {}
      for (const d of document.querySelectorAll('dl div')) {
        const k = d.querySelector('dt')?.textContent?.trim()
        if (k) out[k] = d.querySelector('dd')?.textContent?.trim() ?? ''
      }
      out.__rows = [...document.querySelectorAll('table tbody tr')].map((r) => r.textContent.trim())
      return out
    })
    const want = { 'Checked by camera': '4', 'Marked done': '1', 'Mistakes caught': '1', Expert: '0:40' }
    const bad = Object.entries(want).filter(([k, v]) => stats[k] !== v).map(([k, v]) => `${k} is ${stats[k] ?? 'missing'}, expected ${v}`)
    if (!/^\d+:\d\d$/.test(stats['Your time'] ?? '') || stats['Your time'] === '0:00') bad.push(`Your time is ${stats['Your time'] ?? 'missing'}`)
    if (stats.__rows.length !== 5) bad.push(`${stats.__rows.length} step rows, expected 5`)
    if (bad.length) throw new Error(bad.join('; '))
    return `time ${stats['Your time']}, expert ${stats.Expert}, camera ${stats['Checked by camera']}, by hand ${stats['Marked done']}, mistakes ${stats['Mistakes caught']}`
  })

  await check(spectator, 'spectator mirrors done', async () => {
    await waitStep(spectator, 'All steps complete', 3000)
    return 'second viewer shows All steps complete'
  })
} catch (e) {
  rows.push({ name: 'flow ran', status: 'FAIL', ms: 0, at_s: null, detail: String(e?.message || e).split('\n')[0], screenshot: null })
} finally {
  // Errors are judged last so every screen above is covered.
  rows.push({
    name: 'no page errors',
    status: pageErrors.length ? 'FAIL' : 'PASS',
    ms: 0,
    at_s: null,
    detail: pageErrors.length ? pageErrors.slice(0, 3).join(' | ') : 'none on either page',
    screenshot: null,
  })
  rows.push({
    name: 'no console errors',
    status: consoleErrors.length ? 'FAIL' : 'PASS',
    ms: 0,
    at_s: null,
    detail: consoleErrors.length ? consoleErrors.slice(0, 3).join(' | ') : 'none on either page',
    screenshot: null,
  })
  writeFileSync(join(OUT, 'flow.json'), JSON.stringify({ app: APP, lesson: LESSON, rows, stats, pageErrors, consoleErrors }, null, 2))
  await browser.close()
}

process.exitCode = rows.some((r) => r.status === 'FAIL') ? 1 : 0
