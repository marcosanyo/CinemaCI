/**
 * Cinema CI — Toast Notification Component
 * Displays non-intrusive, floating status toasts.
 */

class ToastManager {
  constructor() {
    this.container = null;
  }

  ensureContainer() {
    if (!this.container) {
      this.container = document.getElementById('toast-container');
      if (!this.container) {
        this.container = document.createElement('div');
        this.container.id = 'toast-container';
        this.container.className = 'toast-container';
        document.body.appendChild(this.container);
      }
    }
  }

  /**
   * @param {string} message
   * @param {'info'|'success'|'warning'|'error'} [type='info']
   * @param {number} [duration=4000]
   */
  show(message, type = 'info', duration = 4000) {
    this.ensureContainer();

    const toast = document.createElement('div');
    toast.className = `toast toast-${type} toast-enter`;

    const iconMap = {
      info: 'ℹ️',
      success: '✓',
      warning: '⚠️',
      error: '❌',
    };

    toast.innerHTML = `
      <span class="toast-icon">${iconMap[type] || 'ℹ️'}</span>
      <span class="toast-message">${message}</span>
      <button class="toast-close" aria-label="Close">&times;</button>
    `;

    const closeBtn = toast.querySelector('.toast-close');
    const dismiss = () => {
      toast.classList.remove('toast-enter');
      toast.classList.add('toast-exit');
      setTimeout(() => {
        if (toast.parentElement) {
          toast.parentElement.removeChild(toast);
        }
      }, 300);
    };

    closeBtn.onclick = dismiss;

    this.container.appendChild(toast);

    if (duration > 0) {
      setTimeout(dismiss, duration);
    }
  }

  info(msg, dur) { this.show(msg, 'info', dur); }
  success(msg, dur) { this.show(msg, 'success', dur); }
  warning(msg, dur) { this.show(msg, 'warning', dur); }
  error(msg, dur) { this.show(msg, 'error', dur); }
}

export const toast = new ToastManager();

