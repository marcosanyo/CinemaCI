/**
 * Cinema CI — Accessible Modal Dialog Component
 */

export class Modal {
  constructor() {
    this.overlay = null;
    this.init();
  }

  init() {
    this.overlay = document.createElement('div');
    this.overlay.className = 'modal-overlay u-hidden';
    this.overlay.innerHTML = `
      <div class="modal-dialog" role="dialog" aria-modal="true">
        <div class="modal-header">
          <div class="modal-title-group">
            <span class="modal-icon" id="modal-icon">🔍</span>
            <h3 class="modal-title" id="modal-title">Details</h3>
          </div>
          <button class="modal-close-btn" id="modal-close-btn" aria-label="Close modal">&times;</button>
        </div>
        <div class="modal-body" id="modal-body"></div>
        <div class="modal-footer" id="modal-footer">
          <button class="btn btn-secondary btn-sm" id="modal-btn-dismiss">Close</button>
        </div>
      </div>
    `;

    document.body.appendChild(this.overlay);

    const closeBtn = this.overlay.querySelector('#modal-close-btn');
    const dismissBtn = this.overlay.querySelector('#modal-btn-dismiss');

    closeBtn.onclick = () => this.close();
    dismissBtn.onclick = () => this.close();

    this.overlay.onclick = (e) => {
      if (e.target === this.overlay) {
        this.close();
      }
    };

    window.addEventListener('keydown', (e) => {
      if (e.key === 'Escape' && !this.overlay.classList.contains('u-hidden')) {
        this.close();
      }
    });
  }

  /**
   * @param {Object} options
   * @param {string} options.title
   * @param {string} [options.icon='🔍']
   * @param {string|HTMLElement} options.content
   * @param {Array<HTMLElement>} [options.actions]
   */
  open({ title, icon = '🔍', content, actions = [] }) {
    const titleEl = this.overlay.querySelector('#modal-title');
    const iconEl = this.overlay.querySelector('#modal-icon');
    const bodyEl = this.overlay.querySelector('#modal-body');
    const footerEl = this.overlay.querySelector('#modal-footer');

    titleEl.textContent = title;
    iconEl.textContent = icon;

    bodyEl.innerHTML = '';
    if (typeof content === 'string') {
      bodyEl.innerHTML = content;
    } else if (content instanceof Node) {
      bodyEl.appendChild(content);
    }

    // Keep default close button and append extra action buttons if provided
    footerEl.innerHTML = '<button class="btn btn-secondary btn-sm" id="modal-btn-dismiss">Close</button>';
    footerEl.querySelector('#modal-btn-dismiss').onclick = () => this.close();

    for (const act of actions) {
      footerEl.appendChild(act);
    }

    this.overlay.classList.remove('u-hidden');
    document.body.classList.add('modal-open');
  }

  close() {
    this.overlay.classList.add('u-hidden');
    document.body.classList.remove('modal-open');
  }
}

export const modal = new Modal();

