"""Camera snapshot/clip capture over RTSP.

Cameras are re-published as local RTSP streams by a separate always-on gateway
(miloco -> MediaMTX), e.g. ``rtsp://127.0.0.1:8554/camera_1``. This module only
pulls from that RTSP URL with ffmpeg, so the MCP server stays free of any camera
SDK, cloud OAuth or native dependency.
"""

import asyncio
import os
import tempfile
import time

from .mihome.base import DeviceError

FFMPEG = os.getenv("MCP_XIAOMI_FFMPEG", "ffmpeg")
CLIP_DIR = os.getenv("MCP_XIAOMI_CLIP_DIR", tempfile.gettempdir())


async def _run(args: list[str], timeout: float) -> tuple[int, bytes, bytes]:
    proc = await asyncio.create_subprocess_exec(
        *args,
        stdin=asyncio.subprocess.DEVNULL,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    try:
        out, err = await asyncio.wait_for(proc.communicate(), timeout=timeout)
    except asyncio.TimeoutError:
        proc.kill()
        raise
    return proc.returncode or 0, out, err


async def snapshot(camera_id: str, rtsp_url: str, timeout: float = 20.0) -> bytes:
    """Grab a single clean JPEG frame from the camera's RTSP stream.

    Selects the first key frame (I-frame) rather than the first decodable frame,
    so the picture is fully decoded — grabbing frame 1 blindly on an HEVC stream
    often lands mid-GOP and yields a gray/garbled image.
    """
    path = os.path.join(tempfile.gettempdir(), f"xiaomi_snap_{camera_id}_{int(time.time())}.jpg")
    args = [
        FFMPEG, "-nostdin", "-loglevel", "error",
        "-rtsp_transport", "tcp", "-i", rtsp_url,
        "-vf", "select=eq(pict_type\\,I)", "-frames:v", "1", "-vsync", "0",
        "-q:v", "2", "-y", path,
    ]
    try:
        rc, _out, err = await _run(args, timeout)
    except asyncio.TimeoutError:
        raise DeviceError(camera_id, f"Timeout capturing snapshot from {rtsp_url}.")
    except FileNotFoundError:
        raise DeviceError(camera_id, f"ffmpeg not found (set MCP_XIAOMI_FFMPEG). Tried '{FFMPEG}'.")
    if rc != 0 or not os.path.exists(path):
        raise DeviceError(camera_id, f"ffmpeg snapshot failed: {err.decode(errors='replace')[-300:]}")
    try:
        with open(path, "rb") as f:
            return f.read()
    finally:
        try:
            os.remove(path)
        except OSError:
            pass


async def clip(camera_id: str, rtsp_url: str, seconds: int, timeout: float | None = None) -> dict:
    """Record ``seconds`` of video from the RTSP stream into an MP4 (no re-encode)."""
    seconds = max(1, min(int(seconds), 300))
    if timeout is None:
        timeout = seconds + 30
    out_path = os.path.join(CLIP_DIR, f"xiaomi_clip_{camera_id}_{int(time.time())}.mp4")
    args = [
        FFMPEG, "-nostdin", "-loglevel", "error",
        "-rtsp_transport", "tcp", "-i", rtsp_url,
        "-t", str(seconds), "-c", "copy", "-movflags", "+faststart", "-y", out_path,
    ]
    try:
        rc, _out, err = await _run(args, timeout)
    except asyncio.TimeoutError:
        raise DeviceError(camera_id, f"Timeout recording clip from {rtsp_url}.")
    except FileNotFoundError:
        raise DeviceError(camera_id, f"ffmpeg not found (set MCP_XIAOMI_FFMPEG). Tried '{FFMPEG}'.")
    if rc != 0 or not os.path.exists(out_path):
        raise DeviceError(camera_id, f"ffmpeg clip failed: {err.decode(errors='replace')[-300:]}")
    return {"path": out_path, "seconds": seconds, "bytes": os.path.getsize(out_path)}
