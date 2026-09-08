/**
 * Cinema CI — Cinematic Media & Video Player Component
 */

export class VideoPlayer {
  /**
   * @param {HTMLElement} container
   * @param {Object} options
   * @param {string} [options.src]
   * @param {string} [options.poster]
   * @param {boolean} [options.autoplay=false]
   * @param {boolean} [options.loop=true]
   */
  constructor(container, options = {}) {
    this.container = container;
    this.options = options;
    this.videoEl = null;
    this.init();
  }

  init() {
    this.container.innerHTML = `
      <div class="cinema-player-wrapper">
        <video class="cinema-video" playsinline preload="auto" ${this.options.loop ? 'loop' : ''}></video>
        <div class="cinema-player-overlay">
          <div class="cinema-controls-bar">
            <button class="player-btn btn-play" title="Play/Pause">▶</button>
            <div class="player-progress-wrap">
              <input type="range" class="player-seeker" min="0" max="100" value="0" step="0.1" />
            </div>
            <span class="player-time font-mono">00:00 / 00:00</span>
            <button class="player-btn btn-mute" title="Mute/Unmute">🔊</button>
            <button class="player-btn btn-fs" title="Fullscreen">⛶</button>
          </div>
        </div>
      </div>
    `;

    this.videoEl = this.container.querySelector('.cinema-video');
    this.btnPlay = this.container.querySelector('.btn-play');
    this.seeker = this.container.querySelector('.player-seeker');
    this.timeEl = this.container.querySelector('.player-time');
    this.btnMute = this.container.querySelector('.btn-mute');
    this.btnFs = this.container.querySelector('.btn-fs');

    this.setupEvents();
    if (this.options.src) {
      this.load(this.options.src);
    }
  }

  setupEvents() {
    const video = this.videoEl;

    this.btnPlay.onclick = () => {
      if (video.paused) {
        video.play();
        this.btnPlay.textContent = '❚❚';
      } else {
        video.pause();
        this.btnPlay.textContent = '▶';
      }
    };

    video.onplay = () => { this.btnPlay.textContent = '❚❚'; };
    video.onpause = () => { this.btnPlay.textContent = '▶'; };

    video.ontimeupdate = () => {
      if (!isNaN(video.duration) && video.duration > 0) {
        const pct = (video.currentTime / video.duration) * 100;
        this.seeker.value = pct;
        this.timeEl.textContent = `${this.formatTime(video.currentTime)} / ${this.formatTime(video.duration)}`;
      }
    };

    this.seeker.oninput = (e) => {
      if (!isNaN(video.duration)) {
        video.currentTime = (e.target.value / 100) * video.duration;
      }
    };

    this.btnMute.onclick = () => {
      video.muted = !video.muted;
      this.btnMute.textContent = video.muted ? '🔇' : '🔊';
    };

    this.btnFs.onclick = () => {
      const wrap = this.container.querySelector('.cinema-player-wrapper');
      if (!document.fullscreenElement) {
        wrap.requestFullscreen().catch(() => {});
      } else {
        document.exitFullscreen().catch(() => {});
      }
    };
  }

  load(src) {
    if (this.videoEl) {
      this.videoEl.src = src;
      this.videoEl.load();
    }
  }

  formatTime(secs) {
    const m = Math.floor(secs / 60);
    const s = Math.floor(secs % 60);
    return `${String(m).padStart(2, '0')}:${String(s).padStart(2, '0')}`;
  }
}

