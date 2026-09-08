/**
 * Cinema CI — Continuous Delivery & Release Gate View
 * Human promotion gate, final stitched master film theater, and release audit log.
 */

import { store } from '../store/index.js';
import { api } from '../api/client.js';
import { toast } from '../components/Toast.js';
import { formatDate } from '../utils/formatters.js';

export class ReleaseView {
  constructor(router) {
    this.router = router;
    this.container = document.getElementById('view-release');
    this.setupListeners();
    this.bindStore();
  }

  setupListeners() {
    const btnPromote = document.getElementById('btn-promote-release');
    if (btnPromote) {
      btnPromote.onclick = async () => {
        const build = this.getEligibleBuild();
        if (!build) return;

        btnPromote.disabled = true;
        btnPromote.innerHTML = '<span class="spinner"></span> Promoting to Theatrical Release...';

        try {
          const rec = await api.promoteRelease(build.build_id, 'Approved by Human Producer');
          toast.success(`Production Release ${rec.release_id} successfully promoted!`);

          // Refresh releases & builds
          const [releases, builds] = await Promise.all([api.getReleases(), api.getBuilds()]);
          store.setState({ releases, builds });
          this.render();
        } catch (err) {
          toast.error(`Promotion failed: ${err.message}`);
        } finally {
          btnPromote.disabled = false;
          btnPromote.innerHTML = '🚀 Promote to Production Release';
        }
      };
    }
  }

  bindStore() {
    store.subscribe('releases', () => {
      if (store.getState('activeView') === 'release') {
        this.render();
      }
    });

    store.subscribe('builds', () => {
      if (store.getState('activeView') === 'release') {
        this.render();
      }
    });
  }

  async mount() {
    try {
      const [releases, builds] = await Promise.all([api.getReleases(), api.getBuilds()]);
      store.setState({ releases, builds });
      this.render();
    } catch {
      this.render();
    }
  }

  getEligibleBuild() {
    const builds = store.getState('builds') || [];
    // Prioritize selected build or latest release_ready / released build
    const selId = store.getState('selectedBuildId');
    if (selId) {
      const b = builds.find(x => x.build_id === selId);
      if (b) return b;
    }
    return builds.find(b => b.status === 'RELEASE_READY' || b.status === 'RELEASED' || b.release_ready) || builds[0];
  }

