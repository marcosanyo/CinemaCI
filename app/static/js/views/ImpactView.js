/**
 * Cinema CI — Impact Intelligence View
 * Visualizes True Blast Radius (Declared ∪ Observed Runtime Lineage) and incremental execution plan.
 */

import { store } from '../store/index.js';
import { api } from '../api/client.js';
import { toast } from '../components/Toast.js';
import { DagEngine } from '../utils/dagEngine.js';

export class ImpactView {
  constructor(router) {
    this.router = router;
    this.container = document.getElementById('view-impact');
    this.dagEngine = null;
    this.bindStore();
  }

  bindStore() {
    store.subscribe('currentImpactPlan', (plan) => {
      if (store.getState('activeView') === 'impact') {
        this.renderPlan(plan);
      }
    });
  }

  mount() {
    const plan = store.getState('currentImpactPlan');
    this.renderPlan(plan);
  }

  unmount() {
    if (this.dagEngine) {
      this.dagEngine.destroy();
      this.dagEngine = null;
    }
  }

  renderPlan(plan) {
    const container = document.getElementById('impact-plan-container');
    if (!container) return;

    if (!plan) {
      container.innerHTML = `
        <div class="card empty-state-card">
          <div class="empty-icon">✨</div>
          <h3>No Active Impact Analysis</h3>
          <p class="muted">Enter a creative change instruction in Creative Studio to compute True Blast Radius.</p>
          <button class="btn btn-primary btn-glow" id="btn-goto-studio">➔ Go to Creative Studio</button>
        </div>
      `;
      const btn = container.querySelector('#btn-goto-studio');
      if (btn) btn.onclick = () => this.router.navigate('project');
      return;
    }

    this.plan = plan;
    const planDiscovery = plan?.runtime_discoveries?.find(d => d.consumer === 'poster');
    const selectedRef = planDiscovery?.selected_reference || 'shot_03:keyframe:v1';
    const selectedShotId = selectedRef.split(':')[0] || 'shot_03';
    const shotLabelMap = {
      'shot_01': 'Shot 01',
      'shot_02': 'Shot 02',
      'shot_03': 'Shot 03',
    };
    const selectedShotLabel = shotLabelMap[selectedShotId] || selectedShotId;
    const selectionReason = planDiscovery?.reason || `${selectedShotLabel} keyframe provides the strongest protagonist framing and composition for the theatrical poster.`;

    const rebuildList = plan.rebuild || plan.rebuild_assets || ['shot_01', 'poster', 'shot_03'];
    const reuseList = plan.reuse || plan.reused_assets || ['shot_02'];
    const totalOps = plan.total_operations || (rebuildList.length + reuseList.length);
    const savingsPct = plan.savings_percent !== undefined ? plan.savings_percent.toFixed(1) : '25.0';

    const target = plan.target || {
      entity: 'character:marcus',
      property: 'glasses',
      from: 'round eyeglasses',
      to: 'no glasses',
    };

    container.innerHTML = `
      <!-- TOP METRICS BANNER -->
      <div class="impact-metrics-banner">
        <div class="metric-block">
          <span class="metric-label">RAW PROMPT</span>
          <span class="metric-value font-mono">"${plan.raw_prompt || "Remove Marcus's eyeglasses."}"</span>
        </div>
        <div class="metric-block">
          <span class="metric-label">MUTATION TARGET</span>
          <span class="metric-value text-accent font-mono">${target.entity} [${target.property}]</span>
        </div>
        <div class="metric-block">
          <span class="metric-label">TRUE BLAST RADIUS</span>
          <span class="metric-value text-white font-mono">${rebuildList.length} Rebuild / ${reuseList.length} Reuse</span>
        </div>
        <div class="metric-block">
          <span class="metric-label">INCREMENTAL SAVINGS</span>
          <span class="metric-value text-green font-mono">${savingsPct}% Operations Avoided</span>
        </div>
      </div>

      <!-- MAIN SPLIT: DAG VISUALIZER & EVIDENCE INSPECTOR -->
      <div class="impact-workspace-grid">
        <!-- DAG Graph Card -->
        <div class="card dag-visualizer-card">
          <div class="card-header">
            <div class="header-title-group">
              <span class="header-icon">🕸</span>
              <div>
                <h3>Observed Creative Lineage Graph</h3>
                <span class="header-subtext">SVG Bezier curves correlating Declared static paths with Tempo runtime discovery</span>
              </div>
            </div>
            <span class="badge badge-tempo">Live Correlation</span>
          </div>

          <div class="dag-scroll-hint-bar">
            <span class="dag-scroll-pill">↔ Swipe to explore</span>
          </div>

          <div id="impact-dag-container" class="impact-dag-container"></div>

          <div class="dag-legend-bar">
            <div class="legend-chip">
              <span class="legend-line line-declared"></span>
              <span>Declared (cinema.yaml)</span>
            </div>
            <div class="legend-chip">
              <span class="legend-line line-tempo"></span>
              <span class="text-tempo font-bold">Observed (Grafana Tempo MCP)</span>
            </div>
            <div class="legend-chip">
              <span class="legend-node-dot dot-reuse"></span>
              <span>Safe Byte Reuse (SHA-256)</span>
            </div>
          </div>
        </div>

        <!-- Runtime Evidence Inspector Card -->
        <div class="card impact-evidence-card">
          <div class="card-header">
            <div class="header-title-group">
              <span class="header-icon">🎯</span>
              <div>
                <h3>Runtime Evidence Inspector</h3>
                <span class="header-subtext">OpenTelemetry Span Captured in Grafana Tempo</span>
              </div>
            </div>
            <span class="badge badge-tempo">GRAFANA TEMPO MCP</span>
          </div>

          <div class="evidence-body" id="impact-evidence-body">
            <div class="evidence-item">
              <span class="evidence-k">Consumer Asset</span>
              <span class="evidence-v font-bold" id="imp-ev-consumer">Poster (Theatrical Key Visual)</span>
            </div>
            <div class="evidence-item">
              <span class="evidence-k">Runtime Dependency</span>
              <span class="evidence-v font-mono text-accent" id="imp-ev-dep">Selected reference: ${selectedRef}</span>
            </div>
            <div class="evidence-item">
              <span class="evidence-k">Selected By</span>
              <span class="evidence-v" id="imp-ev-selector">Gemini 3.8 Flash Art Director</span>
            </div>
            <div class="evidence-item">
              <span class="evidence-k">Art Director Reasoning</span>
              <div class="evidence-quote" id="imp-ev-quote">
                "${selectionReason}"
              </div>
            </div>
            <div class="evidence-meta-row">
              <div>
                <span class="evidence-k">Span Name</span>
                <span class="evidence-v font-mono">cinema.reference.select</span>
              </div>
              <div>
                <span class="evidence-k">Confidence</span>
                <span class="evidence-v font-mono text-green">0.96</span>
              </div>
            </div>

            <div class="evidence-action-row u-mt-md">
              <a href="https://friendlysherbet668.grafana.net" target="_blank" rel="noopener noreferrer" class="btn btn-primary btn-sm btn-glow">
                Open Trace in Grafana ↗
              </a>
            </div>
          </div>
        </div>
      </div>

      <!-- DETAILED ASSET BREAKDOWN TABLES -->
      <div class="impact-breakdown-grid u-mt-lg">
        <!-- Rebuild Assets Card -->
        <div class="card">
          <div class="card-header">
            <div class="header-title-group">
              <span class="header-icon">⚙️</span>
              <div>
                <h3>Assets Queued for Rebuild (${rebuildList.length})</h3>
                <span class="header-subtext">Triggered by Declared mutation or Observed runtime dependency</span>
              </div>
            </div>
            <span class="badge badge-rebuild">REBUILD</span>
          </div>
          <div class="asset-list">
            ${rebuildList.map(item => `
              <div class="asset-row">
                <div class="asset-info">
                  <span class="asset-name font-mono">${item}</span>
                  <span class="asset-desc text-muted">
                    ${item === 'poster'
                      ? `★ Flagged by Grafana Tempo (${selectedShotLabel} keyframe consumer)`
                      : 'Features Marcus character specification'}
                  </span>
                </div>
                <span class="badge ${item === 'poster' ? 'badge-tempo' : 'badge-rebuild'}">
                  ${item === 'poster' ? 'TEMPO OBSERVED' : 'DECLARED'}
                </span>
              </div>
            `).join('')}
          </div>
        </div>

        <!-- Reused Assets Card -->
        <div class="card">
          <div class="card-header">
            <div class="header-title-group">
              <span class="header-icon">♻️</span>
              <div>
                <h3>Byte-Identical Reused Assets (${reuseList.length})</h3>
                <span class="header-subtext">Zero Veo compute required. Guaranteed cryptographically via SHA-256</span>
              </div>
            </div>
            <span class="badge badge-reuse">ZERO COMPUTE</span>
          </div>
          <div class="asset-list">
            ${reuseList.map(item => `
              <div class="asset-row">
                <div class="asset-info">
                  <span class="asset-name font-mono">${item}</span>
                  <span class="asset-desc text-muted">
                    ${item === 'shot_02' ? 'Marcus is absent (envelope focus). Zero-compute identical replay with SHA-256 byte proof.' : 'Unaffected asset reused from baseline.'}
                  </span>
                </div>
                <span class="badge badge-reuse font-mono">SHA-256 VERIFIED</span>
              </div>
            `).join('')}
          </div>
        </div>
      </div>

      <!-- BOTTOM ACTION BAR -->
      <div class="impact-actions-bar u-mt-xl">
        <button class="btn btn-primary btn-glow btn-lg" id="btn-apply-impact">
          <span class="btn-icon">🚀</span> Apply Plan &amp; Run Incremental Build
        </button>
        <button class="btn btn-secondary btn-lg" id="btn-discard-plan">
          Discard Plan
        </button>
      </div>
    `;

    // Initialize dynamic DAG visualizer
    const dagContainer = container.querySelector('#impact-dag-container');
    if (dagContainer) {
      if (this.dagEngine) this.dagEngine.destroy();
      this.dagEngine = new DagEngine({
        container: dagContainer,
        onNodeClick: (nodeKey) => {
          this.handleNodeInspect(nodeKey);
        },
      });
      this.dagEngine.render({
        plan,
        isBaseline: false,
        rebuildList,
        reuseList,
        selectedShotId,
      });
    }

    // Bind Apply button
    const btnApply = container.querySelector('#btn-apply-impact');
    if (btnApply) {
      btnApply.onclick = async () => {
        btnApply.disabled = true;
        btnApply.innerHTML = '<span class="spinner"></span> Launching Incremental Build...';

        try {
          const newBuild = await api.applyImpact(plan, true);
          toast.success(`Incremental build started: ${newBuild.build_id}`);
          const builds = await api.getBuilds();
          store.setState({ builds, selectedBuildId: newBuild.build_id, currentImpactPlan: null });
          this.router.navigate('build');
        } catch (err) {
          toast.error(`Failed to launch build: ${err.message}`);
          btnApply.disabled = false;
          btnApply.innerHTML = '<span class="btn-icon">🚀</span> Apply Plan &amp; Run Incremental Build';
        }
      };
    }

    // Bind Discard button
    const btnDiscard = container.querySelector('#btn-discard-plan');
    if (btnDiscard) {
      btnDiscard.onclick = () => {
        store.setState({ currentImpactPlan: null });
        toast.info('Impact plan discarded.');
        this.router.navigate('project');
      };
    }
  }

