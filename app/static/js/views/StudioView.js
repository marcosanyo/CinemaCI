/**
 * Cinema CI — Studio View (Creative Contract & Production Spec)
 */

import { store } from '../store/index.js';
import { api } from '../api/client.js';
import { toast } from '../components/Toast.js';
import { formatDate, getBuildStatusMeta } from '../utils/formatters.js';

export class StudioView {
  constructor(router) {
    this.router = router;
    this.container = document.getElementById('view-project');
    this.setupListeners();
    this.bindStore();
  }

  setupListeners() {
    // Scenario preset buttons
    const btnHeroCoat = document.getElementById('preset-hero-coat');
    if (btnHeroCoat) {
      btnHeroCoat.onclick = () => {
        const inputPrompt = document.getElementById('input-change-prompt');
        if (inputPrompt) inputPrompt.value = "Remove Marcus's eyeglasses.";
        this.setScenarioGuidance('hero');
        toast.info('Hero Scenario selected: Eyeglasses removal.');
      };
    }

    const btnReset = document.getElementById('preset-reset');
    if (btnReset) {
      btnReset.onclick = async () => {
        try {
          btnReset.disabled = true;
          const res = await api.resetContract();
          const newContract = res.contract || res;
          store.setState({ project: newContract });
          this.renderContract(newContract);
          this.setScenarioGuidance('reset');
          toast.success('Creative contract restored to pristine baseline (glasses: ON).');
        } catch (err) {
          toast.error(`Failed to reset contract: ${err.message}`);
        } finally {
          btnReset.disabled = false;
        }
      };
    }

    // Impact Analysis Button
    const btnAnalyze = document.getElementById('btn-analyze-impact');
    if (btnAnalyze) {
      btnAnalyze.onclick = async () => {
        const inputPrompt = document.getElementById('input-change-prompt');
        const prompt = inputPrompt ? inputPrompt.value.trim() : '';
        if (!prompt) {
          toast.warning('Please enter a creative change instruction.');
          return;
        }

        btnAnalyze.disabled = true;
        btnAnalyze.innerHTML = '<span class="spinner"></span> Analyzing True Blast Radius...';

        try {
          const plan = await api.analyzeImpact(prompt);
          store.setState({ currentImpactPlan: plan });
          toast.success('Impact analysis complete! True Blast Radius derived.');
          this.router.navigate('impact');
        } catch (err) {
          toast.error(`Impact analysis failed: ${err.message}`);
        } finally {
          btnAnalyze.disabled = false;
          btnAnalyze.innerHTML = '<span class="btn-icon">⚡</span> Analyze Change Impact (True Blast Radius)';
        }
      };
    }

    // Full Build Button
    const btnFullBuild = document.getElementById('btn-full-build');
    if (btnFullBuild) {
      btnFullBuild.onclick = async () => {
        btnFullBuild.disabled = true;
        btnFullBuild.innerHTML = '<span class="spinner"></span> Launching Full Build...';
        try {
          const newBuild = await api.startBuild();
          toast.success(`Full build started: ${newBuild.build_id}`);
          const builds = await api.getBuilds();
          store.setState({ builds, selectedBuildId: newBuild.build_id });
          this.router.navigate('build');
        } catch (err) {
          toast.error(`Build failed to start: ${err.message}`);
        } finally {
          btnFullBuild.disabled = false;
          btnFullBuild.textContent = 'Run Full Rebuild';
        }
      };
    }

    // Save Contract
    const btnSave = document.getElementById('btn-save-contract');
    if (btnSave) {
      btnSave.onclick = async () => {
        await this.saveContractFromInputs();
      };
    }

    // Add Scene Shot
    const btnAddShot = document.getElementById('btn-add-shot');
    if (btnAddShot) {
      btnAddShot.onclick = () => {
        this.addNewShotCard();
      };
    }
  }

  bindStore() {
    store.subscribe('project', (proj) => {
      if (proj) this.renderContract(proj);
    });

    store.subscribe('builds', (builds) => {
      this.renderTimeline(builds);
      this.renderPosterCard(builds);
      this.renderShotVideos(builds);
    });
  }

  mount() {
    this.setScenarioGuidance('hero');
    // Initial fetch if needed
    if (!store.getState('project')) {
      api.getProject().then(p => store.setState({ project: p })).catch(() => {});
    }
    if (store.getState('builds').length === 0) {
      api.getBuilds().then(b => store.setState({ builds: b })).catch(() => {});
    } else {
      this.renderPosterCard(store.getState('builds'));
      this.renderShotVideos(store.getState('builds'));
    }
  }

