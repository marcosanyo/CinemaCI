"""Deterministic Temporal Telemetry Analyzer for Cinema CI.

Calculates three CV-based temporal signals on video shots:
  1. Motion-Compensated Temporal Residual
  2. Feature-Track Survival (Shi-Tomasi + Lucas-Kanade with FB validation)
  3. Forward/Backward Optical Flow Consistency (Farneback Dense Flow)

Includes:
  - Multi-scale rolling baseline anomaly detection (Median, MAD, Local Z-Score)
  - Shot boundary detection & margin exclusion
  - Multi-metric correlation & coincidence analysis
  - High-res frame & diagnostic visualization export
  - CSV & JSON telemetry export ready for Grafana / OTel
"""

from __future__ import annotations

import json
import os
import time
from dataclasses import asdict, dataclass
from typing import Any

import cv2
import matplotlib.pyplot as plt
import numpy as np


@dataclass
class FrameTelemetry:
    frame_idx: int
    video_time_sec: float
    is_boundary_margin: bool

    # Metric A: Motion-compensated Residual
    uncompensated_residual: float
    compensated_residual: float
    residual_reduction_ratio: float

    # Metric B: Feature Track Survival
    num_features_detected: int
    num_features_survived: int
    feature_survival_ratio: float
    multi_frame_survival_5f: float

    # Metric C: Forward/Backward Flow Consistency
    fb_flow_mean_error: float
    fb_flow_median_error: float
    fb_flow_p90_error: float
    fb_inconsistent_pixel_ratio: float

    # Local Baseline Deviations (Local Z-scores)
    residual_local_z: float = 0.0
    survival_local_z: float = 0.0
    fb_flow_local_z: float = 0.0

    # Multi-metric Anomaly Coincidence Score (Composite Trigger)
    coincidence_score: float = 0.0


