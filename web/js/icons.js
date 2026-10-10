// Stroke icons (24x24). Paths are constants, so nothing here ever touches user text.
const NS = 'http://www.w3.org/2000/svg';

const ICONS = {
  home: [['path', { d: 'M3 11.5 12 4l9 7.5' }], ['path', { d: 'M5.5 10v9a1 1 0 0 0 1 1H9.5a1 1 0 0 0 1-1v-4h3v4a1 1 0 0 0 1 1h3a1 1 0 0 0 1-1v-9' }]],
  add: [['circle', { cx: 12, cy: 12, r: 9 }], ['path', { d: 'M12 8v8M8 12h8' }]],
  learn: [['path', { d: 'M12 6.5c-1.6-1.2-3.8-1.7-6-1.5v12c2.2-.2 4.4.3 6 1.5 1.6-1.2 3.8-1.7 6-1.5v-12c-2.2-.2-4.4.3-6 1.5Z' }], ['path', { d: 'M12 6.5v12' }]],
  culture: [['circle', { cx: 12, cy: 12, r: 2.3 }], ['path', { d: 'M8.2 8.2a5.3 5.3 0 0 0 0 7.6M15.8 8.2a5.3 5.3 0 0 1 0 7.6M5.3 5.3a9.6 9.6 0 0 0 0 13.4M18.7 5.3a9.6 9.6 0 0 1 0 13.4' }]],
  settings: [['path', { d: 'M4 7h10M17 7h3M4 17h3M10 17h10' }], ['circle', { cx: 14, cy: 7, r: 2.1 }], ['circle', { cx: 7, cy: 17, r: 2.1 }]],
  sun: [['circle', { cx: 12, cy: 12, r: 4.2 }], ['path', { d: 'M12 2.5v2.4M12 19.1v2.4M4.6 4.6l1.7 1.7M17.7 17.7l1.7 1.7M2.5 12h2.4M19.1 12h2.4M4.6 19.4l1.7-1.7M17.7 6.3l1.7-1.7' }]],
  moon: [['path', { d: 'M20 14.5A8.5 8.5 0 1 1 9.5 4a7 7 0 1 0 10.5 10.5Z' }]],
  lock: [['rect', { x: 5, y: 10.5, width: 14, height: 9, rx: 2 }], ['path', { d: 'M8 10.5V7.5a4 4 0 0 1 8 0v3' }]],
  flame: [['path', { d: 'M12 2c1 3-2 4-2 7a4 4 0 0 0 8 0c0-1-.3-2-1-3 1.5.8 3 2.7 3 5.5A6.5 6.5 0 0 1 6.5 18 6.5 6.5 0 0 1 8 7c0 1.5.8 2 .8 2C8 6 9.5 3.5 12 2Z' }]],
  entries: [['rect', { x: 5, y: 4, width: 11, height: 15, rx: 1.5 }], ['path', { d: 'M8.5 8.5h4M8.5 11.5h4M8.5 14.5h2.5' }]],
  clock: [['circle', { cx: 12, cy: 12, r: 9 }], ['path', { d: 'M12 7v5l3.5 2' }]],
  arrow: [['path', { d: 'M5 12h14M13 6l6 6-6 6' }]],
  chevron: [['path', { d: 'M9 5l7 7-7 7' }]],
  back: [['path', { d: 'M15 5 8 12l7 7' }]],
  search: [['circle', { cx: 10.5, cy: 10.5, r: 6 }], ['path', { d: 'M19 19l-4.3-4.3' }]],
  bulb: [['path', { d: 'M9 18h6M10 21h4M8 14a4 4 0 1 1 8 0c0 1.8-1 2.6-1.5 3.3-.3.4-.5.7-.5 1.2h-4c0-.5-.2-.8-.5-1.2C9 16.6 8 15.8 8 14Z' }]],
  external: [['path', { d: 'M7 17 17 7M9 7h8v8' }]],
  play: [['path', { d: 'M7 5.5v13l11-6.5-11-6.5Z' }]],
  mail: [['rect', { x: 3.5, y: 5.5, width: 17, height: 13, rx: 2 }], ['path', { d: 'M4.5 7l7.5 6 7.5-6' }]],
  check: [['path', { d: 'M4 12l5 5 11-11' }]],
  x: [['path', { d: 'M6 6l12 12M18 6 6 18' }]],
  user: [['circle', { cx: 12, cy: 8, r: 3.5 }], ['path', { d: 'M5 20c0-3.9 3.1-6 7-6s7 2.1 7 6' }]],
  logout: [['path', { d: 'M10 5H6a1 1 0 0 0-1 1v12a1 1 0 0 0 1 1h4' }], ['path', { d: 'M15 8l4 4-4 4M19 12H9' }]],
  pencil: [['path', { d: 'M4 20l1-4L16.5 4.5a1.8 1.8 0 0 1 2.5 0l.5.5a1.8 1.8 0 0 1 0 2.5L8 19l-4 1Z' }]],
  history: [['path', { d: 'M4 12a8 8 0 1 0 2.5-5.8' }], ['path', { d: 'M4 4v4h4M12 8v4l3 2' }]],
  offline: [['path', { d: 'M3 3l18 18' }], ['path', { d: 'M8.5 16.5a5 5 0 0 1 7 0M5 13a10 10 0 0 1 3-2M12 20h.01' }]],
  inbox: [['path', { d: 'M4 13l2-7h12l2 7v5a1 1 0 0 1-1 1H5a1 1 0 0 1-1-1v-5Z' }], ['path', { d: 'M4 13h5l1 2h4l1-2h5' }]],
  shield: [['path', { d: 'M12 3l7 3v5c0 4.5-3 8-7 10-4-2-7-5.5-7-10V6l7-3Z' }]],
};

const FILLED = new Set(['moon', 'flame', 'play']);

export function icon(name, size = 20) {
  const parts = ICONS[name];
  const svg = document.createElementNS(NS, 'svg');
  svg.setAttribute('viewBox', '0 0 24 24');
  svg.setAttribute('width', String(size));
  svg.setAttribute('height', String(size));
  svg.setAttribute('aria-hidden', 'true');
  svg.setAttribute('focusable', 'false');
  svg.classList.add('icon');
  if (FILLED.has(name)) {
    svg.setAttribute('fill', 'currentColor');
  } else {
    svg.setAttribute('fill', 'none');
    svg.setAttribute('stroke', 'currentColor');
    svg.setAttribute('stroke-width', '1.8');
    svg.setAttribute('stroke-linecap', 'round');
    svg.setAttribute('stroke-linejoin', 'round');
  }
  for (const [tag, attrs] of parts || []) {
    const el = document.createElementNS(NS, tag);
    for (const [k, v] of Object.entries(attrs)) el.setAttribute(k, String(v));
    svg.appendChild(el);
  }
  return svg;
}
