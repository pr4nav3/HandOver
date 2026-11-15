// Learn (section 7, desktop layout): the live camera on the left, filling its column inside a
// panel; on the right the step's clip with captions filling its column the same way, then the
// step title, the course step list, and the badge with Back and Next. Then Done
// (section 8) with the score, best and weakest step, a tip and the steps breakdown, all from
// this run's real events (section 20).

import { frameUrl, lessonUrl, toSeconds, type Advance, type CameraLink, type HubState, type Lesson, type Mistake, type Step } from "../api";
import { playChime, stopChime } from "../chime";
import { empty, mmss, ring } from "../components";
import { LiveCanvas, type LocalState } from "../frames";
import type { CameraChoice } from "../state";
import { icons } from "../icons";
import { learnFeedback } from "../learn_feedback";
import { replaceLessonPlayback, stopLessonPlayback } from "../lesson_audio";
import {
  DEFAULT_LEARN_LAYOUT,
  MAX_CAMERA_PERCENT,
  MIN_CAMERA_PERCENT,
  layoutFromLeftPercent,
  leftPercent,
  readLearnLayout,
  writeLearnLayout,
  type LearnLayout,
} from "../learn_layout";
import { html, paint, type Raw } from "../util";
import { stepRow } from "./course";

export interface LearnModel {
  state: HubState | null;
  lesson: Lesson | null;
  down: boolean;
  chime: boolean;
  /** running: the hub has this lesson; starting: it was asked to; none: no lesson to show. */
  phase: "running" | "starting" | "none";
  camera: { choice: CameraChoice | null; local: LocalState; link: CameraLink };
}

export interface LearnActions {
  next: (from: number) => void;
  back: (from: number) => void;
  goto: (step: number) => void;
  dismissMistake: () => void;
  library: () => void;
  /** Opens the lesson list (no lesson running). */
  pick: () => void;
  /** Shows the phone pairing code. */
  pair: () => void;
  /** Opens "How should HandOver see your hands?". */
  chooseCamera: () => void;
  /** Tries this computer's camera again after it failed. */
  retryCamera: () => void;
  /** Prevents camera verification from advancing while feedback keeps running. */
  hold: (held: boolean) => void;
  /** The run finished: its summary, for this device's progress and the rating prompt. */
  finished: (s: RunSummary) => void;
}

interface StepRun {
  ms: number;
  how: "camera" | "hand" | "skipped" | null;
  mistakes: number;
  offline: boolean;
}

export interface RunSummary {
  lessonId: string;
  title: string;
  ms: number | null;
  expert: number;
  score: number | null;
  camera: number;
  hand: number;
  skipped: number;
  mistakes: number;
  steps: StepRun[];
}

const TEMPLATE = html`<div class="learn">
  <main class="learn-grid">
    <div class="live-col">
    <section class="panel live" aria-label="Your camera">
      <div class="live-frame hidden"><canvas class="live-canvas" role="img" aria-label="Your camera"></canvas>
        <video class="local-preview" muted playsinline aria-label="This computer's camera" hidden></video>
        <span class="rec" hidden title="Frames come from a recorded video, not a live camera"><span class="rec-dot"></span>Recording</span>
        <p class="live-note" role="status" hidden>Camera lost. Keep going with Next.</p>
      </div>
      <div class="placeholder live-ph"></div>
      <span class="live-chip" hidden></span>
      <span class="badge watching camera-verdict" role="status" aria-live="polite" aria-atomic="true"><span class="badge-dot"></span><span class="badge-label">Getting ready</span></span>
    </section>
    <div class="mistake-card" role="alert" hidden></div>
    </div>
    <button class="learn-divider" type="button" role="separator" aria-orientation="vertical" aria-label="Resize camera and tutorial panels" aria-valuemin="24" aria-valuemax="62"><span></span></button>
    <section class="side">
      <div class="clip-box">
        <div class="clip">
          <video loop playsinline preload="auto" crossorigin="anonymous"></video>
          <button class="unmute" type="button" hidden>${icons.sound}<span>Turn on sound</span></button>
          <span class="result-moment" hidden></span>
          <div class="placeholder clip-ph" hidden><span class="spinner"></span></div>
          <div class="tutorial-transport">
            <button class="tutorial-play" type="button" title="Pause tutorial (K)">${icons.pause}<span>Pause</span></button>
            <button class="replay-clip" type="button" title="Replay tutorial (R)">${icons.refresh}<span class="sr-only">Replay tutorial</span></button>
            <button class="tutorial-cc on" type="button" aria-pressed="true" title="Hide captions (C)">CC</button>
            <input class="tutorial-scrubber" type="range" min="0" max="1" step="0.01" value="0" aria-label="Tutorial position" />
            <span class="tutorial-time" aria-hidden="true">0:00 / 0:00</span>
          </div>
        </div>
      </div>
    </section>
  </main>
  <footer class="learn-footer">
      <div class="step-info">
        <div class="step-meta-row"><p class="step-count" role="status" aria-live="polite">&nbsp;</p>
          <div class="step-actions">
            <div class="learn-layout-tools" aria-label="Workspace layout">
              <button class="quiet small layout-swap" type="button" title="Move the tutorial to the other side">${icons.swap}<span>Swap</span></button>
              <button class="quiet small layout-reset" type="button" title="Restore the default workspace">Reset</button>
            </div>
            <button class="hold-step" type="button" aria-pressed="false" title="Keep camera feedback on this step without advancing (H)">${icons.pause}<span>Hold step</span></button>
          </div>
        </div>
        <h1 class="step-title">&nbsp;</h1>
        <p class="step-instruction">Do this step. HandOver moves on when it sees it done.</p>
        <p class="step-evidence" aria-live="polite"></p>
      </div>
      <div class="controls">
        <details class="steps-disclosure">
          <summary>${icons.grid}<span>All Steps</span><span class="steps-summary-arrow" aria-hidden="true"></span></summary>
          <div class="course-list scroll" aria-label="Steps"></div>
        </details>
        <div class="next-wrap">
          <button class="back" type="button" title="Back (Left Arrow)">Back</button>
          <button class="next" type="button" title="Next (Right Arrow or Space)">Next</button>
        </div>
      </div>
  </footer>
  <div class="done-layer" hidden></div>
  <div class="learn-empty" hidden></div>
</div>`;

