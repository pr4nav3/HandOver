// End to end check of the learn screen against the real server.
//
//   HANDOVER_CHECK=mock scripts/run_server.sh                     (repo root, port 8000)
//   .venv/bin/python -m server.replay lessons/demo-v1/norm.mp4 --loop --select demo-v1
//   npx vite --port 5173                                          (web/, proxies to 8000)
//   node e2e/real-server.mjs                                       (SHOTS_CHANNEL=msedge to use Edge)
//
// Checks: live frames arrive, a camera verified advance happens (badge and
// progress), Next walks to Done without errors, Start over on Done returns
// to step 1.

import { chromium } from 'playwright'
import { join, dirname } from 'node:path'
import { fileURLToPath } from 'node:url'

const APP = process.env.APP || 'http://localhost:5173'
const OUT = join(dirname(fileURLToPath(import.meta.url)), '..', 'screenshots')
const browser = await chromium.launch({ channel: process.env.SHOTS_CHANNEL === 'chromium' ? undefined : process.env.SHOTS_CHANNEL || 'chrome', args: ['--autoplay-policy=no-user-gesture-required'] })
const page = await browser.newPage({ viewport: { width: 1440, height: 900 } })
const problems = []
page.on('pageerror', (e) => problems.push(`pageerror: ${e.message}`))
const check = (ok, msg) => (ok ? console.log('ok  ', msg) : problems.push(msg))

try {
  // Community lists the lessons; the demo card opens #/learn/demo-v1, which selects it.
  await page.goto(`${APP}/#/community`)
  await page.waitForSelector('.lesson-card')
  const title = (await (await fetch(`${APP}/api/lessons`)).json()).find((l) => l.id === 'demo-v1')?.title ?? 'demo-v1'
  await page.click(`.lesson-card:has-text("${title}")`)
  await page.waitForSelector('.step-count:text("Step 1 of 5")', { timeout: 10000 }).catch(() => problems.push('lesson did not start from its card'))

  await page.waitForFunction(() => {
    const canvas = document.querySelector('.live canvas')
    return canvas && !canvas.classList.contains('hidden') && canvas.width > 0
  }, null, { timeout: 15000 }).then(() => check(true, 'live frames shown'), () => check(false, 'no live frames'))

  const verified = await page
    .waitForSelector('.badge.verified', { timeout: 60000 })
    .then(() => true, () => false)
  check(verified, 'camera verified badge appeared')
  await page.screenshot({ path: join(OUT, '19-real-server-verified.png') })
  // The server may report "verified" a moment before it advances.
  const advanced = await page.waitForSelector('.seg.done', { timeout: 10000 }).then(() => true, () => false)
  check(advanced, 'progress shows a done segment after the camera advance')

  for (let i = 0; i < 8 && !(await page.locator('.badge.done').count()); i++) {
    await page.keyboard.press('ArrowRight')
    await page.waitForTimeout(700)
  }
  check((await page.locator('.badge.done').count()) === 1, 'reached Done')
  check((await page.locator('.seg.done').count()) === 5, 'all five segments done')
  await page.waitForSelector('.finish', { timeout: 5000 }).catch(() => {})
  check((await page.locator('.done-title').innerText().catch(() => '')) === 'Lesson complete', 'Done screen shows Lesson complete')
  check((await page.locator('.finish button.next').innerText().catch(() => '')) === 'Start over', 'Done offers Start over')
  await page.screenshot({ path: join(OUT, '20-real-server-done.png') })

  // Start over is a fresh select_lesson: back to step 1.
  await page.click('.finish button.next')
  await page.waitForSelector('.step-count:text("Step 1 of 5")', { timeout: 5000 }).catch(() => {})
  const count = await page.locator('.step-count').innerText()
  check(count.trim() === 'Step 1 of 5', `Start over returns to step 1 (${count.trim()})`)
} finally {
  await browser.close()
}
if (problems.length) {
  console.log('Problems:\n' + problems.join('\n'))
  process.exitCode = 1
} else console.log('All checks passed')
