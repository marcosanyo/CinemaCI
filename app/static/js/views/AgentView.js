/**
 * Cinema CI — Autonomous ADK Agent View
 * Live terminal and event log for Grafana MCP telemetry investigation and surgical repair cycles.
 */

import { store } from '../store/index.js';
import { api } from '../api/client.js';
import { toast } from '../components/Toast.js';
import { formatDate } from '../utils/formatters.js';

export class AgentView {
  constructor(router) {
    this.router = router;
    this.container = document.getElementById('view-agent');
    this.pollTimer = null;
    this._lastRenderedJson = null;
    this.bindStore();
  }

  bindStore() {
    store.subscribe('agentActivity', (activities) => {
      if (store.getState('activeView') === 'agent') {
        this.renderTimeline(activities);
      }
    });

    store.subscribe('builds', () => {
      if (store.getState('activeView') === 'agent') {
        const activities = store.getState('agentActivity');
        if (activities) {
          this.renderTimeline(activities);
        }
      }
    });
  }

  mount() {
    this._lastRenderedJson = null;
    this.fetchActivity();
    this.startPolling();
  }

  unmount() {
    this.stopPolling();
  }

  startPolling() {
    this.stopPolling();
    this.pollTimer = setInterval(() => {
      this.fetchActivity();
    }, 2500);
  }

  stopPolling() {
    if (this.pollTimer) {
      clearInterval(this.pollTimer);
      this.pollTimer = null;
    }
  }

  async fetchActivity() {
    try {
      const activities = await api.getAgentActivity();
      store.setState({ agentActivity: activities });
      this.renderTimeline(activities);
    } catch {
      // Ignore polling errors
    }
  }

