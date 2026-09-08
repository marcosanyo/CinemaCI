/**
 * Cinema CI — Build Inspector View
 * Comprehensive multi-stage QA test matrix, asset deliverable fingerprints, and live log streamer.
 */

import { store } from '../store/index.js';
import { api } from '../api/client.js';
import { toast } from '../components/Toast.js';
import { modal } from '../components/Modal.js';
import { formatDate, formatDuration, getBuildStatusMeta } from '../utils/formatters.js';

export class BuildView {
  constructor(router) {
    this.router = router;
    this.container = document.getElementById('view-build');
    this.pollTimer = null;
    this.activeFilter = 'all';
    this._currentBuildId = null;
    this._lastShotsKey = null;
    this._lastLogsCount = -1;
    this._lastTestsKey = null;

    this.setupListeners();
    this.bindStore();
  }

  setupListeners() {
    // Back to Studio
    const btnBack = document.getElementById('btn-back-project');
    if (btnBack) {
      btnBack.onclick = () => this.router.navigate('project');
    }

    // Tempo link
    const btnTempo = document.getElementById('btn-view-tempo-trace-detail');
    if (btnTempo) {
      btnTempo.onclick = () => this.router.navigate('telemetry');
    }

    // Cancel detail build
    const btnCancel = document.getElementById('btn-cancel-detail-build');
    if (btnCancel) {
      btnCancel.onclick = async () => {
        const bId = store.getState('selectedBuildId');
        if (bId) {
          try {
            await api.cancelBuild(bId);
            toast.warning(`Build ${bId} canceled.`);
            this.refreshBuild(bId);
          } catch (err) {
            toast.error(`Cancel failed: ${err.message}`);
          }
        }
      };
    }

    // Promote Release button
    const btnPromote = document.getElementById('btn-promote-release-detail');
    if (btnPromote) {
      btnPromote.onclick = () => this.router.navigate('release');
    }

      // Repair button
      const btnRepair = document.getElementById('btn-repair');
      if (btnRepair) {
        btnRepair.onclick = async () => {
          const bId = store.getState('selectedBuildId');
          if (!bId) return;

          btnRepair.disabled = true;
          btnRepair.innerHTML = '<span class="spinner"></span> Dispatching ADK Repair Agent...';

          try {
            await api.repairBuild(bId);
            toast.success(`Autonomous surgical repair started for ${bId}.`);
            this.router.navigate('agent');
          } catch (err) {
            toast.error(`Repair failed: ${err.message}`);
          } finally {
            btnRepair.disabled = false;
            btnRepair.innerHTML = '🤖 Repair with ADK Agent';
          }
        };
      }

      // Build selector dropdown
      const selector = document.getElementById('build-selector');
      if (selector) {
        selector.onchange = (e) => {
          const bId = e.target.value;
          if (bId) {
            store.setState({ selectedBuildId: bId });
            this.renderBuild(bId);
          }
        };
      }
    }

    bindStore() {
      store.subscribe('selectedBuildId', (buildId) => {
        if (store.getState('activeView') === 'build') {
          this.renderBuild(buildId);
        }
      });

      store.subscribe('builds', (builds) => {
        if (builds && builds.length > 0) {
          this.updateBuildSelector(builds);
          if (store.getState('activeView') === 'build') {
            const currentId = store.getState('selectedBuildId');
            const latest = builds[0];
            // If current build was blocked and a repair build finished as RELEASE_READY, auto-switch
            if (latest && latest.repair_of && latest.repair_of === currentId && latest.status === 'RELEASE_READY') {
              store.setState({ selectedBuildId: latest.build_id });
            }
          }
        }
      });
    }