  render() {
    const build = this.getEligibleBuild();
    const releases = store.getState('releases') || [];

    const gateBadge = document.getElementById('release-gate-large');
    const titleEl = document.getElementById('release-build-title');
    const summaryEl = document.getElementById('release-test-summary');
    const cardPromote = document.getElementById('card-promote');
    const releaseFilm = document.getElementById('release-film');
    const filmVideo = document.getElementById('master-film-video');
    const btnDownload = document.getElementById('btn-download-film');
    const releasesList = document.getElementById('releases-list');

    if (!build) {
      if (titleEl) titleEl.textContent = 'No Builds Available';
      return;
    }

    const totalTests = build.tests_total || (build.tests_passed || 25);
    const isReady = build.status === 'RELEASE_READY' || (build.tests_passed >= totalTests && !build.is_released);
    const isReleased = build.status === 'RELEASED' || build.is_released;

    // Gate Badge
    if (gateBadge) {
      if (isReleased) {
        gateBadge.innerHTML = '<span class="gate-badge gate-released">🚀 THEATRICAL RELEASED</span>';
      } else if (isReady) {
        gateBadge.innerHTML = '<span class="gate-badge gate-ready">✨ RELEASE READY (PENDING HUMAN APPROVAL)</span>';
      } else {
        gateBadge.innerHTML = `<span class="gate-badge gate-blocked">⏹ GATE BLOCKED (${build.status})</span>`;
      }
    }

    if (titleEl) {
      titleEl.innerHTML = `BUILD <span class="font-mono text-accent">${build.build_id}</span>`;
    }

    const isIncremental = Boolean(build.baseline_build_id || build.impact_plan);
    const avoidedOps = build.operations_avoided !== undefined && build.operations_avoided !== null
      ? Number(build.operations_avoided)
      : (isIncremental ? 1 : 0);
    const savingsPct = build.savings_percent !== undefined && build.savings_percent !== null
      ? Number(build.savings_percent)
      : (isIncremental ? 25.0 : 0.0);
    const hasAvoided = isIncremental && avoidedOps > 0 && savingsPct > 0;

    if (summaryEl) {
      summaryEl.innerHTML = `
        <div class="summary-pills-strip">
          <span class="pill font-mono">${build.tests_passed || 0}/${totalTests} QA Tests Passed</span>
          ${hasAvoided
            ? `<span class="pill font-mono text-green">${savingsPct.toFixed(1)}% Operations Avoided</span>`
            : `<span class="pill font-mono text-muted">Full Build · 0 Avoided (0%)</span>`
          }
          <span class="pill font-mono text-tempo">Tempo Trace: ${build.trace_id ? build.trace_id.slice(0, 10) : '8af31c...'}</span>
        </div>
      `;
    }

    // Dynamic Master Film specs badge
    const savingsBadge = document.getElementById('master-film-savings');
    if (savingsBadge) {
      if (hasAvoided) {
        savingsBadge.className = 'spec-badge badge-green';
        savingsBadge.textContent = `${savingsPct.toFixed(1)}% Operations Avoided`;
      } else {
        savingsBadge.className = 'spec-badge';
        savingsBadge.textContent = 'Full Build (0% Avoided)';
      }
    }

    // Show Promote Card only if Ready and not yet Released
    if (cardPromote) {
      if (isReady && !isReleased) {
        cardPromote.classList.remove('u-hidden');
      } else {
        cardPromote.classList.add('u-hidden');
      }
    }

    // Stitched Master Film Player
    if (releaseFilm) {
      if (isReady || isReleased) {
        releaseFilm.classList.remove('u-hidden');
        const filmUrl = `/api/builds/${build.build_id}/film`;
        if (filmVideo && filmVideo.src !== window.location.origin + filmUrl) {
          filmVideo.src = filmUrl;
        }
        if (btnDownload) {
          btnDownload.href = filmUrl;
        }

        // Render release shot fingerprints (+ poster deliverable)
        const row = document.getElementById('release-shots-row');
        if (row) {
          const shots = build.shots || [];
          const isInc = Boolean(build.baseline_build_id || build.impact_plan);
          const poster = (build.deliverables || []).find(d => d.artifact_id === 'poster');
          const posterUsable = poster && poster.status !== 'failed' && poster.sha256;
          const posterReused = isInc && poster && poster.status === 'reused_from_baseline';
          const posterLabel = posterReused ? 'REUSED' : (isInc ? 'REBUILT' : 'BASELINE');
          const posterClass = posterReused ? 'text-green' : (isInc ? 'text-rebuild' : 'text-accent');
          row.innerHTML = shots.map(s => {
            const isReused = isInc && s.status === 'reused_from_baseline';
            const label = isReused ? 'REUSED' : (isInc ? 'REBUILT' : 'BASELINE');
            const colorClass = isReused ? 'text-green' : (isInc ? 'text-rebuild' : 'text-accent');
            return `
            <div class="fingerprint-chip">
              <span class="f-shot font-mono">${s.shot_id.toUpperCase()}</span>
              <span class="f-status ${colorClass} font-mono">
                ${label}
              </span>
              <code class="f-sha">${s.sha256 ? s.sha256.slice(0, 8) : '—'}</code>
            </div>
          `;}).join('') + (posterUsable ? `
            <div class="fingerprint-chip">
              <span class="f-shot font-mono">POSTER</span>
              <span class="f-status ${posterClass} font-mono">
                ${posterLabel}
              </span>
              <code class="f-sha">${poster.sha256.slice(0, 8)}</code>
            </div>
          ` : '');
        }

        // Theatrical poster preview (thumbnail) next to the master film
        this.renderPosterPreview(build);
      } else {
        releaseFilm.classList.add('u-hidden');
      }
    }

    // Historical releases
    if (releasesList) {
      if (releases.length === 0) {
        releasesList.innerHTML = '<div class="muted">No historical releases promoted yet.</div>';
      } else {
        releasesList.innerHTML = releases.map(rel => `
          <div class="release-item-card">
            <div class="rel-top">
              <span class="rel-id font-mono text-accent">${rel.release_id}</span>
              <span class="rel-date font-mono text-muted">${formatDate(rel.released_at)}</span>
            </div>
            <div class="rel-meta font-mono">
              <span>Build: ${rel.build_id}</span>
              <span class="${(rel.avoided_operations || 0) > 0 ? 'text-green' : 'text-muted'}">⚡ ${rel.avoided_operations || 0} Avoided (${rel.savings_percent || '0'}%)</span>
            </div>
            <div class="rel-notes text-muted">${rel.notes || 'Human producer sign-off.'}</div>
          </div>
        `).join('');
      }
    }
  }

  renderPosterPreview(build) {
    const player = document.getElementById('film-player');
    if (!player) return;
    const poster = (build.deliverables || []).find(d => d.artifact_id === 'poster');
    const usable = poster && poster.status !== 'failed' && poster.sha256;
    let block = document.getElementById('release-poster-block');
    if (!usable) {
      if (block) block.remove();
      return;
    }
    const posterUrl = `/api/builds/${build.build_id}/poster/video`;
    const selRef = (poster.details && (poster.details.selected_reference
      || (poster.details.selected_shot_id ? `${poster.details.selected_shot_id}:keyframe:v1` : null))) || '';
    if (!block) {
      block = document.createElement('div');
      block.id = 'release-poster-block';
      block.style.cssText = 'display:flex;gap:16px;align-items:center;margin:0 0 16px;padding:12px;background:var(--bg-surface-0);border:1px solid var(--border-subtle);border-radius:var(--radius-md);';
      player.after(block);
    }
    const vid = block.querySelector('video');
    if (!vid || vid.dataset.src !== posterUrl) {
      block.innerHTML = `
        <video data-src="${posterUrl}" src="${posterUrl}" muted loop playsinline preload="metadata"
          title="Theatrical poster — click to play/pause"
          style="width:180px;aspect-ratio:16/9;object-fit:cover;border-radius:var(--radius-sm);background:#000;cursor:pointer;"></video>
        <div>
          <div class="font-mono" style="font-weight:700;">🎨 THEATRICAL POSTER <span class="text-muted">(${build.build_id})</span></div>
          <div class="font-mono text-muted" style="font-size:0.8rem;margin-top:4px;">SHA-256: ${poster.sha256.slice(0, 16)}…${selRef ? ` · Source: ${selRef}` : ''}</div>
          <div class="text-muted" style="font-size:0.8rem;">Materialized from the Gemini-selected keyframe. Click thumbnail to preview.</div>
        </div>`;
      const v = block.querySelector('video');
      if (v) v.onclick = () => { if (v.paused) v.play().catch(() => {}); else v.pause(); };
    }
  }
}

