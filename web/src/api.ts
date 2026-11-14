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
}

export interface Lesson {
  id: string
  title: string
  video: string
  steps: Step[]
}

export interface LessonSummary {
  id: string
  title: string
  steps: number
}

export type Status = 'watching' | 'checking' | 'verified' | 'manual' | 'done'

export interface StateMsg {
  type: 'state'
  lesson_id: string | null
  step: number
  total: number
  status: Status
  last_check: { done: 'yes' | 'no' | 'unsure'; confidence: number; latency_ms: number } | null
  camera_connected: boolean
  /** lesson.json mtime in ms; changes after a recut. Older servers omit it. */
  rev?: number
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

/** A non 2xx response, with its status code. */
export class HttpError extends Error {
  status: number
  constructor(status: number, statusText: string) {
    super(`${status} ${statusText}`)
    this.status = status
  }
}

async function getJson<T>(url: string): Promise<T> {
  const res = await fetch(url)
  if (!res.ok) throw new HttpError(res.status, res.statusText)
  return res.json() as Promise<T>
}

export const listLessons = () => getJson<LessonSummary[]>('/api/lessons')
export const getLesson = (id: string) => getJson<Lesson>(`/api/lessons/${encodeURIComponent(id)}`)
export const getJob = (job: string) => getJson<Job>(`/api/jobs/${encodeURIComponent(job)}`)

export async function uploadLesson(file: File, title: string): Promise<{ job: string; id: string }> {
  const body = new FormData()
  body.append('file', file)
  body.append('title', title)
  const res = await fetch('/api/lesson', { method: 'POST', body })
  if (!res.ok) throw new Error(`Upload failed (${res.status})`)
  return res.json()
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
