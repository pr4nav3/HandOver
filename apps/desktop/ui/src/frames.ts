// The live camera, smooth at up to 15 frames per second.
// - Received frames: each `frame` event names the newest JPEG. One fetch and decode runs at a
//   time; events that arrive meanwhile collapse into the newest, so the picture never lags.
//   Decoding is createImageBitmap (off the main thread in WebKit, Chromium and WebView2), and
//   drawing waits for the next animation frame. No object URLs are made, so none can leak.
// - This computer as the camera: getUserMedia at about 15 fps, scaled to a long side of 640 and
//   encoded as JPEG at quality 0.5. A frame is captured only when the last one has been handed
//   to the core, which itself keeps only the newest unsent frame.

/** Runs `work` on the newest value only. A value offered while work is running replaces any
 *  value still waiting; the replaced one is passed to `drop` and never worked on. */
export class LatestOnly<T> {
  private waiting: { v: T } | null = null;
  private running = false;

  constructor(
    private work: (v: T) => Promise<void>,
    private drop: (v: T) => void = () => {},
  ) {}

  get busy(): boolean {
    return this.running;
  }

  offer(v: T) {
    if (this.running) {
      if (this.waiting) this.drop(this.waiting.v);
      this.waiting = { v };
      return;
    }
    void this.run(v);
  }

  /** Forgets a waiting value (for example when the view closes). */
  clear() {
    if (this.waiting) this.drop(this.waiting.v);
    this.waiting = null;
  }

  private async run(v: T) {
    this.running = true;
    try {
      await this.work(v);
    } catch {
      // A failed frame is skipped; the next one tries again.
    }
    this.running = false;
    const next = this.waiting;
    this.waiting = null;
    if (next) void this.run(next.v);
  }
}

/** Draws decoded frames on a canvas, newest only, once per animation frame. */
export class LiveCanvas {
  private pending: ImageBitmap | null = null;
  private raf = 0;
  private pump: LatestOnly<number>;
  /** Called after a frame is drawn, with its size. */
  onDraw: (w: number, h: number) => void = () => {};
  onFail: () => void = () => {};

  constructor(
    readonly canvas: HTMLCanvasElement,
    url: (n: number) => string,
  ) {
    this.pump = new LatestOnly(async (n) => {
      const r = await fetch(url(n), { cache: "no-store" });
      if (!r.ok) {
        this.onFail();
        return;
      }
      const bitmap = await createImageBitmap(await r.blob());
      // A decoded frame that was never drawn is replaced by the newer one.
      this.pending?.close();
      this.pending = bitmap;
      if (!this.raf) this.raf = requestAnimationFrame(() => this.draw());
    });
  }

  /** A new frame number from the hub. */
  offer(n: number) {
    this.pump.offer(n);
  }

  private draw() {
    this.raf = 0;
    const b = this.pending;
    this.pending = null;
    if (!b) return;
    const c = this.canvas;
    if (c.width !== b.width || c.height !== b.height) {
      c.width = b.width;
      c.height = b.height;
    }
    c.getContext("2d")?.drawImage(b, 0, 0);
    const [w, h] = [b.width, b.height];
    b.close();
    this.onDraw(w, h);
  }

  stop() {
    this.pump.clear();
    if (this.raf) cancelAnimationFrame(this.raf);
    this.raf = 0;
    this.pending?.close();
    this.pending = null;
  }
}

export type LocalState = "off" | "starting" | "on" | "denied" | "missing" | "error";

/** Frames per second, long side and JPEG quality for this computer's webcam. */
export const LOCAL_FPS = 15;
export const LOCAL_LONG_SIDE = 640;
export const LOCAL_QUALITY = 0.5;

/** Output size for a source frame: the long side scaled down to `long`, never up. */
export function fitLongSide(w: number, h: number, long = LOCAL_LONG_SIDE): { w: number; h: number } {
  const k = Math.min(1, long / Math.max(w, h, 1));
  return { w: Math.max(1, Math.round(w * k)), h: Math.max(1, Math.round(h * k)) };
}

/** This computer's webcam: shows the preview straight from the <video> and sends JPEGs. */
export class LocalCamera {
  state: LocalState = "off";
  private stream: MediaStream | null = null;
  private timer = 0;
  private sending = false;
  private canvas = document.createElement("canvas");
  onChange: () => void = () => {};

  constructor(
    readonly video: HTMLVideoElement,
    private send: (jpeg: Uint8Array) => Promise<unknown>,
  ) {}

  async start(): Promise<boolean> {
    if (this.stream || this.state === "starting") return true;
    this.set("starting");
    if (!navigator.mediaDevices?.getUserMedia) {
      this.set("missing");
      return false;
    }
    try {
      this.stream = await navigator.mediaDevices.getUserMedia({
        audio: false,
        video: { width: { ideal: 1280 }, height: { ideal: 720 }, frameRate: { ideal: LOCAL_FPS, max: 30 } },
      });
    } catch (e) {
      const name = (e as DOMException)?.name ?? "";
      this.set(name === "NotAllowedError" || name === "SecurityError" ? "denied" : name === "NotFoundError" || name === "OverconstrainedError" ? "missing" : "error");
      return false;
    }
    if ((this.state as LocalState) !== "starting") {
      // Stopped while the permission prompt was up.
      this.stream.getTracks().forEach((t) => t.stop());
      this.stream = null;
      return false;
    }
    this.video.muted = true;
    this.video.srcObject = this.stream;
    void this.video.play().catch(() => {});
    this.timer = window.setInterval(() => this.tick(), 1000 / LOCAL_FPS);
    this.set("on");
    return true;
  }

  stop() {
    window.clearInterval(this.timer);
    this.timer = 0;
    this.stream?.getTracks().forEach((t) => t.stop());
    this.stream = null;
    this.video.srcObject = null;
    if (this.state !== "off") this.set("off");
  }

  private set(s: LocalState) {
    this.state = s;
    this.onChange();
  }

  /** Captures one frame, unless the last one is still on its way. */
  private tick() {
    const v = this.video;
    if (this.sending || !v.videoWidth || v.readyState < 2) return;
    this.sending = true;
    const { w, h } = fitLongSide(v.videoWidth, v.videoHeight);
    const c = this.canvas;
    if (c.width !== w || c.height !== h) {
      c.width = w;
      c.height = h;
    }
    c.getContext("2d")?.drawImage(v, 0, 0, w, h);
    c.toBlob(
      async (blob) => {
        try {
          if (blob && this.stream) await this.send(new Uint8Array(await blob.arrayBuffer()));
        } catch {
          // The next tick tries again.
        }
        this.sending = false;
      },
      "image/jpeg",
      LOCAL_QUALITY,
    );
  }
}
