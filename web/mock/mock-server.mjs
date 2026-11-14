// Mock of the HandOver server for UI development only. Follows CONTRACT.md:
// REST lessons and jobs, static /lessons files with range requests, and
// /ws/ui with fake camera frames and fake state changes.
//
//   PORT=8010 node mock/mock-server.mjs
//
// Env:
//   PORT        default 8000
//   MOCK_AUTO   1 (default) auto-advances steps; 0 waits for next/back or /mock calls
//   MOCK_CAMERA 1 (default) sends fake frames; 0 starts with no camera
//   MOCK_SOURCE camera source in state.camera: phone (default), glasses, browser, file (shows "Recording")
//   MOCK_OFFLINE no_key | rate_limited | errors: start with checks off
//   MOCK_MISTAKE behind:<0-based step> or ahead:<0-based step>: after 4 s on that step send `mistake`
//
// Test hooks (plain GET so curl and Playwright can drive it):
//   /mock/advance?reason=camera   advance one step as if the check passed
//   /mock/status?s=checking       set the status
//   /mock/camera?on=0             connect or disconnect the fake camera
//   /mock/goto?step=3             jump to a step
//   /mock/error?m=text            send {"type":"error"} to UI clients
//   /mock/recut                   bump rev as if the lesson was re-cut
//   /mock/restart                 forget the lesson and jobs, drop UI sockets (server restart)
//   /mock/mistake?kind=behind     send a mistake for the current step now (kind behind or ahead)
//   /mock/offline?r=rate_limited  checks off with a reason; r= (empty) turns checks back on
//   /mock/source?s=file           change the camera source

import { createServer } from 'node:http'
import { createReadStream, existsSync, readdirSync, readFileSync, statSync } from 'node:fs'
import { join, dirname, extname, resolve, sep } from 'node:path'
import { fileURLToPath } from 'node:url'
import { WebSocketServer } from 'ws'
import { FIXTURE_DIR, fixtureExists, makeFixture } from './make-fixture.mjs'

const here = dirname(fileURLToPath(import.meta.url))
const REPO_LESSONS = resolve(here, '..', '..', 'lessons')
const PORT = Number(process.env.PORT || 8000)
const AUTO = process.env.MOCK_AUTO !== '0'

if (!fixtureExists()) {
  console.log('Building mock fixture lesson with ffmpeg')
  makeFixture()
}

// Lesson folders: everything in the repo's lessons/ plus the mock fixture.
function lessonDirs() {
  const dirs = new Map()
  if (existsSync(REPO_LESSONS)) {
    for (const name of readdirSync(REPO_LESSONS)) {
      const dir = join(REPO_LESSONS, name)
      if (existsSync(join(dir, 'lesson.json'))) dirs.set(name, dir)
    }
  }
  if (!dirs.has('mock-demo')) dirs.set('mock-demo', FIXTURE_DIR)
  return dirs
}

// lesson.json mtime in ms, plus a bump per /mock/recut call.
let revBump = 0
function lessonRev(id) {
  const dir = lessonDirs().get(id)
  if (!dir) return 0
  return Math.floor(statSync(join(dir, 'lesson.json')).mtimeMs) + revBump
}

function readLesson(id) {
  const dir = lessonDirs().get(id)
  if (!dir) return null
  return JSON.parse(readFileSync(join(dir, 'lesson.json'), 'utf8'))
}

const TYPES = { '.mp4': 'video/mp4', '.vtt': 'text/vtt', '.jpg': 'image/jpeg', '.json': 'application/json' }

function sendJson(res, code, body) {
  res.writeHead(code, { 'Content-Type': 'application/json' })
  res.end(JSON.stringify(body))
}

