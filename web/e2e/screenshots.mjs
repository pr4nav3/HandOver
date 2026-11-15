// Takes UI screenshots against the dev server plus the mock server, and checks
// the behaviour each screen depends on. Every screen of the app gets a shot:
// Community, Learn (mid lesson, mistake, checks off, camera lost, recording,
// done) and Teach (home, processing, ready, review).
//
//   PORT=8031 MOCK_AUTO=0 node mock/mock-server.mjs
//   VITE_API_TARGET=http://localhost:8031 npx vite --port 5191
//   APP=http://localhost:5191 MOCK=http://localhost:8031 node e2e/screenshots.mjs
//
// Uses installed Google Chrome by default because Playwright's bundled
// Chromium cannot decode H.264 clips. SHOTS_CHANNEL picks another browser:
// msedge (also decodes H.264) or chromium (bundled; clip checks may fail).

import { chromium } from 'playwright'
import { mkdirSync } from 'node:fs'
import { networkInterfaces } from 'node:os'
import { dirname, join } from 'node:path'
import { fileURLToPath } from 'node:url'

const APP = process.env.APP || 'http://localhost:5173'
const MOCK = process.env.MOCK || 'http://localhost:8031'
const LESSON = process.env.LESSON || 'demo-v1'
const OUT = join(dirname(fileURLToPath(import.meta.url)), '..', 'screenshots')
mkdirSync(OUT, { recursive: true })

const want = process.env.SHOTS_CHANNEL || 'chrome'
const channel = want === 'chromium' ? undefined : want
const browser = await chromium.launch({ channel, args: ['--autoplay-policy=no-user-gesture-required'] })
const hook = (p) => fetch(MOCK + p).then((r) => r.json())
const wait = (ms) => new Promise((r) => setTimeout(r, ms))
const problems = []
let passed = 0
const check = (ok, msg) => (ok ? (passed++, console.log('ok  ', msg)) : problems.push(msg))
const shots = []
// The clip on screen is `.clip video:not(.standby)`; its twin buffers the next clip.
const stepCount = (page) => page.locator('.step-count').innerText().then((t) => t.trim())
const waitStep = (page, text, timeout = 4000) =>
  page.waitForFunction((t) => document.querySelector('.step-count')?.textContent?.trim() === t, text, { timeout }).catch(() => {})
// Text of every caption cue currently showing on the learn clip.
const shownCues = (page) =>
  page.evaluate(() => {
    const v = document.querySelector('.clip video:not(.standby)')
    return [...(v?.textTracks ?? [])].filter((t) => t.mode === 'showing').flatMap((t) => [...(t.activeCues ?? [])].map((c) => c.text))
  })
const sentTypes = (page) => page.evaluate(() => window.__sent.map((m) => m.type))

async function shoot(page, name) {
  await page.screenshot({ path: join(OUT, `${name}.png`) })
  shots.push(name)
  console.log('saved', name)
}

// `expected` lists console errors a scenario causes on purpose (a refused upload, a lost job).
async function newPage(width, height, expected = []) {
  const page = await browser.newPage({ viewport: { width, height }, colorScheme: 'light' })
  page.on('pageerror', (e) => problems.push(`pageerror: ${e.message}`))
  page.on('console', (m) => m.type() === 'error' && !expected.some((x) => m.text().includes(x)) && problems.push(`console: ${m.text()}`))
  // Record what the page sends to the hub.
  await page.addInitScript(() => {
    window.__sent = []
    const send = WebSocket.prototype.send
    WebSocket.prototype.send = function (data) {
      if (typeof data === 'string') window.__sent.push(JSON.parse(data))
      return send.call(this, data)
    }
  })
  return page
}

// Waits for the clip on screen to play into a caption cue.
const clipPlaying = (page, label) =>
  page
    .waitForFunction(() => {
      const v = document.querySelector('.clip video:not(.standby)')
      const t = v?.textTracks[0]
      return v && !v.paused && v.currentTime > 1 && t && t.activeCues && t.activeCues.length > 0
    }, null, { timeout: 15000 })
    .catch(() => problems.push(`${label}: clip did not play with an active caption`))

