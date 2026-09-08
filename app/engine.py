"""Cinema CI — Build Engine.

Orchestrates incremental generation, runtime creative lineage, QA, and release.
The core invariant is that runtime lineage is causal: when Gemini selects a shot
keyframe for the poster, the poster artifact is actually materialized from that
selected generated shot rather than from an unrelated fixture.
"""

from __future__ import annotations

import asyncio
import datetime
import hashlib
import logging
import os
import shutil
import subprocess
import time
from typing import Any

from app.evaluator.creative import evaluate_creative, evaluate_cross_shot_consistency
from app.evaluator.regression import detect_regressions
from app.evaluator.technical import evaluate_technical
from app.generator.base import VideoGenerator
from app.model_config import GEMINI_MODEL
from app.models import (
    Build,
    BuildLogEntry,
    BuildStatus,
    CinemaContract,
    DeliverableArtifact,
    ReleaseRecord,
    ShotArtifact,
    TestResult,
    TestStatus,
)
from app.store.artifact_base import ArtifactStore
from app.store.metadata_base import MetadataStore

logger = logging.getLogger(__name__)

_builds: dict[str, Build] = {}
_releases: dict[str, ReleaseRecord] = {}
_canceled_build_ids: set[str] = set()
_metadata_store: MetadataStore | None = None
_artifact_store: ArtifactStore | None = None


def _strict_mode() -> bool:
    """Returns True if strict mode is active."""
    if os.getenv("MOCK_MODE", "false").lower() in ("true", "1", "yes"):
        return False
    return (
        os.getenv("STRICT_MODE", "false").lower() in ("true", "1")
        or os.getenv("CINEMA_STRICT_MODE", "0").lower() in ("true", "1")
    )


def get_metadata_store() -> MetadataStore:
    global _metadata_store
    if _metadata_store is None:
        from app.store import create_metadata_store
        _metadata_store = create_metadata_store()
    return _metadata_store


def get_artifact_store() -> ArtifactStore:
    global _artifact_store
    if _artifact_store is None:
        from app.store import create_artifact_store
        _artifact_store = create_artifact_store()
    return _artifact_store


def _compute_sha256(path: str) -> str:
    if not os.path.exists(path):
        return ""
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while True:
            chunk = f.read(65536)
            if not chunk:
                break
            h.update(chunk)
    return h.hexdigest()[:16]


def _log_build(
    build: Build,
    level: str,
    stage: str,
    message: str,
    shot_id: str | None = None,
    details: dict | None = None,
) -> None:
    entry = BuildLogEntry(
        level=level,
        stage=stage,
        shot_id=shot_id,
        message=message,
        details=details,
    )
    build.logs.append(entry)
    log_func = getattr(logger, level.lower(), logger.info)
    prefix = f"Build {build.build_id} [{stage}" + (f":{shot_id}" if shot_id else "") + "]"
    log_func(f"{prefix} {message}")
    try:
        get_metadata_store().save_build(build)
    except Exception:
        pass


def save_builds_to_disk() -> None:
    store = get_metadata_store()
    for build in _builds.values():
        store.save_build(build)


def load_builds_from_disk() -> None:
    try:
        for build in get_metadata_store().list_builds():
            _builds[build.build_id] = build
        logger.info("Loaded %d builds from MetadataStore", len(_builds))
    except Exception as exc:
        logger.warning("Could not load builds from MetadataStore: %s", exc)


def save_releases_to_disk() -> None:
    store = get_metadata_store()
    for release in _releases.values():
        store.save_release(release)


def load_releases_from_disk() -> None:
    try:
        for release in get_metadata_store().list_releases():
            _releases[release.release_id] = release
        logger.info("Loaded %d releases from MetadataStore", len(_releases))
    except Exception as exc:
        logger.warning("Could not load releases from MetadataStore: %s", exc)


try:
    load_builds_from_disk()
    load_releases_from_disk()
except Exception as _init_err:
    logger.warning("Initial store warm-up warning: %s", _init_err)


def cancel_build(build_id: str) -> Build | None:
    """Cancels execution of a queued or running build."""
    build = get_build(build_id)
    if not build:
        return None
    _canceled_build_ids.add(build_id)
    build.status = BuildStatus.CANCELED
    build.error_summary = "Build execution canceled by user."
    _log_build(build, "WARNING", "CANCEL", "Build execution canceled by user.")
    get_metadata_store().save_build(build)
    return build