    async mount() {
      let builds = store.getState('builds') || [];
      try {
        const fresh = await api.getBuilds();
        if (fresh && fresh.length > 0) {
          builds = fresh;
          store.setState({ builds });
        }
      } catch {}

      let buildId = store.getState('selectedBuildId');
      if (builds && builds.length > 0) {
        const latest = builds[0];
        // If no build selected, or if the latest is a repair of currently selected,
        // or if latest is RELEASE_READY and newer, default to latest:
        if (!buildId || (latest.repair_of && latest.repair_of === buildId) || (latest.build_id > buildId && latest.status === 'RELEASE_READY')) {
          buildId = latest.build_id;
          store.setState({ selectedBuildId: buildId });
        }
      }

      this.updateBuildSelector(builds);
      this.renderBuild(buildId);
    }

    updateBuildSelector(builds) {
      const selector = document.getElementById('build-selector');
      if (!selector || !builds || builds.length === 0) return;

      const currentId = store.getState('selectedBuildId') || builds[0].build_id;
      const optionsHtml = builds.map((b, idx) => {
        const isLatest = idx === 0 ? ' [Latest]' : '';
        const isRepair = b.repair_of ? ` (Repair of ${b.repair_of})` : '';
        const score = b.tests_total ? ` [${b.tests_passed}/${b.tests_total}]` : '';
        return `<option value="${b.build_id}" ${b.build_id === currentId ? 'selected' : ''}>
          ${b.build_id}: ${b.status}${score}${isRepair}${isLatest}
        </option>`;
      }).join('');

      selector.innerHTML = optionsHtml;
    }

  unmount() {
    this.stopPolling();
    this._currentBuildId = null;
    this._lastShotsKey = null;
    this._lastLogsCount = -1;
    this._lastTestsKey = null;
  }

  startPolling(buildId) {
    this.stopPolling();
    this.pollTimer = setInterval(async () => {
      try {
        const updated = await api.getBuild(buildId);
        // Update in store builds list
        const builds = store.getState('builds') || [];
        const idx = builds.findIndex(b => b.build_id === buildId);
        if (idx !== -1) builds[idx] = updated;
        else builds.unshift(updated);
        store.setState({ builds });

        this.renderBuildData(updated);

        const meta = getBuildStatusMeta(updated.status);
        if (meta.isTerminal) {
          this.stopPolling();
        }
      } catch {
        this.stopPolling();
      }
    }, 1500);
  }

  stopPolling() {
    if (this.pollTimer) {
      clearInterval(this.pollTimer);
      this.pollTimer = null;
    }
  }

  async renderBuild(buildId) {
    if (!buildId) {
      const title = document.getElementById('build-title');
      if (title) title.textContent = 'No build selected';
      return;
    }

    if (this._currentBuildId !== buildId) {
      this._currentBuildId = buildId;
      this._lastShotsKey = null;
      this._lastLogsCount = -1;
      this._lastTestsKey = null;
    }

    try {
      const build = await api.getBuild(buildId);
      this.renderBuildData(build);

      const meta = getBuildStatusMeta(build.status);
      if (!meta.isTerminal) {
        this.startPolling(buildId);
      } else {
        this.stopPolling();
      }
    } catch (err) {
      toast.error(`Failed to load build: ${err.message}`);
    }
  }

  async refreshBuild(buildId) {
    const updated = await api.getBuild(buildId);
    this.renderBuildData(updated);
  }