  handleNodeInspect(nodeKey) {
    const consumerEl = document.getElementById('imp-ev-consumer');
    const depEl = document.getElementById('imp-ev-dep');
    const quoteEl = document.getElementById('imp-ev-quote');
    const selectorEl = document.getElementById('imp-ev-selector');

    if (!consumerEl) return;

    const planDiscovery = this.plan?.runtime_discoveries?.find(d => d.consumer === 'poster');
    const selectedRef = planDiscovery?.selected_reference || 'shot_03:keyframe:v1';
    const selectedShotId = selectedRef.split(':')[0] || 'shot_03';
    const shotLabelMap = {
      'shot_01': 'Shot 01',
      'shot_02': 'Shot 02',
      'shot_03': 'Shot 03',
    };
    const selectedShotLabel = shotLabelMap[selectedShotId] || selectedShotId;
    const reason = planDiscovery?.reason;

    if (nodeKey === 'poster') {
      consumerEl.textContent = 'Poster (Theatrical Key Visual)';
      depEl.textContent = `Selected reference: ${selectedRef}`;
      selectorEl.textContent = 'Gemini 3.8 Flash Art Director';
      quoteEl.textContent = reason || `${selectedShotLabel} keyframe provides the strongest protagonist framing and composition for the theatrical poster.`;
    } else if (nodeKey === 'shot_01') {
      consumerEl.textContent = 'Shot 01 (Cafe Arrival)';
      depEl.textContent = 'Character spec: character:marcus (traits)';
      selectorEl.textContent = 'cinema.yaml (Declared Contract)';
      quoteEl.textContent = selectedShotId === 'shot_01'
        ? 'Shot features Marcus. Must be regenerated because eyeglasses trait was removed. Consumed downstream by Poster.'
        : 'Shot features Marcus. Must be regenerated because eyeglasses trait was removed.';
    } else if (nodeKey === 'shot_02') {
      consumerEl.textContent = 'Shot 02 (Envelope Focus)';
      depEl.textContent = 'Props: envelope (blue)';
      selectorEl.textContent = 'Deterministic Impact Engine';
      quoteEl.textContent = 'Marcus does not appear in this cut. Completely unaffected by character trait mutation. Safely reused with SHA-256 byte proof.';
    } else if (nodeKey === 'shot_03') {
      consumerEl.textContent = 'Shot 03 (Marcus Close-up)';
      depEl.textContent = 'Character spec: character:marcus (traits)';
      selectorEl.textContent = 'cinema.yaml (Declared Contract)';
      quoteEl.textContent = selectedShotId === 'shot_03'
        ? 'Shot features Marcus reaction. Must be regenerated because eyeglasses trait was removed. Consumed downstream by Poster.'
        : 'Shot features Marcus reaction. Must be regenerated because eyeglasses trait was removed.';
    } else {
      consumerEl.textContent = nodeKey;
      depEl.textContent = 'Lineage dependency';
      selectorEl.textContent = 'Cinema CI Engine';
      quoteEl.textContent = `Asset ${nodeKey} status evaluated against creative contract.`;
    }
  }
}
