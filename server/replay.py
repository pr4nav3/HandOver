"""Stream a video file to /ws/camera as if it were a live camera.

    python -m server.replay VIDEO.mp4 [--url ws://localhost:8000/ws/camera]
        [--fps 1] [--loop] [--start SEC] [--select LESSON_ID] [--no-hello]

Frames are decoded with ffmpeg and sent in real time (one every 1/fps seconds).
--select first sends select_lesson over /ws/ui on the same host.

On every connect it first sends hello (platform "replay", source "file"), so the
web app shows the "Recording" banner. --no-hello skips it (binary frames only).
A lost connection is retried with backoff (1, 2, 4, up to 10 s) and the video
resumes where it was. ffmpeg: HANDOVER_FFMPEG, else PATH, else /opt/homebrew/bin. Close code 4000 (replaced by a newer camera with the same
device id) stops the replay instead. Text messages from the hub are ignored.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import shutil
import signal
import socket
import subprocess
import sys
import time
from pathlib import Path
from typing import Iterator
from urllib.parse import urlsplit, urlunsplit

import websockets

SOI, EOI = b"\xff\xd8", b"\xff\xd9"
REPLACED = 4000
BACKOFF_MAX = 10.0


def ffmpeg_bin() -> str:
    """HANDOVER_FFMPEG if set, then PATH, then Homebrew's folder (same order as server/teach.py)."""
    override = os.environ.get("HANDOVER_FFMPEG")
    if override:
        if Path(override).is_file():
            return override
        raise RuntimeError(f"HANDOVER_FFMPEG points to {override}, which is not a file.")
    found = shutil.which("ffmpeg")
    if found:
        return found
    brew = Path("/opt/homebrew/bin/ffmpeg")
    if brew.is_file():
        return str(brew)
    raise RuntimeError("ffmpeg not found on PATH. Install ffmpeg and make sure ffmpeg runs from a terminal.")


def jpeg_frames(video: Path, fps: float, start: float) -> Iterator[bytes]:
    """Yield JPEG frames from ffmpeg's MJPEG pipe, split on start/end markers."""
    cmd = [ffmpeg_bin(), "-hide_banner", "-loglevel", "error"]
    if start > 0:
        cmd += ["-ss", str(start)]
    cmd += ["-i", str(video), "-vf", f"fps={fps},scale=1280:-2", "-f", "image2pipe",
            "-vcodec", "mjpeg", "-q:v", "5", "-"]
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stdin=subprocess.DEVNULL)
    buf = b""
    try:
        while True:
            chunk = proc.stdout.read1(65536)
            if not chunk:
                break
            buf += chunk
            while True:
                a = buf.find(SOI)
                if a < 0:
                    buf = b""
                    break
                b = buf.find(EOI, a + 2)
                if b < 0:
                    buf = buf[a:]
                    break
                yield buf[a:b + 2]
                buf = buf[b + 2:]
    finally:
        proc.kill()
        proc.wait()


def frame_stream(video: Path, fps: float, start: float, loop: bool) -> Iterator[bytes]:
    while True:
        yield from jpeg_frames(video, fps, start)
        if not loop:
            return


def hello(video: Path) -> str:
    return json.dumps({
        "type": "hello",
        "device_id": f"replay-{socket.gethostname()}-{os.getpid()}",
        "name": f"Replay: {video.name}",
        "platform": "replay",
        "source": "file",
    })


def ui_url(camera_url: str) -> str:
    p = urlsplit(camera_url)
    return urlunsplit((p.scheme, p.netloc, "/ws/ui", "", ""))


async def select_lesson(camera_url: str, lesson_id: str) -> None:
    async with websockets.connect(ui_url(camera_url), max_size=None) as ws:
        await ws.send(json.dumps({"type": "select_lesson", "id": lesson_id}))
        # Wait for the state that confirms the selection (or an error). Binary live frames are skipped.
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            try:
                msg = await asyncio.wait_for(ws.recv(), max(0.01, deadline - time.monotonic()))
            except asyncio.TimeoutError:
                break
            if isinstance(msg, str):
                data = json.loads(msg)
                if data.get("type") == "error":
                    sys.exit(f"select_lesson failed: {data.get('message')}")
                if data.get("type") == "state" and data.get("lesson_id") == lesson_id:
                    print(f"selected {lesson_id} ({data.get('total')} steps)")
                    return
        sys.exit("select_lesson: no confirmation from server")