  renderPosterCard(builds) {
    const container = document.getElementById('shot-cards-container');
    if (!container) return;
    const list = Array.isArray(builds) ? builds : [];
    const selId = store.getState('selectedBuildId');
    const ordered = selId
      ? [...list.filter(b => b.build_id === selId), ...list.filter(b => b.build_id !== selId)]
      : list;
    const withPoster = ordered.find(b => {
      const p = (b.deliverables || []).find(d => d.artifact_id === 'poster');
      return p && p.status !== 'failed' && p.sha256;
    });
    let card = document.getElementById('studio-poster-card');
    if (!withPoster) {
      if (card) card.remove();
      return;
    }
    const poster = withPoster.deliverables.find(d => d.artifact_id === 'poster');
    const posterUrl = `/api/builds/${withPoster.build_id}/poster/video`;
    const selRef = (poster.details && (poster.details.selected_reference
      || (poster.details.selected_shot_id ? `${poster.details.selected_shot_id}:keyframe:v1` : null))) || '';
    if (!card) {
      card = document.createElement('div');
      card.id = 'studio-poster-card';
      card.style.cssText = 'background:var(--bg-surface-0);border:1px solid var(--border-subtle);border-radius:var(--radius-md);padding:14px;display:flex;flex-direction:column;gap:10px;margin-top:12px;';
      container.after(card);
    }
    if (card.dataset.src !== posterUrl) {
      card.dataset.src = posterUrl;
      card.innerHTML = `
        <div class="shot-card-header">
          <span class="shot-badge">🎨 POSTER (Theatrical Key Visual · ${withPoster.build_id})</span>
        </div>
        <video src="${posterUrl}" muted loop playsinline preload="metadata"
          title="Theatrical poster — click to play/pause"
          style="width:100%;aspect-ratio:16/9;object-fit:cover;border-radius:var(--radius-sm);background:#000;cursor:pointer;"></video>
        <div class="shot-meta-row">
          <span class="shot-pill">SHA-256: ${poster.sha256.slice(0, 8)}</span>
          ${selRef ? `<span class="shot-pill">Source: ${selRef}</span>` : ''}
        </div>`;
      const v = card.querySelector('video');
      if (v) v.onclick = () => { if (v.paused) v.play().catch(() => {}); else v.pause(); };
    }
  }

  setScenarioGuidance(key) {
    const badgeEl = document.getElementById('guidance-badge');
    const titleEl = document.getElementById('guidance-title');
    const descEl = document.getElementById('guidance-desc');
    const noteEl = document.getElementById('guidance-sync-note');
    const bannerEl = document.getElementById('scenario-guidance');

    document.querySelectorAll('.preset-btn').forEach(btn => btn.classList.remove('active'));

    if (key === 'hero') {
      document.getElementById('preset-hero-coat')?.classList.add('active');
      if (badgeEl) { badgeEl.textContent = 'Hero Scenario'; badgeEl.className = 'guidance-badge'; }
      if (titleEl) titleEl.textContent = 'Remove Eyeglasses (Incremental Rebuild)';
      if (descEl) descEl.innerHTML = 'Director requests removing Marcus\'s glasses. Gemini 3.8 Flash &amp; Tempo runtime traces derive True Blast Radius: Rebuild <strong>Shot 01, Shot 03, Poster</strong> | Byte-identical reuse <strong>Shot 02</strong> (1 of 3 video-generation operations avoided, 33.3%).';
      if (noteEl) noteEl.innerHTML = 'ℹ️ <strong>Workflow:</strong> Natural language intent does not overwrite <code>cinema.yaml</code> directly. Clicking <em>"Analyze Change Impact"</em> ➔ <em>"Execute Incremental Build"</em> will autonomously mutate the contract and trigger the minimal rebuild.';
      if (bannerEl) bannerEl.style.borderLeftColor = 'var(--accent-cyan)';
    } else if (key === 'reset') {
      document.getElementById('preset-reset')?.classList.add('active');
      if (badgeEl) { badgeEl.textContent = 'Baseline Contract'; badgeEl.className = 'guidance-badge'; }
      if (titleEl) titleEl.textContent = 'Contract Restored to Baseline';
      if (descEl) descEl.innerHTML = '<code>cinema.yaml</code> has been restored to default baseline: Marcus wears stylish thin-rimmed round eyeglasses, envelope is blue, and all scene prompts are synchronized.';
      if (noteEl) noteEl.innerHTML = '✅ You can now click <em>"Remove Eyeglasses (Incremental Rebuild)"</em> to test the incremental CI pipeline from a clean, verified state.';
      if (bannerEl) bannerEl.style.borderLeftColor = 'var(--accent-indigo)';
    }
  }

