// Pair a Phone and the camera choice. The QR carries
// `handover://connect?hub=<url-encoded http://LAN-IP:port>`, made by the core on this computer
// (core/src/phone.rs). The choice of camera (this computer, a phone, Meta glasses) is kept on
// this device and shown as a "Camera" row with Change.

import { call, type Pairing } from "../api";
import { closeSheet, drawSheet, openSheet, sheetOpen } from "../components";
import { icons } from "../icons";
import { pairedCamera, type PairingCamera } from "../pairing";
import { app, errorText, prefs, rerender, toast, type CameraChoice } from "../state";
import { html, raw, type Raw } from "../util";

export const CAMERA_WORD: Record<CameraChoice, string> = {
  computer: "This computer",
  phone: "A phone",
  glasses: "Meta glasses",
};

let pairing: Pairing | null = null;
let pairingHub = "";
let pairingCamera: "phone" | "glasses" = "phone";
let pairingError = "";
let loadingPairing = false;
/** Which of this file's sheets is open, so hub changes can redraw it. */
let open: "" | "pair" | "camera" = "";
let expectedCamera: PairingCamera = "phone";
let pairingConnected = false;
let pairedTimer = 0;
let pairedAction: (() => void) | null = null;

function watchPairing(camera: PairingCamera, action: () => void) {
  window.clearTimeout(pairedTimer);
  pairedTimer = 0;
  expectedCamera = camera;
  pairingConnected = pairedCamera(app.state, camera);
  pairedAction = action;
}

function stopWatching() {
  window.clearTimeout(pairedTimer);
  pairedTimer = 0;
  pairingConnected = false;
  pairedAction = null;
}

async function loadPairing(force = false, camera: "phone" | "glasses" = "phone") {
  if (loadingPairing || (!force && pairing && pairingHub === app.link.hub && pairingCamera === camera)) return;
  loadingPairing = true;
  pairingError = "";
  try {
    pairing = await call<Pairing>("pairing", { camera });
    pairingHub = app.link.hub;
    pairingCamera = camera;
  } catch (e) {
    pairing = null;
    pairingError = errorText(e);
  }
  loadingPairing = false;
  if (open) drawSheet();
}

/** The QR code with the address under it, or what to do when there is no address. */
function qrBlock(): Raw {
  if (pairingConnected)
    return html`<div class="pair-success" role="status" aria-live="polite">
      <span class="pair-success-ring">${icons.check}</span>
      <p class="pair-success-title">Connected</p>
      <p class="pair-success-line">${app.state?.camera?.name ?? (expectedCamera === "glasses" ? "Meta glasses" : "iPhone camera")}</p>
    </div>`;
  if (pairingError || (!pairing && !loadingPairing && app.link.link === "idle"))
    return html`<div class="qr-empty"><p class="empty-title">Not connected to a hub</p>
      <p class="empty-message">${pairingError || "Connect to a hub first, then pair a phone with it."}</p></div>`;
  if (!pairing || pairingHub !== app.link.hub)
    return html`<div class="qr-block"><div class="qr qr-wait"><span class="spinner"></span></div></div>`;
  if (!pairing.svg || !pairing.hub)
    return html`<div class="qr-empty"><p class="empty-title">This computer is not on a network</p>
      <p class="empty-message">Connect it to the same Wi-Fi as the phone, then try again.</p>
      <button class="secondary small" data-act="pair-retry">Try Again</button></div>`;
  const svg = pairing.svg.replace(/^<\?xml[^>]*>\s*/, "");
  return html`<div class="qr-block">
    <div class="qr" role="img" aria-label="QR code for ${pairing.label}">${raw(svg)}</div>
    <div class="qr-address">
      <button class="quiet small" data-act="pair-copy" title="Copy a fallback address">${icons.copy}<span>Copy fallback address</span></button></div>
  </div>`;
}

/** A live line: is a camera sending to the hub right now? */
function cameraStatus(): Raw {
  const s = app.state;
  if (app.link.link !== "connected") return html``;
  return s?.camera_connected
    ? html`<p class="cam-status ok"><span class="dot ok"></span>${pairingConnected ? "Ready on this Mac" : "Another camera is connected"}${s.camera?.name ? html`: ${s.camera.name}` : ""}</p>`
    : html`<p class="cam-status waiting"><span class="pair-radar"><span></span></span>Waiting for the scan</p>`;
}

const steps = (items: string[]) => html`<ol class="pair-steps">${items.map((t, i) => html`<li><span class="pair-num">${i + 1}</span><span>${t}</span></li>`)}</ol>`;

const PHONE_STEPS = [
  "Scan this code with the iPhone Camera app.",
  "HandOver opens, connects, and starts Be the Camera.",
  "Point the phone at the work. The live picture appears here.",
];
const GLASSES_STEPS = [
  "Scan this code with the iPhone Camera app.",
  "HandOver opens the Meta glasses setup automatically.",
  "Approve the Meta AI handoff, then wear the glasses. The live picture appears here.",
];

function onPairAction(act: string) {
  if (act === "pair-retry") void loadPairing(true);
  else if (act === "pair-copy" && pairing?.hub)
    void navigator.clipboard.writeText(pairing.hub).then(
      () => toast("Copied address"),
      () => toast("Could not copy. Select the address instead."),
    );
}