def get_next_build_id() -> str:
    """Generates the next sequential build ID."""
    return get_metadata_store().get_next_build_id()


def get_next_release_id() -> str:
    """Generates the next sequential release ID."""
    return get_metadata_store().get_next_release_id()


def get_build(build_id: str) -> Build | None:
    """Retrieves a build by ID from cache or persistent MetadataStore."""
    if build_id.startswith("test_") and build_id in _builds:
        return _builds[build_id]
    stored = get_metadata_store().get_build(build_id)
    if stored:
        _builds[build_id] = stored
        return stored
    return _builds.get(build_id)


def get_latest_build(project_id: str | None = None) -> Build | None:
    """Returns the most recent build."""
    builds = get_all_builds(project_id)
    return builds[0] if builds else None


def get_all_builds(project_id: str | None = None) -> list[Build]:
    """Lists all builds sorted in reverse chronological order."""
    stored = get_metadata_store().list_builds(project_id)
    for build in stored:
        _builds[build.build_id] = build
    builds = [b for b in stored if not b.build_id.startswith("test_")]
    if project_id:
        builds = [b for b in builds if b.project_id == project_id]
    return sorted(builds, key=lambda b: b.created_at, reverse=True)


def delete_build(build_id: str) -> bool:
    """Deletes a build from in-memory cache and persistent metadata store."""
    if build_id in _builds:
        del _builds[build_id]
    return get_metadata_store().delete_build(build_id)


def get_latest_passed_build(project_id: str) -> Build | None:
    """Finds the most recent successful build that cleared QA quality gates."""
    for build in get_all_builds(project_id):
        if build.status in (
            BuildStatus.PASSED,
            BuildStatus.RELEASE_READY,
            BuildStatus.APPROVED_FOR_RELEASE,
            BuildStatus.RELEASED,
        ) and build.release_ready:
            return build
    return None


def get_all_releases(project_id: str | None = None) -> list[ReleaseRecord]:
    """Lists all release records sorted in reverse chronological order."""
    stored = get_metadata_store().list_releases(project_id)
    for release in stored:
        _releases[release.release_id] = release
    releases = list(_releases.values())
    if project_id:
        releases = [r for r in releases if r.project_id == project_id]
    return sorted(releases, key=lambda r: r.released_at, reverse=True)


def get_release(release_id: str) -> ReleaseRecord | None:
    """Retrieves a release record by ID."""
    if release_id in _releases:
        return _releases[release_id]
    release = get_metadata_store().get_release(release_id)
    if release:
        _releases[release_id] = release
    return release


def promote_build_to_release(build_id: str, notes: str = "") -> ReleaseRecord:
    build = get_build(build_id)
    if not build:
        raise ValueError(f"Build {build_id} not found")
    if not build.release_ready:
        raise ValueError(
            f"Cannot release build {build_id}: quality gate is not release-ready "
            f"(status: {build.status.value})."
        )

    store = get_metadata_store()
    release_id = store.get_next_release_id()
    now = datetime.datetime.now(datetime.timezone.utc).isoformat()
    film_path = build.master_film_path or os.path.join("storage", build_id, "final_film.mp4")
    release = ReleaseRecord(
        release_id=release_id,
        build_id=build_id,
        project_id=build.project_id,
        film_path=film_path,
        baseline_release_id=build.baseline_build_id,
        rebuilt_count=build.operations_rebuilt,
        reused_count=build.operations_reused,
        avoided_operations=build.operations_avoided,
        savings_percent=build.savings_percent,
        approved_at=now,
        released_at=now,
        notes=notes or f"Promoted build {build_id} to production release",
    )
    _releases[release_id] = release
    store.save_release(release)
    build.status = BuildStatus.RELEASED
    build.is_released = True
    _log_build(build, "INFO", "RELEASE", f"Promoted to production release: {release_id}")
    store.save_build(build)
    try:
        from app.telemetry import emit_log
        emit_log(
            "release_promoted",
            {
                "release_id": release_id,
                "build_id": build_id,
                "project_id": build.project_id,
                "film_path": film_path,
            },
        )
    except Exception as exc:
        logger.warning("Telemetry emit failed: %s", exc)
    return release


