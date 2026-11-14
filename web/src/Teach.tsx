import { useEffect, useRef, useState } from 'react'
import type { DragEvent, FormEvent } from 'react'
import { HttpError, getJob, getLesson, lessonUrl, listLessons, toSeconds, uploadLesson } from './api'
import type { JobStatus, Lesson, LessonSummary } from './api'
import { TopBar } from './TopBar'
import { useFitBox } from './useFitBox'

const JOB_WORDS: Record<JobStatus, string> = {
  queued: 'Queued',
  normalizing: 'Normalizing video',
  extracting: 'Finding steps',
  cutting: 'Cutting clips',
  done: 'Done',
  error: 'Something went wrong',
}

// Consecutive failed job polls (one a second) before giving up.
const MAX_POLL_FAILURES = 30

// Muted, distinct hues for step segments.
const PALETTE = ['#6f93b8', '#7fa682', '#c29d6c', '#a084b3', '#c2837c', '#6aa6a3', '#b3a463', '#8b90c2']
export const stepColor = (i: number) => PALETTE[i % PALETTE.length]

const pad = (n: number) => String(Math.floor(n)).padStart(2, '0')
const fmt = (s: number) => `${pad(s / 60)}:${pad(s % 60)}`
const sizeLabel = (b: number) => (b >= 1e6 ? `${(b / 1e6).toFixed(1)} MB` : `${Math.max(1, Math.round(b / 1e3))} KB`)

export function Teach() {
  const [lessons, setLessons] = useState<LessonSummary[] | null>(null)
  const [lesson, setLesson] = useState<Lesson | null>(null)
  const [error, setError] = useState('')

  const refreshLessons = () =>
    listLessons()
      .then(setLessons)
      .catch(() => setLessons([]))

  useEffect(() => {
    refreshLessons()
  }, [])

  const open = (id: string) => {
    setError('')
    getLesson(id)
      .then(setLesson)
      .catch((err) => setError(err instanceof HttpError && err.detail ? `Could not open that lesson: ${err.detail}` : 'Could not open that lesson.'))
  }

  return (
    <div className="page teach">
      <TopBar route="teach" title={lesson?.title}>
        {lesson && (
          <button className="ghost" onClick={() => setLesson(null)}>
            New lesson
          </button>
        )}
      </TopBar>
      {lesson ? (
        <LessonView lesson={lesson} />
      ) : (
        <Start
          lessons={lessons}
          error={error}
          onOpen={open}
          onCreated={(id) => {
            refreshLessons()
            open(id)
          }}
        />
      )}
    </div>
  )
}

