// Takes UI screenshots against the dev server plus the mock server.
//
//   PORT=8013 MOCK_AUTO=0 node mock/mock-server.mjs
//   VITE_API_TARGET=http://localhost:8013 npx vite --port 5193
//   APP=http://localhost:5193 MOCK=http://localhost:8013 node e2e/screenshots.mjs
//
// Uses installed Google Chrome by default because Playwright's bundled
// Chromium cannot decode H.264 clips. Set SHOTS_CHANNEL=chromium to override.

import { chromium } from 'playwright'
import { mkdirSync } from 'node:fs'
import { dirname, join } from 'node:path'
import { fileURLToPath } from 'node:url'

const APP = process.env.APP || 'http://localhost:5173'
const MOCK = process.env.MOCK || 'http://localhost:8010'
const LESSON = process.env.LESSON || 'demo-v1'
const OUT = join(dirname(fileURLToPath(import.meta.url)), '..', 'screenshots')
mkdirSync(OUT, { recursive: true })

const channel = process.env.SHOTS_CHANNEL === 'chromium' ? undefined : 'chrome'
const browser = await chromium.launch({ channel, args: ['--autoplay-policy=no-user-gesture-required'] })
const hook = (p) => fetch(MOCK + p).then((r) => r.json())
const wait = (ms) => new Promise((r) => setTimeout(r, ms))
const problems = []
const check = (ok, msg) => (ok ? console.log('ok  ', msg) : problems.push(msg))
// The clip on screen is `.clip video:not(.standby)`; its twin buffers the next clip.
const stepCount = (page) => page.locator('.step-count').innerText().then((t) => t.trim())
// Text of every caption cue currently showing on the learn clip.
const shownCues = (page) =>
  page.evaluate(() => {
    const v = document.querySelector('.clip video:not(.standby)')
    return [...(v?.textTracks ?? [])].filter((t) => t.mode === 'showing').flatMap((t) => [...(t.activeCues ?? [])].map((c) => c.text))
  })

async function shoot(page, name) {
  await page.screenshot({ path: join(OUT, `${name}.png`) })
  console.log('saved', name)
}