const expertOf = (s: Step) => Math.max(0, toSeconds(s.end) - toSeconds(s.start));

export class LearnView {
  private q = <T extends Element>(sel: string) => this.el.querySelector(sel) as T;
  private live: LiveCanvas;
  private video: HTMLVideoElement;
  /** The preview of this computer's camera, straight from getUserMedia. */
  readonly localVideo: HTMLVideoElement;
  private model: LearnModel = {
    state: null,
    lesson: null,
    down: false,
    chime: true,
    phase: "none",
    camera: { choice: null, local: "off", link: "off" },
  };
  private hasFrame = false;
  private stale = false;
  private mistake: Mistake | null = null;
  /** The last mistake said aloud. */
  private spoken = "";
  private flashVerified = false;
  private flashTimer = 0;
  private resultTimer = 0;
  private loadedClip = "";
  private userPaused = false;
  private captionsOn = localStorage.getItem("handover.learnCaptions.v1") !== "off";
  private active = false;
  // This run (section 20.1).
  private runStart = 0;
  private runs: StepRun[] = [];
  private pos = 0;
  private posAt = 0;
  private downSince = 0;
  private interrupted = false;
  private summary: RunSummary | null = null;
  private lastListKey = "";
  private mistakeKey = "";
  private layout: LearnLayout = readLearnLayout();
  private draggingLayout = false;

  constructor(
    private el: HTMLElement,
    private actions: LearnActions,
  ) {
    paint(el, TEMPLATE);
    this.live = new LiveCanvas(this.q(".live-canvas"), frameUrl);
    this.live.onDraw = () => this.frameDrawn();
    this.video = this.q(".clip video");
    this.localVideo = this.q(".local-preview");
    this.video.addEventListener("loadedmetadata", () => this.syncTutorialTimeline());
    this.video.addEventListener("timeupdate", () => this.syncTutorialTimeline());
    this.video.addEventListener("durationchange", () => this.syncTutorialTimeline());
    this.video.addEventListener("play", () => this.syncTutorialPlayback());
    this.video.addEventListener("pause", () => this.syncTutorialPlayback());
    this.q(".next").addEventListener("click", () => this.next());
    this.q("button.back").addEventListener("click", () => this.back());
    this.q(".replay-clip").addEventListener("click", () => this.replay());
    this.q(".tutorial-play").addEventListener("click", () => this.toggleTutorial());
    this.q(".tutorial-cc").addEventListener("click", () => this.toggleCaptions());
    this.q<HTMLInputElement>(".tutorial-scrubber").addEventListener("input", (e) => {
      const at = Number((e.currentTarget as HTMLInputElement).value);
      if (Number.isFinite(at)) this.video.currentTime = at;
      this.syncTutorialTimeline();
    });
    this.q(".hold-step").addEventListener("click", () => this.toggleHold());
    this.q(".layout-swap").addEventListener("click", () => {
      this.layout = { ...this.layout, tutorialFirst: !this.layout.tutorialFirst };
      this.commitLayout();
    });
    this.q(".layout-reset").addEventListener("click", () => {
      this.layout = { ...DEFAULT_LEARN_LAYOUT };
      this.commitLayout();
    });
    this.q<HTMLDetailsElement>(".steps-disclosure").addEventListener("toggle", (e) => {
      if ((e.currentTarget as HTMLDetailsElement).open) this.q<HTMLElement>(".course-list .step-row.current")?.scrollIntoView({ block: "nearest" });
    });
    const divider = this.q<HTMLButtonElement>(".learn-divider");
    divider.addEventListener("pointerdown", (e) => this.beginLayoutDrag(e));
    divider.addEventListener("keydown", (e) => this.resizeLayoutWithKeyboard(e));
    this.q(".unmute").addEventListener("click", () => {
      this.video.muted = false;
      this.q<HTMLElement>(".unmute").hidden = true;
      void this.video.play().catch(() => {});
    });
    this.el.addEventListener("click", (e) => {
      const t = (e.target as HTMLElement).closest<HTMLElement>("[data-act]");
      if (!t) return;
      const act = t.dataset.act;
      if (act === "show") {
        this.mistake = null;
        this.actions.goto(Number(t.dataset.step));
      } else if (act === "dismiss") this.dismissMistake();
      else if (act === "learn-step") {
        this.q<HTMLDetailsElement>(".steps-disclosure").open = false;
        this.actions.goto(Number(t.dataset.step));
      }
      else if (act === "restart") {
        this.resetRun();
        this.actions.goto(0);
      } else if (act === "practice") this.actions.goto(Number(t.dataset.step));
      else if (act === "library") this.actions.library();
      else if (act === "pick") this.actions.pick();
      else if (act === "pair-phone") this.actions.pair();
      else if (act === "camera-change") this.actions.chooseCamera();
      else if (act === "camera-retry") this.actions.retryCamera();
    });
    this.applyLayout();
    this.syncCaptionsControl();
    this.syncTutorialPlayback();
    this.syncTutorialTimeline();
  }