function serveFile(req, res, file) {
  const size = statSync(file).size
  const type = TYPES[extname(file)] || 'application/octet-stream'
  const range = /bytes=(\d*)-(\d*)/.exec(req.headers.range || '')
  if (range) {
    const start = range[1] ? Number(range[1]) : 0
    const end = range[2] ? Math.min(Number(range[2]), size - 1) : size - 1
    res.writeHead(206, { 'Content-Type': type, 'Content-Range': `bytes ${start}-${end}/${size}`, 'Accept-Ranges': 'bytes', 'Content-Length': end - start + 1 })
    createReadStream(file, { start, end }).pipe(res)
  } else {
    res.writeHead(200, { 'Content-Type': type, 'Accept-Ranges': 'bytes', 'Content-Length': size })
    createReadStream(file).pipe(res)
  }
}

// Fake upload jobs walk through the statuses, then point at the mock lesson.
const jobs = new Map()
const JOB_FLOW = ['queued', 'normalizing', 'extracting', 'cutting', 'done']

// Shared learn state.
const state = {
  lesson_id: null,
  step: 0,
  status: 'watching',
  camera_connected: process.env.MOCK_CAMERA !== '0',
  last_check: null,
  check_offline: !!process.env.MOCK_OFFLINE,
  check_offline_reason: process.env.MOCK_OFFLINE || null,
  mistake: null,
}
let cameraSource = process.env.MOCK_SOURCE || 'phone'
const cameraInfo = () =>
  state.camera_connected
    ? { name: cameraSource === 'file' ? 'Replay: skipped-flip.mp4' : 'Mock iPhone', platform: cameraSource === 'file' ? 'replay' : 'ios', source: cameraSource }
    : null
const [plantKind, plantStep] = (process.env.MOCK_MISTAKE || '').split(':')
let plantedOn = -1
let stepSince = Date.now()
const clients = new Set()

const steps = () => readLesson(state.lesson_id)?.steps ?? []
const stateMsg = () => ({ type: 'state', ...state, camera: cameraInfo(), total: steps().length, rev: lessonRev(state.lesson_id) })

function broadcast(msg) {
  const text = JSON.stringify(msg)
  for (const ws of clients) ws.send(text)
}

function baseStatus() {
  const s = steps()[state.step]
  return s?.check_type === 'manual' ? 'manual' : 'watching'
}

// Like the hub: send `mistake` once, keep it in state until step change or dismiss.
function sendMistake(kind) {
  const s = state.step
  const list = steps()
  const looks_like = kind === 'ahead' ? Math.min(s + 1, list.length - 1) : Math.max(0, s - 1)
  const message = kind === 'ahead' ? "You're ahead." : list[s]?.common_mistake || `This still looks like step ${looks_like + 1}.`
  const m = { step: s, kind, looks_like, message, confidence: 0.86, source: 'mock' }
  state.mistake = m
  broadcast({ type: 'mistake', ...m })
  broadcast(stateMsg())
}

function setStatus(status) {
  state.status = status
  broadcast(stateMsg())
}

function goTo(to, reason) {
  const total = steps().length
  if (!total) return
  const from = state.step
  if (to >= total) {
    // Same as the real server: announce to == total, then hold step at total - 1.
    if (state.status === 'done') return
    state.step = total - 1
    state.status = 'done'
    state.mistake = null
    if (reason) broadcast({ type: 'advance', from, to: total, reason })
    broadcast(stateMsg())
    return
  }
  state.step = Math.max(0, to)
  state.status = baseStatus()
  state.last_check = null
  state.mistake = null
  if (state.step !== plantedOn) plantedOn = -1
  stepSince = Date.now()
  if (reason) broadcast({ type: 'advance', from, to: state.step, reason })
  broadcast(stateMsg())
}

function selectLesson(id, ws) {
  if (!lessonDirs().has(id)) {
    ws?.send(JSON.stringify({ type: 'error', message: `Unknown lesson: ${id}` }))
    return
  }
  state.lesson_id = id
  state.step = 0
  state.status = baseStatus()
  state.last_check = null
  state.mistake = null
  plantedOn = -1
  stepSince = Date.now()
  broadcast(stateMsg())
}