async function learnRun(width, height, suffix) {
  const page = await browser.newPage({ viewport: { width, height } })
  page.on('pageerror', (e) => problems.push(`pageerror: ${e.message}`))
  page.on('console', (m) => m.type() === 'error' && problems.push(`console: ${m.text()}`))
  // Record what the page sends to the hub.
  await page.addInitScript(() => {
    window.__sent = []
    const send = WebSocket.prototype.send
    WebSocket.prototype.send = function (data) {
      if (typeof data === 'string') window.__sent.push(JSON.parse(data))
      return send.call(this, data)
    }
  })
  await hook('/mock/camera?on=1')
  await page.goto(`${APP}/#/learn`)
  await page.waitForSelector(`.start-card select option[value="${LESSON}"]`, { state: 'attached' })
  await page.selectOption('.start-card select', LESSON)
  await wait(500)
  if (!suffix) await shoot(page, '01-start-overlay')

  await page.click('text=Start lesson')
  await wait(1000)
  await hook('/mock/goto?step=1')
  // Wait for the clip to play into its first caption cue.
  await page.waitForFunction(() => {
    const v = document.querySelector('.clip video:not(.standby)')
    const t = v?.textTracks[0]
    return v && !v.paused && v.currentTime > 1 && t && t.activeCues && t.activeCues.length > 0
  }, null, { timeout: 15000 }).catch(() => problems.push(`${suffix || '1440'}: clip did not play with an active caption`))
  await hook('/mock/status?s=checking')
  await wait(600)
  await shoot(page, `02-learn-mid-lesson${suffix}`)

  if (!suffix) {
    check((await page.getAttribute('.mic', 'aria-pressed')) === 'false', 'voice is off by default (mic not pressed)')
    check((await page.locator('.next-hint').innerText()).includes('press'), 'hint says press, not say, while voice is off')
    await page.click('.mic')
    check((await page.getAttribute('.mic', 'aria-pressed')) === 'true', 'mic button turns voice on')
    await page.click('.mic')
    check((await page.getAttribute('.mic', 'aria-pressed')) === 'false', 'mic button turns voice off again')

    // Space on a focused button presses that button, never Next.
    const stepBeforeSpace = await stepCount(page)
    await page.focus('.mic')
    await page.keyboard.press(' ')
    await wait(400)
    check((await stepCount(page)) === stepBeforeSpace && (await page.getAttribute('.mic', 'aria-pressed')) === 'true', 'Space on the focused mic toggles it and does not press Next')
    await page.keyboard.press(' ')
    await wait(200)
    await page.evaluate(() => document.activeElement?.blur())

    // A status dot never pulses (DESIGN.md principle 8).
    check(await page.evaluate(() => getComputedStyle(document.querySelector('.badge-dot')).animationName === 'none'), 'badge dot has no animation')
    check(
      // getComputedStyle cannot read ::cue, so read the rule itself.
      await page.evaluate(() =>
        [...document.styleSheets]
          .flatMap((sh) => [...sh.cssRules])
          .some((r) => r.selectorText === 'video::cue' && r.style.backgroundColor === 'rgba(0, 0, 0, 0.72)'),
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

    // Two quick Next presses carry the same `from`, so only one step advances.
    await page.waitForFunction(() => document.querySelector('.clip video:not(.standby)').textTracks[0]?.activeCues?.length > 0, null, { timeout: 8000 }).catch(() => {})
    const oldCues = await shownCues(page)
    const before = await stepCount(page)
    await page.keyboard.press('ArrowRight')
    await page.keyboard.press('ArrowRight')
    await wait(150)
    const lingering = (await shownCues(page)).filter((c) => oldCues.includes(c))
    check(lingering.length === 0, `no caption from the previous clip after a step change (${oldCues.join(' | ') || 'no cue showing before'})`)
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
    await shoot(page, '03-verified')

    await hook('/mock/goto?step=2')
    await wait(1500)
    await shoot(page, '04-manual-step')

    await hook('/mock/camera?on=0')
    await wait(800)
    await shoot(page, '05-waiting-for-camera')
    await hook('/mock/camera?on=1')

    await hook('/mock/error?m=Unknown lesson: nope')
    await wait(400)
    await shoot(page, '05b-server-error')
    // The error pill clears on its own; later shots must not carry it.
    await page.waitForSelector('.note.error', { state: 'detached', timeout: 6000 }).catch(() => problems.push('error pill did not clear'))

    // Any camera source that is not a known live camera shows Recording.
    await hook('/mock/source?s=unknown')
    await page.waitForSelector('.rec', { timeout: 3000 }).then(
      () => check(true, 'unknown camera source shows the Recording banner'),
      () => check(false, 'unknown camera source did not show the Recording banner'),
    )
    await hook('/mock/source?s=phone')
    await wait(300)
    check(!(await page.locator('.rec').count()), 'phone camera shows no Recording banner')

    // Checks-off reasons show beside the badge on a camera step.
    await hook('/mock/goto?step=3')
    await hook('/mock/offline?r=budget')
    await wait(300)
    check((await page.locator('.check-meta').innerText()).includes('AI budget reached'), 'budget reason reads "AI budget reached"')
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
    await page.click('.mistake-banner button:has-text("OK")')

    // Advancing past the last step: advance to == total, then status done.
    await hook('/mock/goto?step=4')
    await wait(800)
    await hook('/mock/advance?reason=camera')
    await page.waitForSelector('.badge.done', { timeout: 3000 }).catch(() => problems.push('done badge did not show'))
    await wait(800)
    await shoot(page, '06-done')
    check(await page.locator('.finish').isVisible(), 'done screen replaces the clip')
    check(!(await page.locator('.next-hint').count()), 'no key hint at done')
    check(!(await page.locator('button.next:disabled').count()) && (await page.locator('button.next').innerText()) === 'Start over', 'done shows Start over, no disabled Next')
    check((await page.locator('.step-title').innerText()) !== (await page.locator('.topbar-title').innerText()), 'done screen does not repeat the lesson title')
    check(await page.evaluate(() => [...document.querySelectorAll('.clip video')].every((v) => v.paused)), 'clips stop at done')
    check(!(await page.locator('.mode-pill').count()), 'no Mock checks pill when the hub does not say mock')
    const mistakesShown = await page.locator('.finish-stats div:has(dt:text("Mistakes caught")) dd').innerText()
    check(mistakesShown === '1', `a repeated mistake counts once (Mistakes caught ${mistakesShown})`)

    // Mock checks: a persistent pill, and the summary never claims the camera.
    await hook('/mock/check_mode?m=mock')
    await page.waitForSelector('.mode-pill', { timeout: 3000 }).catch(() => {})
    check((await page.locator('.mode-pill').innerText().catch(() => '')) === 'Mock checks', 'Mock checks pill shows in mock mode')
    const stats = await page.locator('.finish-stats').innerText()
    check(stats.includes('By timer (mock)') && !stats.includes('By camera'), 'done stat says By timer (mock), not By camera')
    check(!(await page.locator('.finish-steps .how', { hasText: 'Camera' }).count()), 'step table claims no camera checks in mock mode')
    await shoot(page, '06b-done-mock-checks')
    await hook('/mock/check_mode?m=')

    await page.evaluate(() => (window.__sent = []))
    await page.click('text=Start over')
    await page.waitForFunction(() => document.querySelector('.step-count')?.textContent?.trim() === 'Step 1 of 5', null, { timeout: 3000 }).catch(() => {})
    check((await stepCount(page)) === 'Step 1 of 5', 'Start over returns to step 1')
    const restartSent = await page.evaluate(() => window.__sent.map((m) => m.type))
    check(restartSent.includes('select_lesson') && !restartSent.includes('goto'), `Start over sends select_lesson, not goto (${restartSent.join(', ')})`)

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
    check((await stepCount(page)) === 'Step 3 of 5' && !(await page.locator('.overlay').count()), `lesson resumes at the same step after a server restart, no picker (${await stepCount(page)})`)
    await shoot(page, '14-resumed-after-restart')
  }
  await page.close()
}

async function teachRun() {
  const page = await browser.newPage({ viewport: { width: 1440, height: 900 } })
  page.on('pageerror', (e) => problems.push(`pageerror: ${e.message}`))
  await page.goto(`${APP}/#/teach`)
  await page.waitForSelector('.lesson-list button')
  await shoot(page, '07-teach-start')

  await page.click(`.lesson-list button:has-text("${LESSON === 'demo-v1' ? 'Demo lesson' : 'mock'}")`)
  await page.waitForSelector('.thumb img')
  await page.waitForFunction(() => [...document.querySelectorAll('.thumb img')].every((i) => i.complete && i.naturalWidth > 0))
  // Seek via the timeline to show the playhead and active segment.
  await page.click('.tl-seg >> nth=2')
  await wait(1500)
  await page.evaluate(() => document.querySelector('.player video')?.pause())
  await shoot(page, '08-teach-lesson')

  await page.click('.thumb >> nth=3')
  await page.waitForFunction(() => {
    const v = document.querySelector('.player video')
    const t = v?.textTracks[0]
    return v && v.currentTime > 1 && t && t.activeCues && t.activeCues.length > 0
  }, null, { timeout: 15000 }).catch(() => problems.push('teach clip did not play with captions'))
  await shoot(page, '09-teach-clip')
  await page.close()
}

async function uploadRun() {
  const page = await browser.newPage({ viewport: { width: 1440, height: 900 } })
  await page.goto(`${APP}/#/teach`)
  await page.setInputFiles('input[type=file]', join(OUT, '..', 'mock', 'fixtures', 'mock-demo', 'clips', '01.mp4'))
  await page.fill('.field input', 'Fold a fortune teller')

  // An upload the hub refuses shows the hub's own words.
  await hook('/mock/upload_fail?m=video%20is%20larger%20than%202%20GB')
  await page.click('text=Make lesson')
  const uploadErr = await page.locator('.job.error').innerText({ timeout: 4000 }).catch(() => '')
  check(uploadErr.includes('video is larger than 2 GB'), `upload error shows the hub detail (${uploadErr})`)

  await page.click('text=Make lesson')
  await page.waitForSelector('.job .spinner')
  await wait(2600)
  await shoot(page, '10-teach-processing')

  // Server restart mid job: the job is gone (404), so show an error, not a spinner.
  await hook('/mock/restart')
  await page.waitForSelector('.job.error', { timeout: 4000 }).then(
    () => check(true, 'lost job shows an error'),
    () => check(false, 'lost job still spinning'),
  )
  await shoot(page, '10b-teach-lost-job')
  await page.close()
}

try {
  await learnRun(1440, 900, '')
  await learnRun(1920, 1080, '-1920')
  await teachRun()
  await uploadRun()
} finally {
  await browser.close()
}
if (problems.length) {
  console.log('Problems:\n' + problems.join('\n'))
  process.exitCode = 1
} else {
  console.log('No problems found')
}
