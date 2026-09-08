/**
 * Cinema CI — DOM Utility Helpers
 * Lightweight, safe DOM manipulation and rendering utilities.
 */

/**
 * Escapes HTML characters to prevent XSS.
 * @param {string} str
 * @returns {string}
 */
export function escapeHtml(str) {
  if (str === null || str === undefined) return '';
  return String(str)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#039;');
}

/**
 * Creates an HTMLElement with attributes, classes, and children.
 * @param {string} tag
 * @param {Object} [props={}]
 * @param {Array<HTMLElement|string>|HTMLElement|string} [children=[]]
 * @returns {HTMLElement}
 */
export function el(tag, props = {}, children = []) {
  const element = document.createElement(tag);

  for (const [key, value] of Object.entries(props)) {
    if (value === null || value === undefined) continue;
    if (key === 'className' || key === 'class') {
      element.className = value;
    } else if (key === 'dataset' && typeof value === 'object') {
      for (const [dKey, dVal] of Object.entries(value)) {
        element.dataset[dKey] = dVal;
      }
    } else if (key.startsWith('on') && typeof value === 'function') {
      const eventName = key.slice(2).toLowerCase();
      element.addEventListener(eventName, value);
    } else if (key === 'style' && typeof value === 'object') {
      Object.assign(element.style, value);
    } else if (typeof value === 'boolean') {
      if (value) element.setAttribute(key, '');
    } else {
      element.setAttribute(key, value);
    }
  }

  const childArray = Array.isArray(children) ? children : [children];
  for (const child of childArray) {
    if (child === null || child === undefined || child === false) continue;
    if (child instanceof Node) {
      element.appendChild(child);
    } else {
      element.appendChild(document.createTextNode(String(child)));
    }
  }

  return element;
}

/**
 * Template tag for sanitized HTML insertion.
 * @param {TemplateStringsArray} strings
 * @param  {...any} values
 * @returns {string}
 */
export function html(strings, ...values) {
  return strings.reduce((acc, str, i) => {
    const val = values[i - 1];
    const sanitized = val instanceof RawHtml ? val.content : escapeHtml(val);
    return acc + sanitized + str;
  });
}

export class RawHtml {
  constructor(content) {
    this.content = String(content);
  }
}

export function raw(content) {
  return new RawHtml(content);
}

/**
 * Clears and replaces container contents with elements or string.
 * @param {HTMLElement|string} containerOrSelector
 * @param {Array<HTMLElement>|HTMLElement|string} content
 */
export function mount(containerOrSelector, content) {
  const container = typeof containerOrSelector === 'string'
    ? document.querySelector(containerOrSelector)
    : containerOrSelector;

  if (!container) return;
  container.innerHTML = '';

  if (typeof content === 'string') {
    container.innerHTML = content;
  } else if (Array.isArray(content)) {
    content.forEach(child => child && container.appendChild(child));
  } else if (content instanceof Node) {
    container.appendChild(content);
  }
}

