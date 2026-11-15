import './teach.css'
import { useEffect, useRef, useState } from 'react'
import type { DragEvent, FormEvent } from 'react'
import { go } from './App'
import { HttpError, getJob, getLesson, lessonUrl, listLessons, toSeconds } from './api'
import type { JobStatus, Lesson, LessonSummary } from './api'
import { ChevronLeftIcon, FilmIcon, VideoIcon } from './icons'
import { TopBar } from './TopBar'
import { ProcessCard, sizeLabel } from './TeachProcessing'
import type { UploadPhase } from './TeachProcessing'
import { useFitBox } from './useFitBox'

// Consecutive failed job polls (one a second) before giving up.
const MAX_POLL_FAILURES = 30

const pad = (n: number) => String(Math.floor(n)).padStart(2, '0')
const fmt = (s: number) => `${pad(s / 60)}:${pad(s % 60)}`
/** "00:03" to "0:03", the step row's short form. */
const short = (ts: string) => {
  const s = toSeconds(ts)
  return `${Math.floor(s / 60)}:${pad(s % 60)}`
}

/**
 * POST /api/lesson with XMLHttpRequest, so the bytes sent are known (fetch has
 * no upload progress). Errors carry the hub's `detail` verbatim.
 */
function sendVideo(file: File, title: string, onProgress: (sent: number, total: number) => void) {
  const xhr = new XMLHttpRequest()
  const done = new Promise<{ job: string; id: string }>((resolve, reject) => {
    xhr.open('POST', '/api/lesson')
    xhr.responseType = 'json'
    xhr.upload.onprogress = (e) => onProgress(e.loaded, e.lengthComputable ? e.total : file.size)
    xhr.onload = () => {
      const body = xhr.response
      if (xhr.status >= 200 && xhr.status < 300 && body?.job) return resolve(body)
      const detail = typeof body?.detail === 'string' ? body.detail : ''
      reject(new HttpError(xhr.status, xhr.statusText, detail || `Upload failed (${xhr.status})`))
    }
    xhr.onerror = () => reject(new Error('Could not reach the hub. Check that it is running, then try again.'))
    xhr.onabort = () => reject(new DOMException('Upload cancelled', 'AbortError'))
    const body = new FormData()
    body.append('file', file)
    body.append('title', title)
    xhr.send(body)
  })
  return { done, abort: () => xhr.abort() }
}

const uploadErrorText = (err: unknown) => {
  const msg = err instanceof Error ? err.message : 'Upload failed'
  return msg === 'too many jobs' ? 'The hub is busy with other lessons. Try again when one finishes.' : msg
}

type Flow = {
  phase: UploadPhase
  sent: number
  total: number
  job: string
  id: string
  status: JobStatus | null
  message: string
  error: string
  lesson: Lesson | null
}

