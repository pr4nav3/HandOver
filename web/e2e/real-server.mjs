// End to end check of the learn screen against the real server.
//
//   HANDOVER_CHECK=mock scripts/run_server.sh                     (repo root, port 8000)
//   .venv/bin/python -m server.replay lessons/demo-v1/norm.mp4 --loop --select demo-v1
//   npx vite --port 5173                                          (web/, proxies to 8000)
//   node e2e/real-server.mjs
//
// Checks: live frames arrive, a camera verified advance happens (badge and
// progress), Next walks to Done without errors, Left arrow from Done returns
// to the last step.

import { chromium } from 'playwright'
import { join, dirname } from 'node:path'
import { fileURLToPath } from 'node:url'

const APP = process.env.APP || 'http://localhost:5173'
const OUT = join(dirname(fileURLToPath(import.meta.url)), '..', 'screenshots')
const browser = await chromium.launch({ channel: 'chrome', args: ['--autoplay-policy=no-user-gesture-required'] })
const page = await browser.newPage({ viewport: { width: 1440, height: 900 } })
const problems = []
page.on('pageerror', (e) => problems.push(`pageerror: ${e.message}`))
const check = (ok, msg) => (ok ? console.log('ok  ', msg) : problems.push(msg))

try {
  await page.goto(`${APP}/#/learn`)
  await page.waitForSelector('.start-card select option[value="demo-v1"]', { state: 'attached' })
  await page.selectOption('.start-card select', 'demo-v1')
  await page.click('text=Start lesson')

  await page.waitForFunction(() => {
    const img = document.querySelector('.live img')
    return img && !img.classList.contains('hidden') && img.src.startsWith('blob:')
  }, null, { timeout: 15000 }).then(() => check(true, 'live frames shown'), () => check(false, 'no live frames'))

  const verified = await page
    .waitForSelector('.badge.verified', { timeout: 60000 })
    .then(() => true, () => false)
  check(verified, 'camera verified badge appeared')
  await page.screenshot({ path: join(OUT, '11-real-server-verified.png') })
  // The server may report "verified" a moment before it advances.
  const advanced = await page.waitForSelector('.seg.done', { timeout: 10000 }).then(() => true, () => false)
  check(advanced, 'progress shows a done segment after the camera advance')

  for (let i = 0; i < 8 && !(await page.locator('.badge.done').count()); i++) {
    await page.keyboard.press('ArrowRight')
    await page.waitForTimeout(700)
  }
  check((await page.locator('.badge.done').count()) === 1, 'reached Done')
  check((await page.locator('.seg.done').count()) === 5, 'all five segments done')
  check(await page.locator('.next').isDisabled(), 'Next disabled at Done')
  await page.screenshot({ path: join(OUT, '12-real-server-done.png') })

  await page.keyboard.press('ArrowLeft')
  await page.waitForTimeout(800)
  const count = await page.locator('.step-count').innerText()
  check(count.trim() === 'Step 5 of 5', `back from Done returns to the last step (${count.trim()})`)
} finally {
  await browser.close()
}
if (problems.length) {
  console.log('Problems:\n' + problems.join('\n'))
  process.exitCode = 1
} else console.log('All checks passed')