  private applyLayout() {
    const grid = this.q<HTMLElement>(".learn-grid");
    const left = leftPercent(this.layout);
    grid.style.setProperty("--learn-left", `${left}%`);
    grid.classList.toggle("tutorial-first", this.layout.tutorialFirst);
    const divider = this.q<HTMLButtonElement>(".learn-divider");
    divider.setAttribute("aria-valuemin", String(this.layout.tutorialFirst ? 100 - MAX_CAMERA_PERCENT : MIN_CAMERA_PERCENT));
    divider.setAttribute("aria-valuemax", String(this.layout.tutorialFirst ? 100 - MIN_CAMERA_PERCENT : MAX_CAMERA_PERCENT));
    divider.setAttribute("aria-valuenow", String(Math.round(left)));
    divider.setAttribute("aria-valuetext", `Tutorial ${Math.round(100 - this.layout.cameraPercent)} percent, camera ${Math.round(this.layout.cameraPercent)} percent`);
    const swap = this.q<HTMLButtonElement>(".layout-swap");
    swap.setAttribute("aria-label", this.layout.tutorialFirst ? "Move tutorial to the right" : "Move tutorial to the left");
    grid.classList.add("layout-ready");
  }

  private commitLayout() {
    writeLearnLayout(this.layout);
    this.applyLayout();
  }

  private setLayoutFromPointer(clientX: number) {
    const grid = this.q<HTMLElement>(".learn-grid");
    const rect = grid.getBoundingClientRect();
    if (!rect.width) return;
    const left = ((clientX - rect.left) / rect.width) * 100;
    this.layout = layoutFromLeftPercent(left, this.layout.tutorialFirst);
    this.applyLayout();
  }

  private beginLayoutDrag(e: PointerEvent) {
    if (e.button !== 0) return;
    const divider = this.q<HTMLButtonElement>(".learn-divider");
    this.draggingLayout = true;
    divider.classList.add("dragging");
    divider.setPointerCapture(e.pointerId);
    this.setLayoutFromPointer(e.clientX);
    const move = (event: PointerEvent) => this.setLayoutFromPointer(event.clientX);
    const finish = () => {
      if (!this.draggingLayout) return;
      this.draggingLayout = false;
      divider.classList.remove("dragging");
      divider.removeEventListener("pointermove", move);
      divider.removeEventListener("pointerup", finish);
      divider.removeEventListener("pointercancel", finish);
      this.commitLayout();
    };
    divider.addEventListener("pointermove", move);
    divider.addEventListener("pointerup", finish);
    divider.addEventListener("pointercancel", finish);
    e.preventDefault();
  }

  private resizeLayoutWithKeyboard(e: KeyboardEvent) {
    const current = leftPercent(this.layout);
    let next: number | null = null;
    if (e.key === "ArrowLeft") next = current - (e.shiftKey ? 10 : 3);
    else if (e.key === "ArrowRight") next = current + (e.shiftKey ? 10 : 3);
    else if (e.key === "Home") next = leftPercent({ ...DEFAULT_LEARN_LAYOUT, tutorialFirst: this.layout.tutorialFirst });
    if (next === null) return;
    this.layout = layoutFromLeftPercent(next, this.layout.tutorialFirst);
    this.commitLayout();
    e.preventDefault();
  }

  resetRun() {
    const now = performance.now();
    this.runStart = now;
    this.runs = [];
    this.pos = 0;
    this.posAt = now;
    this.interrupted = false;
    this.summary = null;
    this.mistake = null;
    window.clearTimeout(this.flashTimer);
    this.flashVerified = false;
    this.render();
  }

  setActive(on: boolean) {
    if (on && this.active) return;
    this.active = on;
    if (!on) {
      this.stopMedia();
    }
    this.render();
  }

  /** Pauses tutorial audio and guidance without unloading the clip. Used by learner Pause/Hold controls. */
  pauseMedia() {
    this.video.pause();
    window.speechSynthesis?.cancel();
    stopChime();
  }

  /** Resumes only the visible, unfinished tutorial. */
  resumeMedia() {
    if (!this.userPaused && this.active && this.model.state?.status !== "done" && this.tutorialLoaded) this.play();
  }

  /** Deterministic lesson teardown. Safe to call repeatedly from route, window, and native close events. */
  stopMedia() {
    stopLessonPlayback(this.video, window.speechSynthesis);
    stopChime();
    this.userPaused = false;
    this.loadedClip = "";
    this.video.querySelectorAll("track").forEach((track) => track.remove());
    window.clearTimeout(this.flashTimer);
    window.clearTimeout(this.resultTimer);
    this.flashVerified = false;
    this.q<HTMLElement>(".result-moment").hidden = true;
    this.live.stop();
  }

  /** Starts the current expert step from the beginning without changing course progress. */
  replay() {
    if (!this.tutorialLoaded) return;
    this.video.currentTime = 0;
    this.userPaused = false;
    if (this.active) this.play();
    this.syncTutorialPlayback();
  }

  /** Pauses or resumes only the expert clip; the live camera and feedback remain active. */
  toggleTutorial() {
    if (!this.tutorialLoaded) return;
    if (this.video.paused) {
      this.userPaused = false;
      if (this.active) this.play();
    } else {
      this.userPaused = true;
      this.video.pause();
    }
    this.syncTutorialPlayback();
  }

