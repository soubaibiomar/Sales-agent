/* SELIA charts: dependency-free SVG line/area, donut and bar charts in the owner's design.
 * Same-origin script (strict CSP, no chart CDN). Text is set with textContent only. */
(function () {
  'use strict';
  const NS = 'http://www.w3.org/2000/svg';
  const C = { olive: '#5D7A2D', oliveFill: 'rgba(93,122,45,0.16)', terra: '#CF6639', sand: '#EBCBAA', light: '#E9DCCD', olive2: '#9DB36A' };
  const PALETTE = [C.olive, C.terra, C.sand, C.olive2, '#B98B62', C.light];

  function el(name, attrs, parent) {
    const n = document.createElementNS(NS, name);
    Object.keys(attrs || {}).forEach(k => n.setAttribute(k, attrs[k]));
    if (parent) parent.appendChild(n);
    return n;
  }
  function clear(host) { while (host.firstChild) host.removeChild(host.firstChild); }

  function niceMax(v) {
    if (v <= 0) return 1;
    const p = Math.pow(10, Math.floor(Math.log10(v)));
    const m = v / p;
    return (m <= 1 ? 1 : m <= 2 ? 2 : m <= 2.5 ? 2.5 : m <= 5 ? 5 : 10) * p;
  }
  function compact(v) {
    const a = Math.abs(v);
    if (a >= 1e6) return (v / 1e6).toLocaleString('fr-FR', { maximumFractionDigits: 1 }) + 'M';
    if (a >= 1e3) return Math.round(v / 1e3).toLocaleString('fr-FR') + 'K';
    return Math.round(v).toLocaleString('fr-FR');
  }
  // Catmull-Rom -> cubic Bezier for the smooth curve of the design.
  function smoothPath(pts) {
    if (pts.length < 2) return pts.length ? 'M' + pts[0][0] + ',' + pts[0][1] : '';
    let d = 'M' + pts[0][0] + ',' + pts[0][1];
    for (let i = 0; i < pts.length - 1; i++) {
      const p0 = pts[i - 1] || pts[i], p1 = pts[i], p2 = pts[i + 1], p3 = pts[i + 2] || p2;
      const c1 = [p1[0] + (p2[0] - p0[0]) / 6, p1[1] + (p2[1] - p0[1]) / 6];
      const c2 = [p2[0] - (p3[0] - p1[0]) / 6, p2[1] - (p3[1] - p1[1]) / 6];
      d += ' C' + c1[0].toFixed(1) + ',' + c1[1].toFixed(1) + ' ' + c2[0].toFixed(1) + ',' + c2[1].toFixed(1) + ' ' + p2[0].toFixed(1) + ',' + p2[1].toFixed(1);
    }
    return d;
  }

  /** line(host, {labels, series:[{values, color, fill}], height, format}) */
  function line(host, opts) {
    clear(host);
    const W = 640, H = opts.height || 230, L = 46, R = 14, T = 12, B = 28;
    const series = opts.series || [{ values: opts.values || [] }];
    const all = series.flatMap(s => s.values).filter(v => typeof v === 'number');
    const max = niceMax(Math.max(0, ...all));
    const n = (opts.labels || []).length;
    const svg = el('svg', { viewBox: '0 0 ' + W + ' ' + H, role: 'img', 'aria-label': opts.ariaLabel || 'Graphique' }, host);
    const grid = el('g', { class: 'chart-grid' }, svg), axis = el('g', { class: 'chart-axis' }, svg);
    const x = i => L + (n <= 1 ? (W - L - R) / 2 : i * (W - L - R) / (n - 1));
    const y = v => T + (H - T - B) * (1 - v / max);
    for (let k = 0; k <= 4; k++) {
      const v = max * k / 4;
      el('line', { x1: L, x2: W - R, y1: y(v), y2: y(v) }, grid);
      el('text', { x: L - 8, y: y(v) + 4, 'text-anchor': 'end' }, axis).textContent = (opts.format || compact)(v);
    }
    const step = Math.max(1, Math.ceil(n / 8));
    (opts.labels || []).forEach((lab, i) => {
      if (i % step === 0 || i === n - 1) el('text', { x: x(i), y: H - 6, 'text-anchor': 'middle' }, axis).textContent = lab;
    });
    const defs = el('defs', {}, svg);
    series.forEach((s, si) => {
      const color = s.color || PALETTE[si];
      const pts = s.values.map((v, i) => [x(i), y(v || 0)]);
      if (!pts.length) return;
      if (s.fill !== false) {
        const gid = 'g' + Math.random().toString(36).slice(2, 8);
        const lg = el('linearGradient', { id: gid, x1: 0, y1: 0, x2: 0, y2: 1 }, defs);
        el('stop', { offset: '0%', 'stop-color': color, 'stop-opacity': 0.22 }, lg);
        el('stop', { offset: '100%', 'stop-color': color, 'stop-opacity': 0.02 }, lg);
        el('path', { d: smoothPath(pts) + ' L' + pts[pts.length - 1][0] + ',' + y(0) + ' L' + pts[0][0] + ',' + y(0) + ' Z', fill: 'url(#' + gid + ')' }, svg);
      }
      el('path', { d: smoothPath(pts), fill: 'none', stroke: color, 'stroke-width': 2.6, 'stroke-linecap': 'round' }, svg);
      pts.forEach((p, i) => {
        const last = i === pts.length - 1;
        if (n > 14 && !last) return;
        const c = el('circle', { cx: p[0], cy: p[1], r: last ? 5.5 : 4, fill: last ? '#FFFBF6' : color, stroke: color, 'stroke-width': last ? 2.6 : 0 }, svg);
        el('title', {}, c).textContent = (opts.labels[i] || '') + ' : ' + (opts.tooltip || compact)(s.values[i] || 0);
      });
    });
    if (!all.length || max === 1 && all.every(v => !v)) {
      const t = el('text', { x: W / 2, y: H / 2, 'text-anchor': 'middle', class: 'chart-empty' }, svg);
      t.textContent = opts.emptyText || 'Aucune donnée sur la période';
      t.setAttribute('fill', '#8E7C70'); t.setAttribute('font-size', '13');
    }
  }

  /** donut(host, {segments:[{label,value,color}], center, sub, legend: true}) */
  function donut(host, opts) {
    clear(host);
    const wrap = document.createElement('div');
    wrap.className = 'donut-wrap';
    host.appendChild(wrap);
    const size = opts.size || 170, r = size / 2 - 14, cx = size / 2, cy = size / 2, sw = opts.stroke || 24;
    const svg = el('svg', { viewBox: '0 0 ' + size + ' ' + size, width: size, height: size, role: 'img', 'aria-label': opts.ariaLabel || 'Répartition' }, wrap);
    const segs = (opts.segments || []).filter(s => s.value > 0);
    const total = segs.reduce((a, s) => a + s.value, 0);
    el('circle', { cx, cy, r, fill: 'none', stroke: '#F1E6DA', 'stroke-width': sw }, svg);
    let acc = 0;
    const circ = 2 * Math.PI * r;
    segs.forEach((s, i) => {
      const frac = s.value / total;
      const c = el('circle', { cx, cy, r, fill: 'none', stroke: s.color || PALETTE[i % PALETTE.length], 'stroke-width': sw,
        'stroke-dasharray': Math.max(0, frac * circ - 2) + ' ' + circ, 'stroke-dashoffset': -acc * circ, transform: 'rotate(-90 ' + cx + ' ' + cy + ')' }, svg);
      el('title', {}, c).textContent = s.label + ' : ' + Math.round(frac * 100) + ' %';
      acc += frac;
    });
    const t1 = el('text', { x: cx, y: cy + (opts.sub ? 2 : 7), 'text-anchor': 'middle', 'font-size': opts.centerSize || 22, 'font-weight': 800, fill: '#2D1E14' }, svg);
    t1.textContent = opts.center != null ? opts.center : (total ? '' : '0');
    if (opts.sub) {
      const t2 = el('text', { x: cx, y: cy + 20, 'text-anchor': 'middle', 'font-size': 11, fill: '#66544A' }, svg);
      t2.textContent = opts.sub;
    }
    if (opts.legend !== false) {
      const ul = document.createElement('ul');
      ul.className = 'donut-legend';
      (opts.segments || []).forEach((s, i) => {
        const li = document.createElement('li');
        const dot = document.createElement('span'); dot.className = 'dot'; dot.style.background = s.color || PALETTE[i % PALETTE.length];
        const lab = document.createElement('span'); lab.textContent = s.label;
        const val = document.createElement('span'); val.className = 'val';
        val.textContent = total ? Math.round(100 * (s.value || 0) / total) + ' %' : '—';
        li.append(dot, lab, val);
        ul.appendChild(li);
      });
      wrap.appendChild(ul);
    }
    if (!total && opts.emptyText) {
      const p = document.createElement('p'); p.className = 'data-state'; p.textContent = opts.emptyText; wrap.appendChild(p);
    }
  }

  /** bars(host, {labels, values, format, color, height}) - vertical bars. */
  function bars(host, opts) {
    clear(host);
    const W = 640, H = opts.height || 220, L = 46, R = 10, T = 10, B = 26;
    const n = opts.values.length, max = niceMax(Math.max(0, ...opts.values));
    const svg = el('svg', { viewBox: '0 0 ' + W + ' ' + H, role: 'img', 'aria-label': opts.ariaLabel || 'Histogramme' }, host);
    const grid = el('g', { class: 'chart-grid' }, svg), axis = el('g', { class: 'chart-axis' }, svg);
    const y = v => T + (H - T - B) * (1 - v / max);
    for (let k = 0; k <= 4; k++) {
      el('line', { x1: L, x2: W - R, y1: y(max * k / 4), y2: y(max * k / 4) }, grid);
      el('text', { x: L - 8, y: y(max * k / 4) + 4, 'text-anchor': 'end' }, axis).textContent = (opts.format || compact)(max * k / 4);
    }
    const slot = (W - L - R) / Math.max(1, n), bw = Math.min(28, slot * 0.55);
    opts.values.forEach((v, i) => {
      const x = L + i * slot + (slot - bw) / 2;
      const r = el('rect', { x, y: y(v), width: bw, height: Math.max(0, y(0) - y(v)), rx: 6, fill: i === n - 1 ? C.olive : C.olive2 }, svg);
      el('title', {}, r).textContent = opts.labels[i] + ' : ' + (opts.tooltip || compact)(v);
      el('text', { x: x + bw / 2, y: H - 6, 'text-anchor': 'middle' }, axis).textContent = opts.labels[i];
    });
  }

  window.SeliaCharts = { line, donut, bars, compact, PALETTE, COLORS: C };
})();