// Start on the first available lesson, preferring a real one.
selectLesson([...lessonDirs().keys()].sort((a, b) => (a === 'mock-demo') - (b === 'mock-demo'))[0])

// Auto mode: watch for a bit, check, then verify and advance.
setInterval(() => {
  if (!AUTO || state.status === 'done' || !state.lesson_id) return
  const t = Date.now() - stepSince
  const manual = steps()[state.step]?.check_type === 'manual'
  if (manual) {
    if (t > 9000) goTo(state.step + 1, 'timer')
    return
  }
  if (plantKind && Number(plantStep) === state.step && plantedOn !== state.step && t > 4000) {
    plantedOn = state.step
    sendMistake(plantKind)
  }
  // Checks off, or a mistake on screen: wait for Next (or a dismiss).
  if (state.check_offline || state.mistake) return
  if (t > 3500 && state.status === 'watching') {
    state.last_check = { done: 'no', confidence: 0.85, latency_ms: 910, reason: 'seams still facing up' }
    setStatus('checking')
  }
  if (t > 7000 && state.status === 'checking') {
    state.last_check = { done: 'yes', confidence: 0.92, latency_ms: 640, reason: null }
    goTo(state.step + 1, 'camera')
  }
}, 250)

// Fake camera: cycle through the current lesson's reference frames.
let frameTick = 0
setInterval(() => {
  if (!state.camera_connected || !clients.size || !state.lesson_id) return
  const dir = lessonDirs().get(state.lesson_id)
  const list = steps()
  if (!dir || !list.length) return
  const s = list[Math.min(state.step, list.length - 1)]
  const others = list.map((x) => x.ref_frame)
  const pick = frameTick++ % 6 < 4 ? s.ref_frame : others[frameTick % others.length]
  const file = join(dir, pick)
  if (!existsSync(file)) return
  const jpeg = readFileSync(file)
  for (const ws of clients) ws.send(jpeg, { binary: true })
}, 400)

const server = createServer((req, res) => {
  const url = new URL(req.url, 'http://x')
  const path = decodeURIComponent(url.pathname)

  if (path === '/api/lessons' && req.method === 'GET') {
    const list = [...lessonDirs().keys()].map((id) => {
      const l = readLesson(id)
      return { id, title: l.title, steps: l.steps.length }
    })
    return sendJson(res, 200, list)
  }
  let m = /^\/api\/lessons\/([^/]+)$/.exec(path)
  if (m && req.method === 'GET') {
    const l = readLesson(m[1])
    return l ? sendJson(res, 200, l) : sendJson(res, 404, { detail: 'Not found' })
  }
  if (path === '/api/lesson' && req.method === 'POST') {
    req.resume()
    req.on('end', () => {
      const job = `job-${Date.now().toString(36)}`
      jobs.set(job, Date.now())
      sendJson(res, 200, { job, id: 'mock-demo' })
    })
    return
  }
  m = /^\/api\/jobs\/([^/]+)$/.exec(path)
  if (m) {
    const began = jobs.get(m[1])
    if (!began) return sendJson(res, 404, { detail: 'Unknown job' })
    const i = Math.min(JOB_FLOW.length - 1, Math.floor((Date.now() - began) / 2000))
    return sendJson(res, 200, { status: JOB_FLOW[i], message: '', id: 'mock-demo' })
  }
  m = /^\/lessons\/([^/]+)\/(.+)$/.exec(path)
  if (m) {
    const dir = lessonDirs().get(m[1])
    const file = dir && resolve(dir, m[2])
    if (!file || !file.startsWith(dir + sep) || !existsSync(file)) {
      res.writeHead(404)
      return res.end()
    }
    return serveFile(req, res, file)
  }
  if (path === '/capture') {
    res.writeHead(200, { 'Content-Type': 'text/plain' })
    return res.end('Mock server: the real capture page lives in the FastAPI server.')
  }

  // Test hooks.
  if (path === '/mock/advance') {
    goTo(state.step + 1, url.searchParams.get('reason') || 'camera')
    return sendJson(res, 200, stateMsg())
  }
  if (path === '/mock/status') {
    setStatus(url.searchParams.get('s') || 'watching')
    return sendJson(res, 200, stateMsg())
  }
  if (path === '/mock/camera') {
    state.camera_connected = url.searchParams.get('on') !== '0'
    broadcast(stateMsg())
    return sendJson(res, 200, stateMsg())
  }
  if (path === '/mock/error') {
    broadcast({ type: 'error', message: url.searchParams.get('m') || 'Mock error' })
    return sendJson(res, 200, { ok: true })
  }
  if (path === '/mock/recut') {
    revBump += 1
    broadcast(stateMsg())
    return sendJson(res, 200, stateMsg())
  }
  if (path === '/mock/restart') {
    jobs.clear()
    state.lesson_id = null
    state.step = 0
    state.status = 'watching'
    state.last_check = null
    for (const ws of clients) ws.terminate()
    clients.clear()
    return sendJson(res, 200, stateMsg())
  }
  if (path === '/mock/mistake') {
    if (state.lesson_id && state.status !== 'done') sendMistake(url.searchParams.get('kind') === 'ahead' ? 'ahead' : 'behind')
    return sendJson(res, 200, stateMsg())
  }
  if (path === '/mock/offline') {
    const r = url.searchParams.get('r') || ''
    state.check_offline = !!r
    state.check_offline_reason = r || null
    broadcast(stateMsg())
    return sendJson(res, 200, stateMsg())
  }
  if (path === '/mock/source') {
    cameraSource = url.searchParams.get('s') || 'phone'
    broadcast(stateMsg())
    return sendJson(res, 200, stateMsg())
  }
  if (path === '/mock/goto') {
    goTo(Number(url.searchParams.get('step') || 0), null)
    return sendJson(res, 200, stateMsg())
  }

  res.writeHead(404)
  res.end()
})

