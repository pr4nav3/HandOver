"""Soak and load test for the HandOver hub.

    .venv/bin/python scripts/soak.py --base http://localhost:8000 --cameras 3 --viewers 10 \
        --minutes 5 --fps 2 [--lesson demo-v1] [--seed 1]

Starts N fake cameras on /ws/camera and M viewers on /ws/ui, all in this one process.

Each camera sends hello (its own device_id), then JPEG frames at --fps. Frames are the lesson's
reference frames (fetched over REST) or a synthesized picture, with a moving box so every frame
differs. A strip of black and white blocks along the top encodes the camera number and a frame
counter; viewers read the strip back from the downscaled frame the hub forwards, so latency is
measured per frame (camera send to viewer receive, same clock).

Every 30 s one random camera and one random viewer disconnect and reconnect. Halfway through, the
active camera stops sending frames (socket stays open) and the test watches state.camera for a switch
to another camera (contract 5, active camera rule).

Hub memory (RSS) is sampled with lsof and ps when the hub runs on this machine.

Exit 0 when healthy, 1 when hub memory grows more than 50 percent (end vs warm baseline) or any
client crashes or is closed by the hub unexpectedly, 2 when the hub is unreachable at start.
"""

from __future__ import annotations

import argparse
import asyncio
import io
import json
import random
import statistics
import subprocess
import sys
import time
import urllib.request
from urllib.parse import urlsplit

import websockets
from PIL import Image, ImageDraw

UI_MAX_FPS = 4  # the hub forwards at most 4 frames per second (contract 7)
RECONNECT_EVERY = 30.0
SWITCH_IDLE = 5.0  # contract 5: active camera idle this long hands over
SWITCH_DEADLINE = 7.0  # report a pass when the switch lands within this
SWITCH_PAUSE = 10.0
CAM_BITS, SEQ_BITS = 4, 11
SEQ_MOD = 1 << SEQ_BITS
BLOCKS = 1 + CAM_BITS + SEQ_BITS + 1 + 1  # white sentinel, cam, seq, parity, black sentinel
MAX_MSG = 8 * 1024 * 1024


def now() -> float:
    return time.monotonic()


# ---------------------------------------------------------------- frame code strip

def code_bits(cam: int, seq: int) -> list[int]:
    bits = [(cam >> i) & 1 for i in range(CAM_BITS)] + [(seq >> i) & 1 for i in range(SEQ_BITS)]
    return [1] + bits + [sum(bits) & 1] + [0]


