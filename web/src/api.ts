// Types and REST helpers that mirror CONTRACT.md.

export type CheckType = 'camera' | 'manual'

export interface Step {
  n: number
  title: string
  start: string
  end: string
  clip: string
  captions: string
  ref_frame: string
  check_type: CheckType
  check_question?: string
  prerequisites?: number[]
  /** Absolute time in norm.mp4 of the reference frame; null = last frame of the clip. */
  ref_time?: string | null
  /** Shown and spoken when the learner is behind. */
  common_mistake?: string
}

export interface Lesson {
  id: string
  title: string
  video: string
  steps: Step[]
  /** Short warnings from the narration. */
  safety?: string[]
  /** Tools named in the narration. */
  tools?: string[]
}

export interface LessonSummary {
  id: string
  title: string
  steps: number
}

export type Status = 'watching' | 'checking' | 'verified' | 'manual' | 'done'

export type CheckOfflineReason = 'no_key' | 'rate_limited' | 'errors' | 'budget'

/** How the hub checks steps. `mock` passes on a timer and never looks at the camera. */
export type CheckMode = 'mock' | 'claude' | 'gemini'

/** The clip the hub expects to show next: a path inside the lesson folder, or one with its captions. */
export type NextClip = string | { clip: string; captions?: string | null }

export interface LastCheck {
  done: 'yes' | 'no' | 'unsure'
  confidence: number
  latency_ms: number
  /** Up to 8 words on what differs from the reference. */
  reason?: string | null
}

export interface CameraInfo {
  name: string
  platform: string
  source: string
}

/** The mistake object, as carried in state (the message minus `type`). */
export interface Mistake {
  step: number
  /** behind: looks like an earlier step; ahead: looks like a later one; live: something wrong on this step. */
  kind: 'behind' | 'ahead' | 'live'
  /** 0-based step the frame looks like, when the hub knows one. */
  looks_like?: number | null
  /** A few words naming the problem, when the hub has them. */
  label?: string | null
  message: string
  confidence: number
  source: string
}

export interface MistakeMsg extends Mistake {
  type: 'mistake'
}

export interface StateMsg {
  type: 'state'
  lesson_id: string | null
  run_id?: string | null // the run the Done screen scores; sent back with end_lesson
  step: number
  total: number
  status: Status
  last_check: LastCheck | null
  camera_connected: boolean
  /** Active camera, or null. Older servers omit it. */
  camera?: CameraInfo | null
  /** Gemini not in use although mode is gemini. */
  check_offline?: boolean
  check_offline_reason?: CheckOfflineReason | null
  /** The current mistake, or null. */
  mistake?: Mistake | null
  /** lesson.json mtime in ms; changes after a recut. Older servers omit it. */
  rev?: number
  /** Seconds between frames offered to the vision model, at least (set_check_interval). Older servers omit it. */
  check_interval_s?: number
  /** Live frames per second forwarded to each viewer, at most. Older servers omit it. */
  ui_fps?: number
  /** Check backend. Older hubs omit it. */
  check_mode?: CheckMode
  /** The next clip to preload, or null when there is none. Older hubs omit it. */
  next_clip?: NextClip | null
}

export interface AdvanceMsg {
  type: 'advance'
  from: number
  to: number
  reason: 'camera' | 'button' | 'voice' | 'timer'
}

export type JobStatus = 'queued' | 'normalizing' | 'extracting' | 'cutting' | 'done' | 'error'

export interface Job {
  status: JobStatus
  message: string
  id: string
}

/** A non 2xx response, with its status code and the hub's `detail` text when it sent one. */
export class HttpError extends Error {
  status: number
  detail: string
  constructor(status: number, statusText: string, detail = '') {
    super(detail || `${status} ${statusText}`)
    this.status = status
    this.detail = detail
  }
}

/** The hub's FastAPI style `{"detail": "..."}` text, or ''. */
async function errorDetail(res: Response): Promise<string> {
  try {
    const body = await res.json()
    return typeof body?.detail === 'string' ? body.detail : ''
  } catch {
    return ''
  }
}

async function getJson<T>(url: string): Promise<T> {
  const res = await fetch(url)
  if (!res.ok) throw new HttpError(res.status, res.statusText, await errorDetail(res))
  return res.json() as Promise<T>
}

export const listLessons = () => getJson<LessonSummary[]>('/api/lessons')
export const getLesson = (id: string) => getJson<Lesson>(`/api/lessons/${encodeURIComponent(id)}`).then(withDefaults)
export const getJob = (job: string) => getJson<Job>(`/api/jobs/${encodeURIComponent(job)}`)

/**
 * Fills the defaults CONTRACT.md section 3 gives for fields a lesson.json may
 * leave out, so a hand-written lesson never breaks the page.
 */
export function withDefaults(raw: Lesson): Lesson {
  const steps = Array.isArray(raw.steps) ? raw.steps : []
  return {
    ...raw,
    video: raw.video || 'norm.mp4',
    steps: steps.map((s, i) => {
      const nn = String(i + 1).padStart(2, '0')
      return {
        ...s,
        n: s.n || i + 1,
        title: s.title ?? '',
        clip: s.clip || `clips/${nn}.mp4`,
        captions: s.captions || `captions/${nn}.vtt`,
        ref_frame: s.ref_frame || `frames/${nn}.jpg`,
        check_type: s.check_type === 'manual' ? 'manual' : 'camera',
      }
    }),
  }
}

/** URL of a file inside a lesson folder. `rev` busts the cache after a recut. */
export const lessonUrl = (id: string, rel: string, rev?: number) =>
  `/lessons/${encodeURIComponent(id)}/${rel.replace(/^\/+/, '')}${rev ? `?v=${rev}` : ''}`

/** "01:05" or "1:02:03" to seconds. */
export function toSeconds(ts: string): number {
  return ts
    .split(':')
    .map(Number)
    .reduce((acc, part) => acc * 60 + (Number.isFinite(part) ? part : 0), 0)
}
