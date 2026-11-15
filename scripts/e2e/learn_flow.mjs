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
// Selectors use visible text and roles from web/src/Community.tsx, Learn.tsx and
// Done.tsx, not class names. The learner starts on #/community and picks the
// lesson's card, which opens #/learn/<id> and selects it on the hub.

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
let t0 = 0 // performance.now() when the lesson card was clicked
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

// Text of the step counter ("Step 2 of 5"). Done hides it and shows "Lesson complete".
const stepCount = (page) => page.getByText(/^Step \d+ of \d+$/).first()
const waitStep = (page, text, timeout) => page.getByText(text, { exact: true }).first().waitFor({ state: 'visible', timeout })

// Installed Chrome decodes the H.264 clips; without it, installed Edge does too.
// E2E_CHANNEL pins one (chrome or msedge).
async function launch() {
  const channels = process.env.E2E_CHANNEL ? [process.env.E2E_CHANNEL] : ['chrome', 'msedge']
  let last
  for (const channel of channels) {
    try {
      const b = await chromium.launch({
        channel,
        headless: process.env.E2E_HEADED !== '1',
        args: ['--autoplay-policy=no-user-gesture-required'],
      })
      console.log(`browser ${channel} ${b.version()}`)
      return b
    } catch (e) {
      last = e
    }
  }
  throw last
}
const browser = await launch()

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

  // The lesson's card shows its title; the hub's list gives it.
  let lessonTitle = LESSON
  const card = () => page.getByRole('button', { name: lessonTitle }).first()
  await check(page, 'community lists the lesson', async () => {
    const list = await fetch(`${APP}/api/lessons`).then((r) => r.json())
    lessonTitle = list.find((l) => l.id === LESSON)?.title || LESSON
    await page.goto(`${APP}/#/community`)
    await card().waitFor({ timeout: 15000 })
    return `card "${lessonTitle}"`
  })

  // The spectator is a second viewer in its own browser context, on plain
  // #/learn: it never selects a lesson (that would restart it), it only watches.
  const specCtx = await browser.newContext({ viewport: { width: 1440, height: 900 } })
  const spectator = await specCtx.newPage()
  watch(spectator, 'spectator')
  await spectator.goto(`${APP}/#/learn`)

  console.log('E2E_READY')

  await check(page, 'pick lesson and start', async () => {
    await card().click()
    t0 = performance.now()
    await page.waitForURL(`**/#/learn/${encodeURIComponent(LESSON)}`, { timeout: 5000 })
    await waitStep(page, 'Step 1 of 5', 5000)
    return `#/learn/${LESSON}, Step 1 of 5`
  })

  await check(page, 'replay camera connects', async () => {
    // The top bar names the active camera ("Replay: norm.mp4") while a lesson shows.
    await page.getByTitle('Active camera').waitFor({ state: 'visible', timeout: 20000 })
    return `camera "${(await page.getByTitle('Active camera').innerText()).trim()}"`
  })

  await check(page, 'live frame appears', async () => {
    // Live frames are drawn on a canvas (role img, "Live camera"), hidden until the first one.
    const canvas = page.getByRole('img', { name: 'Live camera' })
    await canvas.waitFor({ state: 'visible', timeout: 10000 })
    await page.waitForFunction(
      () => {
        const c = document.querySelector('canvas[aria-label="Live camera"]')
        return !!c && !c.classList.contains('hidden') && c.width > 0 && c.height > 0
      },
      null,
      { timeout: 10000 },
    )
    const size = await canvas.evaluate((c) => `${c.width}x${c.height}`)
    return `live frame ${size}`
  })

  await check(page, 'Recording banner shows', async () => {
    await page.getByText('Recording', { exact: true }).waitFor({ state: 'visible', timeout: 5000 })
    return 'frames come from a file'
  })

  await check(page, 'step 1 clip plays with a caption', async () => {
    const cue = await page.waitForFunction(
      () => {
        // The clip on screen; its twin (.standby) buffers the next one.
        const v = document.querySelector('.clip video:not(.standby)')
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
    await page.getByText('Verified', { exact: true }).first().waitFor({ state: 'visible', timeout: 20000 })
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

  await check(page, 'OK dismisses it', async () => {
    await banner.getByRole('button', { name: 'OK', exact: true }).click({ timeout: 2000 })
    const clickedAfter = ((performance.now() - mistakeAt) / 1000).toFixed(1)
    await banner.waitFor({ state: 'hidden', timeout: 1500 })
    const step = (await stepCount(page).innerText()).trim()
    // If the step moved, the camera yes may have cleared the banner, not the click.
    if (step !== 'Step 2 of 5') throw new Error(`step moved to "${step}" before the dismissal could be confirmed`)
    return `banner gone, still Step 2 of 5 (clicked ${clickedAfter} s after it showed)`
  })

  await check(page, 'manual step shows manual badge', async () => {
    await waitStep(page, 'Step 3 of 5', 20000)
    await page.getByText('Manual step', { exact: true }).first().waitFor({ state: 'visible', timeout: 3000 })
    return 'Step 3 of 5, Manual step'
  })

  await check(page, 'Next advances the manual step', async () => {
    await page.getByRole('button', { name: 'Next', exact: true }).click()
    await waitStep(page, 'Step 4 of 5', 3000)
    return 'Step 4 of 5'
  })

  await check(page, 'Done shows real stats', async () => {
    await page.getByText('Lesson complete', { exact: true }).waitFor({ state: 'visible', timeout: 45000 })
    stats = await page.evaluate(() => {
      const out = {}
      for (const d of document.querySelectorAll('dl div')) {
        const k = d.querySelector('dt')?.textContent?.trim()
        if (k) out[k] = d.querySelector('dd')?.textContent?.trim() ?? ''
      }
      // One row per step in the Done step list (Done.tsx, section "Steps").
      out.__rows = [...document.querySelectorAll('section[aria-label="Steps"] ol > li')].map((r) => r.textContent.trim())
      return out
    })
    // A hub in mock mode labels camera passes "By timer (mock)"; a real one "Checked by camera".
    const camKey = 'By timer (mock)' in stats ? 'By timer (mock)' : 'Checked by camera'
    const want = { [camKey]: '4 of 4', 'Marked done': '1', 'Mistakes caught': '1', Expert: '0:40' }
    const bad = Object.entries(want).filter(([k, v]) => stats[k] !== v).map(([k, v]) => `${k} is ${stats[k] ?? 'missing'}, expected ${v}`)
    if (!/^\d+:\d\d$/.test(stats['Your time'] ?? '') || stats['Your time'] === '0:00') bad.push(`Your time is ${stats['Your time'] ?? 'missing'}`)
    if (stats.__rows.length !== 5) bad.push(`${stats.__rows.length} step rows, expected 5`)
    if (bad.length) throw new Error(bad.join('; '))
    return `time ${stats['Your time']}, expert ${stats.Expert}, ${camKey.toLowerCase()} ${stats[camKey]}, by hand ${stats['Marked done']}, mistakes ${stats['Mistakes caught']}`
  })

  await check(spectator, 'spectator mirrors done', async () => {
    await spectator.getByText('Lesson complete', { exact: true }).waitFor({ state: 'visible', timeout: 3000 })
    return 'second viewer shows Lesson complete'
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