def draw_code(img: Image.Image, cam: int, seq: int) -> None:
    w, h = img.size
    bh = max(16, h // 10)
    d = ImageDraw.Draw(img)
    for i, b in enumerate(code_bits(cam, seq % SEQ_MOD)):
        x0, x1 = i * w // BLOCKS, (i + 1) * w // BLOCKS
        d.rectangle([x0, 0, x1, bh], fill=(255, 255, 255) if b else (0, 0, 0))


def read_code(data: bytes) -> tuple[int, int] | None:
    """Return (cam, seq) from a forwarded frame, or None when the strip does not read cleanly."""
    try:
        with Image.open(io.BytesIO(data)) as im:
            im.draft("L", (im.size[0] // 4, im.size[1] // 4))
            g = im.convert("L")
    except Exception:
        return None
    w, h = g.size
    y = max(1, h // 20)
    bits = [1 if g.getpixel((int((i + 0.5) * w / BLOCKS), y)) > 127 else 0 for i in range(BLOCKS)]
    if bits[0] != 1 or bits[-1] != 0:
        return None
    payload = bits[1:-2]
    if sum(payload) & 1 != bits[-2]:
        return None
    cam = sum(b << i for i, b in enumerate(payload[:CAM_BITS]))
    seq = sum(b << i for i, b in enumerate(payload[CAM_BITS:]))
    return cam, seq


# ---------------------------------------------------------------- shared stats

class Stats:
    def __init__(self) -> None:
        self.start = now()
        self.sent: dict[tuple[int, int], float] = {}  # (cam, seq mod) -> send time
        self.frames_sent = 0
        self.latencies: list[float] = []  # ms
        self.recent: list[float] = []
        self.decode_fail = 0
        self.errors: list[str] = []
        self.crashes = 0
        self.unexpected_closes = 0
        self.replaced = 0
        self.rss: list[tuple[float, int]] = []  # (t, KB)
        self.rss_before: int | None = None
        self.state: dict | None = None  # newest state any viewer saw
        self.camera_field_seen = False
        self.cam_name_changes: list[tuple[float, str | None]] = []
        self.last_hello_cam: int | None = None
        self.reconnects: list[str] = []
        self.switch_result = "not run"
        self.decode_cache: dict[int, tuple[int, int] | None] = {}

    def t(self) -> float:
        return now() - self.start

    def error(self, who: str, msg: str) -> None:
        self.errors.append(f"{self.t():6.1f}s {who}: {msg}")


S = Stats()
STOP = asyncio.Event()


def decode_cached(data: bytes) -> tuple[int, int] | None:
    # All viewers get the same bytes, so each forwarded frame is decoded once.
    key = hash(data)
    if key not in S.decode_cache:
        if len(S.decode_cache) > 256:
            S.decode_cache.clear()
        S.decode_cache[key] = read_code(data)
    return S.decode_cache[key]


# ---------------------------------------------------------------- images

def http_get(url: str, timeout: float = 10) -> bytes:
    with urllib.request.urlopen(url, timeout=timeout) as r:
        return r.read()


def load_bases(base: str, lesson: str | None) -> list[Image.Image]:
    imgs: list[Image.Image] = []
    if lesson:
        meta = json.loads(http_get(f"{base}/api/lessons/{lesson}"))
        for i, step in enumerate(meta.get("steps", [])):
            rel = step.get("ref_frame") or f"frames/{i + 1:02d}.jpg"
            try:
                im = Image.open(io.BytesIO(http_get(f"{base}/lessons/{lesson}/{rel}"))).convert("RGB")
            except Exception:
                continue
            im.thumbnail((1280, 1280))
            imgs.append(im)
    if not imgs:
        for hue in [(40, 90, 160), (40, 140, 70), (150, 70, 50)]:
            im = Image.new("RGB", (1280, 720), hue)
            d = ImageDraw.Draw(im)
            for k in range(0, 1280, 160):
                d.rectangle([k, 300, k + 80, 620], fill=tuple(min(255, c + 60) for c in hue))
            imgs.append(im)
    return imgs


def make_frame(bases: list[Image.Image], cam: int, seq: int, fps: float) -> bytes:
    img = bases[(int(seq / (fps * 4)) + cam) % len(bases)].copy()
    w, h = img.size
    d = ImageDraw.Draw(img)
    x = (seq * 37 + cam * 200) % max(1, w - 120)
    d.rectangle([x, h // 2, x + 120, h // 2 + 120], fill=((seq * 13) % 255, 200, (cam * 70) % 255))
    draw_code(img, cam, seq)
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=80)
    return buf.getvalue()


# ---------------------------------------------------------------- clients

class Camera:
    def __init__(self, idx: int, url: str, fps: float, bases: list[Image.Image]):
        self.idx, self.url, self.fps, self.bases = idx, url, fps, bases
        self.device_id = f"soak-cam-{idx}"
        self.name = f"Soak camera {idx}"
        self.seq = 0
        self.paused = False
        self.drop = asyncio.Event()
        self.rx: dict[str, int] = {}
        self.sessions = 0
        self.done = False
        self.close_seen = False

    async def run(self) -> None:
        try:
            while not STOP.is_set() and not self.done:
                await self.session()
                if not STOP.is_set() and not self.done:
                    await asyncio.sleep(1.0)
        except Exception as e:  # anything else is a crash of this client
            S.crashes += 1
            S.error(self.name, f"crashed: {e!r}")

    async def connect(self):
        for attempt in range(5):
            try:
                return await websockets.connect(self.url, max_size=MAX_MSG, open_timeout=10)
            except Exception as e:
                S.error(self.name, f"connect failed ({attempt + 1}/5): {e!r}")
                await asyncio.sleep(1 + attempt)
        raise RuntimeError("could not connect after 5 tries")

    async def session(self) -> None:
        t0 = now()
        ws = await self.connect()
        self.sessions += 1
        if self.sessions > 1:
            S.reconnects.append(f"{self.name} reconnected in {(now() - t0) * 1000:.0f} ms")
        self.drop.clear()
        self.close_seen = False
        reader = asyncio.create_task(self.read(ws))
        try:
            await ws.send(json.dumps({"type": "hello", "device_id": self.device_id, "name": self.name,
                                      "platform": "web", "source": "browser"}))
            S.last_hello_cam = self.idx
            nxt = now()
            while not STOP.is_set() and not self.drop.is_set() and not reader.done():
                if not self.paused:
                    data = await asyncio.to_thread(make_frame, self.bases, self.idx, self.seq, self.fps)
                    S.sent[(self.idx, self.seq % SEQ_MOD)] = now()
                    await ws.send(data)
                    S.frames_sent += 1
                    self.seq += 1
                nxt += 1 / self.fps
                await asyncio.sleep(max(0.0, nxt - now()))
        except websockets.ConnectionClosed as e:
            self.closed_by_hub(e)
        finally:
            await ws.close()
            with_reader = await asyncio.gather(reader, return_exceptions=True)
            if isinstance(with_reader[0], Exception):
                S.error(self.name, f"reader: {with_reader[0]!r}")

    def closed_by_hub(self, e: websockets.ConnectionClosed) -> None:
        if self.close_seen:  # sender and reader can both see the same close
            return
        self.close_seen = True
        code = e.rcvd.code if e.rcvd else None
        if code == 4000:
            S.replaced += 1
            S.error(self.name, "closed 4000 replaced; not reconnecting (contract 6)")
            self.done = True
        elif not self.drop.is_set() and not STOP.is_set():
            S.unexpected_closes += 1
            S.error(self.name, f"closed by hub, code {code}")

    async def read(self, ws) -> None:
        try:
            async for msg in ws:
                kind = "binary" if isinstance(msg, bytes) else json.loads(msg).get("type", "?")
                self.rx[kind] = self.rx.get(kind, 0) + 1
        except websockets.ConnectionClosed as e:
            self.closed_by_hub(e)


class Viewer:
    def __init__(self, idx: int, url: str):
        self.idx, self.url = idx, url
        self.name = f"viewer {idx}"
        self.drop = asyncio.Event()
        self.frames = 0
        self.states = 0
        self.other = 0
        self.out_of_order = 0
        self.last_seq: dict[int, int] = {}
        self.connected_s = 0.0
        self.sent_while = 0  # frames the cameras sent while this viewer was connected
        self.sessions = 0
        self.first_state_ms: list[float] = []

    async def run(self) -> None:
        try:
            while not STOP.is_set():
                await self.session()
                if not STOP.is_set():
                    await asyncio.sleep(1.0)
        except Exception as e:
            S.crashes += 1
            S.error(self.name, f"crashed: {e!r}")

    async def session(self) -> None:
        t0 = now()
        ws = None
        for attempt in range(5):
            try:
                ws = await websockets.connect(self.url, max_size=MAX_MSG, open_timeout=10)
                break
            except Exception as e:
                S.error(self.name, f"connect failed ({attempt + 1}/5): {e!r}")
                await asyncio.sleep(1 + attempt)
        if ws is None:
            raise RuntimeError("could not connect after 5 tries")
        self.sessions += 1
        self.drop.clear()
        connected = now()
        sent0 = S.frames_sent
        got_state = False

        async def watch() -> None:
            stop_wait = asyncio.create_task(STOP.wait())
            drop_wait = asyncio.create_task(self.drop.wait())
            await asyncio.wait([stop_wait, drop_wait], return_when=asyncio.FIRST_COMPLETED)
            stop_wait.cancel()
            drop_wait.cancel()
            await ws.close()

        watcher = asyncio.create_task(watch())
        try:
            async for msg in ws:
                t = now()
                if isinstance(msg, bytes):
                    self.frames += 1
                    code = decode_cached(msg)
                    if code is None:
                        S.decode_fail += 1
                        continue
                    cam, seq = code
                    sent = S.sent.get((cam, seq))
                    if sent is not None and 0 <= t - sent < 30:
                        ms = (t - sent) * 1000
                        S.latencies.append(ms)
                        S.recent.append(ms)
                    prev = self.last_seq.get(cam)
                    if prev is not None and 0 < (prev - seq) % SEQ_MOD < SEQ_MOD // 2:
                        self.out_of_order += 1
                    self.last_seq[cam] = seq
                    continue
                data = json.loads(msg)
                if data.get("type") == "state":
                    self.states += 1
                    if not got_state:
                        got_state = True
                        self.first_state_ms.append((t - t0) * 1000)
                    on_state(data)
                else:
                    self.other += 1
        except websockets.ConnectionClosed as e:
            if not self.drop.is_set() and not STOP.is_set():
                S.unexpected_closes += 1
                S.error(self.name, f"closed by hub, code {e.rcvd.code if e.rcvd else None}")
        finally:
            watcher.cancel()
            await ws.close()
            self.connected_s += now() - connected
            self.sent_while += S.frames_sent - sent0
            if self.sessions > 1 and got_state:
                S.reconnects.append(f"{self.name} reconnected, first state in {self.first_state_ms[-1]:.0f} ms")
            elif not got_state and not STOP.is_set():
                S.error(self.name, "session ended without any state message")


def on_state(data: dict) -> None:
    S.state = data
    if "camera" in data:
        S.camera_field_seen = True
        cam = data.get("camera")
        name = cam.get("name") if isinstance(cam, dict) else None
        if not S.cam_name_changes or S.cam_name_changes[-1][1] != name:
            S.cam_name_changes.append((now(), name))


# ---------------------------------------------------------------- hub memory

def hub_pid(base: str) -> int | None:
    parts = urlsplit(base)
    if parts.hostname not in ("localhost", "127.0.0.1", "::1"):
        return None
    port = parts.port or (443 if parts.scheme == "https" else 80)
    try:
        out = subprocess.run(["lsof", "-ti", f"tcp:{port}", "-sTCP:LISTEN"], capture_output=True, text=True,
                             timeout=5).stdout.split()
        return int(out[0]) if out else None
    except Exception:
        return None


def rss_kb(pid: int) -> int | None:
    try:
        out = subprocess.run(["ps", "-o", "rss=", "-p", str(pid)], capture_output=True, text=True, timeout=5)
        return int(out.stdout.strip())
    except Exception:
        return None


async def sample_memory(pid: int | None) -> None:
    while pid and not STOP.is_set():
        kb = await asyncio.to_thread(rss_kb, pid)
        if kb is None:
            S.error("hub", f"pid {pid} gone (hub exited?)")
            return
        S.rss.append((S.t(), kb))
        await asyncio.sleep(5)


# ---------------------------------------------------------------- scenario tasks

async def chaos(cams: list[Camera], viewers: list[Viewer], rng: random.Random, switch_window) -> None:
    while not STOP.is_set():
        try:
            await asyncio.wait_for(STOP.wait(), RECONNECT_EVERY)
            return
        except asyncio.TimeoutError:
            pass
        lo, hi = switch_window
        busy = len(cams) >= 2 and lo - 2 <= S.t() <= hi + 2  # leave the switch test alone
        if cams and not busy:
            c = rng.choice([c for c in cams if not c.done] or cams)
            c.drop.set()
        if viewers:
            rng.choice(viewers).drop.set()


def active_name() -> str | None:
    cam = (S.state or {}).get("camera")
    return cam.get("name") if isinstance(cam, dict) else None


async def switch_test(cams: list[Camera], at: float) -> None:
    if len(cams) < 2:
        S.switch_result = "skipped (needs 2 or more cameras)"
        return
    await asyncio.sleep(max(0.0, at - S.t()))
    if STOP.is_set():
        return
    name = active_name()
    if not S.camera_field_seen:
        S.switch_result = "not implemented (state.camera never appeared)"
    target = next((c for c in cams if c.name == name), None)
    if target is None:
        target = next((c for c in cams if c.idx == S.last_hello_cam), cams[-1])
    target.paused = True
    paused_at = now()
    switched = None
    while now() - paused_at < SWITCH_PAUSE and not STOP.is_set():
        cur = active_name()
        if S.camera_field_seen and cur and cur != target.name:
            switched = now() - paused_at
            break
        await asyncio.sleep(0.1)
    target.paused = False
    if not S.camera_field_seen:
        S.switch_result = "not implemented (state.camera never appeared)"
    elif switched is None:
        S.switch_result = f"FAIL: {target.name} paused, no switch within {SWITCH_PAUSE:.0f} s"
        S.error("switch", S.switch_result)
    elif switched < SWITCH_IDLE - 0.5:
        S.switch_result = f"early: switched after {switched:.1f} s (rule says 5 s idle)"
    elif switched <= SWITCH_DEADLINE:
        S.switch_result = f"pass: {target.name} paused, switched to {active_name()} in {switched:.1f} s"
    else:
        S.switch_result = f"slow: switched after {switched:.1f} s (expected 5 to 7 s)"


async def status_line(total: float, cams: list[Camera], viewers: list[Viewer]) -> None:
    tty = sys.stdout.isatty()
    every = 1.0 if tty else 10.0
    while not STOP.is_set():
        try:
            await asyncio.wait_for(STOP.wait(), every)
        except asyncio.TimeoutError:
            pass
        if STOP.is_set():
            break
        rec = S.recent
        S.recent = []
        p50 = f"{statistics.median(rec):4.0f} ms" if rec else "   - ms"
        mem = f"{S.rss[-1][1] / 1024:6.1f} MB" if S.rss else "   n/a"
        rx = sum(v.frames for v in viewers)
        line = (f"  {S.t():5.0f}s/{total:.0f}s  sent {S.frames_sent:5d}  viewer frames {rx:6d}  "
                f"p50 {p50}  hub {mem}  step {(S.state or {}).get('step', '-')}  errors {len(S.errors)}")
        print(("\r" + line) if tty else line, end="" if tty else "\n", flush=True)
    if tty:
        print()


# ---------------------------------------------------------------- report

def pct(xs: list[float], p: float) -> float:
    xs = sorted(xs)
    return xs[min(len(xs) - 1, int(round(p / 100 * (len(xs) - 1))))]


def report(args, cams: list[Camera], viewers: list[Viewer], seconds: float) -> int:
    rows: list[tuple[str, str]] = []
    add = lambda k, v: rows.append((k, v))
    add("run", f"{seconds:.0f} s, {len(cams)} cameras at {args.fps:g} fps, {len(viewers)} viewers")
    add("frames sent (all cameras)", str(S.frames_sent))
    lat = S.latencies
    if lat:
        add("latency p50 / p90 / max", f"{pct(lat, 50):.0f} / {pct(lat, 90):.0f} / {max(lat):.0f} ms ({len(lat)} samples)")
    else:
        add("latency p50 / p90 / max", "no frames reached viewers")
    frames = [v.frames for v in viewers]
    states = [v.states for v in viewers]
    add("frames per viewer min / avg / max", f"{min(frames)} / {statistics.mean(frames):.0f} / {max(frames)}" if viewers else "-")
    add("state msgs per viewer min / avg / max", f"{min(states)} / {statistics.mean(states):.0f} / {max(states)}" if viewers else "-")
    stable = [v for v in viewers if v.sessions == 1]
    if len(stable) >= 2:
        ss = [v.states for v in stable]
        add("state msgs, never-dropped viewers", f"min {min(ss)}, max {max(ss)} ({'equal' if min(ss) == max(ss) else 'DIFFER, hub dropped some'})")
    rate = statistics.mean(states) / seconds * 60 if viewers else 0
    add("state message rate", f"{rate:.1f} per viewer per minute")
    # Expected per viewer: frames sent while connected (only the active camera's share once the
    # active-camera rule exists), capped by the hub's 4 per second forward limit.
    share = 1 / len(cams) if S.camera_field_seen and cams else 1
    expected = sum(min(v.sent_while * share, UI_MAX_FPS * v.connected_s) for v in viewers)
    got = sum(frames)
    drop = max(0.0, 1 - got / expected) * 100 if expected else 0.0
    add("frames dropped (estimate)", f"{drop:.1f} % ({got} received of about {expected:.0f} expected, all viewers)")
    add("out of order frames", str(sum(v.out_of_order for v in viewers)))
    add("unreadable frame codes", str(S.decode_fail))
    cam_rx: dict[str, int] = {}
    for c in cams:
        for k, n in c.rx.items():
            cam_rx[k] = cam_rx.get(k, 0) + n
    add("messages to cameras", ", ".join(f"{k} {n}" for k, n in sorted(cam_rx.items())) or "none (hub sends nothing to cameras)")
    add("reconnects", f"{len(S.reconnects)} done" + (f", e.g. {S.reconnects[0]}" if S.reconnects else ""))
    add("active camera switch", S.switch_result)
    growth = None
    if S.rss:
        warm_t = min(15.0, seconds * 0.15)
        warm = next((kb for t, kb in S.rss if t >= warm_t), S.rss[0][1])
        end = S.rss[-1][1]
        peak = max(kb for _, kb in S.rss)
        before = f"{S.rss_before / 1024:.1f}" if S.rss_before else "?"
        growth = (end - warm) / warm * 100
        add("hub RSS before / warm / end / peak", f"{before} / {warm / 1024:.1f} / {end / 1024:.1f} / {peak / 1024:.1f} MB")
        add("hub RSS growth (end vs warm)", f"{growth:+.1f} %")
    else:
        add("hub RSS", "n/a (hub not local or pid not found)")
    add("client crashes / hub closes", f"{S.crashes} / {S.unexpected_closes}")
    add("errors", str(len(S.errors)))

    width = max(len(k) for k, _ in rows)
    print("\nSoak report")
    print("-" * (width + 50))
    for k, v in rows:
        print(f"{k.ljust(width)}  {v}")
    print("-" * (width + 50))
    if S.errors:
        print("First errors:")
        for e in S.errors[:12]:
            print("  " + e)
        if len(S.errors) > 12:
            print(f"  ... and {len(S.errors) - 12} more")

    fails = []
    if growth is not None and growth > 50:
        fails.append(f"hub memory grew {growth:.0f} %")
    if S.crashes or S.unexpected_closes:
        fails.append(f"{S.crashes} client crashes, {S.unexpected_closes} unexpected hub closes")
    print("Result: " + ("FAIL, " + "; ".join(fails) if fails else "pass"))
    return 1 if fails else 0


# ---------------------------------------------------------------- main

async def amain(args) -> int:
    base = args.base.rstrip("/")
    ws_base = "ws" + base[len("http"):] if base.startswith("http") else base
    try:
        await asyncio.to_thread(http_get, f"{base}/api/lessons", 5)
    except Exception as e:
        print(f"hub not reachable at {base}: {e}")
        return 2
    rng = random.Random(args.seed)
    try:
        bases = await asyncio.to_thread(load_bases, base, args.lesson)
    except Exception as e:
        print(f"could not load lesson {args.lesson!r} ({e}); using synthesized frames")
        bases = await asyncio.to_thread(load_bases, base, None)
    pid = await asyncio.to_thread(hub_pid, base)
    if pid:
        S.rss_before = await asyncio.to_thread(rss_kb, pid)

    if args.lesson:
        async with websockets.connect(f"{ws_base}/ws/ui", max_size=MAX_MSG) as ws:
            await ws.send(json.dumps({"type": "select_lesson", "id": args.lesson}))
            await asyncio.sleep(0.5)

    total = args.minutes * 60
    print(f"Soak: {base}, {args.cameras} cameras at {args.fps:g} fps, {args.viewers} viewers, {total:.0f} s, "
          f"hub pid {pid or 'n/a'}, {len(bases)} base images")
    S.start = now()
    viewers = [Viewer(i, f"{ws_base}/ws/ui") for i in range(args.viewers)]
    cams = [Camera(i, f"{ws_base}/ws/camera", args.fps, bases) for i in range(args.cameras)]
    tasks = [asyncio.create_task(v.run()) for v in viewers]
    await asyncio.sleep(0.5)
    for c in cams:
        tasks.append(asyncio.create_task(c.run()))
        await asyncio.sleep(0.2)
    switch_at = total / 2
    side = [asyncio.create_task(sample_memory(pid)),
            asyncio.create_task(chaos(cams, viewers, rng, (switch_at, switch_at + SWITCH_PAUSE))),
            asyncio.create_task(switch_test(cams, switch_at)),
            asyncio.create_task(status_line(total, cams, viewers))]
    try:
        await asyncio.wait_for(STOP.wait(), total)
    except asyncio.TimeoutError:
        pass
    if pid:
        kb = await asyncio.to_thread(rss_kb, pid)
        if kb:
            S.rss.append((S.t(), kb))
    seconds = S.t()
    STOP.set()
    await asyncio.gather(*tasks, *side, return_exceptions=True)
    return report(args, cams, viewers, seconds)


def main() -> None:
    p = argparse.ArgumentParser(description="Soak and load test for the HandOver hub.")
    p.add_argument("--base", default="http://localhost:8000")
    p.add_argument("--cameras", type=int, default=3)
    p.add_argument("--viewers", type=int, default=10)
    p.add_argument("--minutes", type=float, default=5)
    p.add_argument("--fps", type=float, default=2)
    p.add_argument("--lesson", default=None, help="select this lesson and use its frames")
    p.add_argument("--seed", type=int, default=1)
    args = p.parse_args()
    if not 0 <= args.cameras < (1 << CAM_BITS):
        p.error(f"--cameras must be 0 to {(1 << CAM_BITS) - 1}")
    if args.fps <= 0 or args.minutes <= 0:
        p.error("--fps and --minutes must be positive")
    try:
        sys.exit(asyncio.run(amain(args)))
    except KeyboardInterrupt:
        sys.exit(130)


if __name__ == "__main__":
    main()
