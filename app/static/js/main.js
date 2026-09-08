/**
 * Cinema CI — Main Application Entry Point
 * Bootstraps store, router, components, and views using native ES Modules.
 */

import { store } from './store/index.js';
import { api } from './api/client.js';
import { Router } from './router/index.js';
import { Header } from './components/Header.js';
import { toast } from './components/Toast.js';

import { StudioView } from './views/StudioView.js?v=20260906-07';
import { ImpactView } from './views/ImpactView.js';
import { BuildView } from './views/BuildView.js';
import { AgentView } from './views/AgentView.js';
import { ReleaseView } from './views/ReleaseView.js?v=20260906-07';
import { TelemetryView } from './views/TelemetryView.js';

class CinemaApp {
  constructor() {
    this.router = new Router();
    this.header = null;
    this.views = {};
    this.globalPollTimer = null;
  }

  async init() {
    console.log('🎬 Cinema CI — Initializing Director Deck console...');

    // Initialize Header
    this.header = new Header(this.router);

    // Register Views
    this.views.studio = new StudioView(this.router);
    this.views.impact = new ImpactView(this.router);
    this.views.build = new BuildView(this.router);
    this.views.agent = new AgentView(this.router);
    this.views.release = new ReleaseView(this.router);
    this.views.telemetry = new TelemetryView(this.router);

    this.router.register('project', this.views.studio);
    this.router.register('impact', this.views.impact);
    this.router.register('build', this.views.build);
    this.router.register('agent', this.views.agent);
    this.router.register('release', this.views.release);
    this.router.register('telemetry', this.views.telemetry);

    // Initial Data Fetch
    await this.loadInitialData();

    // Init router navigation
    this.router.init();

    // Start background health & build tracking poll
    this.startGlobalStatusPoll();

    console.log('✓ Cinema CI initialized successfully.');
  }

  async loadInitialData() {
    try {
      const [project, builds, releases] = await Promise.all([
        api.getProject().catch(() => null),
        api.getBuilds().catch(() => []),
        api.getReleases().catch(() => []),
      ]);

      const updates = { builds, releases };
      if (project) updates.project = project;
      if (builds.length > 0 && !store.getState('selectedBuildId')) {
        updates.selectedBuildId = builds[0].build_id;
      }

      store.setState(updates);
    } catch (err) {
      console.error('Initial data load failure:', err);
      toast.error('Failed to load initial pipeline status.');
    }
  }

  startGlobalStatusPoll() {
    if (this.globalPollTimer) clearInterval(this.globalPollTimer);

    this.globalPollTimer = setInterval(async () => {
      try {
        const builds = await api.getBuilds();
        store.setState({ builds });
      } catch {
        // Silent poll error
      }
    }, 2500);
  }
}

// Bootstrap on DOM ready
document.addEventListener('DOMContentLoaded', () => {
  const app = new CinemaApp();
  app.init().catch(err => {
    console.error('Fatal initialization error:', err);
  });
});