  renderBuildData(build) {
    if (!build) return;

    // Header & Title
    const titleEl = document.getElementById('build-title');
    const badgeEl = document.getElementById('build-status-badge');
    const savingsEl = document.getElementById('build-savings-banner');
    const btnCancel = document.getElementById('btn-cancel-detail-build');
    const btnPromote = document.getElementById('btn-promote-release-detail');
    const btnRepair = document.getElementById('btn-repair');

    const meta = getBuildStatusMeta(build.status);

    if (titleEl) {
      titleEl.innerHTML = `BUILD <span class="font-mono text-accent">${build.build_id}</span>`;
    }

    const selector = document.getElementById('build-selector');
    if (selector && selector.value !== build.build_id) {
      selector.value = build.build_id;
    }

    if (badgeEl) {
      badgeEl.textContent = meta.label;
      badgeEl.className = `build-status-badge badge ${meta.badgeClass}`;
    }

    if (btnCancel) {
      if (!meta.isTerminal) btnCancel.classList.remove('u-hidden');
      else btnCancel.classList.add('u-hidden');
    }

    // Repair Notice Banner
    const noticeEl = document.getElementById('build-repair-notice');
    if (noticeEl) {
      const builds = store.getState('builds') || [];
      const newerRepair = builds.find(b => b.repair_of === build.build_id);
      if (newerRepair) {
        noticeEl.classList.remove('u-hidden');
        noticeEl.innerHTML = `
          <span>🛠 Repair Build Available: <strong>${newerRepair.build_id}</strong> (${newerRepair.status} - ${newerRepair.tests_passed}/${newerRepair.tests_total} Passed)</span>
          <button type="button" id="btn-switch-repair-build">Switch to ${newerRepair.build_id} ➔</button>
        `;
        const btnSwitch = noticeEl.querySelector('#btn-switch-repair-build');
        if (btnSwitch) {
          btnSwitch.onclick = () => {
            store.setState({ selectedBuildId: newerRepair.build_id });
            this.renderBuild(newerRepair.build_id);
          };
        }
      } else if (build.repair_of) {
        noticeEl.classList.remove('u-hidden');
        noticeEl.innerHTML = `
          <span>🛠 Surgical Repair of <strong>${build.repair_of}</strong> (Regressions resolved)</span>
        `;
      } else {
        noticeEl.classList.add('u-hidden');
      }
    }

    // Savings Banner
    if (savingsEl) {
      if (build.operations_avoided && build.operations_avoided > 0) {
        const shotList = build.shots || [];
        const reusedShots = shotList.filter(s => s.status === 'reused_from_baseline').length;
        const avoidPct = shotList.length > 0 ? ((reusedShots / shotList.length) * 100).toFixed(1) : '0.0';
        savingsEl.classList.remove('u-hidden');
        savingsEl.innerHTML = `
          <span class="savings-sparkle">⚡</span>
          <strong>Incremental Efficiency:</strong>
          <span>${avoidPct}% Video Gen Avoided (${build.operations_avoided} asset reused via SHA-256 byte verification)</span>
        `;
      } else {
        savingsEl.classList.add('u-hidden');
      }
    }

    // Action buttons visibility
    if (btnPromote) {
      if (build.status === 'RELEASE_READY' || build.release_ready) {
        btnPromote.classList.remove('u-hidden');
      } else {
        btnPromote.classList.add('u-hidden');
      }
    }

    if (btnRepair) {
      if (build.status === 'BLOCKED' || build.regressions > 0) {
        btnRepair.classList.remove('u-hidden');
      } else {
        btnRepair.classList.add('u-hidden');
      }
    }

    // Test Summary Counters
    const passedEl = document.getElementById('tests-passed');
    const totalEl = document.getElementById('tests-total');
    const breakdownEl = document.getElementById('test-category-breakdown');

    const totalTests = build.tests_total || (build.tests_passed || 25);
    const passedTests = build.tests_passed || 0;

    if (passedEl) passedEl.textContent = passedTests;
    if (totalEl) totalEl.textContent = totalTests;

    if (breakdownEl) {
      const techPassed = build.technical_tests_passed || (passedTests > 15 ? 15 : passedTests);
      const techTotal = build.technical_tests_total || 15;
      const creativePassed = build.creative_tests_passed || (passedTests - techPassed);
      const creativeTotal = build.creative_tests_total || 10;

      breakdownEl.innerHTML = `
        <div class="cat-pill">
          <span class="cat-title">Technical QA (PyAV):</span>
          <span class="font-mono text-green">${techPassed}/${techTotal}</span>
        </div>
        <div class="cat-pill">
          <span class="cat-title">Creative Contract (Gemini):</span>
          <span class="font-mono text-green">${creativePassed}/${creativeTotal}</span>
        </div>
        ${build.regressions > 0 ? `
          <div class="cat-pill cat-regression">
            <span class="cat-title">Regressions:</span>
            <span class="font-mono text-danger font-bold">${build.regressions}</span>
          </div>
        ` : ''}
      `;
    }

    // Deliverables / Shots Grid
    this.renderShotsAndDeliverables(build);

    // QA Test Results Matrix
    this.renderTestMatrix(build.test_results || []);

    // Logs Stream
    this.renderLogs(build.logs || []);
  }

