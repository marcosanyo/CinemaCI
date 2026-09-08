/**
 * Cinema CI — Dynamic DAG Lineage Graph Engine
 * Renders an interactive 3-stage Directed Acyclic Graph (DAG) with animated SVG Bezier curves.
 * Dynamically correlates Manifest Declared Dependencies with Grafana Tempo Observed Runtime Edges.
 */

export class DagEngine {
  /**
   * @param {Object} options
   * @param {HTMLElement} options.container
   * @param {Function} [options.onNodeClick]
   */
  constructor(options) {
    this.container = options.container;
    this.onNodeClick = options.onNodeClick || (() => {});
    this.activeNodeId = null;
    this.resizeObserver = null;
    this.edges = [];
  }

  /**
   * Builds and renders the DAG based on dynamic plan and build data.
   * @param {Object} params
   * @param {Object} [params.plan] - ImpactPlan
   * @param {Object} [params.build] - Build record
   * @param {Array<string>} [params.rebuildList]
   * @param {Array<string>} [params.reuseList]
   * @param {Array<Object>} [params.runtimeDiscoveries]
   */
  render(params = {}) {
    if (!this.container) return;

    const plan = params.plan || {};
    const build = params.build || {};
    const isBaseline = params.isBaseline ?? (!build?.baseline_build_id && !build?.impact_plan);
    const isBuilding = build?.status === 'BUILDING' || build?.status === 'queued';
    const rebuildList = params.rebuildList || plan.rebuild || plan.rebuild_assets || (isBaseline ? ['shot_01', 'shot_02', 'shot_03', 'poster'] : ['shot_01', 'poster', 'shot_03']);
    const reuseList = params.reuseList || plan.reuse || plan.reused_assets || (isBaseline ? [] : ['shot_02']);

    const target = params.target || plan.target || (isBaseline ? {
      entity: 'cinema.yaml',
      property: 'project',
      from: 'contract',
      to: 'v1',
    } : {
      entity: 'character:marcus',
      property: 'glasses',
      from: 'round eyeglasses',
      to: 'no glasses',
    });

    const getShotState = (id) => {
      const s = build?.shots?.find(x => x.shot_id === id);
      const sha = s?.sha256 ? s.sha256.slice(0, 8) : null;
      const isReused = !isBaseline && (s?.status === 'reused_from_baseline' || reuseList.includes(id));
      const isGenerated = s?.status === 'generated' || Boolean(sha);

      if (isBuilding) {
        if (isGenerated) {
          return {
            action: isReused ? 'REUSED' : (isBaseline ? 'BASELINE GEN' : 'DONE'),
            badgeClass: isReused ? 'badge-reuse' : (isBaseline ? 'badge-accent' : 'badge-pass'),
            meta: `Completed with Veo 3.1${sha ? ` (SHA: ${sha})` : ''}`,
            sha,
          };
        }
        // Determine if currently generating
        const prevId = id === 'shot_02' ? 'shot_01' : id === 'shot_03' ? 'shot_02' : null;
        const prevDone = prevId ? Boolean(build?.shots?.find(x => x.shot_id === prevId)?.sha256) : true;
        if (prevDone && !isGenerated) {
          return {
            action: 'BUILDING...',
            badgeClass: 'badge-running',
            meta: 'Generating with Veo 3.1 in Cloud...',
            sha: null,
          };
        }
        return {
          action: isBaseline ? 'BASELINE QUEUED' : 'QUEUED',
          badgeClass: 'badge-accent',
          meta: 'Awaiting pipeline execution',
          sha: null,
        };
      }

      if (isBaseline) {
        return {
          action: 'BASELINE GEN',
          badgeClass: 'badge-accent',
          meta: isGenerated ? `Veo 3.1 (SHA: ${sha || 'verified'})` : 'Features Scene in cinema.yaml',
          sha,
        };
      }

      if (isReused) {
        return {
          action: 'REUSE',
          badgeClass: 'badge-reuse',
          meta: sha ? 'Marcus absent · Zero-Compute Reused' : 'Marcus absent · Marked for Zero-Compute Reuse',
          sha: sha || null,
        };
      }

      return {
        action: 'REBUILD',
        badgeClass: 'badge-rebuild',
        meta: isGenerated ? `Rebuilt with Veo 3.1 (SHA: ${sha})` : 'Features Marcus · Rebuilt with Veo 3.1',
        sha,
      };
    };

    // Dynamically detect which shot Gemini selected as the poster keyframe
    const posterArt = build?.deliverables?.find(d => d.artifact_id === 'poster');
    const posterDetails = posterArt?.details || {};
    const planDiscovery = (params.runtimeDiscoveries || plan?.runtime_discoveries || [])?.find(d => d.consumer === 'poster');
    const planRef = planDiscovery?.selected_reference;

    const selectSpan = build?.spans?.find(sp => 
      sp.name === 'cinema.reference.select' || 
      sp.name?.includes('reference.select') ||
      Boolean(sp.attributes && sp.attributes['cinema.reference.selected'])
    );
    const spanRef = selectSpan?.attributes ? selectSpan.attributes['cinema.reference.selected'] : null;

    const selectedShotId = (
      params.selectedShotId
      || posterDetails.selected_shot_id
      || (posterDetails.selected_reference ? posterDetails.selected_reference.split(':')[0] : null)
      || (planRef ? planRef.split(':')[0] : null)
      || (spanRef ? String(spanRef).split(':')[0] : null)
      || 'shot_03'
    );

    const shotLabelMap = {
      'shot_01': 'Shot 01',
      'shot_02': 'Shot 02',
      'shot_03': 'Shot 03',
    };
    const selectedShotLabel = shotLabelMap[selectedShotId] || selectedShotId.replace('_', ' ').toUpperCase();

    const s1State = getShotState('shot_01');
    const s2State = getShotState('shot_02');
    const s3State = getShotState('shot_03');

    // Construct Stage 1 nodes: shots
    const stage1Nodes = [
      {
        id: 'node-shot_01',
        key: 'shot_01',
        title: 'Shot 01 (Cafe Arrival)',
        icon: '🎬',
        meta: s1State.meta,
        action: s1State.action,
        badgeClass: s1State.badgeClass,
        sha: s1State.sha,
        isKeyframe: selectedShotId === 'shot_01',
      },
      {
        id: 'node-shot_03',
        key: 'shot_03',
        title: 'Shot 03 (Marcus Closer Look)',
        icon: '🎬',
        meta: s3State.meta,
        action: s3State.action,
        badgeClass: s3State.badgeClass,
        sha: s3State.sha,
        isKeyframe: selectedShotId === 'shot_03',
      },
      {
        id: 'node-shot_02',
        key: 'shot_02',
        title: 'Shot 02 (Envelope Focus)',
        icon: '🎬',
        meta: s2State.meta,
        action: s2State.action,
        badgeClass: s2State.badgeClass,
        sha: s2State.sha,
        isKeyframe: selectedShotId === 'shot_02',
      },
    ];

    // Poster deliverable state
    let posterAction = isBaseline ? 'KEY VISUAL' : 'RUNTIME EDGE';
    let posterBadge = isBaseline ? 'badge-accent' : 'badge-tempo';
    let posterMeta = isBaseline
      ? `Keyframe Poster (Gemini 3.8 + Title Composition) · ${selectedShotLabel} keyframe`
      : `Observed via Grafana Tempo · ${selectedShotLabel} keyframe consumer`;
    if (isBuilding) {
      const posterDone = Boolean(posterArt?.sha256);
      posterAction = posterDone ? 'COMPOSED' : 'PENDING';
      posterBadge = posterDone ? 'badge-pass' : 'badge-accent';
      posterMeta = posterDone ? `Poster Composed (${selectedShotLabel} keyframe)` : `Awaiting ${selectedShotLabel} keyframe selection...`;
    }

    // Construct Stage 2 nodes: Deliverables
    const stage2Nodes = [
      {
        id: 'node-poster',
        key: 'poster',
        title: 'Poster (Theatrical Key Visual)',
        icon: '🎨',
        meta: posterMeta,
        action: posterAction,
        badgeClass: posterBadge,
        isTempoRuntime: !isBaseline,
        span: 'cinema.reference.select',
      },
      {
        id: 'node-master_film',
        key: 'master_film',
        title: 'Master Film Assembly',
        icon: '🎞️',
        meta: build?.master_film_path ? 'Master film packaged and ready' : 'Stitched Master Delivery Cut',
        action: build?.master_film_path ? 'RELEASE READY' : 'FINAL CUT',
        badgeClass: build?.master_film_path ? 'badge-pass' : 'badge-accent',
        isTempoRuntime: false,
      },
    ];

    this.container.innerHTML = `
      <div class="dag-wrapper" id="dag-wrapper">
        <svg id="dag-svg-canvas" class="dag-svg-canvas" xmlns="http://www.w3.org/2000/svg">
          <defs>
            <linearGradient id="edge-grad-cyan" x1="0%" y1="0%" x2="100%" y2="0%">
              <stop offset="0%" stop-color="#38bdf8" stop-opacity="0.8"/>
              <stop offset="100%" stop-color="#818cf8" stop-opacity="0.8"/>
            </linearGradient>
            <linearGradient id="edge-grad-tempo" x1="0%" y1="0%" x2="100%" y2="0%">
              <stop offset="0%" stop-color="#38bdf8" stop-opacity="0.9"/>
              <stop offset="100%" stop-color="#c084fc" stop-opacity="1"/>
            </linearGradient>
            <filter id="neon-glow-tempo" x="-30%" y="-30%" width="160%" height="160%">
              <feGaussianBlur stdDeviation="3" result="blur" />
              <feMerge>
                <feMergeNode in="blur" />
                <feMergeNode in="SourceGraphic" />
              </feMerge>
            </filter>
            <marker id="arrow-declared" viewBox="0 0 10 10" refX="8" refY="5" markerWidth="6" markerHeight="6" orient="auto">
              <path d="M 0 1.5 L 8 5 L 0 8.5 z" fill="#38bdf8"/>
            </marker>
            <marker id="arrow-tempo" viewBox="0 0 10 10" refX="8" refY="5" markerWidth="7" markerHeight="7" orient="auto">
              <path d="M 0 1 L 9 5 L 0 9 z" fill="#c084fc"/>
            </marker>
            <marker id="arrow-master" viewBox="0 0 10 10" refX="8" refY="5" markerWidth="6" markerHeight="6" orient="auto">
              <path d="M 0 1.5 L 8 5 L 0 8.5 z" fill="#818cf8"/>
            </marker>
          </defs>
          <g id="dag-edges-layer"></g>
        </svg>

        <div class="dag-grid">
          <!-- STAGE 0: ROOT INTENT -->
          <div class="dag-col stage-intent">
            <div class="dag-col-header">
              <span class="dag-step-tag">STAGE 0: ROOT INTENT</span>
              <h4>${isBaseline ? 'Specification Baseline' : 'Mutation Source'}</h4>
            </div>
            <div class="dag-node dag-node-root ${this.activeNodeId === (isBaseline ? 'cinema.yaml' : 'character:marcus') ? 'is-active' : ''}" id="node-root" data-node="${isBaseline ? 'cinema.yaml' : 'character:marcus'}" tabindex="0">
              <div class="node-icon-circle root-icon">${isBaseline ? '📜' : '👤'}</div>
              <div class="node-details">
                <div class="node-title">${isBaseline ? 'cinema.yaml' : (target.entity || 'Character (Marcus)')}</div>
                <div class="node-meta-line">${isBaseline ? 'Project Contract Baseline' : 'Visual Contract Mutation'}</div>
                <div class="node-mutation-pill">
                  ${isBaseline ? `
                    <span class="pill-k">mode:</span>
                    <span class="pill-from">contract</span>
                    <span class="pill-arrow">➔</span>
                    <span class="pill-to">v1</span>
                  ` : `
                    <span class="pill-k">${target.property || 'glasses'}:</span>
                    <span class="pill-from">${(target.from || 'round').toLowerCase()}</span>
                    <span class="pill-arrow">➔</span>
                    <span class="pill-to">${(target.to || 'none').toLowerCase()}</span>
                  `}
                </div>
              </div>
            </div>
          </div>

          <!-- STAGE 1: PRODUCTION ASSETS -->
          <div class="dag-col stage-assets">
            <div class="dag-col-header">
              <span class="dag-step-tag">STAGE 1: PRODUCTION ASSETS</span>
              <h4>Shots &amp; References</h4>
            </div>
            <div class="dag-nodes-stack">
              ${stage1Nodes.map(n => {
                const nodeClass = n.action === 'REUSE'
                  ? 'node-reuse'
                  : n.action === 'REBUILD'
                  ? 'node-rebuild'
                  : 'node-baseline';
                const iconClass = n.action === 'REUSE'
                  ? 'icon-reuse'
                  : n.action === 'REBUILD'
                  ? 'icon-rebuild'
                  : (n.action === 'BUILDING...' ? 'icon-running' : 'icon-baseline');
                const badgeClass = n.badgeClass || (
                  n.action === 'REUSE' ? 'badge-reuse' :
                  n.action === 'REBUILD' ? 'badge-rebuild' :
                  (n.action === 'BUILDING...' ? 'badge-running' : 'badge-accent')
                );
                return `
                <div class="dag-node ${nodeClass} ${this.activeNodeId === n.key ? 'is-active' : ''}" id="${n.id}" data-node="${n.key}" tabindex="0">
                  <div class="node-icon-circle ${iconClass}">${n.icon}</div>
                  <div class="node-details">
                    <div class="node-title">${n.title}</div>
                    <div class="node-meta-line">${n.meta}</div>
                    ${n.isKeyframe ? '<div class="node-keyframe-tag">★ Dynamic Keyframe Selected by Gemini</div>' : ''}
                    ${n.sha ? `<div class="node-sha-badge">SHA: <code>${n.sha}</code> ✓</div>` : ''}
                  </div>
                  <span class="node-action-badge ${badgeClass}">${n.action}</span>
                </div>
              `;}).join('')}
            </div>
          </div>

          <!-- STAGE 2: DOWNSTREAM DELIVERABLES -->
          <div class="dag-col stage-deliverables">
            <div class="dag-col-header">
              <span class="dag-step-tag tempo-tag">STAGE 2: RUNTIME LINEAGE</span>
              <h4>Downstream Deliverables</h4>
            </div>
            <div class="dag-nodes-stack">
              ${stage2Nodes.map(n => `
                <div class="dag-node ${n.isTempoRuntime ? 'node-tempo-runtime' : 'node-master'} ${this.activeNodeId === n.key ? 'is-active' : ''}" id="${n.id}" data-node="${n.key}" tabindex="0">
                  <div class="node-icon-circle ${n.isTempoRuntime ? 'icon-tempo' : 'icon-master'}">${n.icon}</div>
                  <div class="node-details">
                    <div class="node-title ${n.isTempoRuntime ? 'text-tempo' : ''}">${n.title}</div>
                    ${n.isTempoRuntime ? `
                      <div class="node-tempo-callout">
                        <span class="tempo-sparkle">⚡</span>
                        <strong>Discovered via Grafana Tempo MCP</strong>
                        <div class="tempo-sub">Hidden runtime dependency on ${selectedShotLabel}</div>
                      </div>
                      <div class="node-span-pill">Span: <code>${n.span}</code></div>
                    ` : `
                      <div class="node-meta-line">${n.meta}</div>
                    `}
                  </div>
                  <span class="node-action-badge ${n.badgeClass || (n.isTempoRuntime ? 'badge-tempo' : 'badge-accent')}">
                    ${n.action}
                  </span>
                </div>
              `).join('')}
            </div>
          </div>
        </div>
      </div>
    `;

    // Define connection edges
    if (isBaseline) {
      this.edges = [
        // Baseline declares all 3 shots
        { from: 'node-root', to: 'node-shot_01', type: 'declared' },
        { from: 'node-root', to: 'node-shot_02', type: 'declared' },
        { from: 'node-root', to: 'node-shot_03', type: 'declared' },

        // Poster consumes selected shot keyframe (runtime selection)
        { from: `node-${selectedShotId}`, to: 'node-poster', type: 'tempo', animated: true },

        // Deliverables to master film
        { from: 'node-shot_01', to: 'node-master_film', type: 'master' },
        { from: 'node-shot_02', to: 'node-master_film', type: 'master' },
        { from: 'node-shot_03', to: 'node-master_film', type: 'master' },
      ];
    } else {
      this.edges = [
        // Declared from Root to Rebuilt assets (Marcus appears in Shot 01 and Shot 03)
        { from: 'node-root', to: 'node-shot_01', type: 'declared' },
        { from: 'node-root', to: 'node-shot_03', type: 'declared' },

        // CRITICAL RUNTIME EDGE: Selected Shot -> Poster (Grafana Tempo Discovered!)
        { from: `node-${selectedShotId}`, to: 'node-poster', type: 'tempo', animated: true },

        // Deliverable assembly edges to Master Film
        { from: 'node-shot_01', to: 'node-master_film', type: 'master' },
        { from: 'node-shot_02', to: 'node-master_film', type: 'master' },
        { from: 'node-shot_03', to: 'node-master_film', type: 'master' },
      ];
    }

    // Setup event listeners
    this.attachEvents();

    // Draw initial SVG lines on next animation frame
    requestAnimationFrame(() => {
      this.drawEdges();
    });

    // Handle container resizing
    this.setupResizeObserver();
  }