async function learnRun() {
  // A fresh hub with no lesson, so picking the card starts a new run.
  await hook('/mock/restart')
  await hook('/mock/camera?on=1')
  await hook('/mock/source?s=phone')
  await hook('/mock/check_mode?m=')
  await hook('/mock/offline?r=')
  const lessons = await fetch(APP + '/api/lessons').then((r) => r.json())
  const title = lessons.find((l) => l.id === LESSON)?.title ?? LESSON

  const page = await newPage(1440, 900)
  await page.goto(`${APP}/#/community`)
  await page.waitForSelector('.lesson-card')
  await page.waitForFunction(() => [...document.querySelectorAll('.lesson-card img')].every((i) => i.complete), null, { timeout: 5000 }).catch(() => {})
  await wait(300)
  check((await page.locator('.lesson-card').count()) === lessons.length, `community shows one card per lesson (${lessons.length})`)
  await shoot(page, '01-community')

  // A card opens #/learn/<id>, which sends select_lesson for it.
  await page.click(`.lesson-card:has-text("${title}")`)
  await page.waitForFunction((id) => location.hash === `#/learn/${id}`, LESSON, { timeout: 3000 }).catch(() => {})
  check((await page.evaluate(() => location.hash)) === `#/learn/${LESSON}`, `lesson card navigates to #/learn/${LESSON}`)
  await waitStep(page, 'Step 1 of 5')
  const picked = await page.evaluate(() => window.__sent.filter((m) => m.type === 'select_lesson').map((m) => m.id))
  check(picked.length === 1 && picked[0] === LESSON, `the route sends select_lesson once (${picked.join(', ')})`)

  await hook('/mock/goto?step=1')
  await clipPlaying(page, '1440')
  await hook('/mock/status?s=checking')
  await wait(600)
  await shoot(page, '02-learn-mid-lesson')

  check((await page.locator('.next-hint').innerText()).trim() === 'or press →', 'key hint reads "or press →"')

  // Check settings popover: the check rate lives behind the ⋯ button.
  // Space on a focused button presses that button, never Next.
  const stepBeforeSpace = await stepCount(page)
  await page.focus('.more-button')
  await page.keyboard.press(' ')
  await page.waitForSelector('.popover .check-rate', { timeout: 2000 }).catch(() => {})
  check(
    (await stepCount(page)) === stepBeforeSpace && (await page.locator('.popover .check-rate').isVisible()),
    'Space on the focused ⋯ button opens check settings and does not press Next',
  )
  const rates = await page.locator('.check-rate button').allInnerTexts()
  check(rates.join('|') === '0.5 s|1 s|2 s' && (await page.locator('.check-rate button.on').innerText()) === '1 s', `check rate offers ${rates.join(', ')} with 1 s on`)
  await page.evaluate(() => (window.__sent = []))
  await page.click('.check-rate button:has-text("2 s")')
  await page.waitForSelector('.check-rate button.on:has-text("2 s")', { timeout: 2000 }).catch(() => {})
  const rateSent = await page.evaluate(() => window.__sent.find((m) => m.type === 'set_check_interval')?.seconds)
  check(rateSent === 2 && (await page.locator('.check-rate button.on').innerText()) === '2 s', 'picking 2 s sends set_check_interval and the hub echo marks it on')
  await shoot(page, '03-check-settings')
  await page.click('.check-rate button:has-text("1 s")')
  await page.keyboard.press('Escape')
  await wait(200)
  check(!(await page.locator('.popover').count()), 'Escape closes check settings')
  await page.evaluate(() => document.activeElement?.blur())

  // A status dot never pulses (DESIGN.md principle 8).
  check(await page.evaluate(() => getComputedStyle(document.querySelector('.badge-dot')).animationName === 'none'), 'badge dot has no animation')
  check(
    // getComputedStyle cannot read ::cue, so read the rule itself.
    await page.evaluate(() =>
      [...document.styleSheets]
        .flatMap((sh) => [...sh.cssRules])
        .some((r) => {
          if (r.selectorText !== 'video::cue') return false
          const bg = r.style.backgroundColor
          const v = /^var\((--[\w-]+)\)$/.exec(bg)
          return (v ? getComputedStyle(document.documentElement).getPropertyValue(v[1]).trim() : bg) === 'rgba(0, 0, 0, 0.72)'
        }),
    ),
    'caption background is 72% black',
  )

  // A lesson.json without clip, captions and ref_frame gets the contract defaults.
  await hook('/mock/strip_paths?on=1')
  const stripped = await hook('/mock/recut')
  const defaulted = await page
    .waitForFunction(
      (rev) => {
        const v = document.querySelector('.clip video:not(.standby)')
        return v && v.src.includes(`clips/02.mp4?v=${rev}`) && v.querySelector('track')?.src.includes('captions/02.vtt') && v.readyState >= 2
      },
      stripped.rev,
      { timeout: 6000 },
    )
    .then(() => true, () => false)
  check(defaulted, 'missing clip and captions paths fall back to clips/NN.mp4 and captions/NN.vtt')
  await hook('/mock/strip_paths?on=0')

  // Badge: checking and watching are one visual state, so the pulse never restarts.
  const badgeBefore = await page.getAttribute('.badge', 'class')
  await hook('/mock/status?s=watching')
  await wait(200)
  check(badgeBefore === (await page.getAttribute('.badge', 'class')), `badge class unchanged across checking/watching (${badgeBefore})`)

  // Recut: a new rev reloads the clip with ?v=<rev>.
  const srcBefore = await page.evaluate(() => document.querySelector('.clip video:not(.standby)').src)
  const recut = await hook('/mock/recut')
  await page.waitForFunction((rev) => document.querySelector('.clip video:not(.standby)').src.endsWith(`?v=${rev}`), recut.rev, { timeout: 5000 }).then(
    () => check(true, `recut reloads the clip (${srcBefore.split('/').pop()} -> ?v=${recut.rev})`),
    () => check(false, 'recut did not reload the clip with the new rev'),
  )
  const trackSrc = await page.evaluate(() => document.querySelector('.clip video:not(.standby) track')?.src ?? '')
  check(trackSrc.endsWith(`?v=${recut.rev}`), 'captions URL carries the new rev')

  // Two quick Next presses carry the same `from`, so only one step advances,
  // and no caption from the old clip lingers on the new one.
  await page.waitForFunction(() => document.querySelector('.clip video:not(.standby)').textTracks[0]?.activeCues?.length > 0, null, { timeout: 8000 }).catch(() => {})
  const oldCues = await shownCues(page)
  const before = await stepCount(page)
  await page.keyboard.press('ArrowRight')
  await page.keyboard.press('ArrowRight')
  // Right after the change, the only caption track drawing is the new clip's.
  // (Compared by track, not text: a clip's first cue may repeat the last step's words.)
  await waitStep(page, 'Step 3 of 5', 2000)
  const drawing = await page.evaluate(() =>
    [...document.querySelectorAll('.clip video track')].filter((t) => t.track.mode === 'showing').map((t) => t.src.split('/').pop()),
  )
  check(
    drawing.length === 1 && drawing[0].startsWith('03.vtt'),
    `no caption track from the previous clip after a step change (showing: ${drawing.join(', ') || 'none'}; before: ${oldCues.join(' | ') || 'no cue'})`,
  )
  await wait(700)
  const after = await stepCount(page)
  check(before === 'Step 2 of 5' && after === 'Step 3 of 5', `double Next advances one step (${before} -> ${after})`)
  await hook('/mock/goto?step=1')
  await wait(600)

  // Preload: the standby element already holds step 3's clip, buffered, and
  // the advance swaps it on screen instead of loading.
  const ready = await page
    .waitForFunction(() => {
      const s = document.querySelector('.clip video.standby')
      return s && s.src.includes('clips/03.mp4') && s.readyState >= 3
    }, null, { timeout: 8000 })
    .then(() => true, () => false)
  check(ready, 'standby video holds the next clip, buffered, before the advance')
  const standbySlot = await page.evaluate(() => document.querySelector('.clip video.standby')?.dataset.slot)
  await hook('/mock/advance?reason=camera')
  await page.waitForSelector('.badge.verified', { timeout: 3000 }).catch(() => problems.push('verified badge did not show'))
  const swapped = await page.evaluate(() => {
    const v = document.querySelector('.clip video:not(.standby)')
    return { slot: v?.dataset.slot, src: v?.src ?? '', captions: v?.querySelector('track')?.src ?? '', mode: v?.textTracks[0]?.mode }
  })
  check(
    swapped.slot === standbySlot && swapped.src.includes('clips/03.mp4') && swapped.captions.includes('captions/03.vtt') && swapped.mode === 'showing',
    `advance swaps in the preloaded clip and captions (slot ${standbySlot} -> ${swapped.slot}, ${swapped.src.split('/').pop()})`,
  )
  await wait(300)
  await shoot(page, '04-verified')

  // Step 3 is a manual step: no camera check, press Next.
  await waitStep(page, 'Step 3 of 5')
  await wait(1500)
  check((await page.locator('.badge').innerText()).includes('Manual step'), 'manual step shows the Manual step badge')
  await shoot(page, '05-manual-step')

  // The Steps list jumps: a row click sends goto for that step.
  await page.evaluate(() => (window.__sent = []))
  await page.click('.steps-card .sl-row >> nth=3')
  await waitStep(page, 'Step 4 of 5')
  const gotoSent = await page.evaluate(() => window.__sent.filter((m) => m.type === 'goto').map((m) => m.step))
  check(gotoSent.join() === '3' && (await stepCount(page)) === 'Step 4 of 5', `Steps list row sends goto 3 (${gotoSent.join()})`)
  check((await page.locator('.steps-card .sl-row.current .sl-name').innerText()) === 'Pattern 4', 'Steps list marks the current row')

  // A behind mistake: amber card with Show step and OK; Show step goes there.
  await hook('/mock/mistake?kind=behind')
  await page.waitForSelector('.mistake-banner', { timeout: 3000 }).catch(() => {})
  await wait(400)
  const behind = await page.locator('.mistake-banner').innerText().catch(() => '')
  check(behind.includes('Show step 3') && behind.includes('OK'), `behind mistake offers Show step 3 and OK (${behind.replace(/\n/g, ' | ')})`)
  check((await page.locator('.progress .seg.mistake').count()) === 1, 'progress marks the step with the mistake')
  await shoot(page, '06-mistake')
  await page.click('.mistake-banner button:has-text("Show step 3")')
  await waitStep(page, 'Step 3 of 5')
  check((await stepCount(page)) === 'Step 3 of 5' && !(await page.locator('.mistake-banner').count()), 'Show step goes to that step and closes the card')

  // Camera drops after sending frames: the last frame stays, dimmed, with a note.
  await hook('/mock/goto?step=1')
  await wait(1200)
  await hook('/mock/camera?on=0')
  await page.waitForSelector('.live-note', { timeout: 3000 }).catch(() => {})
  check((await page.locator('.live-note').innerText().catch(() => '')).includes('Camera lost'), 'a dropped camera says Camera lost')
  check(await page.evaluate(() => !!document.querySelector('.pane.live canvas')?.classList.contains('lost')), 'the last frame stays, dimmed')
  check((await page.locator('.step-do').innerText()) === 'Do this step, then press Next.', 'no camera means press Next')
  await wait(400)
  await shoot(page, '07-camera-lost')
  await hook('/mock/camera?on=1')
  await page.waitForSelector('.live-note', { state: 'detached', timeout: 4000 }).catch(() => problems.push('Camera lost note did not clear when the camera came back'))

  await hook('/mock/error?m=Unknown lesson: nope')
  await wait(400)
  check((await page.locator('.note.error').innerText().catch(() => '')) === 'Unknown lesson: nope', 'a hub error shows its text in the top bar')
  await shoot(page, '08-server-error')
  // The error pill clears on its own; later shots must not carry it.
  await page.waitForSelector('.note.error', { state: 'detached', timeout: 6000 }).catch(() => problems.push('error pill did not clear'))

  // Any camera source that is not a known live camera shows Recording.
  await hook('/mock/source?s=file')
  await page.waitForSelector('.rec', { timeout: 3000 }).catch(() => {})
  check(await page.locator('.rec').isVisible(), 'a replay file shows the Recording banner')
  await wait(500)
  await shoot(page, '09-recording')
  await hook('/mock/source?s=unknown')
  await wait(300)
  check(await page.locator('.rec').isVisible(), 'unknown camera source shows the Recording banner')
  await hook('/mock/source?s=phone')
  await wait(300)
  check(!(await page.locator('.rec').count()), 'phone camera shows no Recording banner')

  // Checks-off reasons show beside the badge on a camera step.
  await hook('/mock/goto?step=3')
  await hook('/mock/offline?r=budget')
  await wait(400)
  check((await page.locator('.check-meta').innerText()).includes('AI budget reached'), 'budget reason reads "AI budget reached"')
  check((await page.locator('.badge').innerText()).includes('Checks off, use Next'), 'badge reads "Checks off, use Next"')
  await shoot(page, '10-checks-off')
  await hook('/mock/offline?r=no_key')
  await wait(300)
  check((await page.locator('.check-meta').innerText()).includes('No API key'), 'no_key reads "No API key"')
  await hook('/mock/offline?r=')

  // A live mistake: its label, an OK button, no Show step. Sent twice, counted once.
  await hook('/mock/mistake?kind=live&label=Wrong%20fold')
  await hook('/mock/mistake?kind=live&label=Wrong%20fold')
  await page.waitForSelector('.mistake-banner', { timeout: 3000 }).catch(() => {})
  const banner = await page.locator('.mistake-banner').innerText().catch(() => '')
  check(banner.includes('Wrong fold') && banner.includes('OK') && !banner.includes('Show step'), `live mistake shows its label and OK only (${banner.replace(/\n/g, ' | ')})`)
  await shoot(page, '06b-mistake-live')
  await page.click('.mistake-banner button:has-text("OK")')

  // Advancing past the last step: advance to == total, then status done.
  await hook('/mock/goto?step=4')
  await wait(800)
  await hook('/mock/advance?reason=camera')
  await page.waitForSelector('.badge.done', { state: 'attached', timeout: 3000 }).catch(() => problems.push('done badge did not show'))
  await page.waitForSelector('.finish', { timeout: 3000 }).catch(() => {})
  await wait(800)
  await shoot(page, '11-done')
  check(await page.locator('.finish').isVisible(), 'done screen replaces the clip')
  check((await page.locator('.done-title').innerText()) === 'Lesson complete', 'done title reads Lesson complete')
  check(!(await page.locator('.next-hint').isVisible()), 'no key hint at done')
  check(
    (await page.locator('.finish button.next').innerText()) === 'Start over' && !(await page.locator('.finish button.next:disabled').count()),
    'done shows Start over, enabled',
  )
  check(!(await page.locator('.step-title').isVisible()), 'done screen shows no step title')
  check(await page.evaluate(() => [...document.querySelectorAll('.clip video')].every((v) => v.paused)), 'clips stop at done')
  const realStats = await page.locator('.finish-stats').innerText()
  check(realStats.includes('Checked by camera') && !realStats.includes('mock') && !(await page.locator('.done-note').count()), 'no mock wording when the hub does not say mock')
  // One behind and one live mistake (the live one sent twice).
  const mistakesShown = await page.locator('.finish-stats div:has(dt:text("Mistakes caught")) dd').innerText()
  check(mistakesShown === '2', `a repeated mistake counts once (Mistakes caught ${mistakesShown}, want 2)`)
  check((await page.locator('.finish .bd-row').count()) === 5, 'done step table has a row per step')

  // Start over: a fresh select_lesson, not goto 0.
  await page.evaluate(() => (window.__sent = []))
  await page.click('.finish button.next')
  await waitStep(page, 'Step 1 of 5', 3000)
  check((await stepCount(page)) === 'Step 1 of 5' && !(await page.locator('.finish').count()), 'Start over returns to step 1')
  const restartSent = await sentTypes(page)
  check(restartSent.includes('select_lesson') && !restartSent.includes('goto'), `Start over sends select_lesson, not goto (${restartSent.join(', ')})`)

  // Mock checks: the badge meta says Simulated checks, and Done never claims the camera.
  await hook('/mock/check_mode?m=mock')
  await hook('/mock/goto?step=3')
  await wait(500)
  check((await page.locator('.check-meta span').first().innerText()) === 'Simulated checks', 'badge meta reads "Simulated checks" in mock mode')
  check((await page.locator('.step-do').innerText()).includes('Simulated checks move on'), 'step line says simulated checks move on')
  await hook('/mock/goto?step=4')
  await wait(400)
  await hook('/mock/advance?reason=camera')
  await page.waitForSelector('.finish', { timeout: 3000 }).catch(() => {})
  await wait(600)
  const stats = await page.locator('.finish-stats').innerText()
  check(stats.includes('By timer (mock)') && !stats.includes('Checked by camera'), 'done stat says By timer (mock), not Checked by camera')
  const metas = await page.locator('.finish .bd-meta').allInnerTexts()
  check(
    metas.some((m) => m.trim() === 'Timer (mock)') && !metas.some((m) => m.includes('Checked by camera')),
    `step table says Timer (mock), never Checked by camera (${metas.map((m) => m.trim()).join(' | ')})`,
  )
  check((await page.locator('.done-note').innerText().catch(() => '')).startsWith('Simulated checks'), 'done note explains simulated checks')
  await shoot(page, '11b-done-mock-checks')
  await hook('/mock/check_mode?m=')
  await page.click('.finish button.next')
  await waitStep(page, 'Step 1 of 5', 3000)

  // Server restart: it comes back with no lesson; the page picks it again and returns to the step.
  await hook('/mock/goto?step=2')
  await wait(400)
  await page.evaluate(() => (window.__sent = []))
  await hook('/mock/restart')
  await page
    .waitForFunction(
      () => window.__sent.some((m) => m.type === 'goto' && m.step === 2) && document.querySelector('.step-count')?.textContent?.trim() === 'Step 3 of 5',
      null,
      { timeout: 8000 },
    )
    .catch(() => {})
  await wait(400)
  const resumedSent = await sentTypes(page)
  check(
    (await stepCount(page)) === 'Step 3 of 5' && resumedSent.includes('select_lesson') && !(await page.locator('.learn-empty').count()),
    `lesson resumes at the same step after a server restart (${await stepCount(page)}; sent ${resumedSent.join(', ')})`,
  )
  await shoot(page, '12-resumed-after-restart')

  // End asks first; Escape keeps going, End lesson goes back to Community.
  await page.click('.end-button')
  await page.waitForSelector('.confirm-card', { timeout: 2000 }).catch(() => {})
  await shoot(page, '13-end-confirm')
  await page.keyboard.press('Escape')
  await wait(200)
  check(!(await page.locator('.confirm-card').count()) && (await stepCount(page)) === 'Step 3 of 5', 'Escape closes the End card and keeps the lesson')
  await page.evaluate(() => (window.__sent = []))
  await page.click('.end-button')
  await page.click('.confirm-card button:has-text("End lesson")')
  await page.waitForSelector('.lesson-card', { timeout: 3000 }).catch(() => {})
  check((await page.evaluate(() => location.hash)) === '#/community' && (await page.locator('.lesson-card').first().isVisible()), 'End lesson goes back to Community')
  check((await sentTypes(page)).includes('end_lesson'), 'End lesson sends end_lesson')
  check(!(await page.locator('.end-button').count()), 'no End button on Community')
  await page.close()
}

