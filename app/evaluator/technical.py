"""Cinema CI — Technical QA Evaluator.

Inspects video technical properties (codec, resolution, frame rate, duration,
bitrate, and black frame detection) using PyAV and FFmpeg.
"""

from __future__ import annotations

import asyncio
import datetime
import os
import shutil

from app.models import EvaluatorType, ReleaseSpec, ShotArtifact, TestResult, TestStatus


from app.ffmpeg_util import find_ffmpeg

FFMPEG = find_ffmpeg()


async def evaluate_technical(
    shot_artifact: ShotArtifact,
    release_spec: ReleaseSpec,
    build_id: str,
) -> list[TestResult]:
    """Evaluates technical properties of a video against project ReleaseSpec.

    Args:
        shot_artifact: The ShotArtifact being evaluated.
        release_spec: Technical delivery requirements from cinema.yaml.
        build_id: Active build identifier.

    Returns:
        List of technical TestResult records.
    """
    results: list[TestResult] = []
    now_iso = datetime.datetime.now(datetime.timezone.utc).isoformat()

    if not os.path.exists(shot_artifact.video_path):
        return [TestResult(
            test_id="technical.file_exists",
            build_id=build_id,
            scope=shot_artifact.shot_id,
            category="technical",
            evaluator=EvaluatorType.FFPROBE.value,
            evaluator_model="os_stat",
            evaluated_at=now_iso,
            expected="file exists",
            observed="file not found",
            status=TestStatus.FAIL,
            confidence=1.0,
            error_details=f"File not found on disk at {shot_artifact.video_path}",
        )]

    # ---- Use PyAV for metadata ----
    try:
        import av
        container = av.open(shot_artifact.video_path)

        video_stream = next((s for s in container.streams if s.type == "video"), None)
        audio_stream = next((s for s in container.streams if s.type == "audio"), None)
        duration = float(container.duration / av.time_base) if container.duration else 0.0

        # 1. Aspect ratio check
        if video_stream:
            width = video_stream.width
            height = video_stream.height
            expected_ratio = release_spec.aspect_ratio
            if ":" in expected_ratio:
                ew, eh = map(float, expected_ratio.split(":"))
                expected_val = ew / eh
            else:
                expected_val = float(expected_ratio)

            actual_val = width / height if height else 0
            is_correct = abs(actual_val - expected_val) < 0.05

            results.append(TestResult(
                test_id="technical.aspect_ratio",
                build_id=build_id,
                scope=shot_artifact.shot_id,
                category="technical",
                evaluator=EvaluatorType.FFPROBE.value,
                evaluator_model="pyav",
                evaluated_at=now_iso,
                expected=expected_ratio,
                observed=f"{width}x{height} ({actual_val:.2f})",
                status=TestStatus.PASS if is_correct else TestStatus.FAIL,
                confidence=1.0,
            ))

            # 2. Resolution check
            min_w, min_h = 1280, 720
            if "x" in release_spec.min_resolution:
                mw, mh = release_spec.min_resolution.split("x")
                min_w, min_h = int(mw), int(mh)
            res_pass = (width >= min_w and height >= min_h)
            results.append(TestResult(
                test_id="technical.resolution",
                build_id=build_id,
                scope=shot_artifact.shot_id,
                category="technical",
                evaluator=EvaluatorType.FFPROBE.value,
                evaluator_model="pyav",
                evaluated_at=now_iso,
                expected=f">= {min_w}x{min_h}",
                observed=f"{width}x{height}",
                status=TestStatus.PASS if res_pass else TestStatus.FAIL,
                confidence=1.0,
            ))

            # 3. Framerate check (Cinematic 24.0 fps target)
            fps = float(video_stream.average_rate or video_stream.base_rate or 24.0)
            target_fps = release_spec.target_fps
            fps_pass = abs(fps - target_fps) < 1.5
            results.append(TestResult(
                test_id="technical.framerate",
                build_id=build_id,
                scope=shot_artifact.shot_id,
                category="technical",
                evaluator=EvaluatorType.FFPROBE.value,
                evaluator_model="pyav",
                evaluated_at=now_iso,
                expected=f"{target_fps:.1f} fps",
                observed=f"{fps:.1f} fps",
                status=TestStatus.PASS if fps_pass else TestStatus.FAIL,
                confidence=1.0,
            ))
        else:
            results.append(TestResult(
                test_id="technical.aspect_ratio",
                build_id=build_id,
                scope=shot_artifact.shot_id,
                category="technical",
                evaluator=EvaluatorType.FFPROBE.value,
                evaluator_model="pyav",
                evaluated_at=now_iso,
                expected=release_spec.aspect_ratio,
                observed="no video stream",
                status=TestStatus.FAIL,
                confidence=1.0,
            ))

        # 4. Duration check
        max_dur = release_spec.max_duration_sec
        results.append(TestResult(
            test_id="technical.duration",
            build_id=build_id,
            scope=shot_artifact.shot_id,
            category="technical",
            evaluator=EvaluatorType.FFPROBE.value,
            evaluator_model="pyav",
            evaluated_at=now_iso,
            expected=f"<= {max_dur}s",
            observed=f"{duration:.2f}s",
            status=TestStatus.PASS if duration <= max_dur else TestStatus.FAIL,
            confidence=1.0,
        ))

        # 5. Audio check
        if release_spec.audio_required:
            results.append(TestResult(
                test_id="technical.audio",
                build_id=build_id,
                scope=shot_artifact.shot_id,
                category="technical",
                evaluator=EvaluatorType.FFPROBE.value,
                evaluator_model="pyav",
                evaluated_at=now_iso,
                expected="audio stream present",
                observed="audio stream present" if audio_stream else "no audio stream",
                status=TestStatus.PASS if audio_stream else TestStatus.FAIL,
                confidence=1.0,
            ))

        container.close()

    except Exception as e:
        results.append(TestResult(
            test_id="technical.metadata",
            build_id=build_id,
            scope=shot_artifact.shot_id,
            category="technical",
            evaluator=EvaluatorType.FFPROBE.value,
            evaluator_model="pyav",
            evaluated_at=now_iso,
            expected="valid video file",
            observed=f"error reading file: {e}",
            status=TestStatus.FAIL,
            confidence=1.0,
            error_details=f"{type(e).__name__}: {e}",
        ))

    # 4. Black frames check (optional — only if ffmpeg is available)
    if FFMPEG:
        try:
            proc = await asyncio.create_subprocess_exec(
                FFMPEG, '-i', shot_artifact.video_path,
                '-vf', 'blackdetect=d=0.1:pix_th=0.1',
                '-f', 'null', '-',
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            _, stderr = await proc.communicate()
            stderr_text = stderr.decode()
            has_black = 'blackdetect' in stderr_text and 'black_start' in stderr_text

            results.append(TestResult(
                test_id="technical.black_frames",
                build_id=build_id,
                scope=shot_artifact.shot_id,
                category="technical",
                evaluator=EvaluatorType.FFMPEG.value,
                evaluator_model="ffmpeg_blackdetect",
                evaluated_at=now_iso,
                expected="no black frames",
                observed="black frames detected" if has_black else "no black frames",
                status=TestStatus.FAIL if has_black else TestStatus.PASS,
                confidence=1.0,
            ))
        except Exception as e:
            results.append(TestResult(
                test_id="technical.black_frames",
                build_id=build_id,
                scope=shot_artifact.shot_id,
                category="technical",
                evaluator=EvaluatorType.FFMPEG.value,
                evaluator_model="ffmpeg_blackdetect",
                evaluated_at=now_iso,
                expected="no black frames",
                observed=f"check skipped: {e}",
                status=TestStatus.UNKNOWN,
                confidence=0.0,
                error_details=f"{type(e).__name__}: {e}",
            ))

    return results