class TemporalTelemetryEngine:
    def __init__(
        self,
        margin_sec: float = 0.25,
        rolling_window_sec: float = 1.0,
        fb_error_threshold: float = 1.5,
        max_features: int = 400,
    ):
        self.margin_sec = margin_sec
        self.rolling_window_sec = rolling_window_sec
        self.fb_error_threshold = fb_error_threshold
        self.max_features = max_features

    def analyze_video(
        self,
        video_path: str,
        shot_id: str = "shot_01",
        cut_boundaries: list[int] | None = None,
    ) -> tuple[list[FrameTelemetry], dict[str, Any]]:
        """Runs deterministic temporal telemetry on a video file."""
        if not os.path.exists(video_path):
            raise FileNotFoundError(f"Video not found: {video_path}")

        cap = cv2.VideoCapture(video_path)
        fps = cap.get(cv2.CAP_PROP_FPS) or 24.0
        total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
        width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
        height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))

        margin_frames = int(round(fps * self.margin_sec))
        rolling_frames = max(5, int(round(fps * self.rolling_window_sec)))

        frames_gray = []
        frames_color = []

        start_time = time.time()

        while True:
            ret, frame = cap.read()
            if not ret:
                break
            frames_color.append(frame)
            gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
            frames_gray.append(gray)

        cap.release()
        num_frames = len(frames_gray)
        if num_frames < 2:
            return [], {}

        # Precompute dense optical flows and metrics
        raw_telemetries: list[FrameTelemetry] = []

        # Track multi-frame feature lifetimes (5-frame window history)
        feature_tracker_history: list[np.ndarray] = []

        # Compute frame-by-frame metrics for t -> t+1
        for t in range(num_frames - 1):
            sec = t / fps
            is_margin = (t < margin_frames) or (t >= num_frames - 1 - margin_frames)

            # Check cut boundaries if multi-shot
            if cut_boundaries:
                for cut_f in cut_boundaries:
                    if abs(t - cut_f) <= margin_frames:
                        is_margin = True

            I_t = frames_gray[t]
            I_next = frames_gray[t + 1]

            # -------------------------------------------------------------
            # METRIC A & C: Dense Optical Flow (Farneback) & Warp Residual
            # -------------------------------------------------------------
            # Downscale slightly for robust, fast flow computation if large
            scale = 0.5 if (width > 960) else 1.0
            if scale != 1.0:
                small_t = cv2.resize(I_t, (0, 0), fx=scale, fy=scale)
                small_next = cv2.resize(I_next, (0, 0), fx=scale, fy=scale)
            else:
                small_t = I_t
                small_next = I_next

            # Forward Flow: t -> t+1
            flow_fwd = cv2.calcOpticalFlowFarneback(
                small_t,
                small_next,
                None,
                pyr_scale=0.5,
                levels=3,
                winsize=15,
                iterations=3,
                poly_n=5,
                poly_sigma=1.2,
                flags=0,
            )

            # Backward Flow: t+1 -> t
            flow_bwd = cv2.calcOpticalFlowFarneback(
                small_next,
                small_t,
                None,
                pyr_scale=0.5,
                levels=3,
                winsize=15,
                iterations=3,
                poly_n=5,
                poly_sigma=1.2,
                flags=0,
            )

            if scale != 1.0:
                flow_fwd_full = cv2.resize(flow_fwd, (width, height)) * (1.0 / scale)
                flow_bwd_full = cv2.resize(flow_bwd, (width, height)) * (1.0 / scale)
            else:
                flow_fwd_full = flow_fwd
                flow_bwd_full = flow_bwd

            # --- Metric A: Motion-compensated Residual ---
            # Forward warp I_t toward I_{t+1} using flow_fwd_full
            h_f, w_f = I_t.shape
            grid_x, grid_y = np.meshgrid(np.arange(w_f), np.arange(h_f))

            # Warping coordinate: for each pixel (x,y) in target (t+1), where does it come from in t?
            # Using backward flow from t+1 or forward flow with remap:
            map_x = (grid_x + flow_bwd_full[..., 0]).astype(np.float32)
            map_y = (grid_y + flow_bwd_full[..., 1]).astype(np.float32)

            warped_t_to_next = cv2.remap(
                I_t,
                map_x,
                map_y,
                interpolation=cv2.INTER_LINEAR,
                borderMode=cv2.BORDER_REFLECT,
            )

            # Mask out outer boundary to avoid border padding artifacts
            border_margin = int(10 * (width / 1280.0))
            inner_mask = np.zeros_like(I_t, dtype=bool)
            inner_mask[
                border_margin:-border_margin, border_margin:-border_margin
            ] = True

            uncomp_diff = np.abs(
                I_next.astype(np.float32) - I_t.astype(np.float32)
            )[inner_mask]
            comp_diff = np.abs(
                I_next.astype(np.float32) - warped_t_to_next.astype(np.float32)
            )[inner_mask]

            uncomp_residual = float(np.mean(uncomp_diff) / 255.0)
            comp_residual = float(np.mean(comp_diff) / 255.0)
            reduction_ratio = (
                (uncomp_residual - comp_residual) / (uncomp_residual + 1e-6)
                if uncomp_residual > 0
                else 0.0
            )

            # --- Metric C: Forward/Backward Flow Consistency ---
            # For each pixel (x, y) in t:
            # fwd target = (x + u_f, y + v_f)
            # Sample bwd flow at fwd target
            fwd_x = np.clip(grid_x + flow_fwd_full[..., 0], 0, w_f - 1).astype(np.float32)
            fwd_y = np.clip(grid_y + flow_fwd_full[..., 1], 0, h_f - 1).astype(np.float32)

            bwd_u_at_fwd = cv2.remap(
                flow_bwd_full[..., 0],
                fwd_x,
                fwd_y,
                interpolation=cv2.INTER_LINEAR,
                borderMode=cv2.BORDER_REFLECT,
            )
            bwd_v_at_fwd = cv2.remap(
                flow_bwd_full[..., 1],
                fwd_x,
                fwd_y,
                interpolation=cv2.INTER_LINEAR,
                borderMode=cv2.BORDER_REFLECT,
            )

            # Reconstructed position offset from original (x, y)
            fb_err_x = flow_fwd_full[..., 0] + bwd_u_at_fwd
            fb_err_y = flow_fwd_full[..., 1] + bwd_v_at_fwd
            fb_error_map = np.sqrt(fb_err_x**2 + fb_err_y**2)[inner_mask]

            fb_mean = float(np.mean(fb_error_map))
            fb_median = float(np.median(fb_error_map))
            fb_p90 = float(np.percentile(fb_error_map, 90))
            inconsistent_ratio = float(
                np.mean(fb_error_map > self.fb_error_threshold)
            )

            # -------------------------------------------------------------
            # METRIC B: Feature-Track Survival (Shi-Tomasi + Lucas-Kanade)
            # -------------------------------------------------------------
            # Detect corner features in I_t
            p0 = cv2.goodFeaturesToTrack(
                I_t,
                maxCorners=self.max_features,
                qualityLevel=0.01,
                minDistance=10,
                blockSize=7,
            )

            if p0 is not None and len(p0) > 0:
                num_detected = len(p0)
                # LK Forward: t -> t+1
                p1, st_fwd, err_fwd = cv2.calcOpticalFlowPyrLK(
                    I_t,
                    I_next,
                    p0,
                    None,
                    winSize=(15, 15),
                    maxLevel=3,
                    criteria=(
                        cv2.TERM_CRITERIA_EPS | cv2.TERM_CRITERIA_COUNT,
                        20,
                        0.03,
                    ),
                )

                # LK Backward check: t+1 -> t
                p0_back, st_bwd, _ = cv2.calcOpticalFlowPyrLK(
                    I_next,
                    I_t,
                    p1,
                    None,
                    winSize=(15, 15),
                    maxLevel=3,
                    criteria=(
                        cv2.TERM_CRITERIA_EPS | cv2.TERM_CRITERIA_COUNT,
                        20,
                        0.03,
                    ),
                )

                # Survival condition: forward status==1, backward status==1, and FB cycle error < 1.5 px
                valid_tracks = (
                    (st_fwd.ravel() == 1)
                    & (st_bwd.ravel() == 1)
                    & (
                        np.linalg.norm(
                            p0.reshape(-1, 2) - p0_back.reshape(-1, 2), axis=1
                        )
                        < 1.5
                    )
                )

                num_survived = int(np.sum(valid_tracks))
                survival_ratio = float(num_survived / num_detected)
            else:
                num_detected = 0
                num_survived = 0
                survival_ratio = 1.0

            # 5-frame multi-frame track survival window
            # (tracks persistent across 5 frames)
            if t >= 4:
                # Track features from t-4 to t+1
                p_init = cv2.goodFeaturesToTrack(
                    frames_gray[t - 4],
                    maxCorners=200,
                    qualityLevel=0.01,
                    minDistance=10,
                )
                if p_init is not None and len(p_init) > 0:
                    curr_p = p_init
                    all_alive = True
                    for k in range(t - 4, t + 1):
                        next_p, st, _ = cv2.calcOpticalFlowPyrLK(
                            frames_gray[k],
                            frames_gray[k + 1],
                            curr_p,
                            None,
                            winSize=(15, 15),
                            maxLevel=3,
                        )
                        valid = st.ravel() == 1
                        curr_p = next_p[valid]
                        if len(curr_p) == 0:
                            all_alive = False
                            break
                    mf_survival = float(len(curr_p) / len(p_init))
                else:
                    mf_survival = 1.0
            else:
                mf_survival = survival_ratio

            rec = FrameTelemetry(
                frame_idx=t,
                video_time_sec=sec,
                is_boundary_margin=is_margin,
                uncompensated_residual=uncomp_residual,
                compensated_residual=comp_residual,
                residual_reduction_ratio=reduction_ratio,
                num_features_detected=num_detected,
                num_features_survived=num_survived,
                feature_survival_ratio=survival_ratio,
                multi_frame_survival_5f=mf_survival,
                fb_flow_mean_error=fb_mean,
                fb_flow_median_error=fb_median,
                fb_flow_p90_error=fb_p90,
                fb_inconsistent_pixel_ratio=inconsistent_ratio,
            )
            raw_telemetries.append(rec)

        # -------------------------------------------------------------
        # LOCAL BASELINE & Z-SCORE DEVIATION COMPUTATION
        # -------------------------------------------------------------
        n = len(raw_telemetries)
        half_w = rolling_frames // 2

        comp_residuals = np.array([r.compensated_residual for r in raw_telemetries])
        survival_drops = np.array(
            [1.0 - r.feature_survival_ratio for r in raw_telemetries]
        )
        fb_errors = np.array([r.fb_flow_p90_error for r in raw_telemetries])

        # Physical noise floors to prevent division by near-zero MAD in static shots
        FLOOR_RES = 0.0025      # ~0.6 pixel intensity out of 255
        FLOOR_SURV = 0.03       # 3% feature tracking noise
        FLOOR_FB = 0.20         # 0.2 pixel optical flow resolution

        for i in range(n):
            w_start = max(0, i - half_w)
            w_end = min(n, i + half_w + 1)

            # Metric A local Z
            win_res = comp_residuals[w_start:w_end]
            med_res = np.median(win_res)
            mad_res = np.median(np.abs(win_res - med_res))
            effective_scale_res = max(1.4826 * mad_res, FLOOR_RES)
            raw_telemetries[i].residual_local_z = float(
                (comp_residuals[i] - med_res) / effective_scale_res
            )

            # Metric B local Z (drop in survival)
            win_surv = survival_drops[w_start:w_end]
            med_surv = np.median(win_surv)
            mad_surv = np.median(np.abs(win_surv - med_surv))
            effective_scale_surv = max(1.4826 * mad_surv, FLOOR_SURV)
            raw_telemetries[i].survival_local_z = float(
                (survival_drops[i] - med_surv) / effective_scale_surv
            )

            # Metric C local Z
            win_fb = fb_errors[w_start:w_end]
            med_fb = np.median(win_fb)
            mad_fb = np.median(np.abs(win_fb - med_fb))
            effective_scale_fb = max(1.4826 * mad_fb, FLOOR_FB)
            raw_telemetries[i].fb_flow_local_z = float(
                (fb_errors[i] - med_fb) / effective_scale_fb
            )

            # Composite coincidence score:
            # Positive response when residual increases, survival drops, and FB error increases
            # Only active if not in margin
            if not raw_telemetries[i].is_boundary_margin:
                z_a = max(0.0, raw_telemetries[i].residual_local_z)
                z_b = max(0.0, raw_telemetries[i].survival_local_z)
                z_c = max(0.0, raw_telemetries[i].fb_flow_local_z)

                # 3-metric geometric/harmonic coincidence
                # High score only when multiple signals spike simultaneously
                coincidence = (z_a * z_b * z_c) ** (1.0 / 3.0)
                raw_telemetries[i].coincidence_score = float(coincidence)
            else:
                raw_telemetries[i].coincidence_score = 0.0

        elapsed_sec = time.time() - start_time
        fps_proc = num_frames / (elapsed_sec + 1e-6)

        summary = {
            "shot_id": shot_id,
            "video_path": video_path,
            "total_frames": num_frames,
            "fps": fps,
            "duration_sec": num_frames / fps,
            "processing_time_sec": elapsed_sec,
            "processing_fps": fps_proc,
            "margin_frames_excluded": margin_frames,
            "mean_compensated_residual": float(np.mean(comp_residuals)),
            "mean_uncompensated_residual": float(
                np.mean([r.uncompensated_residual for r in raw_telemetries])
            ),
            "mean_feature_survival": float(
                np.mean([r.feature_survival_ratio for r in raw_telemetries])
            ),
            "mean_fb_flow_error_p90": float(np.mean(fb_errors)),
        }

        return raw_telemetries, summary


