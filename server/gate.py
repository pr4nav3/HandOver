"""Motion gate: decide which camera frames are worth a vision check.

Calling the model on every frame (about 1 fps) breaks rate limits and wastes
calls on blurry, mid-motion frames. The gate allows a check only when the scene
has settled after motion and looks different from the last checked frame, plus
a heartbeat every few seconds (even during motion) so a slow change or a shaky
camera is never left unchecked.

Pillow only (no numpy or OpenCV). Each frame is decoded straight to a small
grayscale image using the JPEG decoder's built-in downscaling, blurred, and
compared with the previous one. Measure of difference between two frames: the
fraction of pixels whose gray value differs by more than 25.

Env (a constructor argument wins over env; a bad value falls back to the default):
    HANDOVER_GATE=0                disable the gate (every frame is allowed)
    HANDOVER_GATE_MOTION           hold while motion is above this (default 0.02)
    HANDOVER_GATE_STILL            a frame is still below this (default 0.005)
    HANDOVER_GATE_STILL_FRAMES     still frames in a row to count as settled (default 2)
    HANDOVER_GATE_CHANGE           change vs the last checked frame (default 0.018)
    HANDOVER_GATE_HEARTBEAT_S      seconds between heartbeat checks (default 6.0)
"""

from __future__ import annotations

import io
import logging
import os
import threading
from typing import Optional

from PIL import Image, ImageChops, ImageFilter

log = logging.getLogger("handover.gate")

SIZE = (160, 90)
PIXEL_DIFF = 25  # gray levels; below this counts as sensor noise or lighting flicker
BLUR_RADIUS = 1.5


def _env_num(name: str, default: float, cast: type = float) -> float:
    """Read a positive number from env so thresholds can be tuned without code edits."""
    raw = os.environ.get(name)
    if raw is None or raw.strip() == "":
        return default
    try:
        value = cast(raw)
    except ValueError:
        log.warning("gate: ignoring bad %s=%r, using %s", name, raw, default)
        return default
    if value <= 0:
        log.warning("gate: ignoring non-positive %s=%r, using %s", name, raw, default)
        return default
    return value


def _small(jpeg: bytes) -> Image.Image:
    """Decode to a blurred 160x90 gray image; draft() lets libjpeg scale down for speed."""
    img = Image.open(io.BytesIO(jpeg))
    if img.format != "JPEG":
        raise ValueError("not a JPEG")
    img.draft("L", (SIZE[0] * 2, SIZE[1] * 2))
    img = img.convert("L").resize(SIZE, Image.BILINEAR)
    return img.filter(ImageFilter.GaussianBlur(BLUR_RADIUS))


def diff_fraction(a: Image.Image, b: Image.Image) -> float:
    """Fraction of pixels whose gray value differs by more than PIXEL_DIFF."""
    hist = ImageChops.difference(a, b).histogram()
    return sum(hist[PIXEL_DIFF + 1 :]) / (a.width * a.height)


class MotionGate:
    """Per-step frame filter for the check loop.

    Motion history (previous frame, still counter) survives reset() because it
    describes the camera stream, not the step; so right after an advance a still
    scene can be checked at once instead of waiting to settle again.

    Thread-safe: observe() may run in a worker thread while reset() runs on the
    event loop. A lock covers every state change (decoding stays outside it), so
    reset() always lands between two observe() calls and never leaves stale history.
    """

    def __init__(
        self,
        enabled: Optional[bool] = None,
        *,
        motion_thresh: Optional[float] = None,
        still_thresh: Optional[float] = None,
        still_frames: Optional[int] = None,
        change_thresh: Optional[float] = None,
        heartbeat_s: Optional[float] = None,
    ) -> None:
        if enabled is None:
            enabled = os.environ.get("HANDOVER_GATE", "1") != "0"
        self.enabled = enabled
        self.motion_thresh = motion_thresh if motion_thresh is not None else _env_num("HANDOVER_GATE_MOTION", 0.02)
        self.still_thresh = still_thresh if still_thresh is not None else _env_num("HANDOVER_GATE_STILL", 0.005)
        self.still_frames = int(
            still_frames if still_frames is not None else _env_num("HANDOVER_GATE_STILL_FRAMES", 2, int)
        )
        self.change_thresh = change_thresh if change_thresh is not None else _env_num("HANDOVER_GATE_CHANGE", 0.018)
        self.heartbeat_s = heartbeat_s if heartbeat_s is not None else _env_num("HANDOVER_GATE_HEARTBEAT_S", 6.0)

        self._prev: Optional[Image.Image] = None  # last decoded frame, for motion
        self._still_count = 0
        self._checked: Optional[Image.Image] = None  # frame of the last issued check
        self._since: Optional[float] = None  # heartbeat anchor: last check, else first frame of the step
        self._frames_seen = 0
        self._checks_allowed = 0
        self._last_motion: Optional[float] = None
        self._last_change: Optional[float] = None
        self._lock = threading.Lock()

    def observe(self, jpeg: bytes, now: float) -> bool:
        """Feed one frame; True means run a check on it. Never raises."""
        if not self.enabled:
            with self._lock:
                self._frames_seen += 1
                self._checks_allowed += 1
            return True
        try:
            cur = _small(jpeg)  # the slow part, done without holding the lock
        except Exception as e:  # corrupt or non-JPEG bytes must not break the loop
            log.debug("gate: unreadable frame (%s)", e)
            with self._lock:
                self._frames_seen += 1
            return False
        with self._lock:
            self._frames_seen += 1
            return self._judge(cur, now)

    def _judge(self, cur: Image.Image, now: float) -> bool:
        """Decide on a decoded frame; caller holds the lock."""
        if self._since is None:
            self._since = now
        prev, self._prev = self._prev, cur
        if prev is None:
            self._last_motion = None
            self._still_count = 0
            return False
        motion = diff_fraction(prev, cur)
        self._last_motion = motion
        self._still_count = self._still_count + 1 if motion < self.still_thresh else 0

        # Heartbeat wins even in motion: a shaky chest-mounted phone may never settle,
        # and the contract promises a check at least every heartbeat_s.
        if now - self._since >= self.heartbeat_s:
            allow = True
        elif motion > self.motion_thresh:
            allow = False  # motion only holds the change-triggered checks
        else:
            if self._checked is None:
                self._last_change = None
                changed = True  # nothing checked yet on this step
            else:
                self._last_change = diff_fraction(self._checked, cur)
                changed = self._last_change > self.change_thresh
            allow = self._still_count >= self.still_frames and changed
        if allow:
            self._checks_allowed += 1
        return allow

    def mark_checked(self, now: float) -> None:
        """Record that a check was issued on the most recent frame."""
        with self._lock:
            self._checked = self._prev
            self._since = now

    def reset(self) -> None:
        """Forget the last check (call on step change) so the next settled frame is allowed."""
        with self._lock:
            self._checked = None
            self._since = None
            self._last_change = None

    @property
    def settled(self) -> bool:
        """True when the newest frame is still, so a fast confirm can trust it; always True when disabled."""
        with self._lock:
            return not self.enabled or self._still_count >= self.still_frames

    @property
    def stats(self) -> dict:
        """Counters and the latest measurements, for logs."""
        with self._lock:
            return {
                "frames_seen": self._frames_seen,
                "checks_allowed": self._checks_allowed,
                "last_motion": self._last_motion,
                "last_change": self._last_change,
            }