const wss = new WebSocketServer({ noServer: true })
server.on('upgrade', (req, socket, head) => {
  const path = new URL(req.url, 'http://x').pathname
  if (path === '/ws/ui') {
    wss.handleUpgrade(req, socket, head, (ws) => wss.emit('connection', ws))
  } else if (path === '/ws/camera') {
    wss.handleUpgrade(req, socket, head, (ws) => ws.on('message', () => {}))
  } else {
    socket.destroy()
  }
})

wss.on('connection', (ws) => {
  clients.add(ws)
  ws.send(JSON.stringify(stateMsg()))
  ws.on('close', () => clients.delete(ws))
  ws.on('message', (data, isBinary) => {
    if (isBinary) return
    let msg
    try {
      msg = JSON.parse(String(data))
    } catch {
      return
    }
    // Like the real server: next/back whose `from` is not the current step is
    // stale (a camera advance won the race) and is dropped. No `from` = legacy.
    const stale = (msg.type === 'next' || msg.type === 'back') && msg.from !== undefined && msg.from !== state.step
    if (msg.type === 'select_lesson') selectLesson(msg.id, ws)
    else if (!state.lesson_id) ws.send(JSON.stringify({ type: 'error', message: 'No lesson selected' }))
    else if (stale) console.log(`ignored stale ${msg.type} from ${msg.from} (at ${state.step})`)
    else if (msg.type === 'next' && state.status !== 'done') goTo(state.step + 1, msg.reason || 'button')
    else if (msg.type === 'back') goTo(state.status === 'done' ? state.step : state.step - 1, null) // back from done returns to the last step
    else if (msg.type === 'goto') goTo(Number(msg.step) || 0, null)
    else if (msg.type === 'dismiss_mistake') {
      state.mistake = null
      broadcast(stateMsg())
    }
  })
})

server.listen(PORT, () => {
  console.log(`Mock HandOver server on http://localhost:${PORT} (auto ${AUTO ? 'on' : 'off'})`)
  console.log(`Lessons: ${[...lessonDirs().keys()].join(', ')}`)
})
