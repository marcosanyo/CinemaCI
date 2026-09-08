/**
 * Cinema CI — Reactive Application Store
 * Centralized pub/sub state container with automatic reactivity and polling lifecycle management.
 */

class Store {
  constructor() {
    this.state = {
      project: null,
      builds: [],
      selectedBuildId: null,
      currentImpactPlan: null,
      releases: [],
      agentActivity: [],
      agentMode: 'AUTONOMOUS',
      activeView: 'project',
      activeBuildRunning: false,
      telemetryOverview: null,
      handledRepairBuilds: new Set(),
    };

    /** @type {Map<string, Set<Function>>} */
    this.subscribers = new Map();

    this.pollTimers = {
      build: null,
      global: null,
      agent: null,
    };
  }

  /**
   * Retrieves a snapshot of the current state or a specific key.
   * @param {string} [key]
   * @returns {any}
   */
  getState(key) {
    return key ? this.state[key] : { ...this.state };
  }

  /**
   * Updates state partially and notifies relevant subscribers.
   * @param {Object} partialState
   */
  setState(partialState) {
    const changedKeys = [];
    for (const [key, value] of Object.entries(partialState)) {
      if (this.state[key] !== value) {
        this.state[key] = value;
        changedKeys.push(key);
      }
    }

    for (const key of changedKeys) {
      this.notify(key, this.state[key]);
    }
    if (changedKeys.length > 0) {
      this.notify('*', this.state);
    }
  }

  /**
   * Subscribes to changes on a specific state key or '*' for all changes.
   * @param {string} key
   * @param {Function} callback
   * @returns {Function} Unsubscribe function
   */
  subscribe(key, callback) {
    if (!this.subscribers.has(key)) {
      this.subscribers.set(key, new Set());
    }
    this.subscribers.get(key).add(callback);

    // Immediate callback with current value
    callback(key === '*' ? this.state : this.state[key]);

    return () => {
      const subs = this.subscribers.get(key);
      if (subs) {
        subs.delete(callback);
      }
    };
  }

  /**
   * Dispatches notifications to subscribers.
   * @private
   */
  notify(key, value) {
    const subs = this.subscribers.get(key);
    if (subs) {
      subs.forEach(cb => {
        try {
          cb(value);
        } catch (err) {
          console.error(`Store subscription error on key '${key}':`, err);
        }
      });
    }
  }

  /**
   * Returns the currently selected build object if available.
   * @returns {Object|null}
   */
  getSelectedBuild() {
    if (!this.state.selectedBuildId || !this.state.builds) return null;
    return this.state.builds.find(b => b.build_id === this.state.selectedBuildId) || null;
  }
}

export const store = new Store();