  renderTimeline(activities) {
    const timelineEl = document.getElementById('agent-timeline');
    const statusEl = document.getElementById('agent-status');
    if (!timelineEl) return;

    const list = Array.isArray(activities)
      ? activities
      : (activities?.steps || activities?.activity || []);

    const builds = store.getState('builds') || [];
    const latestBuild = builds.length > 0 ? builds[0] : null;

    // Check if data actually changed to avoid resetting scroll and re-rendering DOM
    const currentJson = JSON.stringify({
      listLen: list.length,
      lastStep: list[list.length - 1],
      latestBuildId: latestBuild?.build_id,
      latestBuildStatus: latestBuild?.status,
      latestBuildTests: latestBuild?.tests_passed
    });

    if (this._lastRenderedJson === currentJson) {
      return; // No changes, leave DOM and scroll intact
    }

    if (!list || list.length === 0) {
      this._lastRenderedJson = currentJson;
      timelineEl.innerHTML = `
        <div class="agent-empty-box">
          <div class="empty-sparkle">🤖</div>
          <h3>Autonomous Agent Standing By</h3>
          <p class="muted">
            The ADK agent listens for Grafana Alertmanager webhooks, queries Loki logs and Prometheus metrics via official MCP tools,
            and surgically repairs failing video cuts.
          </p>
          <div class="agent-demo-actions u-mt-md">
            <button class="btn btn-secondary btn-sm" id="btn-agent-sim-alert">
              ⚡ Dispatch Simulated Regression Alert
            </button>
          </div>
        </div>
      `;
      const btnSim = timelineEl.querySelector('#btn-agent-sim-alert');
      if (btnSim) {
        btnSim.onclick = async () => {
          try {
            await api.simulateAlert({ alertname: 'CinemaRegressionDetected', build_id: 'latest', shot_id: 'shot_03' });
            toast.warning('Simulated regression alert sent to ADK Agent!');
            this.fetchActivity();
          } catch (err) {
            toast.error(`Simulation failed: ${err.message}`);
          }
        };
      }
      if (statusEl) {
        statusEl.textContent = 'IDLE';
        statusEl.className = 'agent-status status-idle';
      }
      return;
    }

    const isWorking = list.some(s => !s.done && s.action !== 'agent_response');

    if (statusEl) {
      statusEl.textContent = isWorking ? 'RUNNING' : 'COMPLETED';
      statusEl.className = `agent-status ${isWorking ? 'status-running' : 'status-ready'}`;
    }

    // Preserve scroll position of terminal body
    const bodyEl = timelineEl.querySelector('.agent-terminal-body');
    const prevScrollTop = bodyEl ? bodyEl.scrollTop : 0;
    const isScrolledToBottom = bodyEl ? (bodyEl.scrollHeight - bodyEl.scrollTop <= bodyEl.clientHeight + 80) : true;

    // Check if a repair build exists and should show completion action banner
    const hasReport = list.some(act => act.action === 'agent_response' || act.detail?.includes('Report'));
    const isRepairBuild = latestBuild && (Boolean(latestBuild.repair_of) || latestBuild.status === 'RELEASE_READY');
    const showRepairBanner = !isWorking && hasReport && isRepairBuild;

    let bannerHtml = '';
    if (showRepairBanner && latestBuild) {
      const isReady = latestBuild.status === 'RELEASE_READY' || latestBuild.release_ready;
      bannerHtml = `
        <div class="agent-repair-banner ${isReady ? '' : 'banner-running'}">
          <div class="repair-banner-left">
            <span class="repair-banner-icon">${isReady ? '✅' : '⚙️'}</span>
            <div>
              <div class="repair-banner-title">
                <span>Surgical Repair: </span>
                <span class="font-mono text-accent">${latestBuild.build_id}</span>
                <span class="badge ${isReady ? 'badge-pass' : 'badge-running'}">${latestBuild.status}</span>
                <span class="font-mono text-muted text-sm">(${latestBuild.tests_passed}/${latestBuild.tests_total} Passed)</span>
              </div>
              <div class="repair-banner-desc">
                ${isReady
                  ? 'The ADK agent isolated the regression via Grafana MCP, rebuilt failing assets with character contract alignment, and achieved full QA pass.'
                  : 'Surgical regeneration in progress...'}
              </div>
            </div>
          </div>
          <div class="repair-banner-actions">
            <button class="btn btn-secondary btn-sm" id="btn-agent-view-build" type="button">
              🔍 View in Build Inspector ➔
            </button>
            ${isReady ? `
              <button class="btn btn-primary btn-sm btn-glow" id="btn-agent-promote-build" type="button">
                🚀 Promote to Release
              </button>
            ` : ''}
          </div>
        </div>
      `;
    }

    timelineEl.innerHTML = `
      ${bannerHtml}
      <div class="agent-terminal-header">
        <div class="terminal-dots">
          <span class="t-dot dot-red"></span>
          <span class="t-dot dot-yellow"></span>
          <span class="t-dot dot-green"></span>
        </div>
        <span class="terminal-title font-mono">google-adk://gemini-3.8-flash/mcp-grafana/supervisor</span>
        <button class="btn-refresh-term" id="btn-term-refresh" title="Refresh">🔄</button>
      </div>
      <div class="agent-terminal-body">
        ${list.map(act => {
          const isError = act.action === 'agent_error';
          const isReport = act.action === 'agent_response' || act.detail?.includes('Report');
          const isDone = Boolean(act.done || isReport);
          const badgeClass = isError ? 'badge-regression' : (isReport ? 'badge-pass' : (isDone ? 'badge-pass' : 'badge-running'));
          const badgeText = isError ? 'ERROR' : (isReport ? 'REPORT' : (isDone ? 'COMPLETED' : 'RUNNING'));
          const messageText = act.detail || act.message || '';

          return `
            <div class="agent-entry">
              <div class="entry-header">
                <span class="entry-ts font-mono text-muted">${formatDate(act.timestamp)}</span>
                <span class="badge ${badgeClass}">
                  ${badgeText}
                </span>
                <span class="entry-action font-mono text-accent">${act.tool_name || act.action || 'Investigation'}</span>
                ${act.shot_id ? `<span class="entry-shot font-mono">[${act.shot_id}]</span>` : ''}
              </div>
              ${messageText ? `
                <div class="entry-message font-mono" style="white-space: pre-wrap; background: rgba(0,0,0,0.3); padding: 8px 12px; border-radius: 4px; line-height: 1.6;">${messageText}</div>
              ` : ''}
              ${act.tool_name ? `
                <div class="entry-tools">
                  <span class="tools-label text-muted">MCP Tool:</span>
                  <span class="tool-tag font-mono">${act.tool_name}</span>
                </div>
              ` : ''}
              ${act.tool_output ? `
                <details class="u-mt-xs">
                  <summary class="text-muted font-mono" style="cursor: pointer; font-size: 0.75rem;">View MCP Response Data</summary>
                  <pre class="entry-details-pre font-mono u-mt-xs">${act.tool_output}</pre>
                </details>
              ` : ''}
            </div>
          `;
        }).join('')}
      </div>
    `;

    // Restore scroll position
    const newBodyEl = timelineEl.querySelector('.agent-terminal-body');
    if (newBodyEl) {
      if (isScrolledToBottom) {
        newBodyEl.scrollTop = newBodyEl.scrollHeight;
      } else {
        newBodyEl.scrollTop = prevScrollTop;
      }
    }

    this._lastRenderedJson = currentJson;

    // Attach listeners
    const refreshBtn = timelineEl.querySelector('#btn-term-refresh');
    if (refreshBtn) {
      refreshBtn.onclick = () => this.fetchActivity();
    }

    const btnViewBuild = timelineEl.querySelector('#btn-agent-view-build');
    if (btnViewBuild && latestBuild) {
      btnViewBuild.onclick = () => {
        store.setState({ selectedBuildId: latestBuild.build_id });
        this.router.navigate('build');
      };
    }

    const btnPromoteBuild = timelineEl.querySelector('#btn-agent-promote-build');
    if (btnPromoteBuild && latestBuild) {
      btnPromoteBuild.onclick = () => {
        store.setState({ selectedBuildId: latestBuild.build_id });
        this.router.navigate('release');
      };
    }

    // If agent completed work, relax polling frequency so UI doesn't churn
    if (!isWorking && this.pollTimer) {
      this.stopPolling();
      this.pollTimer = setInterval(() => {
        this.fetchActivity();
      }, 10000);
    }
  }
}

