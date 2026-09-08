/**
 * Cinema CI — Single-Page App Router
 * Handles hash navigation, view transitions, and keyboard shortcuts.
 */

import { store } from '../store/index.js';

export class Router {
  constructor() {
    this.routes = new Map();
    this.currentRoute = null;

    window.addEventListener('hashchange', () => this.handleHashChange());
    this.setupShortcuts();
  }

  /**
   * Registers a view component to a route key.
   * @param {string} name
   * @param {Object} viewInstance
   */
  register(name, viewInstance) {
    this.routes.set(name, viewInstance);
  }

  /**
   * Initializes router with default route or current hash.
   */
  init() {
    const hash = window.location.hash.replace('#', '') || 'project';
    this.navigate(hash);
  }

  /**
   * Transitions to a designated view.
   * @param {string} name
   */
  navigate(name) {
    // Map alias names
    let routeKey = name;
    if (name === 'studio') routeKey = 'project';

    if (!this.routes.has(routeKey)) {
      routeKey = 'project';
    }

    if (this.currentRoute && this.currentRoute.unmount) {
      this.currentRoute.unmount();
    }

    // Hide all view DOM containers
    document.querySelectorAll('.view').forEach(el => {
      el.classList.remove('active');
    });

    const activeViewEl = document.getElementById(`view-${routeKey}`);
    if (activeViewEl) {
      activeViewEl.classList.add('active');
    }

    // Update URL hash without re-triggering hashchange
    if (window.location.hash !== `#${routeKey}`) {
      window.history.replaceState(null, '', `#${routeKey}`);
    }

    const view = this.routes.get(routeKey);
    this.currentRoute = view;

    store.setState({ activeView: routeKey });

    if (view && view.mount) {
      view.mount();
    }

    window.scrollTo({ top: 0, behavior: 'smooth' });
  }

  handleHashChange() {
    const hash = window.location.hash.replace('#', '');
    if (hash && hash !== store.getState('activeView')) {
      this.navigate(hash);
    }
  }

  setupShortcuts() {
    window.addEventListener('keydown', (e) => {
      // Don't trigger when user is typing in textarea or input
      const tag = (e.target && e.target.tagName) || '';
      const isInput = tag === 'INPUT' || tag === 'TEXTAREA' || e.target.isContentEditable;

      // 1-6 keys for fast tab switching when not in inputs
      if (!isInput && !e.ctrlKey && !e.metaKey && !e.altKey) {
        const keyMap = {
          '1': 'project',
          '2': 'impact',
          '3': 'build',
          '4': 'agent',
          '5': 'release',
          '6': 'telemetry',
        };
        if (keyMap[e.key]) {
          e.preventDefault();
          this.navigate(keyMap[e.key]);
          return;
        }
      }

      // Cmd+Enter or Ctrl+Enter: Analyze Impact
      if ((e.metaKey || e.ctrlKey) && e.key === 'Enter') {
        const analyzeBtn = document.getElementById('btn-analyze-impact');
        if (analyzeBtn) {
          e.preventDefault();
          analyzeBtn.click();
        }
      }
    });
  }
}