/** Pair a Phone: the QR and how to use it. From Home and Settings. */
export function pairSheet() {
  open = "pair";
  watchPairing("phone", () => {
    closeSheet();
    toast("iPhone camera connected");
  });
  void loadPairing(false, "phone");
  openSheet({
    title: "Pair a Phone",
    wide: true,
    body: () => html`<div class="pair">
      ${qrBlock()}
      <div class="pair-text">
        <p class="sheet-lede">Use a phone as the camera that watches your hands.</p>
        ${steps(PHONE_STEPS)}
        ${cameraStatus()}
        <p class="hint">The phone must be on the same Wi-Fi as this hub.</p>
        <div class="form-actions"><button class="primary" data-sheet="close">Done</button></div>
      </div>
    </div>`,
    onAction: onPairAction,
    onClose: () => {
      open = "";
      stopWatching();
    },
  });
}

/**
 * "How should HandOver see your hands?" Picking a choice remembers it. With `then`, the sheet is
 * part of starting a lesson: the last button says Start Lesson and runs `then`.
 */
export function cameraSheet(opts: { then?: () => void; step?: CameraChoice } = {}) {
  let step: "choose" | CameraChoice = opts.step && opts.step !== "computer" ? opts.step : "choose";
  open = "camera";
  if (step === "phone" || step === "glasses") void loadPairing(false, step);
  const done = () => {
    closeSheet();
    if (opts.then) opts.then();
    else rerender();
  };
  if (step === "phone" || step === "glasses") watchPairing(step, done);
  else stopWatching();
  const option = (v: CameraChoice, icon: Raw, title: string, line: string, tag = "") =>
    html`<button class="role-card camera-option ${prefs.camera === v ? "on" : ""}" data-act="cam-pick" data-cam="${v}" role="radio" aria-checked="${prefs.camera === v}">
      <span class="tile">${icon}</span>
      <span class="role-text"><span class="option-title">${title}${tag ? html` <span class="badge-soft">${tag}</span>` : ""}</span><span class="option-line">${line}</span></span>
      <span class="role-check">${prefs.camera === v ? icons.checkFill : icons.chevron}</span></button>`;
  openSheet({
    title: step === "phone" ? "Use a Phone" : step === "glasses" ? "Use Meta Glasses" : "How should HandOver see your hands?",
    wide: step !== "choose",
    body: () => {
      if (step === "choose")
        return html`<div class="form">
          <p class="sheet-lede">Point a camera at your hands and your work. You can change this anytime.</p>
          <div class="role-list" role="radiogroup" aria-label="Camera">
            ${option("computer", icons.laptop, "This Computer's Camera", "Use the webcam on this computer.")}
            ${option("phone", icons.phone, "A Phone", "Prop up a phone running HandOver and point it at your work.")}
            ${option("glasses", icons.glasses, "Meta Glasses", "Ray-Ban Meta glasses, connected through the HandOver phone app.", "Experimental")}
          </div>
        </div>`;
      return html`<div class="pair">
        ${qrBlock()}
        <div class="pair-text">
          <p class="sheet-lede">${step === "phone" ? "Set up the phone as your camera." : "The glasses send their camera through the HandOver phone app."}</p>
          ${steps(step === "phone" ? PHONE_STEPS : GLASSES_STEPS)}
          ${cameraStatus()}
          ${step === "glasses" ? html`<p class="hint">Experimental. The glasses need Developer Mode on in the Meta AI app.</p>` : html`<p class="hint">The phone must be on the same Wi-Fi as this hub.</p>`}
          <div class="form-actions"><button class="secondary" data-act="cam-back">Back</button>
            <button class="primary" data-act="cam-done">${opts.then ? "Start Lesson" : "Done"}</button></div>
        </div>
      </div>`;
    },
    onAction: (act, el) => {
      if (act === "cam-pick") {
        const v = el.dataset.cam as CameraChoice;
        prefs.camera = v;
        rerender();
        if (v === "computer") return done();
        step = v;
        reopen();
      } else if (act === "cam-back") {
        step = "choose";
        reopen();
      } else if (act === "cam-done") done();
      else onPairAction(act);
    },
    onClose: () => {
      open = "";
      stopWatching();
    },
  });
  // The sheet's width depends on the step, so it is opened again rather than redrawn.
  function reopen() {
    cameraSheet({ ...opts, step: step === "choose" ? undefined : step });
  }
}

/** Redraws an open pairing or camera sheet when the hub's state changes. */
export function pairLive() {
  if (!open || !sheetOpen()) return;
  const connected = pairedCamera(app.state, expectedCamera);
  if (connected !== pairingConnected) {
    pairingConnected = connected;
    window.clearTimeout(pairedTimer);
    pairedTimer = 0;
    drawSheet();
    if (connected && pairedAction) {
      pairedTimer = window.setTimeout(() => {
        pairedTimer = 0;
        const action = pairedAction;
        pairedAction = null;
        action?.();
      }, 900);
    }
    return;
  }
  drawSheet();
}

/** "Camera: A phone, Change", for the lesson page and Settings. */
export function cameraRow(): Raw {
  const c = prefs.camera;
  const icon = c === "computer" ? icons.laptop : c === "glasses" ? icons.glasses : c === "phone" ? icons.phone : icons.smallCamera;
  return html`<div class="camera-row">
    <span class="camera-row-icon">${icon}</span>
    <span class="camera-row-label">Camera</span>
    <span class="camera-row-value">${c ? CAMERA_WORD[c] : "Not chosen yet"}</span>
    <button class="quiet small" data-act="camera-change">${c ? "Change" : "Choose"}</button>
  </div>`;
}