// The same lesson in a small laptop window.
async function learnSmall() {
  await hook('/mock/camera?on=1')
  const page = await newPage(1366, 768)
  await page.goto(`${APP}/#/learn/${LESSON}`)
  await waitStep(page, 'Step 1 of 5', 6000)
  await hook('/mock/goto?step=1')
  await clipPlaying(page, '1366')
  await hook('/mock/status?s=checking')
  await wait(600)
  const fits = await page.evaluate(
    () => document.documentElement.scrollHeight <= innerHeight && document.querySelector('.learn-body button.next').getBoundingClientRect().bottom <= innerHeight,
  )
  check(fits, '1366x768: no page scroll and Next is on screen')
  await shoot(page, '02b-learn-mid-lesson-1366')
  await page.close()
}

// The page a phone would see: the first LAN address of this machine (Vite listens on all of them).
function lanApp() {
  if (process.env.LAN_APP) return process.env.LAN_APP
  const ip = Object.values(networkInterfaces())
    .flat()
    .find((a) => a && a.family === 'IPv4' && !a.internal && !a.address.startsWith('169.254.'))?.address
  return ip ? APP.replace(/\/\/(localhost|127\.0\.0\.1)/, `//${ip}`) : null
}

// No camera yet: the live pane says how to connect one. On localhost (the mock's
// hub-info has no capture URL) it gives the typed address hint; on a LAN address
// it shows the capture page's QR code.
async function noCameraRun() {
  await hook('/mock/camera?on=0')
  for (const [app, name] of [[APP, '14-connect-camera-localhost'], [lanApp(), '14b-connect-camera-lan']]) {
    if (!app) continue
    const page = await newPage(1440, 900)
    await page.goto(`${app}/#/learn/${LESSON}`)
    await page.waitForSelector('.connect', { timeout: 6000 }).catch(() => problems.push(`${name}: no connect panel`))
    await wait(1200)
    const local = name.includes('localhost')
    check((await page.locator('.connect .qr').count()) === (local ? 0 : 1), `${name}: ${local ? 'no QR code on localhost' : 'a QR code on a LAN address'}`)
    check((await page.locator('.connect a[href="/capture"]').count()) === 1, `${name}: link to /capture`)
    check(!(await page.locator('.connect a[href^="handover:"]').count()), `${name}: no handover:// link`)
    check((await page.locator('.step-do').innerText()) === 'Do this step, then press Next.', `${name}: no camera means press Next`)
    await shoot(page, name)
    await page.close()
  }
  await hook('/mock/camera?on=1')
}