export function Teach() {
  const [lessons, setLessons] = useState<LessonSummary[] | null>(null)
  const [lesson, setLesson] = useState<Lesson | null>(null)
  const [openError, setOpenError] = useState('')

  // Upload form and processing; kept here so Review steps and back keep the ready card.
  const [file, setFile] = useState<File | null>(null)
  const [title, setTitle] = useState('')
  const [flow, setFlow] = useState<Flow | null>(null)
  const abortRef = useRef<(() => void) | null>(null)

  const refreshLessons = () =>
    listLessons()
      .then(setLessons)
      .catch(() => setLessons([]))

  useEffect(() => {
    refreshLessons()
    return () => abortRef.current?.()
  }, [])

  const open = (id: string) => {
    setOpenError('')
    getLesson(id)
      .then(setLesson)
      .catch((err) => setOpenError(err instanceof HttpError && err.detail ? `Could not open that lesson: ${err.detail}` : 'Could not open that lesson.'))
  }

  const patch = (p: Partial<Flow>) => setFlow((f) => (f ? { ...f, ...p } : f))

  const start = async () => {
    if (!file || !title.trim()) return
    abortRef.current?.()
    setFlow({ phase: 'uploading', sent: 0, total: file.size, job: '', id: '', status: null, message: '', error: '', lesson: null })
    const req = sendVideo(file, title.trim(), (sent, total) => patch({ sent, total }))
    abortRef.current = req.abort
    try {
      const res = await req.done
      patch({ phase: 'polling', job: res.job, id: res.id, status: 'queued', sent: file.size, total: file.size })
    } catch (err) {
      if (err instanceof DOMException && err.name === 'AbortError') return
      patch({ phase: 'error', error: uploadErrorText(err) })
    } finally {
      if (abortRef.current === req.abort) abortRef.current = null
    }
  }

  const cancel = () => {
    abortRef.current?.()
    abortRef.current = null
    setFlow(null)
  }

  // Poll the job once a second until it finishes.
  const jobId = flow?.phase === 'polling' ? flow.job : ''
  useEffect(() => {
    if (!jobId) return
    let live = true
    let failures = 0
    const stop = () => window.clearInterval(timer)
    const timer = window.setInterval(async () => {
      try {
        const j = await getJob(jobId)
        if (!live) return
        failures = 0
        if (j.status === 'error') {
          stop()
          patch({ phase: 'error', error: j.message || 'The hub could not make this lesson.' })
        } else if (j.status === 'done') {
          stop()
          patch({ phase: 'done', status: 'done', id: j.id, message: '' })
          refreshLessons()
          getLesson(j.id)
            .then((l) => patch({ lesson: l }))
            .catch(() => {})
        } else patch({ status: j.status, message: j.message })
      } catch (err) {
        if (!live) return
        // 404: the hub restarted and forgot the job, so it will never finish.
        if (err instanceof HttpError && err.status === 404) {
          stop()
          patch({ phase: 'error', error: 'The hub restarted and lost this job. Upload the video again.' })
        }
        // Keep polling through brief network hiccups, but not forever.
        else if (++failures >= MAX_POLL_FAILURES) {
          stop()
          patch({ phase: 'error', error: 'Lost contact with the hub. Check that it is running, then upload again.' })
        }
      }
    }, 1000)
    return () => {
      live = false
      stop()
    }
  }, [jobId])

  const teachAnother = () => {
    setFlow(null)
    setFile(null)
    setTitle('')
  }

  return (
    <div className="page teach">
      <TopBar route="teach" />
      {lesson ? (
        <LessonView lesson={lesson} onBack={() => setLesson(null)} />
      ) : (
        <div className="page-body">
          <div className="page-inner teach-inner">
            <header className="page-head">
              <div>
                <h1>Teach</h1>
                <p className="page-sub">Record a task once. HandOver turns it into steps.</p>
              </div>
            </header>
            <div className="teach-grid">
              {flow ? (
                <ProcessCard
                  phase={flow.phase}
                  title={title.trim()}
                  fileName={file?.name ?? ''}
                  fileSize={file?.size ?? 0}
                  sent={flow.sent}
                  total={flow.total}
                  job={flow.job}
                  status={flow.status}
                  message={flow.message}
                  error={flow.error}
                >
                  {flow.phase === 'done' ? (
                    <Ready lesson={flow.lesson} id={flow.id} onReview={() => flow.lesson && setLesson(flow.lesson)} onAnother={teachAnother} />
                  ) : flow.phase === 'error' ? (
                    <>
                      <p className="hint">Try again sends the same video. If it fails again, record a new take and talk through each step.</p>
                      <div className="process-actions" key="error-actions">
                        <button className="primary" onClick={start}>
                          Try again
                        </button>
                        <button className="secondary" onClick={() => setFlow(null)}>
                          Change video
                        </button>
                      </div>
                    </>
                  ) : (
                    <>
                      <p className="hint">You can leave this screen. The hub keeps working, and the lesson shows up in Your lessons.</p>
                      {flow.phase === 'uploading' && (
                        <div className="process-actions" key="upload-actions">
                          <button className="secondary" onClick={cancel}>
                            Cancel
                          </button>
                        </div>
                      )}
                    </>
                  )}
                </ProcessCard>
              ) : (
                <NewLesson file={file} title={title} setFile={setFile} setTitle={setTitle} onSubmit={start} />
              )}
              <YourLessons lessons={lessons} error={openError} onOpen={open} />
            </div>
          </div>
        </div>
      )}
    </div>
  )
}