  renderContract(projectData) {
    if (!projectData) return;

    // Title & Tagline
    const titleEl = document.getElementById('project-title');
    if (titleEl && projectData.project?.title) {
      titleEl.textContent = projectData.project.title;
    }

    // Character Bible (Marcus)
    const marcus = projectData.characters?.marcus;
    if (marcus && marcus.traits) {
      const coatInput = document.getElementById('input-marcus-coat');
      const hairInput = document.getElementById('input-marcus-hair');
      const glassesInput = document.getElementById('input-marcus-glasses');

      if (coatInput) coatInput.value = marcus.traits.coat || 'black coat';
      if (hairInput) hairInput.value = marcus.traits.hair || 'short fade haircut';
      if (glassesInput) glassesInput.value = marcus.traits.glasses || 'no glasses';
    }

    // Props
    const envelope = projectData.props?.envelope;
    if (envelope) {
      const propColorInput = document.getElementById('input-prop-envelope-color');
      if (propColorInput) propColorInput.value = envelope.color || 'blue';
    }

    // Shots Container
    const shotsContainer = document.getElementById('shot-cards-container');
    const badge = document.getElementById('shot-count-badge');
    const shots = projectData.shots || [];

    if (badge) badge.textContent = `${shots.length} Scene Shots`;

    if (shotsContainer) {
      shotsContainer.innerHTML = shots.map((shot, idx) => `
        <div class="shot-card" data-shot-id="${shot.id}">
          <div class="shot-card-header">
            <span class="shot-badge">SHOT 0${idx + 1} (${shot.id})</span>
            <button class="btn-icon-danger btn-delete-shot" title="Delete shot" data-idx="${idx}">&times;</button>
          </div>
          <div class="shot-field">
            <label class="field-sublabel">Action &amp; Narrative</label>
            <input type="text" class="form-input shot-action-input" value="${shot.action || ''}" placeholder="Character action..." />
          </div>
          <div class="shot-field">
            <label class="field-sublabel">Prompt Description</label>
            <textarea class="form-textarea shot-desc-input" rows="2">${shot.description || ''}</textarea>
          </div>
          <div class="shot-meta-row">
            <span class="shot-pill">Camera: ${shot.camera || 'Eye level'}</span>
            <span class="shot-pill">Duration: ${shot.duration_sec || 5.0}s</span>
          </div>
        </div>
      `).join('');

      // Setup delete shot listeners
      shotsContainer.querySelectorAll('.btn-delete-shot').forEach(btn => {
        btn.onclick = (e) => {
          const idx = parseInt(e.target.dataset.idx, 10);
          const current = store.getState('project');
          if (current && current.shots) {
            current.shots.splice(idx, 1);
            store.setState({ project: { ...current } });
            toast.info('Shot removed from sequence.');
          }
        };
      });

      this.renderShotVideos(store.getState('builds'));
    }
  }

  pickMediaBuild(builds) {
    const list = Array.isArray(builds) ? builds : [];
    const hasUsableShot = (b) => (b.shots || []).some(s => s.sha256 && s.status !== 'failed');
    const selId = store.getState('selectedBuildId');
    if (selId) {
      const sel = list.find(b => b.build_id === selId);
      if (sel && hasUsableShot(sel)) return sel;
    }
    return list.find(hasUsableShot) || null;
  }

  renderShotVideos(builds) {
    const container = document.getElementById('shot-cards-container');
    if (!container) return;
    const mediaBuild = this.pickMediaBuild(builds);
    container.querySelectorAll('.shot-card[data-shot-id]').forEach(card => {
      const shotId = card.dataset.shotId;
      const shot = mediaBuild ? (mediaBuild.shots || []).find(s => s.shot_id === shotId) : null;
      const usable = shot && shot.sha256 && shot.status !== 'failed';
      const url = usable ? `/api/builds/${mediaBuild.build_id}/shots/${shotId}/video` : null;
      let vid = card.querySelector('video[data-studio-shot]');
      if (!url) {
        if (vid) vid.remove();
        return;
      }
      if (!vid) {
        vid = document.createElement('video');
        vid.dataset.studioShot = shotId;
        vid.muted = true;
        vid.loop = true;
        vid.playsInline = true;
        vid.preload = 'metadata';
        vid.title = `${shotId} — latest build ${mediaBuild.build_id} (click to play/pause)`;
        vid.style.cssText = 'width:100%;aspect-ratio:16/9;object-fit:cover;border-radius:var(--radius-sm);background:#000;cursor:pointer;margin-bottom:2px;';
        vid.onclick = () => { if (vid.paused) vid.play().catch(() => {}); else vid.pause(); };
        card.prepend(vid);
      }
      if (vid.dataset.src !== url) {
        vid.dataset.src = url;
        vid.src = url;
        vid.load();
      }
    });
  }

