"""Cinema CI — FFmpeg discovery utility.

Finds ffmpeg binary from system PATH, imageio_ffmpeg, or common installation paths.
"""

from __future__ import annotations

import shutil


def find_ffmpeg() -> str:
    """Finds the ffmpeg binary on PATH or via imageio_ffmpeg."""
    path = shutil.which("ffmpeg")
    if path:
        return path
    try:
        import imageio_ffmpeg
        exe = imageio_ffmpeg.get_ffmpeg_exe()
        if exe:
            return exe
    except Exception:
        pass
    return "ffmpeg"