function NewLesson({
  file,
  title,
  setFile,
  setTitle,
  onSubmit,
}: {
  file: File | null
  title: string
  setFile: (f: File) => void
  setTitle: (t: string) => void
  onSubmit: () => void
}) {
  const [dragging, setDragging] = useState(false)
  const inputRef = useRef<HTMLInputElement>(null)

  const pick = (f: File | undefined) => {
    if (!f) return
    setFile(f)
    if (!title) {
      const base = f.name.replace(/\.[^.]+$/, '').replace(/[-_]+/g, ' ').trim()
      setTitle(base ? base[0].toUpperCase() + base.slice(1) : '')
    }
  }

  const onDrop = (e: DragEvent) => {
    e.preventDefault()
    setDragging(false)
    pick(e.dataTransfer.files[0])
  }

  const submit = (e: FormEvent) => {
    e.preventDefault()
    onSubmit()
  }

  return (
    <form className="panel teach-card upload" onSubmit={submit}>
      <h2>New lesson</h2>
      <div
        className={`option-card drop ${dragging ? 'over' : ''} ${file ? 'has-file' : ''}`}
        onDragOver={(e) => {
          e.preventDefault()
          setDragging(true)
        }}
        onDragLeave={() => setDragging(false)}
        onDrop={onDrop}
        onClick={() => inputRef.current?.click()}
        role="button"
        tabIndex={0}
        onKeyDown={(e) => {
          if (e.key === 'Enter' || e.key === ' ') {
            e.preventDefault()
            inputRef.current?.click()
          }
        }}
      >
        <input ref={inputRef} type="file" accept="video/*" hidden onChange={(e) => pick(e.target.files?.[0])} />
        <span className="tile">{file ? <FilmIcon size={24} /> : <VideoIcon />}</span>
        <span className="option-text">
          {file ? (
            <>
              <span className="option-title file-name">{file.name}</span>
              <span className="option-line">{sizeLabel(file.size)}. Click to choose another.</span>
            </>
          ) : (
            <>
              <span className="option-title">Choose a video</span>
              <span className="option-line">or drop it here</span>
            </>
          )}
        </span>
      </div>
      <label className="field">
        <span>Title</span>
        <input value={title} onChange={(e) => setTitle(e.target.value)} placeholder="Fold a fortune teller" maxLength={120} />
      </label>
      <p className="hint">One video of the whole task works best. Talk through each step as you do it.</p>
      <div className="upload-row">
        <button className="primary" type="submit" disabled={!file || !title.trim()}>
          Make lesson
        </button>
      </div>
    </form>
  )
}

function LessonThumb({ id }: { id: string }) {
  const [failed, setFailed] = useState(false)
  return (
    <span className="row-cover">
      {failed ? <FilmIcon size={22} /> : <img src={lessonUrl(id, 'frames/01.jpg')} alt="" loading="lazy" onError={() => setFailed(true)} />}
    </span>
  )
}

function YourLessons({ lessons, error, onOpen }: { lessons: LessonSummary[] | null; error: string; onOpen: (id: string) => void }) {
  return (
    <section className="panel teach-card existing">
      <h2>Your lessons</h2>
      {error && <p className="open-error">{error}</p>}
      {lessons === null && (
        <p className="muted loading-line">
          <span className="spinner" /> Loading
        </p>
      )}
      {lessons?.length === 0 && (
        <div className="lessons-empty">
          <FilmIcon />
          <span>No lessons yet.</span>
        </div>
      )}
      {!!lessons?.length && (
        <>
          <ul className="lesson-list">
            {lessons.map((l) => (
              <li key={l.id}>
                <button className="lesson-row" onClick={() => onOpen(l.id)}>
                  <LessonThumb id={l.id} />
                  <span className="row-text">
                    <span className="row-title">{l.title || l.id}</span>
                    <span className="row-meta">
                      {l.steps} {l.steps === 1 ? 'step' : 'steps'}
                    </span>
                  </span>
                </button>
                <button className="quiet try" onClick={() => go('learn', l.id)}>
                  Try it
                </button>
              </li>
            ))}
          </ul>
          <p className="hint">Open a lesson to review its steps.</p>
        </>
      )}
    </section>
  )
}

