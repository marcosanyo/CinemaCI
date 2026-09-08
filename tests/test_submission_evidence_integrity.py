"""Unit tests for hackathon submission evidence integrity.

These tests are intentionally local and deterministic. They protect the invariants that
strict mode must never reinterpret Cinema CI's local semantic span mirror as real Tempo
evidence, and that the poster materializer consumes an actual source video.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from app.engine import _materialize_poster_from_selected_shot
from app.impact.observed import normalize_trace_spans


class StrictTempoEvidenceTests(unittest.TestCase):
    def test_strict_mode_rejects_local_semantic_span_mirror(self):
        mirror = {
            "spans": [
                {
                    "name": "cinema.reference.select",
                    "attributes": {
                        "cinema.consumer": "poster:v1",
                        "cinema.reference.selected": "shot_01:keyframe:v1",
                    },
                }
            ]
        }
        with patch.dict(os.environ, {"STRICT_MODE": "true", "CINEMA_STRICT_MODE": "1"}, clear=False):
            self.assertEqual(normalize_trace_spans(mirror), [])

    def test_strict_mode_accepts_span_with_real_trace_identifiers(self):
        tempo_like = {
            "spans": [
                {
                    "name": "cinema.reference.select",
                    "traceId": "4bf92f3577b34da6a3ce929d0e0e4736",
                    "spanId": "00f067aa0ba902b7",
                    "attributes": {
                        "cinema.reference.selected": "shot_01:keyframe:v1",
                    },
                }
            ]
        }
        with patch.dict(os.environ, {"STRICT_MODE": "true", "CINEMA_STRICT_MODE": "1"}, clear=False):
            spans = normalize_trace_spans(tempo_like)
        self.assertEqual(len(spans), 1)
        self.assertEqual(spans[0]["trace_id"], "4bf92f3577b34da6a3ce929d0e0e4736")
        self.assertEqual(spans[0]["span_id"], "00f067aa0ba902b7")

    def test_non_strict_mode_allows_local_mirror_for_development(self):
        mirror = {
            "spans": [
                {
                    "name": "cinema.reference.select",
                    "attributes": {"cinema.reference.selected": "shot_01:keyframe:v1"},
                }
            ]
        }
        with patch.dict(os.environ, {"STRICT_MODE": "false", "CINEMA_STRICT_MODE": "0"}, clear=False):
            spans = normalize_trace_spans(mirror)
        self.assertEqual(len(spans), 1)
        self.assertEqual(spans[0]["name"], "cinema.reference.select")


@unittest.skipUnless(shutil.which("ffmpeg"), "ffmpeg is required for poster materialization test")
class PosterMaterializationTests(unittest.TestCase):
    def test_poster_is_materialized_from_actual_source_video(self):
        with tempfile.TemporaryDirectory() as tmp:
            source = os.path.join(tmp, "shot_01.mp4")
            poster = os.path.join(tmp, "poster.mp4")

            subprocess.run(
                [
                    "ffmpeg", "-y", "-loglevel", "error",
                    "-f", "lavfi", "-i", "color=size=320x180:rate=24:color=black",
                    "-t", "1", "-c:v", "libx264", "-pix_fmt", "yuv420p", source,
                ],
                check=True,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.PIPE,
                timeout=30,
            )

            with patch.dict(os.environ, {"STRICT_MODE": "true", "CINEMA_STRICT_MODE": "1"}, clear=False):
                _materialize_poster_from_selected_shot(source, poster)

            self.assertTrue(os.path.exists(poster))
            self.assertGreater(os.path.getsize(poster), 0)


if __name__ == "__main__":
    unittest.main()
