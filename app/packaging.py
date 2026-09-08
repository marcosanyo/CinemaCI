"""Cinema CI — Master Film Packaging & Stitching Module.

Concatenates validated shot video clips into a single continuous master film
when a build passes all Quality Gate checks.
"""

from __future__ import annotations

import logging
import os

import av

from app.models import ShotArtifact

logger = logging.getLogger(__name__)


def stitch_build_shots(build_dir: str, shot_artifacts: list[ShotArtifact]) -> str | None:
    """Stitches validated shot video artifacts into a single master MP4 film using PyAV.

    Args:
        build_dir: Directory where the build's shots reside.
        shot_artifacts: List of shot artifacts in chronological order.

    Returns:
        Path to the stitched master film MP4, or None if stitching failed.
    """
    valid_paths = []
    for s in shot_artifacts:
        if s.video_path and os.path.exists(s.video_path):
            valid_paths.append(s.video_path)

    if not valid_paths:
        logger.warning(f"No valid shot video files found to stitch in {build_dir}")
        return None

    out_path = os.path.join(build_dir, "final_film.mp4")
    logger.info(f"Packaging master film: stitching {len(valid_paths)} shots into {out_path}...")

    try:
        first_in = av.open(valid_paths[0])
        in_v = first_in.streams.video[0]
        w, h = in_v.width, in_v.height
        first_in.close()

        out_c = av.open(out_path, mode="w")
        out_v = out_c.add_stream("h264", rate=24)
        out_v.width = w
        out_v.height = h
        out_v.pix_fmt = "yuv420p"

        frame_idx = 0
        for path in valid_paths:
            inc = av.open(path)
            for frame in inc.decode(video=0):
                img = frame.to_ndarray(format="rgb24")
                out_frame = av.VideoFrame.from_ndarray(img, format="rgb24")
                out_frame.pts = frame_idx
                frame_idx += 1
                for packet in out_v.encode(out_frame):
                    out_c.mux(packet)
            inc.close()

        for packet in out_v.encode():
            out_c.mux(packet)
        out_c.close()

        duration_sec = round(frame_idx / 24.0, 2)
        logger.info(f"Master film packaging complete: {out_path} ({duration_sec}s, {os.path.getsize(out_path)} bytes)")
        return out_path

    except Exception as e:
        logger.error(f"Failed to stitch master film in {build_dir}: {e}")
        return None