  attachEvents() {
    this.container.onclick = (e) => {
      const nodeEl = e.target.closest('[data-node]');
      if (!nodeEl) return;
      const nodeKey = nodeEl.dataset.node;
      this.setActiveNode(nodeKey);
      this.onNodeClick(nodeKey);
    };
  }

  setActiveNode(nodeKey) {
    this.activeNodeId = nodeKey;
    this.container.querySelectorAll('.dag-node').forEach(el => {
      if (el.dataset.node === nodeKey) {
        el.classList.add('is-active');
      } else {
        el.classList.remove('is-active');
      }
    });
    this.drawEdges();
  }

  drawEdges() {
    const svg = this.container.querySelector('#dag-svg-canvas');
    const edgesLayer = this.container.querySelector('#dag-edges-layer');
    const wrapper = this.container.querySelector('#dag-wrapper');
    if (!svg || !edgesLayer || !wrapper) return;

    const wrapRect = wrapper.getBoundingClientRect();
    const width = Math.max(wrapper.offsetWidth, wrapper.scrollWidth, wrapRect.width);
    const height = Math.max(wrapper.offsetHeight, wrapper.scrollHeight, wrapRect.height);

    svg.setAttribute('width', width);
    svg.setAttribute('height', height);
    svg.setAttribute('viewBox', `0 0 ${width} ${height}`);

    edgesLayer.innerHTML = '';

    for (const edge of this.edges) {
      const fromEl = this.container.querySelector(`#${edge.from}`);
      const toEl = this.container.querySelector(`#${edge.to}`);
      if (!fromEl || !toEl) continue;

      const fRect = fromEl.getBoundingClientRect();
      const tRect = toEl.getBoundingClientRect();

      // Smart source and target vertical connection point offsets
      // Staggers multiple lines on shared nodes to prevent visual crowding
      let sourceOffsetY = 0;
      let targetOffsetY = 0;

      // Offsets for branching edges from Root
      if (edge.from === 'node-root') {
        if (edge.to === 'node-shot_01') sourceOffsetY = -8;
        else if (edge.to === 'node-shot_02') sourceOffsetY = 8;
        else sourceOffsetY = 0;
      }

      // Offsets for outgoing edges from Shot nodes
      if (edge.from.startsWith('node-shot_')) {
        if (edge.type === 'tempo') {
          sourceOffsetY = -6; // Tempo runtime edge leaves slightly upper
        } else if (edge.type === 'master') {
          sourceOffsetY = 6;  // Master cut edge leaves slightly lower
        }
      }

      // Offsets for converging edges into Master Film node
      if (edge.to === 'node-master_film') {
        if (edge.from === 'node-shot_01') targetOffsetY = -12;
        else if (edge.from === 'node-shot_03') targetOffsetY = 0;
        else if (edge.from === 'node-shot_02') targetOffsetY = 12;
      }

      // Coordinates strictly relative to wrapper origin
      const x1 = fRect.right - wrapRect.left;
      const y1 = fRect.top + fRect.height / 2 - wrapRect.top + sourceOffsetY;
      const x2 = tRect.left - wrapRect.left - 4; // 4px margin before card border for clean arrowhead seating
      const y2 = tRect.top + tRect.height / 2 - wrapRect.top + targetOffsetY;

      // Mathematically guaranteed monotonic cubic Bezier
      // Control point offset is capped at <= 50% of horizontal distance (dx),
      // ensuring cx1 <= cx2. This permanently eliminates reverse looping, kinks,
      // and connector intrusion into node cards on mobile and tablet.
      const dx = Math.max(x2 - x1, 16);
      const curveOffset = Math.min(dx * 0.5, 64);
      const cx1 = x1 + curveOffset;
      const cy1 = y1;
      const cx2 = x2 - curveOffset;
      const cy2 = y2;

      const d = `M ${x1} ${y1} C ${cx1} ${cy1}, ${cx2} ${cy2}, ${x2} ${y2}`;
      const path = document.createElementNS('http://www.w3.org/2000/svg', 'path');
      path.setAttribute('d', d);

      const isTempo = edge.type === 'tempo';
      const isMaster = edge.type === 'master';

      if (isTempo) {
        path.setAttribute('class', 'dag-edge-tempo');
        path.setAttribute('stroke', '#c084fc');
        path.setAttribute('stroke-width', '2.5');
        path.setAttribute('fill', 'none');
        path.setAttribute('filter', 'url(#neon-glow-tempo)');
        path.setAttribute('marker-end', 'url(#arrow-tempo)');
      } else if (isMaster) {
        path.setAttribute('class', 'dag-edge-master');
        path.setAttribute('stroke', 'rgba(129, 140, 248, 0.45)');
        path.setAttribute('stroke-width', '1.5');
        path.setAttribute('stroke-dasharray', '5 4');
        path.setAttribute('fill', 'none');
        path.setAttribute('marker-end', 'url(#arrow-master)');
      } else {
        path.setAttribute('class', 'dag-edge-declared');
        path.setAttribute('stroke', '#38bdf8');
        path.setAttribute('stroke-width', '2');
        path.setAttribute('fill', 'none');
        path.setAttribute('marker-end', 'url(#arrow-declared)');
      }

      edgesLayer.appendChild(path);
    }
  }