  /** Shows or hides the tutorial's authored WebVTT captions and remembers the choice. */
  toggleCaptions() {
    this.captionsOn = !this.captionsOn;
    localStorage.setItem("handover.learnCaptions.v1", this.captionsOn ? "on" : "off");
    for (const track of Array.from(this.video.textTracks)) track.mode = this.captionsOn ? "showing" : "hidden";
    this.syncCaptionsControl();
  }

  private syncCaptionsControl() {
    const button = this.q<HTMLButtonElement>(".tutorial-cc");
    button.classList.toggle("on", this.captionsOn);
    button.setAttribute("aria-pressed", String(this.captionsOn));
    button.title = `${this.captionsOn ? "Hide" : "Show"} captions (C)`;
  }

  /** J/L: inspect the expert movement without changing the lesson step. */
  seekTutorial(delta: number) {
    const duration = this.video.duration;
    if (!Number.isFinite(duration) || duration <= 0) return;
    this.video.currentTime = Math.max(0, Math.min(duration, this.video.currentTime + delta));
    this.syncTutorialTimeline();
  }

  toggleHold() {
    const s = this.model.state;
    if (!s?.lesson_id || s.status === "done" || this.model.down) return;
    this.actions.hold(!s.held);
  }

  private syncTutorialPlayback() {
    const paused = this.video.paused;
    const button = this.q<HTMLButtonElement>(".tutorial-play");
    paint(button, paused ? html`${icons.play}<span>Play</span>` : html`${icons.pause}<span>Pause</span>`);
    button.setAttribute("aria-label", paused ? "Play tutorial" : "Pause tutorial");
    button.title = `${paused ? "Play" : "Pause"} tutorial (K)`;
    button.disabled = !this.tutorialLoaded;
  }

  private get tutorialLoaded() {
    return !!this.video.getAttribute("src");
  }

  private syncTutorialTimeline() {
    const duration = Number.isFinite(this.video.duration) ? this.video.duration : 0;
    const current = Number.isFinite(this.video.currentTime) ? this.video.currentTime : 0;
    const range = this.q<HTMLInputElement>(".tutorial-scrubber");
    range.max = String(Math.max(duration, 0.01));
    range.value = String(Math.min(current, duration || current));
    range.disabled = !duration;
    range.setAttribute("aria-valuetext", `${this.tutorialTime(current)} of ${this.tutorialTime(duration)}`);
    this.q(".tutorial-time").textContent = `${this.tutorialTime(current)} / ${this.tutorialTime(duration)}`;
  }

  private tutorialTime(seconds: number) {
    const safe = Math.max(0, Math.floor(Number.isFinite(seconds) ? seconds : 0));
    return `${Math.floor(safe / 60)}:${String(safe % 60).padStart(2, "0")}`;
  }

  private run(i: number): StepRun {
    while (this.runs.length <= i) this.runs.push({ ms: 0, how: null, mistakes: 0, offline: false });
    return this.runs[i];
  }

  update(m: LearnModel) {
    const prev = this.model.state;
    this.model = m;
    const s = m.state;
    const now = performance.now();
    // A disconnect over 10 s marks the run interrupted (section 20.1).
    if (m.down && !this.downSince) this.downSince = now;
    if (!m.down && this.downSince) {
      if (now - this.downSince > 10000) this.interrupted = true;
      this.downSince = 0;
    }
    if (s) {
      if (s.mistake !== undefined) this.mistake = s.mistake;
      // Camera lost keeps the last frame, dimmed, until the hub says a camera is back.
      if (!s.camera_connected && prev?.camera_connected) this.stale = true;
      if (s.camera_connected) this.stale = false;
      const pos = s.status === "done" ? s.total : s.step;
      if (this.runStart && pos !== this.pos) {
        if (this.pos < s.total) this.run(this.pos).ms += now - this.posAt;
        // Left forward by goto (no advance message) counts as skipped.
        for (let k = this.pos; k < pos && k < s.total; k++) if (!this.run(k).how) this.run(k).how = "skipped";
        this.pos = pos;
        this.posAt = now;
      }
      if (s.check_offline && s.step < s.total) this.run(s.step).offline = true;
      if (s.status === "done" && prev?.status !== "done" && this.runStart) this.finish();
      if (s.status !== "done") this.summary = null;
    }
    this.render();
  }

  /** True while this computer's own camera is the picture (its echo from the hub is ignored). */
  private get localOn(): boolean {
    return this.model.camera.choice === "computer" && this.model.camera.local === "on";
  }

  /** A new live frame from the hub: only the newest is fetched, decoded and drawn. */
  onFrame(n: number) {
    if (!this.active || this.localOn) return;
    this.live.offer(n);
  }

  private frameDrawn() {
    const first = !this.hasFrame;
    this.hasFrame = true;
    // Only a change of state needs a render; plain new frames are already on the canvas. A frame
    // still on its way when the camera went does not clear the camera lost state.
    if (first) this.render();
  }


  onAdvance(a: Advance) {
    const steps = this.model.lesson?.steps ?? [];
    if (a.to > a.from && a.from < steps.length) {
      this.run(a.from).how = a.reason === "camera" ? "camera" : "hand";
      // An ahead advance (k to k+2) jumps over k+1.
      for (let k = a.from + 1; k < a.to && k < steps.length; k++) if (!this.run(k).how) this.run(k).how = "skipped";
      if (a.to < steps.length) this.resultMoment(a.from, a.reason);
    }
    if (a.reason !== "camera") return;
    if (this.model.chime && this.active) playChime();
    this.flashVerified = true;
    window.clearTimeout(this.flashTimer);
    this.flashTimer = window.setTimeout(() => {
      this.flashVerified = false;
      this.render();
    }, 1800);
    this.render();
  }

