// A short, soft two note chime made with Web Audio, the same as the web app. No audio files.

let ctx: AudioContext | null = null;

/** Call from a user gesture so later chimes are allowed to play. */
export function unlockAudio() {
  if (!ctx) ctx = new AudioContext();
  if (ctx.state === "suspended") void ctx.resume();
}

function note(ac: AudioContext, freq: number, at: number, length: number) {
  const osc = ac.createOscillator();
  const gain = ac.createGain();
  osc.type = "sine";
  osc.frequency.value = freq;
  gain.gain.setValueAtTime(0, at);
  gain.gain.linearRampToValueAtTime(0.16, at + 0.02);
  gain.gain.exponentialRampToValueAtTime(0.0001, at + length);
  osc.connect(gain).connect(ac.destination);
  osc.start(at);
  osc.stop(at + length + 0.05);
}

export function playChime() {
  if (!ctx) return;
  const t = ctx.currentTime + 0.01;
  note(ctx, 880, t, 0.35);
  note(ctx, 1318.5, t + 0.12, 0.55);
}