  setupResizeObserver() {
    if (this.resizeObserver) this.resizeObserver.disconnect();
    const wrapper = this.container.querySelector('#dag-wrapper');
    if (!wrapper) return;

    this.resizeObserver = new ResizeObserver(() => {
      this.drawEdges();
    });
    this.resizeObserver.observe(wrapper);
    if (this.container) {
      this.resizeObserver.observe(this.container);
    }
    // Also observe individual nodes to catch dynamic text wrapping or badge changes
    this.container.querySelectorAll('.dag-node').forEach(node => {
      this.resizeObserver.observe(node);
    });

    // Re-draw when web fonts load
    if (document.fonts && document.fonts.ready) {
      document.fonts.ready.then(() => {
        this.drawEdges();
      }).catch(() => {});
    }

    // Bind window resize and orientation change handlers
    if (!this.onWindowResize) {
      this.onWindowResize = () => this.drawEdges();
      window.addEventListener('resize', this.onWindowResize, { passive: true });
      window.addEventListener('orientationchange', this.onWindowResize, { passive: true });
    }
  }

  destroy() {
    if (this.resizeObserver) {
      this.resizeObserver.disconnect();
      this.resizeObserver = null;
    }
    if (this.onWindowResize) {
      window.removeEventListener('resize', this.onWindowResize);
      window.removeEventListener('orientationchange', this.onWindowResize);
      this.onWindowResize = null;
    }
  }
}