def _poster_font_path(bold: bool = True) -> str | None:
    """Resolve a DejaVu TTF bundled with matplotlib (no system fonts required)."""
    try:
        import matplotlib
        base = os.path.join(os.path.dirname(matplotlib.__file__), "mpl-data", "fonts", "ttf")
        for name in (("DejaVuSans-Bold.ttf" if bold else "DejaVuSans.ttf"), "DejaVuSans.ttf"):
            candidate = os.path.join(base, name)
            if os.path.exists(candidate):
                return candidate
    except Exception:
        pass
    return None


def _compose_theatrical_poster(keyframe_path: str, title: str) -> None:
    """Burn a theatrical title treatment onto the extracted keyframe (deterministic).

    Turns the raw selected frame into a legible key visual: 1280x720 cover crop,
    bottom scrim for legibility, tracked-out title, rule line, production credit.
    Pure Pillow + bundled DejaVu; no network, no model calls.
    """
    from PIL import Image, ImageDraw, ImageFont, ImageOps

    title_text = (title or "Untitled").strip().upper()
    img = Image.open(keyframe_path).convert("RGB")
    img = ImageOps.fit(img, (1280, 720), Image.LANCZOS)

    # Bottom scrim: transparent -> black for title legibility.
    scrim = Image.new("L", (1, 720))
    for y in range(720):
        if y < 400:
            scrim.putpixel((0, y), 0)
        else:
            scrim.putpixel((0, y), int(200 * (y - 400) / 320))
    scrim = scrim.resize((1280, 720))
    black = Image.new("RGB", (1280, 720), (0, 0, 0))
    img = Image.composite(black, img, scrim)

    draw = ImageDraw.Draw(img)
    font_bold = _poster_font_path(bold=True)
    font_regular = _poster_font_path(bold=False)

    def tracked_text_width(text: str, font, tracking: int) -> int:
        widths = [draw.textlength(ch, font=font) for ch in text]
        return int(sum(widths) + tracking * max(0, len(text) - 1))

    try:
        title_font = ImageFont.truetype(font_bold, 76) if font_bold else ImageFont.load_default()
        credit_font = ImageFont.truetype(font_regular, 24) if font_regular else ImageFont.load_default()
    except Exception:
        title_font = ImageFont.load_default()
        credit_font = ImageFont.load_default()

    # Title with manual per-character shadow pass.
    for dx, dy, fill in ((3, 3, (0, 0, 0)), (0, 0, (245, 240, 230))):
        total = tracked_text_width(title_text, title_font, 10)
        x = 640 - total / 2 + dx
        for ch in title_text:
            draw.text((x, 548 + dy), ch, font=title_font, fill=fill)
            x += draw.textlength(ch, font=title_font) + 10

    # Gold rule + production credit.
    draw.rectangle([490, 640, 790, 643], fill=(201, 162, 75))
    credit = "A  C I N E M A  C I  P R O D U C T I O N"
    cw = draw.textlength(credit, font=credit_font)
    draw.text((640 - cw / 2, 652), credit, font=credit_font, fill=(201, 162, 75))

    img.save(keyframe_path, "JPEG", quality=92)


