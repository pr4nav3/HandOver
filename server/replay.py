"""Stream a video file to /ws/camera as if it were a live camera.

    python -m server.replay VIDEO.mp4 [--url ws://localhost:8000/ws/camera]
        [--fps 1] [--loop] [--start SEC] [--select LESSON_ID]

Frames are decoded with ffmpeg and sent in real time (one every 1/fps seconds).
--select first sends select_lesson over /ws/ui on the same host.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import subprocess
import sys
import time
from pathlib import Path
from typing import Iterator
from urllib.parse import urlsplit, urlunsplit

import websockets

SOI, EOI = b"\xff\xd8", b"\xff\xd9"


def jpeg_frames(video: Path, fps: float, start: float) -> Iterator[bytes]:
    """Yield JPEG frames from ffmpeg's MJPEG pipe, split on start/end markers."""
    cmd = ["ffmpeg", "-hide_banner", "-loglevel", "error"]
    if start > 0:
        cmd += ["-ss", str(start)]
    cmd += ["-i", str(video), "-vf", f"fps={fps},scale=1280:-2", "-f", "image2pipe",
            "-vcodec", "mjpeg", "-q:v", "5", "-"]
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE)
    buf = b""
    try:
        while True:
            chunk = proc.stdout.read(65536)
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


def ui_url(camera_url: str) -> str:
    p = urlsplit(camera_url)
    return urlunsplit((p.scheme, p.netloc, "/ws/ui", "", ""))


async def select_lesson(camera_url: str, lesson_id: str) -> None:
    async with websockets.connect(ui_url(camera_url), max_size=None) as ws:
        await ws.send(json.dumps({"type": "select_lesson", "id": lesson_id}))
        # Wait for the state that confirms the selection (or an error).
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            msg = await asyncio.wait_for(ws.recv(), deadline - time.monotonic())
            if isinstance(msg, str):
                data = json.loads(msg)
                if data.get("type") == "error":
                    sys.exit(f"select_lesson failed: {data.get('message')}")
                if data.get("type") == "state" and data.get("lesson_id") == lesson_id:
                    print(f"selected {lesson_id} ({data.get('total')} steps)")
                    return
        sys.exit("select_lesson: no confirmation from server")


async def run(a: argparse.Namespace) -> None:
    if a.select:
        await select_lesson(a.url, a.select)
    period = 1.0 / a.fps
    sent = 0
    while True:
        try:
            async with websockets.connect(a.url, max_size=None) as ws:
                print(f"connected to {a.url}")
                while True:
                    next_t = time.monotonic()
                    for frame in jpeg_frames(a.video, a.fps, a.start):
                        await ws.send(frame)
                        sent += 1
                        print(f"\rframes sent: {sent}", end="", flush=True)
                        next_t += period
                        await asyncio.sleep(max(0.0, next_t - time.monotonic()))
                    if not a.loop:
                        print()
                        return
        except (OSError, websockets.ConnectionClosed) as e:
            print(f"\nconnection lost ({e}); retrying in 2 s")
            await asyncio.sleep(2)


def main() -> None:
    ap = argparse.ArgumentParser(prog="python -m server.replay")
    ap.add_argument("video", type=Path)
    ap.add_argument("--url", default="ws://localhost:8000/ws/camera")
    ap.add_argument("--fps", type=float, default=1.0)
    ap.add_argument("--loop", action="store_true")
    ap.add_argument("--start", type=float, default=0.0, help="start offset in seconds")
    ap.add_argument("--select", metavar="LESSON_ID", help="send select_lesson over /ws/ui first")
    a = ap.parse_args()
    if not a.video.is_file():
        sys.exit(f"no such file: {a.video}")
    try:
        asyncio.run(run(a))
    except KeyboardInterrupt:
        print()


if __name__ == "__main__":
    main()