  renderShotsAndDeliverables(build) {
    const rowEl = document.getElementById('shots-row');
    if (!rowEl) return;

    const shots = build.shots || [];
    const deliverables = (build.deliverables || []).filter(
      d => !['audio', 'subtitle'].includes(d.artifact_id.toLowerCase()) && !d.artifact_id.toLowerCase().includes('reference')
    );

    const items = [
      ...shots.map(s => {
        const hasVideo = !!(s.sha256 && s.status !== 'failed' && s.status !== 'generating' && s.status !== 'pending' && s.status !== 'rebuilding');
        return {
          type: 'shot',
          id: s.shot_id,
          title: s.shot_id.toUpperCase(),
          status: s.status,
          sha: s.sha256,
          model: s.model_used || 'Google Veo 3.1',
          hasVideo,
          videoUrl: `/api/builds/${build.build_id}/shots/${s.shot_id}/video`,
        };
      }),
      ...deliverables.map(d => {
        const isPoster = d.artifact_id.toLowerCase() === 'poster';
        const hasVideo = isPoster ? !!(d.sha256 && d.status !== 'failed') : false;
        return {
          type: 'deliverable',
          id: d.artifact_id,
          title: d.artifact_id.replace(/_/g, ' ').toUpperCase(),
          status: d.status,
          sha: d.sha256,
          model: d.model_used || 'Gemini 3.8 Flash',
          hasVideo,
          videoUrl: isPoster ? `/api/builds/${build.build_id}/poster/video` : null,
        };
      }),
    ];

    const currentKey = `${build.build_id}|` + items.map(item => `${item.id}:${item.status}:${item.sha}:${item.hasVideo}`).join('|');
    if (this._lastShotsKey === currentKey && rowEl.children.length === items.length) {
      return; // Shots DOM is already up to date; preserve active video playback!
    }
    this._lastShotsKey = currentKey;

    const isIncremental = Boolean(build.baseline_build_id || build.impact_plan);

    rowEl.innerHTML = items.map(item => {
      const isReused = isIncremental && (item.status === 'reused_from_baseline' || item.status === 'REUSED');
      const isGenerating = item.status === 'generating' || item.status === 'rebuilding' || (!item.sha && item.status !== 'failed' && !isReused);

      let thumbContent = '';
      if (item.type === 'shot' || item.id === 'poster') {
        if (item.hasVideo) {
          thumbContent = `
            <video src="${item.videoUrl}" muted playsinline loop preload="metadata"></video>
            <div class="thumb-hover-overlay">▶ Hover to Play</div>
          `;
        } else if (isGenerating) {
          thumbContent = `
            <div class="thumb-generating-spinner">
              <span class="spinner"></span>
              <span>${item.id === 'poster' ? 'Composing Poster (Gemini + FFmpeg)...' : 'Generating with Veo 3.1...'}</span>
            </div>
          `;
        } else {
          thumbContent = `
            <div class="thumb-icon-placeholder">${item.id === 'poster' ? '🎨' : '🎬'}</div>
          `;
        }
      } else {
        thumbContent = `
          <div class="thumb-icon-placeholder">📁</div>
        `;
      }

      const badgeLabel = isReused ? 'REUSED' : (isIncremental ? 'REBUILT' : 'BASELINE');
      const badgeStyle = isReused ? 'badge-reuse' : (isIncremental ? 'badge-rebuild' : 'badge-accent');

      return `
        <div class="shot-preview-card ${isReused ? 'card-reused' : 'card-rebuilt'}" data-item-id="${item.id}">
          <div class="shot-preview-thumb">
            ${thumbContent}
            <span class="thumb-badge ${badgeStyle}">
              ${badgeLabel}
            </span>
          </div>
          <div class="shot-preview-body">
            <div class="shot-title-line">
              <span class="shot-name font-bold font-mono">${item.title}</span>
            </div>
            <div class="shot-meta-line text-muted">
              <span>Model: ${item.model}</span>
            </div>
            <div class="shot-sha-line font-mono">
              <span class="sha-label">SHA-256:</span>
              <code class="sha-val" title="${item.sha || ''}">${item.sha ? item.sha.slice(0, 8) : (isGenerating ? 'Generating...' : '—')}</code>
              ${isReused ? '<span class="text-green" title="Identical Cryptographic Proof">✓</span>' : ''}
            </div>
          </div>
        </div>
      `;
    }).join('');

    // Setup hover-to-play with safe event listeners
    rowEl.querySelectorAll('.shot-preview-card').forEach(card => {
      const video = card.querySelector('video');
      const thumb = card.querySelector('.shot-preview-thumb');
      if (video && thumb) {
        thumb.onmouseenter = () => {
          const playPromise = video.play();
          if (playPromise !== undefined) {
            playPromise.catch(() => {});
          }
        };
        thumb.onmouseleave = () => {
          video.pause();
        };
      }
    });
  }