def _materialize_poster_from_selected_shot(
    source_video: str, poster_path: str, title: str = "The Blue Envelope"
) -> None:
    """Create a poster key-visual MP4 from the actual selected generated shot.

    This makes the observed Shot -> Poster runtime edge causal and auditable. We extract
    a real frame from the selected shot, compose a deterministic theatrical title
    treatment onto that exact frame with Pillow, and encode a short key-visual clip. In
    strict mode any failure is fatal. Non-strict development mode may copy the selected
    source video as a fallback, which still preserves the causal dependency.
    """
    if not source_video or not os.path.exists(source_video):
        raise RuntimeError(f"Selected poster source video does not exist: {source_video}")

    keyframe_path = os.path.splitext(poster_path)[0] + "_selected_keyframe.jpg"
    from app.ffmpeg_util import find_ffmpeg
    ffmpeg_bin = find_ffmpeg()
    try:
        # 1. Try PyAV first for keyframe extraction
        keyframe_extracted = False
        try:
            import av
            with av.open(source_video) as container:
                if container.streams.video:
                    stream = container.streams.video[0]
                    for frame in container.decode(stream):
                        frame.to_image().save(keyframe_path, "JPEG")
                        keyframe_extracted = os.path.exists(keyframe_path) and os.path.getsize(keyframe_path) > 0
                        break
        except Exception:
            keyframe_extracted = False

        if not keyframe_extracted:
            subprocess.run(
                [
                    ffmpeg_bin, "-y", "-loglevel", "error",
                    "-ss", "0.5", "-i", source_video,
                    "-frames:v", "1", "-q:v", "2", keyframe_path,
                ],
                check=True,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.PIPE,
                timeout=30,
            )
        # Theatrical title treatment on the exact selected frame (deterministic).
        _compose_theatrical_poster(keyframe_path, title)
        subprocess.run(
            [
                ffmpeg_bin, "-y", "-loglevel", "error",
                "-loop", "1", "-i", keyframe_path,
                "-t", "1.5", "-r", "24",
                "-vf", "scale=1280:720:force_original_aspect_ratio=decrease,pad=1280:720:(ow-iw)/2:(oh-ih)/2",
                "-c:v", "libx264", "-pix_fmt", "yuv420p", poster_path,
            ],
            check=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
            timeout=45,
        )
        if not os.path.exists(poster_path) or os.path.getsize(poster_path) == 0:
            raise RuntimeError("ffmpeg produced an empty poster artifact")
    except Exception as exc:
        mock_mode = os.getenv("MOCK_MODE", "false").lower() in ("true", "1", "yes")
        if not mock_mode:
            raise RuntimeError(
                f"Production/Strict Mode: failed to materialize poster from selected shot {source_video}: {exc}. "
                "Fallback copy is strictly prohibited outside MOCK_MODE."
            ) from exc
        logger.info("MOCK_MODE active: Using direct file copy for poster artifact fallback: %s", exc)
        shutil.copy2(source_video, poster_path)
    finally:
        try:
            if os.path.exists(keyframe_path):
                os.remove(keyframe_path)
        except OSError:
            pass