def save_telemetry_data(
    records: list[FrameTelemetry],
    summary: dict[str, Any],
    out_csv_path: str,
    out_json_path: str,
) -> None:
    """Export frame telemetry to CSV and JSON formats."""
    import csv

    os.makedirs(os.path.dirname(out_csv_path), exist_ok=True)
    os.makedirs(os.path.dirname(out_json_path), exist_ok=True)

    # Save CSV
    if records:
        keys = list(asdict(records[0]).keys())
        with open(out_csv_path, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=keys)
            writer.writeheader()
            for r in records:
                writer.writerow(asdict(r))

    # Save JSON
    data = {
        "summary": summary,
        "frames": [asdict(r) for r in records],
    }
    with open(out_json_path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)


def render_timeline_visualization(
    records: list[FrameTelemetry],
    summary: dict[str, Any],
    visual_annotations: list[dict[str, Any]],
    out_png_path: str,
) -> None:
    """Generate high quality timeline visualization comparing the 3 metrics and visual ground truth."""
    os.makedirs(os.path.dirname(out_png_path), exist_ok=True)

    times = [r.video_time_sec for r in records]
    res_comp = [r.compensated_residual for r in records]
    res_uncomp = [r.uncompensated_residual for r in records]
    surv_ratio = [r.feature_survival_ratio * 100.0 for r in records]
    surv_mf5 = [r.multi_frame_survival_5f * 100.0 for r in records]
    fb_p90 = [r.fb_flow_p90_error for r in records]
    fb_ratio = [r.fb_inconsistent_pixel_ratio * 100.0 for r in records]

    # Z-scores
    z_a = [r.residual_local_z for r in records]
    z_b = [r.survival_local_z for r in records]
    z_c = [r.fb_flow_local_z for r in records]
    coincidence = [r.coincidence_score for r in records]

    fig, axes = plt.subplots(4, 1, figsize=(14, 12), sharex=True)
    shot_title = summary.get("shot_id", "Shot")

    fig.suptitle(
        f"Cinema CI Deterministic Temporal Telemetry: {shot_title} ({summary.get('duration_sec', 0):.2f}s)",
        fontsize=14,
        fontweight="bold",
        y=0.98,
    )

    # Shading for visual ground truth annotations
    for ax in axes:
        for ann in visual_annotations:
            start_s = ann.get("start_sec", 0.0)
            end_s = ann.get("end_sec", 0.0)
            label_text = f"Visual: {ann.get('issue', '')} ({ann.get('severity', '')})"
            ax.axvspan(
                start_s,
                end_s,
                color="red",
                alpha=0.18,
                label=label_text if ax == axes[0] else "",
            )

        # Margin exclusion shading
        margin_sec = summary.get("margin_frames_excluded", 6) / summary.get(
            "fps", 24.0
        )
        dur = summary.get("duration_sec", 8.0)
        ax.axvspan(0, margin_sec, color="gray", alpha=0.12, hatch="//")
        ax.axvspan(dur - margin_sec, dur, color="gray", alpha=0.12, hatch="//")

    # Panel 1: Metric A - Motion-compensated Residual
    axes[0].plot(
        times,
        res_uncomp,
        color="gray",
        linestyle="--",
        alpha=0.6,
        label="Raw Pixel Diff (Uncompensated)",
    )
    axes[0].plot(
        times,
        res_comp,
        color="#1f77b4",
        linewidth=2.0,
        label="Motion-Compensated Residual (Warped)",
    )
    axes[0].set_ylabel("Residual (MAE / 255)")
    axes[0].set_title(
        "A. Motion-compensated Temporal Residual (Forward Warp Error)"
    )
    axes[0].grid(True, alpha=0.3)
    axes[0].legend(loc="upper right", framealpha=0.8)

    # Panel 2: Metric B - Feature-track Survival
    axes[1].plot(
        times,
        surv_ratio,
        color="#2ca02c",
        linewidth=2.0,
        label="1-Frame Survival Rate (%)",
    )
    axes[1].plot(
        times,
        surv_mf5,
        color="#98df8a",
        linestyle=":",
        linewidth=1.8,
        label="5-Frame Track Lifetime (%)",
    )
    axes[1].set_ylabel("Survival Rate (%)")
    axes[1].set_ylim(0, 105)
    axes[1].set_title(
        "B. Feature-Track Survival (Shi-Tomasi + LK with Cycle Validation)"
    )
    axes[1].grid(True, alpha=0.3)
    axes[1].legend(loc="lower right", framealpha=0.8)

    # Panel 3: Metric C - Forward/Backward Flow Consistency
    ax3_twin = axes[2].twinx()
    p1 = axes[2].plot(
        times,
        fb_p90,
        color="#d62728",
        linewidth=2.0,
        label="FB Flow Inconsistency (P90 px)",
    )
    p2 = ax3_twin.plot(
        times,
        fb_ratio,
        color="#ff7f0e",
        linestyle="--",
        linewidth=1.5,
        label="Inconsistent Pixels (>1.5px %)",
    )
    axes[2].set_ylabel("Flow Error (px)", color="#d62728")
    ax3_twin.set_ylabel("Inconsistent %", color="#ff7f0e")
    axes[2].set_title("C. Forward/Backward Optical Flow Inconsistency")
    axes[2].grid(True, alpha=0.3)

    lines = p1 + p2
    labels = [l.get_label() for l in lines]
    axes[2].legend(lines, labels, loc="upper right", framealpha=0.8)

    # Panel 4: Normalized Local Z-Scores & Multi-metric Coincidence
    axes[3].plot(
        times,
        z_a,
        color="#1f77b4",
        alpha=0.6,
        linewidth=1.2,
        label="Residual Local Z (Spike ↑)",
    )
    axes[3].plot(
        times,
        z_b,
        color="#2ca02c",
        alpha=0.6,
        linewidth=1.2,
        label="Survival Drop Local Z (Drop ↑)",
    )
    axes[3].plot(
        times,
        z_c,
        color="#d62728",
        alpha=0.6,
        linewidth=1.2,
        label="FB Inconsistency Local Z (Spike ↑)",
    )
    axes[3].plot(
        times,
        coincidence,
        color="#9467bd",
        linewidth=2.5,
        label="3-Metric Coincidence Score",
    )
    axes[3].axhline(
        2.5,
        color="black",
        linestyle=":",
        alpha=0.7,
        label="Anomaly Threshold (Z >= 2.5)",
    )
    axes[3].set_ylabel("Local Z-Score")
    axes[3].set_xlabel("Video Time (seconds)")
    axes[3].set_title(
        "D. Multi-Metric Correlation & Coincidence Anomaly Trigger"
    )
    axes[3].grid(True, alpha=0.3)
    axes[3].legend(loc="upper right", framealpha=0.8, ncol=2)

    plt.tight_layout()
    plt.savefig(out_png_path, dpi=180)
    plt.close()