  /** Section 7.10: a short note after each finished step. */
  private resultMoment(i: number, reason: Advance["reason"]) {
    const steps = this.model.lesson?.steps ?? [];
    const r = this.run(i);
    const ms = r.ms + (this.pos === i ? performance.now() - this.posAt : 0);
    const t = ms / 1000;
    const exp = steps[i] ? expertOf(steps[i]) : 0;
    let text: string;
    if (r.mistakes) text = `Done. ${r.mistakes} ${r.mistakes === 1 ? "mistake" : "mistakes"} fixed.`;
    else if (t >= 1 && exp) {
      if (t < exp * 0.9) text = `Nice. ${mmss(t, true)}, faster than the expert.`;
      else if (t <= exp * 1.1) text = `Done. ${mmss(t, true)}, about the expert's time.`;
      else text = `Done in ${mmss(t, true)}.`;
    } else text = reason === "camera" ? "Verified." : "Done.";
    const el = this.q<HTMLElement>(".result-moment");
    el.textContent = text;
    el.hidden = false;
    el.classList.remove("show");
    void el.offsetWidth;
    el.classList.add("show");
    window.clearTimeout(this.resultTimer);
    this.resultTimer = window.setTimeout(() => (el.hidden = true), 1500);
  }

  onMistake(m: Mistake) {
    this.mistake = m;
    if (this.active && m.step < (this.model.lesson?.steps.length ?? 0)) this.run(m.step).mistakes += 1;
    if (this.active) this.speak(m);
    this.render();
  }

  /** Says the mistake once, when the system has a voice. A repeat of the same note stays quiet. */
  private speak(m: Mistake) {
    const key = `${this.model.state?.rev ?? 0}:${m.step}:${m.kind}:${m.message}`;
    const tts = typeof window !== "undefined" ? window.speechSynthesis : undefined;
    if (!tts || !m.message || key === this.spoken) return;
    this.spoken = key;
    tts.cancel();
    tts.speak(new SpeechSynthesisUtterance(m.message));
  }

  dismissMistake() {
    if (!this.mistake) return;
    this.mistake = null;
    this.actions.dismissMistake();
    this.render();
  }

  next() {
    const s = this.model.state;
    if (s?.lesson_id && s.status !== "done" && !this.model.down) {
      // Stop the old narration at the gesture boundary; do not wait for the hub round trip.
      this.pauseMedia();
      this.actions.next(s.step);
    }
  }

  back() {
    const s = this.model.state;
    if (s?.lesson_id && !this.model.down) {
      this.pauseMedia();
      this.actions.back(s.step);
    }
  }

  /** Section 20: the run's numbers, frozen when the lesson finishes. */
  private finish() {
    const lesson = this.model.lesson;
    const steps = lesson?.steps ?? [];
    const runs = steps.map((_, i) => this.run(i));
    const expert = steps.reduce((a, s) => a + expertOf(s), 0);
    const timed = runs.filter((r) => r.ms > 0).length;
    const camSteps = steps.map((s, i) => ({ s, r: runs[i] })).filter(({ s, r }) => s.check_type === "camera" && !r.offline);
    let score: number | null = null;
    if (!this.interrupted && timed >= steps.length / 2 && steps.length) {
      const checked = camSteps.length ? camSteps.filter(({ r }) => r.how === "camera").length / camSteps.length : null;
      const paces = steps.map((s, i) => (runs[i].how === "skipped" ? 0 : runs[i].ms > 0 ? Math.min(1, expertOf(s) / (runs[i].ms / 1000)) : null)).filter((p): p is number => p !== null);
      const pace = paces.length ? paces.reduce((a, b) => a + b, 0) / paces.length : 0;
      const mistakes = runs.reduce((a, r) => a + r.mistakes, 0);
      const clean = 1 - Math.min(1, mistakes / steps.length);
      score = checked === null ? Math.round(100 * (0.6 * pace + 0.4 * clean)) : Math.round(100 * (0.5 * checked + 0.3 * pace + 0.2 * clean));
    }
    this.summary = {
      lessonId: lesson?.id ?? "",
      title: lesson?.title ?? "",
      ms: this.interrupted || !this.runStart ? null : performance.now() - this.runStart,
      expert,
      score,
      camera: runs.filter((r) => r.how === "camera").length,
      hand: runs.filter((r) => r.how === "hand").length,
      skipped: runs.filter((r) => r.how === "skipped").length,
      mistakes: runs.reduce((a, r) => a + r.mistakes, 0),
      steps: runs.map((r) => ({ ...r })),
    };
    this.actions.finished(this.summary);
  }

  /** How each step went this run, for the course list and saved progress. */
  howList(): (string | null)[] {
    return (this.model.lesson?.steps ?? []).map((_, i) => this.runs[i]?.how ?? null);
  }