function Start({
  lessons,
  error,
  onOpen,
  onCreated,
}: {
  lessons: LessonSummary[] | null
  error: string
  onOpen: (id: string) => void
  onCreated: (id: string) => void
}) {
  const [file, setFile] = useState<File | null>(null)
  const [title, setTitle] = useState('')
  const [dragging, setDragging] = useState(false)
  const [job, setJob] = useState<{ job: string; status: JobStatus; message: string } | null>(null)
  const [uploadError, setUploadError] = useState('')
  const [uploading, setUploading] = useState(false)
  const inputRef = useRef<HTMLInputElement>(null)
  const createdRef = useRef(onCreated)
  createdRef.current = onCreated

  // Poll the job once a second until it finishes.
  const jobId = job?.job
  useEffect(() => {
    if (!jobId) return
    let live = true
    let failures = 0
    const fail = (message: string) => {
      window.clearInterval(timer)
      setJob({ job: jobId, status: 'error', message })
    }
    const timer = window.setInterval(async () => {
      try {
        const j = await getJob(jobId)
        if (!live) return
        failures = 0
        setJob({ job: jobId, status: j.status, message: j.message })
        if (j.status === 'done' || j.status === 'error') window.clearInterval(timer)
        if (j.status === 'done') createdRef.current(j.id)
      } catch (err) {
        if (!live) return
        // 404: the server restarted and forgot the job, so it will never finish.
        if (err instanceof HttpError && err.status === 404) fail('The server restarted and lost this job. Upload the video again.')
        // Keep polling through brief network hiccups, but not forever.
        else if (++failures >= MAX_POLL_FAILURES) fail('Lost contact with the server. Check that it is running, then upload again.')
      }
    }, 1000)
    return () => {
      live = false
      window.clearInterval(timer)
    }
  }, [jobId])

  const pick = (f: File | undefined) => {
    if (!f) return
    setFile(f)
    if (!title) setTitle(f.name.replace(/\.[^.]+$/, '').replace(/[-_]+/g, ' '))
  }

  const onDrop = (e: DragEvent) => {
    e.preventDefault()
    setDragging(false)
    pick(e.dataTransfer.files[0])
  }

  const submit = async (e: FormEvent) => {
    e.preventDefault()
    if (!file || !title.trim()) return
    setUploadError('')
    try {
      setUploading(true)
      const res = await uploadLesson(file, title.trim())
      setJob({ job: res.job, status: 'queued', message: '' })
    } catch (err) {
      setUploadError(err instanceof Error ? err.message : 'Upload failed')
    } finally {
      setUploading(false)
    }
  }

  const busy = uploading || (!!job && job.status !== 'error')

  return (
    <main className="teach-start">
      <form className="panel upload" onSubmit={submit}>
        <h2>New lesson</h2>
        <p className="muted">Upload one video of the whole task. It is cut into steps with captions.</p>
        <div
          className={`drop ${dragging ? 'over' : ''} ${file ? 'has-file' : ''}`}
          onDragOver={(e) => {
            e.preventDefault()
            setDragging(true)
          }}
          onDragLeave={() => setDragging(false)}
          onDrop={onDrop}
          onClick={() => inputRef.current?.click()}
          role="button"
          tabIndex={0}
          onKeyDown={(e) => (e.key === 'Enter' || e.key === ' ') && inputRef.current?.click()}
        >
          <input ref={inputRef} type="file" accept="video/*" hidden onChange={(e) => pick(e.target.files?.[0])} />
          {file ? (
            <>
              <strong>{file.name}</strong>
              <span className="muted">{sizeLabel(file.size)}. Click to choose another.</span>
            </>
          ) : (
            <>
              <strong>Drop a video here</strong>
              <span className="muted">or click to choose a file</span>
            </>
          )}
        </div>
        <label className="field">
          <span>Title</span>
          <input value={title} onChange={(e) => setTitle(e.target.value)} placeholder="Fold a fortune teller" />
        </label>
        <div className="upload-row">
          <button className="primary" type="submit" disabled={!file || !title.trim() || busy}>
            Make lesson
          </button>
          {uploading && (
            <span className="job" aria-live="polite">
              <span className="spinner" />
              Uploading
            </span>
          )}
          {!uploading && job && (
            <span className={`job ${job.status}`} aria-live="polite">
              {job.status !== 'error' && <span className="spinner" />}
              {job.status === 'error' ? job.message || JOB_WORDS.error : JOB_WORDS[job.status]}
            </span>
          )}
          {uploadError && <span className="job error">{uploadError}</span>}
        </div>
      </form>

      <section className="panel existing">
        <h2>Open a lesson</h2>
        {error && <p className="job error">{error}</p>}
        {lessons === null && <p className="muted">Loading</p>}
        {lessons?.length === 0 && <p className="muted">No lessons yet.</p>}
        <ul className="lesson-list">
          {lessons?.map((l) => (
            <li key={l.id}>
              <button onClick={() => onOpen(l.id)}>
                <span>{l.title}</span>
                <span className="muted">{l.steps} steps</span>
              </button>
            </li>
          ))}
        </ul>
      </section>
    </main>
  )
}