async def drain(ws) -> None:
    """Read and drop everything the hub sends (state, camera_status, ...), so its queue never fills."""
    async for _ in ws:
        pass


def close_code(e: websockets.ConnectionClosed) -> int | None:
    return e.rcvd.code if e.rcvd is not None else None


async def run(a: argparse.Namespace) -> int:
    if a.select:
        await select_lesson(a.url, a.select)
    period = 1.0 / a.fps
    frames = frame_stream(a.video, a.fps, a.start, a.loop)
    pending: bytes | None = None  # a frame that was read but not sent when the connection dropped
    sent = 0
    delay = 1.0
    try:
        while True:
            try:
                async with websockets.connect(a.url, max_size=None) as ws:
                    print(f"connected to {a.url}" + ("" if a.no_hello else " (sent hello)"), flush=True)
                    delay = 1.0
                    if not a.no_hello:
                        await ws.send(hello(a.video))
                    reader = asyncio.create_task(drain(ws))
                    try:
                        next_t = time.monotonic()
                        while True:
                            frame = pending or await asyncio.to_thread(next, frames, None)
                            if frame is None:
                                print(f"\nend of video after {sent} frames", flush=True)
                                return 0
                            pending = frame
                            await ws.send(frame)
                            pending = None
                            sent += 1
                            print(f"\rframes sent: {sent}", end="", flush=True)
                            next_t += period
                            await asyncio.sleep(max(0.0, next_t - time.monotonic()))
                            if reader.done():  # the hub closed the socket while we slept
                                reader.result()
                    finally:
                        reader.cancel()
            except websockets.ConnectionClosed as e:
                if close_code(e) == REPLACED:
                    print(f"\nclosed by hub (4000 {e.rcvd.reason or 'replaced'}); not reconnecting", flush=True)
                    return 0
                print(f"\nconnection lost ({e}); retrying in {delay:.0f} s", flush=True)
            except (OSError, websockets.InvalidHandshake, asyncio.TimeoutError) as e:
                print(f"\ncannot connect ({e}); retrying in {delay:.0f} s", flush=True)
            await asyncio.sleep(delay)
            delay = min(BACKOFF_MAX, delay * 2)
    finally:
        try:
            frames.close()  # stops ffmpeg
        except ValueError:  # still running in the reader thread; ffmpeg ends with our process
            pass


def main() -> None:
    ap = argparse.ArgumentParser(prog="python -m server.replay")
    ap.add_argument("video", type=Path)
    ap.add_argument("--url", default="ws://localhost:8000/ws/camera")
    ap.add_argument("--fps", type=float, default=1.0)
    ap.add_argument("--loop", action="store_true")
    ap.add_argument("--start", type=float, default=0.0, help="start offset in seconds")
    ap.add_argument("--select", metavar="LESSON_ID", help="send select_lesson over /ws/ui first")
    ap.add_argument("--no-hello", action="store_true", help="send binary frames only, no hello")
    a = ap.parse_args()
    if not a.video.is_file():
        sys.exit(f"no such file: {a.video}")
    if a.fps <= 0:
        sys.exit("--fps must be above 0")
    try:
        ffmpeg_bin()
    except RuntimeError as e:
        sys.exit(str(e))

    def on_term(*_):
        raise KeyboardInterrupt

    signal.signal(signal.SIGTERM, on_term)  # stop the same clean way as Ctrl+C
    try:
        code = asyncio.run(run(a))
    except KeyboardInterrupt:
        print("\nstopped", flush=True)
        code = 0
    sys.exit(code)


if __name__ == "__main__":
    main()