function Ready({ lesson, id, onReview, onAnother }: { lesson: Lesson | null; id: string; onReview: () => void; onAnother: () => void }) {
  const n = lesson?.steps.length
  return (
    <div className="ready">
      <p className="ready-line">
        {n === undefined ? 'Loading the steps.' : `HandOver found ${n} ${n === 1 ? 'step' : 'steps'}, cut a clip for each, and added captions.`}
      </p>
      {lesson && lesson.steps.length > 0 && (
        <ol className="ready-strip" aria-label="Steps">
          {lesson.steps.slice(0, 6).map((s, i) => (
            <li key={i} className="ready-frame">
              <img src={lessonUrl(lesson.id, s.ref_frame)} alt="" loading="lazy" />
              <span className="ready-num">{i + 1}</span>
            </li>
          ))}
          {lesson.steps.length > 6 && <li className="ready-more">+{lesson.steps.length - 6}</li>}
        </ol>
      )}
      <div className="process-actions">
        <button className="primary" onClick={() => go('learn', id)}>
          Try it as a learner
        </button>
        <button className="secondary" onClick={onReview} disabled={!lesson}>
          Review steps
        </button>
        <button className="quiet another" onClick={onAnother}>
          Teach another
        </button>
      </div>
    </div>
  )
}

function LessonView({ lesson, onBack }: { lesson: Lesson; onBack: () => void }) {
  const videoRef = useRef<HTMLVideoElement>(null)
  // null = the full normalized video, otherwise the index of the clip playing.
  const [clip, setClip] = useState<number | null>(null)
  const [time, setTime] = useState(0)
  const [duration, setDuration] = useState(0)
  const [aspect, setAspect] = useState(16 / 9)
  const colRef = useRef<HTMLElement>(null)
  const belowRef = useRef<HTMLDivElement>(null)
  const box = useFitBox(colRef, aspect, belowRef, 16)

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
      <div className="review-head">
        <button className="ghost back" onClick={onBack}>
          <ChevronLeftIcon />
          Back to Teach
        </button>
        <div className="review-title">
          <h1>{lesson.title}</h1>
          <span className="muted tabular">
            {steps.length} {steps.length === 1 ? 'step' : 'steps'}, {fmt(total)}
          </span>
        </div>
        <button className="primary" onClick={() => go('learn', lesson.id)}>
          Try it as a learner
        </button>
      </div>

      <div className="review-body">
        <section className="player-col" ref={colRef}>
          <div className="player" style={box ? { width: box.w, height: box.h } : undefined}>
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
            <div className="timeline" aria-label="Steps timeline">
              <div className="track">
                {spans.map((s, i) => (
                  <button
                    key={i}
                    className={`tl-seg ${activeSeg === i ? 'active' : ''}`}
                    style={{
                      left: `${(s.start / total) * 100}%`,
                      width: `${(Math.max(s.end - s.start, 0.2) / total) * 100}%`,
                    }}
                    title={`${i + 1}. ${steps[i].title}`}
                    aria-label={`Step ${i + 1}: ${steps[i].title}`}
                    onClick={() => seek(i)}
                  >
                    <span>{i + 1}</span>
                  </button>
                ))}
                {clip === null && <span className="playhead" style={{ left: `${Math.min(time / total, 1) * 100}%` }} />}
              </div>
              <div className="tl-scale">
                <span>00:00</span>
                <span>{fmt(total)}</span>
              </div>
            </div>
            <div className="player-meta">
              {clip === null ? (
                <span className="muted">Full video. Pick a step to play its clip with captions.</span>
              ) : (
                <>
                  <span className="meta-text">
                    <span className="meta-title">
                      {clip + 1}. {steps[clip].title}
                    </span>
                    <span className="muted tabular">
                      {steps[clip].start} to {steps[clip].end}, {steps[clip].check_type === 'manual' ? 'manual check' : 'camera check'}
                    </span>
                  </span>
                  <button className="ghost" onClick={() => setClip(null)}>
                    Show full video
                  </button>
                </>
              )}
            </div>
          </div>
        </section>

        <section className="panel step-list" aria-label="Steps">
          <h2 className="step-list-head">Steps</h2>
          <div className="thumbs">
            {steps.map((s, i) => (
              <button key={i} className={`thumb step-row ${clip === i ? 'active' : ''}`} onClick={() => setClip(i)}>
                <span className="step-num">{i + 1}</span>
                <span className="thumb-img">
                  <img src={lessonUrl(lesson.id, s.ref_frame)} alt="" loading="lazy" />
                </span>
                <span className="thumb-text">
                  <span className="thumb-title">{s.title}</span>
                  <span className="thumb-meta">
                    {s.check_type === 'manual' && <span className="thumb-tag">Manual</span>}
                    <span className="tabular">
                      {short(s.start)}–{short(s.end)}
                    </span>
                  </span>
                </span>
              </button>
            ))}
          </div>
        </section>
      </div>
    </main>
  )
}
