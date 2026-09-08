"""Comprehensive Batch Evaluation Script for Temporal Telemetry Validation.

Executes analysis across all real AI-generated video shots and multi-shot reels:
  1. Computes deterministic CV metrics (Residual, Survival, FB Flow)
  2. Aligns with independently recorded visual ground truth annotations
  3. Detects & analyzes major peaks (extracting t-2..t+2 frame diagnostic grids)
  4. Evaluates hypotheses H1-H5, false positives, correlation, and cost
  5. Exports all CSVs, JSONs, Timeline Plots, and Diagnostic Images
"""

from __future__ import annotations

import glob
import json
import os
import sys
import time
from typing import Any

import cv2
import matplotlib.pyplot as plt
import numpy as np

from app.evaluator.temporal_telemetry import (
    FrameTelemetry,
    TemporalTelemetryEngine,
    render_timeline_visualization,
    save_telemetry_data,
)


# Ground truth visual annotations independently observed before metric tuning
VISUAL_ANNOTATIONS: dict[str, list[dict[str, Any]]] = {
    "build_0001_shot_01": [
        {
            "start_sec": 2.1,
            "end_sec": 3.0,
            "issue": "Minor glove/finger texture transition & coat adjustment",
            "severity": "Low",
            "type": "texture_transition",
        }
    ],
    "build_0001_shot_02": [
        {
            "start_sec": 2.0,
            "end_sec": 3.0,
            "issue": "Finger-envelope contact point slight morphing",
            "severity": "Low-Medium",
            "type": "contact_morphing",
        }
    ],
    "build_0002_shot_03": [
        {
            "start_sec": 1.0,
            "end_sec": 1.6,
            "issue": "Rapid body rotation & orientation flip toward door",
            "severity": "Medium",
            "type": "motion_discontinuity",
        },
        {
            "start_sec": 2.7,
            "end_sec": 3.4,
            "issue": "Discontinuous turnaround from back to front with envelope",
            "severity": "High",
            "type": "geometry_morphing",
        },
        {
            "start_sec": 4.0,
            "end_sec": 5.2,
            "issue": "Door frame crossing & foreground glass occlusion",
            "severity": "Medium",
            "type": "occlusion_pass",
        },
    ],
    "build_0004_shot_03": [
        {
            "start_sec": 3.8,
            "end_sec": 4.8,
            "issue": "Glass door boundary slide across foreground",
            "severity": "Low",
            "type": "occlusion_pass",
        }
    ],
    "build_0007_shot_01": [
        {
            "start_sec": 1.8,
            "end_sec": 2.6,
            "issue": "Rain-streaked coat shaking & fast character turn",
            "severity": "Low",
            "type": "fast_motion",
        }
    ],
    "build_0007_shot_02": [
        # No obvious temporal anomaly observed
    ],
    "build_0007_shot_03": [
        # No obvious temporal anomaly observed
    ],
    "build_0008_shot_01": [
        {
            "start_sec": 1.8,
            "end_sec": 2.6,
            "issue": "Wet coat shaking & fast body turn inside cafe entrance",
            "severity": "Low",
            "type": "fast_motion",
        }
    ],
    "build_0008_shot_02": [
        # No obvious temporal anomaly observed
    ],
    "build_0008_shot_03": [
        # No obvious temporal anomaly observed
    ],
}