async function teachRun() {
  const lessons = await fetch(APP + '/api/lessons').then((r) => r.json())
  const title = lessons.find((l) => l.id === LESSON)?.title ?? LESSON
  const page = await newPage(1440, 900)
  await page.goto(`${APP}/#/teach`)
  await page.waitForSelector('.lesson-list .lesson-row')
  await page.waitForFunction(() => [...document.querySelectorAll('.lesson-list img')].every((i) => i.complete), null, { timeout: 5000 }).catch(() => {})
  check((await page.locator('.lesson-list .lesson-row').count()) === lessons.length, 'Your lessons lists every lesson')
  check(await page.locator('button:has-text("Make lesson")').isDisabled(), 'Make lesson is off until a video and title are in')
  await shoot(page, '15-teach-home')

  await page.click(`.lesson-list .lesson-row:has-text("${title}")`)
  await page.waitForSelector('.thumb img')
  await page.waitForFunction(() => [...document.querySelectorAll('.thumb img')].every((i) => i.complete && i.naturalWidth > 0))
  check((await page.locator('.thumb').count()) === 5 && (await page.locator('.tl-seg').count()) === 5, 'review shows a thumb and a timeline segment per step')
  // Seek via the timeline to show the playhead and active segment.
  await page.click('.tl-seg >> nth=2')
  await wait(1500)
  await page.evaluate(() => document.querySelector('.player video')?.pause())
  check((await page.locator('.tl-seg.active').count()) === 1, 'timeline marks the segment playing')
  await shoot(page, '18-teach-review')

  await page.click('.thumb >> nth=3')
  await page.waitForFunction(() => {
    const v = document.querySelector('.player video')
    const t = v?.textTracks[0]
    return v && v.currentTime > 1 && t && t.activeCues && t.activeCues.length > 0
  }, null, { timeout: 15000 }).catch(() => problems.push('teach clip did not play with captions'))
  check((await page.locator('.thumb.active').count()) === 1, 'the picked step is marked')
  await shoot(page, '18b-teach-clip')
  await page.click('button:has-text("Back to Teach")')
  check(await page.locator('.lesson-list').isVisible(), 'Back to Teach returns to the home')
  await page.close()
}

