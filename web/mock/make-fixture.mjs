// Builds a small placeholder lesson for UI development only, in
// web/mock/fixtures/mock-demo. Calm colored scenes stand in for real video;
// the captions carry the step text. Needs ffmpeg on PATH.
//
//   node mock/make-fixture.mjs

import { execFileSync } from 'node:child_process'
import { mkdirSync, writeFileSync, existsSync, rmSync } from 'node:fs'
import { join, dirname } from 'node:path'
import { fileURLToPath } from 'node:url'

const here = dirname(fileURLToPath(import.meta.url))
export const FIXTURE_DIR = join(here, 'fixtures', 'mock-demo')

const STEP_SECONDS = 6
const STEPS = [
  { title: 'Start with a square sheet, colored side down', check: 'manual', cues: ['Start with a square sheet of paper.', 'Colored side facing down.'] },
  { title: 'Fold in half both ways and unfold', check: 'camera', cues: ['Fold it in half, corner to corner.', 'Unfold, then fold the other diagonal.'] },
  { title: 'Fold all four corners to the center', check: 'camera', cues: ['Bring each corner to the center point.', 'Crease firmly so the flaps stay down.'] },
  { title: 'Flip it over', check: 'manual', cues: ['Turn the paper over.', 'The flaps are now underneath.'] },
  { title: 'Fold the new corners to the center again', check: 'camera', cues: ['Fold the four new corners to the center.', 'You should see a smaller square.'] },
  { title: 'Fold in half and open the pockets', check: 'camera', cues: ['Fold it in half to make a rectangle.', 'Push your fingers into the four pockets.'] },
]
const COLORS = ['0x2c3a4a', '0x30402f', '0x47392a', '0x3a2f47', '0x4a302e', '0x2b4241']

const pad = (n) => String(n).padStart(2, '0')
const mmss = (s) => `${pad(Math.floor(s / 60))}:${pad(s % 60)}`
const vttTime = (s) => `00:${pad(Math.floor(s / 60))}:${pad(s % 60)}.000`

function ffmpeg(args) {
  execFileSync('ffmpeg', ['-hide_banner', '-loglevel', 'error', '-y', ...args], { stdio: 'inherit' })
}

export function makeFixture() {
  rmSync(FIXTURE_DIR, { recursive: true, force: true })
  for (const d of ['clips', 'captions', 'frames']) mkdirSync(join(FIXTURE_DIR, d), { recursive: true })

  const steps = []
  STEPS.forEach((s, i) => {
    const nn = pad(i + 1)
    const clip = join(FIXTURE_DIR, 'clips', `${nn}.mp4`)
    // A soft card that drifts across a muted background.
    const filter =
      `color=c=${COLORS[i]}:s=1280x720:d=${STEP_SECONDS}:r=30[bg];` +
      `color=c=0xe9e4da:s=300x300:d=${STEP_SECONDS}:r=30[card];` +
      `[bg][card]overlay=x='300+${120 * (i % 3)}+t*60':y='200+40*sin(t*1.3)',format=yuv420p[v]`
    ffmpeg(['-filter_complex', filter, '-f', 'lavfi', '-i', `anullsrc=r=48000:cl=mono`, '-map', '[v]', '-map', '0:a?', '-t', String(STEP_SECONDS), '-c:v', 'libx264', '-preset', 'veryfast', '-c:a', 'aac', '-shortest', clip])
    ffmpeg(['-sseof', '-0.2', '-i', clip, '-frames:v', '1', '-q:v', '3', join(FIXTURE_DIR, 'frames', `${nn}.jpg`)])
    const half = STEP_SECONDS / 2
    writeFileSync(
      join(FIXTURE_DIR, 'captions', `${nn}.vtt`),
      `WEBVTT\n\n${vttTime(0)} --> ${vttTime(half)}\n${s.cues[0]}\n\n${vttTime(half)} --> ${vttTime(STEP_SECONDS)}\n${s.cues[1]}\n`,
    )
    steps.push({
      n: i + 1,
      title: s.title,
      start: mmss(i * STEP_SECONDS),
      end: mmss((i + 1) * STEP_SECONDS),
      clip: `clips/${nn}.mp4`,
      captions: `captions/${nn}.vtt`,
      ref_frame: `frames/${nn}.jpg`,
      check_type: s.check,
      check_question: `Mock check for step ${i + 1}`,
      prerequisites: i ? [i] : [],
    })
  })

  const list = steps.map((s) => `file '${join(FIXTURE_DIR, s.clip)}'`).join('\n')
  const listFile = join(FIXTURE_DIR, 'concat.txt')
  writeFileSync(listFile, list)
  ffmpeg(['-f', 'concat', '-safe', '0', '-i', listFile, '-c', 'copy', join(FIXTURE_DIR, 'norm.mp4')])
  rmSync(listFile)

  const lesson = { id: 'mock-demo', title: 'Fold a fortune teller (mock)', video: 'norm.mp4', steps }
  writeFileSync(join(FIXTURE_DIR, 'lesson.json'), JSON.stringify(lesson, null, 2))
  return lesson
}

export const fixtureExists = () => existsSync(join(FIXTURE_DIR, 'lesson.json'))

if (process.argv[1] === fileURLToPath(import.meta.url)) {
  makeFixture()
  console.log(`Fixture written to ${FIXTURE_DIR}`)
}