  private render() {
    const { state: s, lesson, down } = this.model;
    const steps = lesson?.steps ?? [];
    const total = steps.length || s?.total || 0;
    const isDone = s?.status === "done";
    const idx = Math.max(0, Math.min(s?.step ?? 0, steps.length - 1));
    const step = steps.length ? steps[idx] : null;
    const activeMistake = this.mistake && !isDone && this.mistake.step === s?.step ? this.mistake : null;

    // Live camera: this computer's own preview, or the hub's frames. Never a frozen frame
    // while the hub is unreachable.
    const local = this.localOn;
    const showHub = !local && !down && this.hasFrame && (!!s?.camera_connected || this.stale);
    const showLive = local || showHub;
    const cameraLost = showHub && (this.stale || !s?.camera_connected);
    const manualStep = step?.check_type === "manual";
    this.q<HTMLElement>(".learn-grid").classList.toggle("manual-focus", !!manualStep);
    const livePane = this.q<HTMLElement>(".live");
    livePane.hidden = !!manualStep;
    livePane.classList.toggle("waiting", !showLive);
    this.q<HTMLElement>(".live-frame").classList.toggle("hidden", !showLive);
    this.localVideo.hidden = !local;
    this.live.canvas.hidden = local;
    this.live.canvas.classList.toggle("lost", cameraLost);
    this.q<HTMLElement>(".live-note").hidden = !cameraLost;
    this.q<HTMLElement>(".rec").hidden = !(showHub && !cameraLost && s?.camera?.source === "file");
    const ph = this.q<HTMLElement>(".live-ph");
    ph.hidden = showLive;
    if (!showLive) paint(ph, this.placeholder());
    const chip = this.q<HTMLElement>(".live-chip");
    const link = this.model.camera.link;
    const camName = local
      ? link === "standby"
        ? "This computer, standby: another camera is active"
        : link === "sending"
          ? "This computer"
          : link === "replaced"
            ? "This computer, stopped: another window took over"
            : "This computer, connecting"
      : !down && s?.camera_connected && s?.camera?.source !== "file"
        ? s?.camera?.name
        : "";
    chip.hidden = !camName;
    chip.textContent = camName ?? "";

    // Mistake card, directly above the list (section 7.2).
    const card = this.q<HTMLElement>(".mistake-card");
    livePane.classList.toggle("verdict-caution", !!activeMistake);
    const mistakeKey = activeMistake ? JSON.stringify(activeMistake) : "";
    if (mistakeKey !== this.mistakeKey) {
      this.mistakeKey = mistakeKey;
      card.getAnimations().forEach((animation) => animation.cancel());
      if (window.matchMedia("(prefers-reduced-motion: reduce)").matches) card.hidden = !activeMistake;
      else if (activeMistake) {
        card.hidden = false;
        card.animate([{ opacity: 0, transform: "translateY(8px)" }, { opacity: 1, transform: "translateY(0)" }], { duration: 280, easing: "ease-out" });
      } else if (!card.hidden) {
        const exit = card.animate([{ opacity: 1 }, { opacity: 0 }], { duration: 200, easing: "ease-out" });
        void exit.finished.then(() => { if (!this.mistakeKey) card.hidden = true; }).catch(() => {});
      }
    } else if (!activeMistake && !card.getAnimations().length) card.hidden = true;
    if (activeMistake)
      paint(
        card,
        html`<p class="mistake-text">${activeMistake.message}</p>
          <div class="mistake-actions">
            ${activeMistake.kind === "behind"
              ? html`<button type="button" class="ghost small" data-act="show" data-step="${activeMistake.looks_like}">Show Step ${activeMistake.looks_like + 1}</button>
                  <button type="button" class="ghost small" data-act="dismiss">I'm Fine</button>`
              : html`<button type="button" class="ghost small" data-act="dismiss">OK</button>`}
          </div>`,
      );

    // Clip and captions: reload only when the clip URL changes.
    const clipKey = lesson && step ? lessonUrl(lesson.id, step.clip, s?.rev) : "";
    const v = this.video;
    // Only while Learn is open, so the clip is not fetched for a lesson nobody is viewing.
    if (clipKey && clipKey !== this.loadedClip && lesson && step && this.active) {
      this.loadedClip = clipKey;
      this.userPaused = false;
      stopChime();
      v.querySelectorAll("track").forEach((t) => {
        t.track.mode = "disabled";
        t.remove();
      });
      const track = document.createElement("track");
      track.kind = "captions";
      track.srclang = "en";
      track.label = "English";
      track.default = true;
      track.src = lessonUrl(lesson.id, step.captions, s?.rev);
      v.appendChild(track);
      track.track.mode = this.captionsOn ? "showing" : "hidden";
      replaceLessonPlayback(v, clipKey, window.speechSynthesis);
    }
    v.classList.toggle("hidden", !step);
    if (this.active && step && !isDone && !this.userPaused && v.paused && this.tutorialLoaded) this.play();
    if (isDone || !this.active) v.pause();
    this.q<HTMLElement>(".clip-ph").hidden = !!step;

    this.q(".step-count").textContent = step ? `Step ${idx + 1} of ${total}` : " ";
    this.q(".step-title").textContent = step ? step.title : " ";
    const hold = this.q<HTMLButtonElement>(".hold-step");
    const held = !!s?.held && !isDone;
    hold.disabled = !s?.lesson_id || isDone || down;
    hold.classList.toggle("on", held);
    hold.setAttribute("aria-pressed", String(held));
    paint(hold, html`${icons.pause}<span>${held ? "Release hold" : "Hold step"}</span>`);
    hold.title = held ? "Allow camera verification to advance (H)" : "Keep camera feedback on this step without advancing (H)";

    // Course list: rebuilt only when something in it changed.
    const how = this.howList();
    const listKey = JSON.stringify([lesson?.id, s?.rev, idx, isDone, how, steps.length]);
    if (listKey !== this.lastListKey && lesson) {
      this.lastListKey = listKey;
      const list = this.q<HTMLElement>(".course-list");
      paint(
        list,
        html`${steps.map((st, i) => stepRow(lesson.id, st, i, s?.rev, how[i], !isDone && i === idx, this.runs[i]?.ms ? this.runs[i].ms / 1000 : null, "learn-step"))}`,
      );
      list.querySelector<HTMLElement>(".step-row.current")?.scrollIntoView({ block: "nearest" });
    }
    this.q<HTMLElement>(".course-list .step-row.current")?.classList.toggle("caution", !!activeMistake);

    // The verdict belongs to the learner's picture; evidence stays beside the current instruction.
    const feedback = learnFeedback(s, step, this.flashVerified);
    const b = this.q<HTMLElement>(".badge");
    b.className = `badge camera-verdict ${activeMistake ? "caution" : feedback.tone} phase-${feedback.phase}`;
    b.hidden = !step;
    this.q(".badge-label").textContent = activeMistake ? "Mistake caught" : feedback.label;
    livePane.classList.toggle("verdict-good", feedback.phase === "verified");
    this.q(".step-instruction").textContent = manualStep
      ? "Complete this step, then use Next."
      : "Do this step. HandOver moves on when it sees it done.";
    const check = s?.last_check;
    this.q(".step-evidence").textContent = check && !manualStep
      ? `Last check ${(check.latency_ms / 1000).toFixed(1)} s${s?.check_reason || check.reason ? ` · ${s?.check_reason || check.reason}` : ""}`
      : manualStep ? "" : feedback.action;

    const can = !!s?.lesson_id && !down;
    const nextBtn = this.q<HTMLButtonElement>(".next");
    nextBtn.disabled = !can || !step || isDone;
    nextBtn.title = down ? "Waiting for the hub" : "Next (Right Arrow or Space)";
    this.q<HTMLButtonElement>("button.back").disabled = !can || (!isDone && idx === 0);

    // Done.
    const done = this.q<HTMLElement>(".done-layer");
    done.hidden = !(isDone && this.summary);
    if (isDone && this.summary) paint(done, this.doneMarkup(this.summary, lesson));

    // No lesson, or one on its way.
    const blank = this.q<HTMLElement>(".learn-empty");
    const phase = this.model.phase;
    blank.hidden = phase === "running" && !!lesson;
    if (!blank.hidden)
      paint(
        blank,
        phase === "none"
          ? empty(icons.filmBig, "No lesson running", "Pick a lesson to start learning.", html`<button class="primary" data-act="pick">Pick a Lesson</button>`)
          : html`<div class="empty-state"><span class="spinner"></span><p class="empty-message">Starting the lesson</p></div>`,
      );
  }

  /** What the live pane says before there is a picture: depends on the chosen camera. */
  private placeholder(): Raw {
    const { choice, local } = this.model.camera;
    const box = (icon: Raw, title: string, hint: string, actions: Raw | string = "") =>
      html`${icon}<p class="placeholder-title">${title}</p><p class="placeholder-hint">${hint}</p>${actions ? html`<div class="placeholder-actions">${actions}</div>` : ""}`;
    const change = html`<button class="ghost small" data-act="camera-change">Change Camera</button>`;
    if (this.model.down) return box(icons.camera, "Reconnecting to the hub", "The picture comes back when the hub does.");
    if (choice === "computer") {
      if (local === "denied")
        return box(icons.camera, "Camera access is off", "Allow HandOver to use the camera in your system settings, then try again.", html`<button class="ghost small" data-act="camera-retry">Try Again</button>${change}`);
      if (local === "missing")
        return box(icons.camera, "No camera found", "Connect a webcam, or use a phone as the camera.", html`<button class="ghost small" data-act="camera-retry">Try Again</button>${change}`);
      if (local === "error")
        return box(icons.camera, "The camera did not start", "Close other apps that use the camera, then try again.", html`<button class="ghost small" data-act="camera-retry">Try Again</button>${change}`);
      return html`<span class="spinner"></span><p class="placeholder-title">Starting the camera</p>`;
    }
    if (choice === "phone")
      return box(icons.camera, "Waiting for the phone", "Open HandOver on the phone and tap Be the Camera.", html`<button class="ghost small" data-act="pair-phone">Show Pairing Code</button>${change}`);
    if (choice === "glasses")
      return box(icons.camera, "Waiting for the glasses", "On the phone, open HandOver, tap Be the Camera, then choose Glasses.", html`<button class="ghost small" data-act="pair-phone">Show Pairing Code</button>${change}`);
    return box(icons.camera, "No camera yet", "Choose how HandOver sees your hands.", html`<button class="ghost small" data-act="camera-change">Choose Camera</button>`);
  }

  private play() {
    const v = this.video;
    v.play().catch(() => {
      if (v.muted) return;
      v.muted = true;
      this.q<HTMLElement>(".unmute").hidden = false;
      v.play().catch(() => {});
    });
  }

  private doneMarkup(r: RunSummary, lesson: Lesson | null): Raw {
    const steps = lesson?.steps ?? [];
    const camTotal = steps.filter((s) => s.check_type === "camera").length;
    const label = r.score === null ? "Not enough data" : r.score >= 85 ? "Excellent" : r.score >= 60 ? "Good" : "Keep practicing";
    const tone = r.score === null ? "var(--panel-2)" : r.score >= 85 ? "var(--green)" : r.score >= 60 ? "var(--accent)" : "var(--amber)";
    // Section 20.3.
    const q = steps
      .map((s, i) => ({ i, s, r: r.steps[i], ratio: r.steps[i]?.ms ? r.steps[i].ms / 1000 / Math.max(0.1, expertOf(s)) : 0 }))
      .filter((x) => x.r && x.r.ms > 0 && x.r.how !== "skipped");
    let best: (typeof q)[number] | undefined;
    let weak: (typeof q)[number] | undefined;
    if (q.length >= 2) {
      weak = [...q].sort((a, b) => b.r.mistakes - a.r.mistakes || b.ratio - a.ratio)[0];
      const clean = q.filter((x) => !x.r.mistakes);
      best = [...clean.filter((x) => x.r.how === "camera"), ...clean].sort((a, b) => a.ratio - b.ratio)[0];
      const camClean = clean.filter((x) => x.r.how === "camera").sort((a, b) => a.ratio - b.ratio);
      if (camClean.length) best = camClean[0];
    }
    // Section 20.4.
    let tip = "Try it again without looking at the clip.";
    const skippedAt = r.steps.findIndex((x) => x.how === "skipped");
    if (weak?.s.common_mistake) tip = `On step ${weak.i + 1}, watch for this: ${weak.s.common_mistake}`;
    else if (weak && weak.r.mistakes) tip = `Replay step ${weak.i + 1}'s clip before you try it again.`;
    else if (weak && weak.ratio > 2) tip = `Step ${weak.i + 1} took the longest. Watch the expert's hands closely there.`;
    else if (skippedAt >= 0) tip = `You skipped step ${skippedAt + 1}. Try it once so the camera can check it.`;
    else if (r.steps.some((x) => x.offline)) tip = "Checks were off for part of this run, so try again for a full score.";
    const maxT = Math.max(1, ...steps.map((s, i) => Math.max(expertOf(s), (r.steps[i]?.ms ?? 0) / 1000)));
    const reason = (x: NonNullable<typeof best>) =>
      x.r.how === "camera" ? `Checked by camera in ${mmss(x.r.ms / 1000, true)}.` : `${mmss(x.r.ms / 1000, true)} against ${mmss(expertOf(x.s), true)}.`;
    const weakReason = (x: NonNullable<typeof weak>) =>
      `${x.r.mistakes ? `${x.r.mistakes} ${x.r.mistakes === 1 ? "mistake" : "mistakes"}, ` : ""}${mmss(x.r.ms / 1000)} against ${mmss(expertOf(x.s))}.`;
    const howWord = { camera: "Checked by camera", hand: "Marked done", skipped: "Skipped" } as Record<string, string>;
    return html`<div class="done-card">
      <div class="done-left scroll">
        <div class="score">${ring(r.score === null ? 0 : r.score / 100, 120, tone)}
          <span class="score-center">${r.score === null ? html`<span class="score-none">Not enough data</span>` : html`<span class="score-num">${r.score}</span><span class="score-label">${label}</span>`}</span></div>
        <h1 class="done-title">Lesson complete</h1>
        <p class="done-sub">${r.title}</p>
        <dl class="done-stats">
          <div><dt>Your time</dt><dd>${r.ms === null ? html`<span class="muted small">Not enough data</span>` : mmss(r.ms / 1000)}</dd></div>
          <div><dt>Expert</dt><dd>${mmss(r.expert)}</dd></div>
          <div><dt>Checked by camera</dt><dd>${r.camera} of ${camTotal}</dd></div>
          <div><dt>Marked done</dt><dd>${r.hand}</dd></div>
          <div><dt>Mistakes caught</dt><dd>${r.mistakes}</dd></div>
          ${r.skipped ? html`<div><dt>Skipped</dt><dd>${r.skipped}</dd></div>` : ""}
        </dl>
        ${best && weak && best.i !== weak.i
          ? html`<div class="pair-cards"><div class="card mini"><p class="eyebrow">Best step</p><p class="mini-title">Step ${best.i + 1}. ${best.s.title}</p><p class="muted small">${reason(best)}</p></div>
              <div class="card mini"><p class="eyebrow">Practice this</p><p class="mini-title">Step ${weak.i + 1}. ${weak.s.title}</p><p class="muted small">${weakReason(weak)}</p></div></div>`
          : html`<div class="card mini"><p class="muted small">Not enough data to compare steps.</p></div>`}
        <div class="card tip">${icons.bulb}<span>${tip}</span></div>
        <div class="done-actions">
          ${weak ? html`<button class="primary" data-act="practice" data-step="${weak.i}">Practice Step ${weak.i + 1}</button>` : ""}
          <button class="secondary" data-act="restart">Start Over</button>
          <button class="quiet" data-act="library">Back to Lessons</button>
        </div>
      </div>
      <div class="done-right">
        <h2>Steps</h2>
        <div class="breakdown scroll">${steps.map((s, i) => {
          const x = r.steps[i];
          const you = x?.ms ? x.ms / 1000 : 0;
          const faster = you && you < expertOf(s);
          return html`<div class="bd-row">
            <span class="bd-num">${i + 1}</span>
            <div class="bd-main"><p class="bd-title">${s.title}</p>
              <div class="bd-bars"><span class="tb exp" style="width:${(expertOf(s) / maxT) * 100}%"></span>
                ${you ? html`<span class="tb you ${faster ? "fast" : ""}" style="width:${(you / maxT) * 100}%"></span>` : ""}</div>
              <p class="bd-meta">${x?.how ? howWord[x.how] : "Not finished in order"}${x?.mistakes ? html` <span class="caution">${x.mistakes} ${x.mistakes === 1 ? "mistake" : "mistakes"}</span>` : ""}</p></div>
            <span class="bd-times">${you ? mmss(you, true) : "No time"}<br /><span class="muted">${mmss(expertOf(s), true)}</span></span>
          </div>`;
        })}</div>
      </div>
    </div>`;
  }
}