function LessonView({ lesson }: { lesson: Lesson }) {
  const videoRef = useRef<HTMLVideoElement>(null)
  // null = the full normalized video, otherwise the index of the clip playing.
  const [clip, setClip] = useState<number | null>(null)
  const [time, setTime] = useState(0)
  const [duration, setDuration] = useState(0)
  const [aspect, setAspect] = useState(16 / 9)
  const colRef = useRef<HTMLElement>(null)
  const belowRef = useRef<HTMLDivElement>(null)
  const box = useFitBox(colRef, aspect, belowRef, 14)

  const steps = lesson.steps
  const spans = steps.map((s) => ({ start: toSeconds(s.start), end: toSeconds(s.end) }))
  const lastEnd = spans.length ? Math.max(...spans.map((s) => s.end)) : 0
  const total = Math.max(duration, lastEnd, 1)

  // Swap the player source: full video or a single clip with its captions.
  useEffect(() => {
    const video = videoRef.current
    if (!video) return
    video.querySelectorAll('track').forEach((t) => t.remove())
    if (clip === null) {
      video.src = lessonUrl(lesson.id, lesson.video || 'norm.mp4')
      video.load()
      return
    }
    const s = steps[clip]
    const track = document.createElement('track')
    track.kind = 'captions'
    track.srclang = 'en'
    track.label = 'English'
    track.default = true
    track.src = lessonUrl(lesson.id, s.captions)
    video.appendChild(track)
    track.track.mode = 'showing'
    video.src = lessonUrl(lesson.id, s.clip)
    video.load()
    video.play().catch(() => {})
  }, [lesson, clip, steps])

  const seek = (i: number) => {
    const video = videoRef.current
    if (!video) return
    const to = spans[i].start
    if (clip !== null) {
      setClip(null)
      video.addEventListener(
        'loadedmetadata',
        () => {
          video.currentTime = to
          video.play().catch(() => {})
        },
        { once: true },
      )
    } else {
      video.currentTime = to
      video.play().catch(() => {})
    }
  }

  const activeSeg = clip ?? spans.findIndex((s) => time >= s.start && time < s.end)

  return (
    <main className="teach-lesson">
      <section className="player-col" ref={colRef}>
        <div className="panel player" style={box ? { width: box.w, height: box.h } : undefined}>
          <video
            ref={videoRef}
            controls
            playsInline
            onTimeUpdate={(e) => setTime(e.currentTarget.currentTime)}
            onLoadedMetadata={(e) => {
              const v = e.currentTarget
              if (clip === null) setDuration(v.duration || 0)
              if (v.videoWidth && v.videoHeight) setAspect(v.videoWidth / v.videoHeight)
            }}
          />
        </div>
        <div className="player-below" ref={belowRef}>
          <div className="player-meta">
            {clip === null ? (
              <span className="muted">Full video. {steps.length} steps.</span>
            ) : (
              <>
                <span>
                  Step {clip + 1}: {steps[clip].title}
                </span>
                <button className="ghost small" onClick={() => setClip(null)}>
                  Show full video
                </button>
              </>
            )}
          </div>
          <div className="timeline" aria-label="Steps timeline">
            <div className="track">
              <div className="track-inner">
                {spans.map((s, i) => (
                  <button
                    key={i}
                    className={`tl-seg ${activeSeg === i ? 'active' : ''}`}
                    style={{
                      left: `${(s.start / total) * 100}%`,
                      width: `${(Math.max(s.end - s.start, 0.2) / total) * 100}%`,
                      background: stepColor(i),
                    }}
                    title={`${i + 1}. ${steps[i].title}`}
                    onClick={() => seek(i)}
                  >
                    <span>{i + 1}</span>
                  </button>
                ))}
                {clip === null && <span className="playhead" style={{ left: `${(time / total) * 100}%` }} />}
              </div>
            </div>
            <div className="tl-scale">
              <span>00:00</span>
              <span>{fmt(total)}</span>
            </div>
          </div>
        </div>
      </section>

      <section className="thumbs" aria-label="Steps">
        {steps.map((s, i) => (
          <button key={i} className={`thumb ${clip === i ? 'active' : ''}`} onClick={() => setClip(i)}>
            <span className="thumb-img">
              <img src={lessonUrl(lesson.id, s.ref_frame)} alt="" loading="lazy" />
              {s.check_type === 'manual' && <span className="thumb-tag">Manual</span>}
            </span>
            <span className="thumb-text">
              <span className="thumb-num" style={{ color: stepColor(i) }}>
                Step {i + 1}
                <span className="muted">
                  {' '}
                  {s.start} to {s.end}
                </span>
              </span>
              <span className="thumb-title">{s.title}</span>
            </span>
          </button>
        ))}
      </section>
    </main>
  )
}
