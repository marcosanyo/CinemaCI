/**
 * Cinema CI — Top App Header & Global Banner Component
 */

import { store } from '../store/index.js';
import { api } from '../api/client.js';
import { toast } from './Toast.js';

export class Header {
  constructor(router) {
    this.router = router;
    this.banner = document.getElementById('global-build-banner');
    this.statusEl = document.getElementById('header-status');
    this.bannerText = document.getElementById('global-banner-text');
    this.btnViewBuild = document.getElementById('btn-view-running-build');
    this.btnCancelBuild = document.getElementById('btn-cancel-running-build');

    this.setupListeners();
    this.bindStore();
  }

  setupListeners() {
    // Navigation items
    document.querySelectorAll('.nav-btn').forEach(btn => {
      btn.addEventListener('click', () => {
        const view = btn.dataset.view;
        if (view) this.router.navigate(view);
      });
    });

    // Home link
    const brand = document.getElementById('brand-home-link');
    if (brand) {
      brand.addEventListener('click', () => this.router.navigate('project'));
    }

    // Header stack pills
    const grafanaPill = document.querySelector('.pill-grafana');
    if (grafanaPill) {
      grafanaPill.addEventListener('click', () => this.router.navigate('telemetry'));
    }

    // Global Banner actions
    if (this.btnViewBuild) {
      this.btnViewBuild.addEventListener('click', () => {
        const runningBuild = store.getState('builds').find(b =>
          ['QUEUED', 'BUILDING', 'GENERATING', 'TESTING', 'VALIDATING'].includes(b.status)
        );
        if (runningBuild) {
          store.setState({ selectedBuildId: runningBuild.build_id });
          this.router.navigate('build');
        }
      });
    }

    if (this.btnCancelBuild) {
      this.btnCancelBuild.addEventListener('click', async () => {
        const runningBuild = store.getState('builds').find(b =>
          ['QUEUED', 'BUILDING', 'GENERATING', 'TESTING', 'VALIDATING'].includes(b.status)
        );
        if (runningBuild) {
          try {
            await api.cancelBuild(runningBuild.build_id);
            toast.warning(`Build ${runningBuild.build_id} canceled.`);
          } catch (err) {
            toast.error(`Cancel failed: ${err.message}`);
          }
        }
      });
    }
  }

  bindStore() {
    // Watch builds to update banner and header status
    store.subscribe('builds', (builds) => {
      this.updateStatus(builds);
    });

    // Watch activeView to update active nav tab
    store.subscribe('activeView', (view) => {
      document.querySelectorAll('.nav-btn').forEach(btn => {
        if (btn.dataset.view === view) {
          btn.classList.add('active');
        } else {
          btn.classList.remove('active');
        }
      });
    });
  }

  updateStatus(builds) {
    if (!builds || builds.length === 0) {
      if (this.statusEl) {
        this.statusEl.textContent = 'IDLE';
        this.statusEl.className = 'system-status-indicator status-idle';
      }
      if (this.banner) this.banner.classList.add('u-hidden');
      return;
    }

    const latest = builds[0];
    const isRunning = ['QUEUED', 'BUILDING', 'GENERATING', 'TESTING', 'VALIDATING'].includes(latest.status);

    if (this.statusEl) {
      this.statusEl.textContent = latest.status;
      this.statusEl.className = `system-status-indicator status-${latest.status.toLowerCase().replace(/_/g, '-')}`;
    }

    if (this.banner) {
      if (isRunning) {
        this.banner.classList.remove('u-hidden');
        if (this.bannerText) {
          this.bannerText.textContent = `Autonomous Build in progress (${latest.build_id}) — Operations avoided: ${latest.operations_avoided || 0}`;
        }
      } else {
        this.banner.classList.add('u-hidden');
      }
    }
  }
}