class BuildEngine:
    """Orchestrates incremental generation, runtime lineage, QA, and delivery."""

    def __init__(
        self,
        contract: CinemaContract,
        generator: VideoGenerator,
        storage_path: str = "storage",
        artifact_store: ArtifactStore | None = None,
        metadata_store: MetadataStore | None = None,
    ) -> None:
        self.contract = contract
        self.generator = generator
        self.storage_path = storage_path
        self.artifact_store = artifact_store or get_artifact_store()
        self.metadata_store = metadata_store or get_metadata_store()

    async def run_build(
        self,
        build_id: str,
        baseline_build: Build | None = None,
        shots_to_regenerate: list[str] | None = None,
        impact_plan: Any | None = None,
    ) -> Build:
        start_time = time.time()
        build = get_build(build_id)
        if not build:
            build = Build(build_id=build_id, project_id=self.contract.project.id)
            _builds[build_id] = build
            self.metadata_store.save_build(build)

        is_incremental = bool(impact_plan or shots_to_regenerate)
        all_ops = [s.id for s in self.contract.shots] + ["poster"]
        build.operations_total = len(all_ops)

        if not is_incremental:
            baseline_build = None
            build.baseline_build_id = None
            rebuild_set = {s.id for s in self.contract.shots} | {"poster"}
            reuse_set: set[str] = set()
        else:
            if baseline_build is None:
                baseline_build = get_latest_passed_build(self.contract.project.id)
            build.baseline_build_id = baseline_build.build_id if baseline_build else None
            if impact_plan:
                plan_dict = impact_plan.model_dump() if hasattr(impact_plan, "model_dump") else impact_plan
                rebuild_set = set(plan_dict.get("rebuild", []))
                reuse_set = set(plan_dict.get("reuse", []))
            elif shots_to_regenerate:
                rebuild_set = set(shots_to_regenerate)
                reuse_set = {s.id for s in self.contract.shots if s.id not in rebuild_set}
            else:
                rebuild_set, reuse_set = set(), set()

        build.status = BuildStatus.BUILDING
        if impact_plan:
            build.impact_plan = impact_plan.model_dump() if hasattr(impact_plan, "model_dump") else impact_plan
        self.metadata_store.save_build(build)

        _log_build(
            build,
            "INFO",
            "SETUP",
            f"Build initialized (baseline: {build.baseline_build_id or 'none'}, incremental: {is_incremental})",
        )

        scratch_build_dir = os.path.join(self.storage_path, build_id)
        os.makedirs(scratch_build_dir, exist_ok=True)

        from app.telemetry import emit_log, get_tracer
        tracer = get_tracer()
        emit_log(
            "incremental_build_started",
            {
                "build_id": build_id,
                "baseline_build_id": build.baseline_build_id,
                "rebuild_list": list(rebuild_set),
                "reuse_list": list(reuse_set),
            },
        )

        with tracer.start_as_current_span(
            "cinema.build",
            attributes={
                "cinema.project_id": self.contract.project.id,
                "cinema.build_id": build_id,
                "cinema.baseline_build_id": build.baseline_build_id or "none",
                "cinema.is_incremental": is_incremental,
            },
        ) as build_span:
            ctx = build_span.get_span_context()
            if ctx.is_valid:
                build.trace_id = f"{ctx.trace_id:032x}"
                build.span_id = f"{ctx.span_id:016x}"
                _log_build(build, "INFO", "SETUP", f"OpenTelemetry trace: trace_id={build.trace_id}")

            try:
                build.shots = []
                build.deliverables = []
                build.test_results = []

                # Shots
                for shot_spec in self.contract.shots:
                    if build_id in _canceled_build_ids:
                        build.status = BuildStatus.CANCELED
                        build.error_summary = "Build execution canceled by user."
                        self.metadata_store.save_build(build)
                        return build

                    output_path = os.path.join(scratch_build_dir, f"{shot_spec.id}.mp4")
                    logical_path = f"projects/{self.contract.project.id}/builds/{build_id}/{shot_spec.id}.mp4"
                    is_reuse = bool(is_incremental and baseline_build and shot_spec.id in reuse_set)
                    if is_reuse:
                        base_logical = f"projects/{self.contract.project.id}/builds/{baseline_build.build_id}/{shot_spec.id}.mp4"
                        if self.artifact_store.exists(base_logical):
                            self.artifact_store.copy(base_logical, logical_path)
                            old_sha = self.artifact_store.sha256(base_logical)
                            sha = self.artifact_store.sha256(logical_path)
                            if old_sha != sha:
                                raise RuntimeError(f"SHA-256 mismatch while reusing {shot_spec.id}")
                            self.artifact_store.get_file(logical_path, output_path)
                        else:
                            baseline_shot = next((s for s in baseline_build.shots if s.shot_id == shot_spec.id), None)
                            if not baseline_shot or not os.path.exists(baseline_shot.video_path):
                                if _strict_mode():
                                    raise RuntimeError(f"Strict Mode: baseline shot missing: {shot_spec.id}")
                                fixture = f"fixtures/blue-envelope/{shot_spec.id}.mp4"
                                if os.path.exists(fixture):
                                    shutil.copy2(fixture, output_path)
                                else:
                                    with open(output_path, "wb") as f:
                                        f.write(b"reused_fixture_bytes")
                            else:
                                shutil.copy2(baseline_shot.video_path, output_path)
                            self.artifact_store.put_file(output_path, logical_path)
                            sha = self.artifact_store.sha256(logical_path)

                        build.shots.append(
                            ShotArtifact(
                                shot_id=shot_spec.id,
                                video_path=output_path,
                                prompt_used=shot_spec.description,
                                version=1,
                                sha256=sha,
                                status="reused_from_baseline",
                                reused_from_build=baseline_build.build_id,
                                model_used="reused",
                                generated_at=datetime.datetime.now(datetime.timezone.utc).isoformat(),
                            )
                        )
                        with tracer.start_as_current_span(
                            f"cinema.reuse.{shot_spec.id}",
                            attributes={
                                "cinema.shot_id": shot_spec.id,
                                "cinema.output.sha256": sha,
                                "cinema.status": "reused_from_baseline",
                            },
                        ):
                            _log_build(build, "INFO", "REUSE", f"BYTE IDENTICAL REUSE: {shot_spec.id} (SHA256: {sha})")
                        emit_log(
                            "artifact_reused",
                            {
                                "build_id": build_id,
                                "shot_id": shot_spec.id,
                                "sha256": sha,
                                "reused_from_build": baseline_build.build_id,
                            },
                        )
                        continue

                    _log_build(build, "INFO", "GENERATE", f"Generating {shot_spec.id} with {type(self.generator).__name__}")
                    started = time.time()
                    with tracer.start_as_current_span(
                        "cinema.generate.shot",
                        attributes={
                            "cinema.project_id": self.contract.project.id,
                            "cinema.build_id": build_id,
                            "cinema.shot_id": shot_spec.id,
                            "cinema.generator": type(self.generator).__name__,
                            "cinema.model": getattr(self.generator, "model_name", "fixture"),
                        },
                    ):
                        result = await self.generator.generate(
                            shot_spec,
                            self.contract.characters,
                            self.contract.props,
                            output_path,
                        )
                    duration = round(time.time() - started, 2)
                    if not result.success:
                        raise RuntimeError(f"Generation failed for {shot_spec.id}: {result.error}")
                    self.artifact_store.put_file(output_path, logical_path)
                    sha = self.artifact_store.sha256(logical_path)
                    build.shots.append(
                        ShotArtifact(
                            shot_id=shot_spec.id,
                            video_path=output_path,
                            prompt_used=shot_spec.description,
                            version=1 if not baseline_build else next(
                                (s.version for s in baseline_build.shots if s.shot_id == shot_spec.id), 0
                            ) + 1,
                            sha256=sha,
                            status="generated",
                            generation_duration_sec=duration,
                            model_used=getattr(self.generator, "model_name", "fixture"),
                            generated_at=datetime.datetime.now(datetime.timezone.utc).isoformat(),
                        )
                    )
                    _log_build(build, "INFO", "GENERATE", f"Generated {shot_spec.id} in {duration}s (SHA256: {sha})")
                    emit_log("artifact_rebuilt", {"build_id": build_id, "shot_id": shot_spec.id, "sha256": sha})

                # Poster: runtime selection AND real causal consumption of selected shot.
                poster_path = os.path.join(scratch_build_dir, "poster.mp4")
                logical_poster = f"projects/{self.contract.project.id}/builds/{build_id}/poster.mp4"
                if is_incremental and baseline_build and "poster" in reuse_set:
                    base_logical = f"projects/{self.contract.project.id}/builds/{baseline_build.build_id}/poster.mp4"
                    if not self.artifact_store.exists(base_logical):
                        if _strict_mode():
                            raise RuntimeError("Strict Mode: baseline poster missing")
                        base_local = os.path.join(self.storage_path, baseline_build.build_id, "poster.mp4")
                        if os.path.exists(base_local):
                            shutil.copy2(base_local, poster_path)
                            self.artifact_store.put_file(poster_path, logical_poster)
                        else:
                            raise RuntimeError("Cannot reuse poster: baseline artifact missing")
                    else:
                        self.artifact_store.copy(base_logical, logical_poster)
                        self.artifact_store.get_file(logical_poster, poster_path)
                    old_sha = self.artifact_store.sha256(base_logical) if self.artifact_store.exists(base_logical) else _compute_sha256(poster_path)
                    sha = self.artifact_store.sha256(logical_poster)
                    if old_sha and sha and old_sha != sha:
                        raise RuntimeError("SHA-256 mismatch while reusing poster")
                    build.deliverables.append(
                        DeliverableArtifact(
                            artifact_id="poster",
                            artifact_type="poster",
                            file_path=poster_path,
                            sha256=sha,
                            status="reused_from_baseline",
                            reused_from_build=baseline_build.build_id,
                            version=1,
                        )
                    )
                else:
                    from app.dynamic_selection import select_poster_hero_reference

                    selection = await select_poster_hero_reference(
                        shots=build.shots,
                        project_name=self.contract.project.title,
                        characters=self.contract.characters,
                    )
                    selected_shot = next(
                        (s for s in build.shots if s.shot_id == selection.selected_shot_id),
                        None,
                    )
                    if not selected_shot:
                        raise RuntimeError(f"Poster selection returned unknown shot: {selection.selected_shot_id}")

                    source_sha = selected_shot.sha256 or _compute_sha256(selected_shot.video_path)
                    with tracer.start_as_current_span(
                        "cinema.reference.select",
                        attributes={
                            "cinema.consumer": "poster:v2" if baseline_build else "poster:v1",
                            "cinema.reference.candidates": ", ".join(selection.candidates),
                            "cinema.reference.selected": selection.selected_reference,
                            "cinema.selection.reason": selection.reason,
                            "cinema.selection.confidence": selection.confidence,
                            "cinema.selection.visual_candidates": selection.visual_candidates_evaluated,
                            "cinema.ai.model": GEMINI_MODEL,
                            "cinema.source.sha256": source_sha,
                        },
                    ) as ref_span:
                        span_ctx = ref_span.get_span_context() if hasattr(ref_span, "get_span_context") else None
                        span_id_hex = format(span_ctx.span_id, "016x") if span_ctx and getattr(span_ctx, "span_id", None) else f"{build.build_id}_ref_select"
                        trace_id_hex = format(span_ctx.trace_id, "032x") if span_ctx and getattr(span_ctx, "trace_id", None) else (build.trace_id or f"{build.build_id}_trace")
                        build.spans.append(
                            {
                                "name": "cinema.reference.select",
                                "span_id": span_id_hex,
                                "trace_id": trace_id_hex,
                                "attributes": {
                                    "cinema.consumer": "poster:v2" if baseline_build else "poster:v1",
                                    "cinema.reference.selected": selection.selected_reference,
                                    "cinema.selection.reason": selection.reason,
                                    "cinema.selection.confidence": selection.confidence,
                                    "cinema.selection.visual_candidates": selection.visual_candidates_evaluated,
                                    "cinema.ai.model": GEMINI_MODEL,
                                    "cinema.source.sha256": source_sha,
                                },
                            }
                        )
                        _log_build(
                            build,
                            "INFO",
                            "RUNTIME_LINEAGE",
                            f"Gemini visually selected {selection.selected_reference}; poster will consume that generated shot",
                        )

                    _materialize_poster_from_selected_shot(
                        selected_shot.video_path,
                        poster_path,
                        title=self.contract.project.title,
                    )
                    self.artifact_store.put_file(poster_path, logical_poster)
                    sha = self.artifact_store.sha256(logical_poster)
                    build.deliverables.append(
                        DeliverableArtifact(
                            artifact_id="poster",
                            artifact_type="poster",
                            file_path=poster_path,
                            sha256=sha,
                            status="generated",
                            version=2 if baseline_build else 1,
                            details={
                                "selected_reference": selection.selected_reference,
                                "selected_shot_id": selection.selected_shot_id,
                                "source_shot_sha256": source_sha,
                                "selection_reason": selection.reason,
                                "selection_confidence": selection.confidence,
                                "visual_candidates_evaluated": selection.visual_candidates_evaluated,
                                "evaluator_model": GEMINI_MODEL,
                                "poster_materialization": "actual_selected_generated_keyframe",
                            },
                        )
                    )
                    with tracer.start_as_current_span(
                        "cinema.generate.poster",
                        attributes={
                            "cinema.artifact_id": "poster",
                            "cinema.input.selected_reference": selection.selected_reference,
                            "cinema.input.source_sha256": source_sha,
                            "cinema.output.sha256": sha,
                        },
                    ):
                        _log_build(
                            build,
                            "INFO",
                            "GENERATE",
                            f"Materialized poster from {selection.selected_reference} (source SHA: {source_sha}, poster SHA: {sha})",
                        )

                rebuilt = [s for s in build.shots if s.status == "generated"] + [
                    d for d in build.deliverables if d.status == "generated"
                ]
                reused = [s for s in build.shots if s.status == "reused_from_baseline"] + [
                    d for d in build.deliverables if d.status == "reused_from_baseline"
                ]
                build.operations_rebuilt = len(rebuilt)
                build.operations_reused = len(reused)
                build.operations_avoided = max(0, build.operations_total - build.operations_rebuilt)
                build.savings_percent = (
                    round(build.operations_avoided / build.operations_total * 100, 1)
                    if build.operations_total
                    else 0.0
                )
                _log_build(
                    build,
                    "INFO",
                    "INCREMENTAL_SUMMARY",
                    f"Operations: {build.operations_rebuilt} rebuilt, {build.operations_reused} reused, "
                    f"{build.operations_avoided} avoided ({build.savings_percent}% artifact operations avoided).",
                )
                self.metadata_store.save_build(build)

                # QA
                build.status = BuildStatus.VALIDATING
                self.metadata_store.save_build(build)
                _log_build(build, "INFO", "EVALUATE", "Beginning technical and creative QA")
                results: list[TestResult] = []
                for shot_art in build.shots:
                    shot_spec = next((s for s in self.contract.shots if s.id == shot_art.shot_id), None)
                    if not shot_spec:
                        continue
                    with tracer.start_as_current_span(f"cinema.validate.technical.{shot_art.shot_id}"):
                        tech = await evaluate_technical(shot_art, self.contract.release, build_id)
                    results.extend(tech)
                    with tracer.start_as_current_span(f"cinema.validate.creative.{shot_art.shot_id}"):
                        creative = await evaluate_creative(
                            shot_art,
                            shot_spec,
                            self.contract.characters,
                            self.contract.props,
                            build_id,
                        )
                    results.extend(creative)

                char_shots = [
                    s for s in build.shots
                    if any(s.shot_id == spec.id and spec.characters for spec in self.contract.shots)
                ]
                if len(char_shots) >= 2:
                    with tracer.start_as_current_span("cinema.validate.creative.cross_shot"):
                        results.extend(
                            await evaluate_cross_shot_consistency(char_shots, self.contract.characters, build_id)
                        )

                if baseline_build and baseline_build.test_results:
                    results = detect_regressions(results, baseline_build.test_results)

                build.test_results = results
                build.tests_total = len(results)
                build.tests_passed = sum(1 for r in results if r.status == TestStatus.PASS)
                build.creative_tests_total = sum(1 for r in results if r.category == "creative")
                build.creative_tests_passed = sum(
                    1 for r in results if r.category == "creative" and r.status == TestStatus.PASS
                )
                build.technical_tests_total = sum(1 for r in results if r.category == "technical")
                build.technical_tests_passed = sum(
                    1 for r in results if r.category == "technical" and r.status == TestStatus.PASS
                )
                failed = [r for r in results if r.status in (TestStatus.FAIL, TestStatus.REGRESSION)]
                unknown = [r for r in results if r.status == TestStatus.UNKNOWN]
                build.regressions = sum(1 for r in results if r.status == TestStatus.REGRESSION)
                build.unknowns = len(unknown)
                build.build_duration_sec = round(time.time() - start_time, 2)

                emit_log(
                    "validation_completed",
                    {
                        "build_id": build_id,
                        "tests_total": build.tests_total,
                        "tests_passed": build.tests_passed,
                        "regressions": build.regressions,
                    },
                )

                is_repair = bool(getattr(build, "repair_of", None))
                has_hard_block = (build.regressions > 0) or bool(failed)

                if has_hard_block or (not is_repair and len(unknown) > 2):
                    build.status = BuildStatus.BLOCKED
                    build.release_ready = False
                    build.error_summary = (
                        f"Quality gate BLOCKED ({build.tests_passed}/{build.tests_total} passed, "
                        f"{build.regressions} regressions)."
                    )
                    _log_build(build, "ERROR", "QUALITY_GATE", build.error_summary)
                else:
                    build.status = BuildStatus.RELEASE_READY
                    build.release_ready = True
                    build.error_summary = None
                    _log_build(
                        build,
                        "INFO",
                        "QUALITY_GATE",
                        f"Quality gate PASSED ({build.tests_passed}/{build.tests_total}). RELEASE CANDIDATE READY.",
                    )
                    emit_log(
                        "release_candidate_created",
                        {"build_id": build_id, "operations_avoided": build.operations_avoided},
                    )
                    try:
                        from app.packaging import stitch_build_shots
                        with tracer.start_as_current_span("cinema.package.release_candidate"):
                            stitched = await asyncio.to_thread(stitch_build_shots, scratch_build_dir, build.shots)
                            if stitched and os.path.exists(stitched):
                                logical_film = f"projects/{self.contract.project.id}/builds/{build_id}/final_film.mp4"
                                film_uri = self.artifact_store.put_file(stitched, logical_film)
                                build.master_film_path = stitched if os.path.exists(stitched) else film_uri
                                _log_build(build, "INFO", "PACKAGING", f"Master film stored: {film_uri}")
                    except Exception as exc:
                        _log_build(build, "WARNING", "PACKAGING", f"Master film stitching warning: {exc}")

                self.metadata_store.save_build(build)
                try:
                    from app.telemetry import record_build_completed, record_test_results
                    record_build_completed(self.contract.project.id, build)
                    record_test_results(self.contract.project.id, results)
                    for test in results:
                        emit_log(
                            "cinema_test_result",
                            {
                                "project_id": self.contract.project.id,
                                "build_id": build_id,
                                "shot_id": test.scope,
                                "test_id": test.test_id,
                                "status": test.status.value,
                                "expected": test.expected,
                                "observed": test.observed,
                            },
                        )
                except Exception as exc:
                    logger.warning("Telemetry error (non-fatal): %s", exc)

            except Exception as exc:
                logger.error("Build %s failed: %s", build_id, exc, exc_info=True)
                build.error_summary = f"Build failed: {exc}"
                _log_build(build, "ERROR", "PIPELINE", f"Fatal build failure: {exc}")
                build.status = BuildStatus.BLOCKED
                build.release_ready = False
                build.build_duration_sec = round(time.time() - start_time, 2)
                self.metadata_store.save_build(build)

        return build