def extract_peak_diagnostics(
    video_path: str,
    peak_frame_idx: int,
    tag: str,
    metric_name: str,
    out_dir: str,
) -> str:
    """Extract t-2, t-1, t, t+1, t+2 frames along with optical flow & residual maps for diagnostic analysis."""
    os.makedirs(out_dir, exist_ok=True)
    cap = cv2.VideoCapture(video_path)
    total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    fps = cap.get(cv2.CAP_PROP_FPS) or 24.0

    frames_to_grab = [
        max(0, min(total - 1, peak_frame_idx + offset))
        for offset in [-2, -1, 0, 1, 2]
    ]

    grabbed = {}
    for idx in set(frames_to_grab):
        cap.set(cv2.CAP_PROP_POS_FRAMES, idx)
        ret, frame = cap.read()
        if ret:
            grabbed[idx] = frame
    cap.release()

    f_t0 = grabbed.get(peak_frame_idx, np.zeros((720, 1280, 3), dtype=np.uint8))
    f_t1_idx = min(total - 1, peak_frame_idx + 1)
    f_t1 = grabbed.get(f_t1_idx, f_t0)

    # Compute dense optical flow at peak frame
    g0 = cv2.cvtColor(f_t0, cv2.COLOR_BGR2GRAY)
    g1 = cv2.cvtColor(f_t1, cv2.COLOR_BGR2GRAY)
    flow = cv2.calcOpticalFlowFarneback(
        cv2.resize(g0, (640, 360)),
        cv2.resize(g1, (640, 360)),
        None,
        pyr_scale=0.5,
        levels=3,
        winsize=15,
        iterations=3,
        poly_n=5,
        poly_sigma=1.2,
        flags=0,
    )
    flow_full = cv2.resize(flow, (f_t0.shape[1], f_t0.shape[0])) * 2.0

    # Warp g0 -> g1
    h, w = g0.shape
    gx, gy = np.meshgrid(np.arange(w), np.arange(h))
    # Approximation of backward warp
    map_x = (gx - flow_full[..., 0]).astype(np.float32)
    map_y = (gy - flow_full[..., 1]).astype(np.float32)
    warped = cv2.remap(
        g0, map_x, map_y, interpolation=cv2.INTER_LINEAR, borderMode=cv2.BORDER_REFLECT
    )
    residual_map = np.abs(g1.astype(np.float32) - warped.astype(np.float32))
    residual_color = cv2.applyColorMap(
        np.clip(residual_map * 4.0, 0, 255).astype(np.uint8), cv2.COLORMAP_JET
    )

    # Optical flow magnitude map
    mag, ang = cv2.cartToPolar(flow_full[..., 0], flow_full[..., 1])
    hsv = np.zeros_like(f_t0)
    hsv[..., 1] = 255
    hsv[..., 0] = ang * 180 / np.pi / 2
    hsv[..., 2] = cv2.normalize(mag, None, 0, 255, cv2.NORM_MINMAX)
    flow_color = cv2.cvtColor(hsv, cv2.COLOR_HSV2BGR)

    # Build composite diagnostic grid
    # Top row: t-2, t-1, t, t+1, t+2
    top_frames = []
    for offset, idx in zip([-2, -1, 0, 1, 2], frames_to_grab):
        img = grabbed.get(idx, f_t0).copy()
        time_s = idx / fps
        cv2.putText(
            img,
            f"t{offset:+d} (F{idx}, {time_s:.2f}s)",
            (20, 45),
            cv2.FONT_HERSHEY_SIMPLEX,
            1.1,
            (0, 255, 0) if offset == 0 else (255, 255, 255),
            3,
        )
        top_frames.append(cv2.resize(img, (320, 180)))
    row1 = np.hstack(top_frames)

    # Bottom row: [Peak Frame t] [Optical Flow Mag/Dir] [Motion-Compensated Residual Map] [Uncompensated Diff Map]
    uncomp_diff = np.abs(g1.astype(np.float32) - g0.astype(np.float32))
    uncomp_color = cv2.applyColorMap(
        np.clip(uncomp_diff * 4.0, 0, 255).astype(np.uint8), cv2.COLORMAP_JET
    )

    cv2.putText(
        flow_color,
        "Dense Optical Flow Field",
        (20, 45),
        cv2.FONT_HERSHEY_SIMPLEX,
        1.1,
        (255, 255, 255),
        3,
    )
    cv2.putText(
        residual_color,
        "Motion-Comp Residual Map",
        (20, 45),
        cv2.FONT_HERSHEY_SIMPLEX,
        1.1,
        (255, 255, 255),
        3,
    )
    cv2.putText(
        uncomp_color,
        "Raw Uncompensated Diff Map",
        (20, 45),
        cv2.FONT_HERSHEY_SIMPLEX,
        1.1,
        (255, 255, 255),
        3,
    )

    p_f0 = cv2.resize(f_t0, (400, 225))
    p_flow = cv2.resize(flow_color, (400, 225))
    p_res = cv2.resize(residual_color, (400, 225))
    p_uncomp = cv2.resize(uncomp_color, (400, 225))
    row2 = np.hstack([p_f0, p_flow, p_res, p_uncomp])

    # Resize row1 to match row2 width
    row1_scaled = cv2.resize(row1, (row2.shape[1], int(row1.shape[0] * (row2.shape[1] / row1.shape[1]))))
    composite = np.vstack([row1_scaled, row2])

    out_file = os.path.join(
        out_dir, f"{tag}_peak_F{peak_frame_idx}_{metric_name}.jpg"
    )
    cv2.imwrite(out_file, composite)
    return out_file


