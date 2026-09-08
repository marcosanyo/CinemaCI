"""Generate fixture videos with audio for Cinema CI testing."""

import os
import numpy as np

FIXTURES_DIR = "fixtures/blue-envelope"
os.makedirs(FIXTURES_DIR, exist_ok=True)

FPS = 24
DURATION = 5  # seconds
W, H = 1280, 720
SAMPLE_RATE = 44100


def make_video_with_audio(path, bg_color, label=""):
    """Create a video with audio using av."""
    import av

    container = av.open(path, mode='w')

    # Video stream
    video_stream = container.add_stream('libx264', rate=FPS)
    video_stream.width = W
    video_stream.height = H
    video_stream.pix_fmt = 'yuv420p'

    # Audio stream
    audio_stream = container.add_stream('aac', rate=SAMPLE_RATE)
    audio_stream.layout = 'stereo'

    frames = FPS * DURATION
    samples_per_frame = SAMPLE_RATE // FPS

    for i in range(frames):
        # Video frame
        img = np.full((H, W, 3), bg_color, dtype=np.uint8)
        # Subtle animated gradient
        t = i / frames
        bar_h = int(60 + 20 * np.sin(t * np.pi * 2))
        bar_color = [min(255, c + 30) for c in bg_color]
        img[H - bar_h:, :] = bar_color

        frame = av.VideoFrame.from_ndarray(img, format='rgb24')
        for packet in video_stream.encode(frame):
            container.mux(packet)

        # Audio frame (quiet ambient tone)
        t_audio = np.linspace(
            i * samples_per_frame / SAMPLE_RATE,
            (i + 1) * samples_per_frame / SAMPLE_RATE,
            samples_per_frame,
            dtype=np.float32,
        )
        # Soft sine wave
        tone = (np.sin(2 * np.pi * 220 * t_audio) * 0.1).astype(np.float32)
        audio_data = np.stack([tone, tone])  # stereo

        audio_frame = av.AudioFrame.from_ndarray(audio_data, format='fltp', layout='stereo')
        audio_frame.rate = SAMPLE_RATE
        audio_frame.pts = i * samples_per_frame
        for packet in audio_stream.encode(audio_frame):
            container.mux(packet)

    # Flush
    for packet in video_stream.encode():
        container.mux(packet)
    for packet in audio_stream.encode():
        container.mux(packet)

    container.close()
    print(f"Created: {path}")


# Shot 01 — Alice enters (dark warm tones)
make_video_with_audio(
    os.path.join(FIXTURES_DIR, "shot_01.mp4"),
    [30, 25, 20],
    "Shot 01"
)

# Shot 02 — Alice picks up envelope
make_video_with_audio(
    os.path.join(FIXTURES_DIR, "shot_02.mp4"),
    [35, 30, 25],
    "Shot 02"
)

# Shot 03 — Cafe ambiance / establishing (no Alice)
make_video_with_audio(
    os.path.join(FIXTURES_DIR, "shot_03.mp4"),
    [25, 22, 20],
    "Shot 03"
)
make_video_with_audio(
    os.path.join(FIXTURES_DIR, "shot_03_pass.mp4"),
    [25, 22, 20],
    "Shot 03 Pass"
)
make_video_with_audio(
    os.path.join(FIXTURES_DIR, "shot_03_fail.mp4"),
    [80, 20, 20],
    "Shot 03 Fail"
)

# Shot 04 — Alice exits cafe
make_video_with_audio(
    os.path.join(FIXTURES_DIR, "shot_04.mp4"),
    [28, 24, 22],
    "Shot 04"
)
make_video_with_audio(
    os.path.join(FIXTURES_DIR, "shot_04_pass.mp4"),
    [28, 24, 22],
    "Shot 04 Pass"
)
make_video_with_audio(
    os.path.join(FIXTURES_DIR, "shot_04_fail.mp4"),
    [85, 22, 20],
    "Shot 04 Fail"
)

# Poster / Key Visual
make_video_with_audio(
    os.path.join(FIXTURES_DIR, "poster.mp4"),
    [32, 28, 24],
    "Theatrical Poster Key Visual"
)

print("All fixtures created with audio!")