  addNewShotCard() {
    const current = store.getState('project') || { shots: [] };
    const nextIdx = (current.shots?.length || 0) + 1;
    const newShot = {
      id: `shot_0${nextIdx}`,
      description: `Cinematic follow shot of Marcus in cafe environment.`,
      action: 'Marcus steps into the dim light of the doorway.',
      camera: 'Medium tracking shot, 35mm lens, shallow depth of field',
      duration_sec: 5.0,
      characters: ['marcus'],
      props: { envelope: { present: true } },
    };

    current.shots = current.shots || [];
    current.shots.push(newShot);
    store.setState({ project: { ...current } });
    toast.success(`Added Shot 0${nextIdx} to production reel.`);
  }

  async saveContractFromInputs() {
    const current = store.getState('project');
    if (!current) return;

    const coat = document.getElementById('input-marcus-coat')?.value || 'black coat';
    const hair = document.getElementById('input-marcus-hair')?.value || 'short fade haircut';
    const glasses = document.getElementById('input-marcus-glasses')?.value || 'no glasses';
    const propColor = document.getElementById('input-prop-envelope-color')?.value || 'blue';

    if (!current.characters) current.characters = {};
    if (!current.characters.marcus) current.characters.marcus = { name: 'Marcus', description: '', traits: {} };
    current.characters.marcus.traits = { coat, hair, glasses };

    if (!current.props) current.props = {};
    if (!current.props.envelope) current.props.envelope = { name: 'Blue Envelope', description: '' };
    current.props.envelope.color = propColor;

    // Collect shot cards inputs
    const shotCards = document.querySelectorAll('.shot-card');
    shotCards.forEach((card, idx) => {
      const action = card.querySelector('.shot-action-input')?.value;
      const desc = card.querySelector('.shot-desc-input')?.value;
      if (current.shots && current.shots[idx]) {
        current.shots[idx].action = action || current.shots[idx].action;
        current.shots[idx].description = desc || current.shots[idx].description;
      }
    });

    try {
      await api.saveContract(current);
      store.setState({ project: { ...current } });
      const statusEl = document.getElementById('save-status');
      if (statusEl) {
        statusEl.textContent = '✓ Saved successfully';
        statusEl.className = 'save-status text-green';
        setTimeout(() => { statusEl.textContent = ''; }, 3000);
      }
      toast.success('Creative contract specification saved.');
    } catch (err) {
      toast.error(`Save failed: ${err.message}`);
    }
  }

  renderTimeline(builds) {
    const timelineEl = document.getElementById('build-timeline');
    if (!timelineEl) return;

    if (!builds || builds.length === 0) {
      timelineEl.innerHTML = '<div class="muted">No builds executed yet.</div>';
      return;
    }

    timelineEl.innerHTML = builds.map(b => {
      const meta = getBuildStatusMeta(b.status);
      const isSelected = b.build_id === store.getState('selectedBuildId');
      return `
        <div class="timeline-card ${isSelected ? 'is-selected' : ''}" data-build-id="${b.build_id}" role="button" tabindex="0">
          <div class="timeline-header">
            <span class="timeline-build-id font-mono">${b.build_id}</span>
            <span class="badge ${meta.badgeClass}">${meta.label}</span>
          </div>
          <div class="timeline-meta">
            <span class="timeline-time">${formatDate(b.created_at)}</span>
            <span class="timeline-duration">${b.build_duration_sec ? `${b.build_duration_sec.toFixed(1)}s` : '—'}</span>
          </div>
          <div class="timeline-stats">
            <span class="text-green font-mono">${b.tests_passed || 0}/${b.tests_total || (b.tests_passed || 25)} tests</span>
            ${b.operations_avoided ? `<span class="timeline-savings font-mono text-accent">⚡ ${b.operations_avoided} ops avoided</span>` : ''}
          </div>
        </div>
      `;
    }).join('');

    timelineEl.querySelectorAll('.timeline-card').forEach(card => {
      card.onclick = () => {
        const bId = card.dataset.buildId;
        store.setState({ selectedBuildId: bId });
        this.router.navigate('build');
      };
    });
  }
}