async function uploadRun() {
  const video = join(OUT, '..', 'mock', 'fixtures', 'mock-demo', 'clips', '01.mp4')
  const page = await newPage(1440, 900, ['status of 413', 'status of 404'])
  await page.goto(`${APP}/#/teach`)
  await page.setInputFiles('input[type=file]', video)
  await page.fill('.field input', 'Fold a fortune teller')

  // An upload the hub refuses shows the hub's own words, and Try again resends it.
  await hook('/mock/upload_fail?m=video%20is%20larger%20than%202%20GB')
  await page.click('button:has-text("Make lesson")')
  const uploadErr = await page.locator('.job.error').innerText({ timeout: 4000 }).catch(() => '')
  check(uploadErr.includes('video is larger than 2 GB'), 'upload error shows the hub detail (video is larger than 2 GB)')
  await page.click('button:has-text("Try again")')
  await page.waitForSelector('.job .spinner')
  await wait(4300)
  check(!(await page.locator('.job.error').count()), 'Try again sends the video again')
  await shoot(page, '16-teach-processing')

  await page.waitForSelector('.ready', { timeout: 15000 }).catch(() => problems.push('upload never reached the ready card'))
  await page.waitForFunction(() => [...document.querySelectorAll('.ready-frame img')].every((i) => i.complete), null, { timeout: 5000 }).catch(() => {})
  await wait(400)
  const readyLine = await page.locator('.ready-line').innerText().catch(() => '')
  check(/found 6 steps/.test(readyLine) && (await page.locator('.ready-frame').count()) === 6, `ready card counts the steps (${readyLine})`)
  await shoot(page, '17-teach-ready')

  // Server restart mid job: the job is gone (404), so show an error, not a spinner.
  await page.click('button:has-text("Teach another")')
  await page.setInputFiles('input[type=file]', video)
  await page.fill('.field input', 'Fold a fortune teller')
  await page.click('button:has-text("Make lesson")')
  await page.waitForSelector('.job .spinner')
  await hook('/mock/restart')
  await page.waitForSelector('.job.error', { timeout: 4000 }).then(
    () => check(true, 'lost job shows an error'),
    () => check(false, 'lost job still spinning'),
  )
  check((await page.locator('.job.error').innerText()).includes('lost this job'), 'lost job says the hub lost it')
  await shoot(page, '16b-teach-lost-job')
  await page.close()
}

try {
  await learnRun()
  await learnSmall()
  await noCameraRun()
  await teachRun()
  await uploadRun()
} finally {
  await browser.close()
}
console.log(`\n${passed} checks passed, ${problems.length} problems, ${shots.length} screenshots`)
if (problems.length) {
  console.log('Problems:\n' + problems.join('\n'))
  process.exitCode = 1
} else {
  console.log('No problems found')
}