  renderTestMatrix(tests) {
    const listEl = document.getElementById('test-results-list');
    if (!listEl) return;

    // Filter out any legacy audio test results
    const cleanTests = (tests || []).filter(
      t => t.test_id !== 'technical.audio' && !t.test_id?.includes('audio')
    );

    const testsKey = `${cleanTests.length}:${this.activeFilter}:${cleanTests.map(t => `${t.test_id}:${t.status}`).join(',')}`;
    if (this._lastTestsKey === testsKey && listEl.children.length > 0) {
      return;
    }
    this._lastTestsKey = testsKey;

    if (cleanTests.length === 0) {
      listEl.innerHTML = '<div class="muted">No test evaluations recorded for this build.</div>';
      return;
    }

    listEl.innerHTML = `
      <div class="test-filters-bar u-mb-md">
        <button class="filter-chip ${this.activeFilter === 'all' ? 'active' : ''}" data-filter="all">All (${cleanTests.length})</button>
        <button class="filter-chip ${this.activeFilter === 'PASS' ? 'active' : ''}" data-filter="PASS">Passed (${cleanTests.filter(t => t.status === 'PASS').length})</button>
        <button class="filter-chip ${this.activeFilter === 'REGRESSION' ? 'active' : ''}" data-filter="REGRESSION">Regressions (${cleanTests.filter(t => t.status === 'REGRESSION' || t.status === 'FAIL').length})</button>
        <button class="filter-chip ${this.activeFilter === 'technical' ? 'active' : ''}" data-filter="technical">Technical QA</button>
        <button class="filter-chip ${this.activeFilter === 'creative' ? 'active' : ''}" data-filter="creative">Creative Contract</button>
      </div>
      <div class="tests-table-wrap">
        <table class="tests-table">
          <thead>
            <tr>
              <th>Status</th>
              <th>Test ID / Scope</th>
              <th>Category</th>
              <th>Evaluator</th>
              <th>Contract Expected</th>
              <th>Observed Evidence</th>
            </tr>
          </thead>
          <tbody>
            ${cleanTests
              .filter(t => {
                if (this.activeFilter === 'all') return true;
                if (this.activeFilter === 'PASS') return t.status === 'PASS';
                if (this.activeFilter === 'REGRESSION') return t.status === 'REGRESSION' || t.status === 'FAIL';
                if (this.activeFilter === 'technical') return t.category === 'technical';
                if (this.activeFilter === 'creative') return t.category === 'creative';
                return true;
              })
              .map(t => {
                const isPass = t.status === 'PASS';
                const isRegress = t.status === 'REGRESSION' || t.status === 'FAIL';
                return `
                  <tr class="test-row ${isRegress ? 'row-regress' : ''}" data-test-id="${t.test_id}">
                    <td class="col-status">
                      <span class="badge ${isPass ? 'badge-pass' : 'badge-regression'}">${t.status}</span>
                    </td>
                    <td class="col-id font-mono">
                      <div class="test-id-text">${t.test_id}</div>
                      <div class="test-scope-text text-muted">${t.scope}</div>
                    </td>
                    <td class="col-cat">
                      <span class="cat-tag">${t.category}</span>
                    </td>
                    <td class="col-eval font-mono text-muted">
                      ${t.evaluator}
                    </td>
                    <td class="col-expected">${t.expected}</td>
                    <td class="col-observed">
                      <span class="${isRegress ? 'text-danger font-bold' : ''}">${t.observed}</span>
                    </td>
                  </tr>
                `;
              }).join('')}
          </tbody>
        </table>
      </div>
    `;

    // Filter chip listeners
    listEl.querySelectorAll('.filter-chip').forEach(btn => {
      btn.onclick = (e) => {
        this.activeFilter = e.target.dataset.filter;
        this._lastTestsKey = null;
        this.renderTestMatrix(tests);
      };
    });

    // Row click for detail modal
    listEl.querySelectorAll('.test-row').forEach(tr => {
      tr.onclick = () => {
        const tId = tr.dataset.testId;
        const test = cleanTests.find(x => x.test_id === tId);
        if (test) this.showTestDetailModal(test);
      };
    });
  }