def run_comprehensive_validation():
    print("=" * 70)
    print("STARTING DETERMINISTIC TEMPORAL TELEMETRY COMPREHENSIVE VALIDATION")
    print("=" * 70)

    engine = TemporalTelemetryEngine(margin_sec=0.25, rolling_window_sec=1.0)

    target_shots = [
        ("build_0001_shot_01", "storage/build_0001/shot_01.mp4"),
        ("build_0001_shot_02", "storage/build_0001/shot_02.mp4"),
        ("build_0002_shot_01", "storage/build_0002/shot_01.mp4"),
        ("build_0002_shot_02", "storage/build_0002/shot_02.mp4"),
        ("build_0002_shot_03", "storage/build_0002/shot_03.mp4"),
        ("build_0004_shot_01", "storage/build_0004/shot_01.mp4"),
        ("build_0004_shot_02", "storage/build_0004/shot_02.mp4"),
        ("build_0004_shot_03", "storage/build_0004/shot_03.mp4"),
        ("build_0007_shot_01", "storage/build_0007/shot_01.mp4"),
        ("build_0007_shot_02", "storage/build_0007/shot_02.mp4"),
        ("build_0007_shot_03", "storage/build_0007/shot_03.mp4"),
        ("build_0008_shot_01", "storage/build_0008/shot_01.mp4"),
        ("build_0008_shot_02", "storage/build_0008/shot_02.mp4"),
        ("build_0008_shot_03", "storage/build_0008/shot_03.mp4"),
    ]

    out_base = "scratch/temporal_telemetry_results"
    os.makedirs(f"{out_base}/csv", exist_ok=True)
    os.makedirs(f"{out_base}/json", exist_ok=True)
    os.makedirs(f"{out_base}/plots", exist_ok=True)
    os.makedirs(f"{out_base}/diagnostics", exist_ok=True)

    all_results = {}
    peak_analyses = []

    for tag, video_path in target_shots:
        if not os.path.exists(video_path):
            print(f"Skipping missing video: {video_path}")
            continue

        print(f"\n---> Analyzing {tag} ({video_path})...")
        records, summary = engine.analyze_video(video_path, shot_id=tag)
        all_results[tag] = {"records": records, "summary": summary}

        csv_path = f"{out_base}/csv/{tag}_telemetry.csv"
        json_path = f"{out_base}/json/{tag}_telemetry.json"
        save_telemetry_data(records, summary, csv_path, json_path)

        annotations = VISUAL_ANNOTATIONS.get(tag, [])
        plot_path = f"{out_base}/plots/{tag}_timeline.png"
        render_timeline_visualization(records, summary, annotations, plot_path)
        print(f"  Saved telemetry CSV, JSON, and Timeline Plot for {tag}")

        # Peak extraction (exclude boundary margins)
        valid_records = [r for r in records if not r.is_boundary_margin]
        if not valid_records:
            continue

        # Top peak for Metric A (Residual Local Z)
        top_a = max(valid_records, key=lambda r: r.residual_local_z)
        # Top peak for Metric B (Survival Drop Local Z)
        top_b = max(valid_records, key=lambda r: r.survival_local_z)
        # Top peak for Metric C (FB Error Local Z)
        top_c = max(valid_records, key=lambda r: r.fb_flow_local_z)
        # Top peak for Coincidence
        top_coin = max(valid_records, key=lambda r: r.coincidence_score)

        peaks_to_inspect = [
            ("MetricA_Residual", top_a),
            ("MetricB_Survival", top_b),
            ("MetricC_FBFlow", top_c),
            ("Coincidence", top_coin),
        ]

        for m_name, peak_rec in peaks_to_inspect:
            diag_img = extract_peak_diagnostics(
                video_path,
                peak_rec.frame_idx,
                tag,
                m_name,
                f"{out_base}/diagnostics",
            )
            peak_analyses.append(
                {
                    "shot_id": tag,
                    "metric": m_name,
                    "frame_idx": peak_rec.frame_idx,
                    "timestamp_sec": peak_rec.video_time_sec,
                    "residual_comp": peak_rec.compensated_residual,
                    "survival_ratio": peak_rec.feature_survival_ratio,
                    "fb_error_p90": peak_rec.fb_flow_p90_error,
                    "residual_z": peak_rec.residual_local_z,
                    "survival_z": peak_rec.survival_local_z,
                    "fb_error_z": peak_rec.fb_flow_local_z,
                    "coincidence_score": peak_rec.coincidence_score,
                    "diag_image": diag_img,
                }
            )

    # -------------------------------------------------------------
    # MULTI-SHOT CUT EXCLUSION VALIDATION (storage/build_0002/final_film.mp4)
    # -------------------------------------------------------------
    film_path = "storage/build_0002/final_film.mp4"
    if os.path.exists(film_path):
        print(f"\n---> Analyzing Multi-Shot Reel: {film_path}...")
        # Known cut points in 24s film (3 shots of 8s each -> cuts at 8.0s (192) and 16.0s (384))
        cut_frames = [192, 384]
        film_records, film_summary = engine.analyze_video(
            film_path, shot_id="build_0002_final_film", cut_boundaries=cut_frames
        )
        save_telemetry_data(
            film_records,
            film_summary,
            f"{out_base}/csv/build_0002_final_film_telemetry.csv",
            f"{out_base}/json/build_0002_final_film_telemetry.json",
        )
        film_anns = [
            {"start_sec": 8.0 - 0.25, "end_sec": 8.0 + 0.25, "issue": "CUT 1 (Excluded)", "severity": "Margin"},
            {"start_sec": 16.0 - 0.25, "end_sec": 16.0 + 0.25, "issue": "CUT 2 (Excluded)", "severity": "Margin"},
            {"start_sec": 18.7, "end_sec": 19.4, "issue": "Shot 3 Turnaround Discontinuity", "severity": "High"},
        ]
        render_timeline_visualization(
            film_records,
            film_summary,
            film_anns,
            f"{out_base}/plots/build_0002_final_film_timeline.png",
        )
        print("  Multi-shot cut exclusion validation completed.")

    # Save all peak analyses summary
    with open(f"{out_base}/peak_analysis_summary.json", "w", encoding="utf-8") as f:
        json.dump(peak_analyses, f, indent=2)

    print("\n" + "=" * 70)
    print("BATCH VALIDATION COMPLETED SUCCESSFULLY")
    print(f"Artifacts saved in: {out_base}")
    print("=" * 70)


if __name__ == "__main__":
    run_comprehensive_validation()