  showTestDetailModal(test) {
    const isPass = test.status === 'PASS';
    modal.open({
      title: `QA Test: ${test.test_id}`,
      icon: isPass ? '✓' : '⚠️',
      content: `
        <div class="modal-qa-details">
          <div class="modal-detail-row">
            <span class="detail-k">Status</span>
            <span class="badge ${isPass ? 'badge-pass' : 'badge-regression'}">${test.status}</span>
          </div>
          <div class="modal-detail-row">
            <span class="detail-k">Scope</span>
            <span class="detail-v font-mono">${test.scope}</span>
          </div>
          <div class="modal-detail-row">
            <span class="detail-k">Evaluator Engine</span>
            <span class="detail-v font-mono">${test.evaluator} (${test.evaluator_model || 'Standard'})</span>
          </div>
          <div class="modal-detail-row">
            <span class="detail-k">Expected Value</span>
            <div class="detail-box">${test.expected}</div>
          </div>
          <div class="modal-detail-row">
            <span class="detail-k">Observed Value</span>
            <div class="detail-box ${!isPass ? 'box-danger' : ''}">${test.observed}</div>
          </div>
          ${test.error_details ? `
            <div class="modal-detail-row">
              <span class="detail-k">Error Diagnostics</span>
              <div class="detail-box box-danger font-mono">${test.error_details}</div>
            </div>
          ` : ''}
        </div>
      `,
    });
  }

  renderLogs(logs) {
    const container = document.getElementById('build-logs-list');
    if (!container) return;

    const cleanLogs = (logs || []).filter(
      l => !l.message?.toLowerCase().includes('audio') && !l.message?.toLowerCase().includes('subtitle')
    );

    if (this._lastLogsCount === cleanLogs.length && container.children.length > 0) {
      return;
    }
    this._lastLogsCount = cleanLogs.length;

    if (cleanLogs.length === 0) {
      container.innerHTML = '<div class="muted">No execution logs emitted.</div>';
      return;
    }

    container.innerHTML = cleanLogs.map(l => `
      <div class="log-line log-${(l.level || 'INFO').toLowerCase()}">
        <span class="log-ts font-mono text-muted">${formatDate(l.timestamp)}</span>
        <span class="log-stage font-mono">[${l.stage || 'BUILD'}]</span>
        <span class="log-lvl lvl-${(l.level || 'INFO').toLowerCase()}">${l.level}</span>
        <span class="log-msg">${l.message}</span>
      </div>
    `).join('');
  }
}

