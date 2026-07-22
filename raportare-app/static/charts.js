/* Grafice SVG minimale, fara nicio dependenta externa (fara CDN). */
const CHART_PALETTE = ['#3b5fe0', '#22c55e', '#f59e0b', '#ef4444', '#8b5cf6', '#06b6d4'];

function fmtNum(n) {
  return new Intl.NumberFormat('ro-RO', { maximumFractionDigits: 0 }).format(n);
}

function svgEl(tag, attrs) {
  const el = document.createElementNS('http://www.w3.org/2000/svg', tag);
  for (const k in attrs) el.setAttribute(k, attrs[k]);
  return el;
}

/** Grafic bare grupate (2 serii) pe categorii, cu axa Y si legenda. */
function renderGroupedBarChart(containerId, categories, seriesList, opts = {}) {
  const container = document.getElementById(containerId);
  const W = container.clientWidth || 560, H = opts.height || 260;
  const padL = 60, padB = 46, padT = 16, padR = 16;
  const plotW = W - padL - padR, plotH = H - padT - padB;

  const allValues = seriesList.flatMap(s => s.data);
  const maxV = Math.max(1, ...allValues);
  const minV = Math.min(0, ...allValues);
  const range = maxV - minV || 1;

  const svg = svgEl('svg', { width: W, height: H, viewBox: `0 0 ${W} ${H}` });

  // gridlines + axa Y
  const ticks = 4;
  for (let i = 0; i <= ticks; i++) {
    const v = minV + (range * i) / ticks;
    const y = padT + plotH - ((v - minV) / range) * plotH;
    svg.appendChild(svgEl('line', { x1: padL, x2: W - padR, y1: y, y2: y, stroke: '#e2e8f0', 'stroke-width': 1 }));
    const label = svgEl('text', { x: padL - 8, y: y + 4, 'text-anchor': 'end', 'font-size': 11, fill: '#64748b' });
    label.textContent = fmtNum(v);
    svg.appendChild(label);
  }

  const groupW = plotW / categories.length;
  const barGap = 6;
  const barW = (groupW - barGap * (seriesList.length + 1)) / seriesList.length;

  categories.forEach((cat, ci) => {
    seriesList.forEach((s, si) => {
      const v = s.data[ci] || 0;
      const barH = (Math.abs(v) / range) * plotH;
      const x = padL + ci * groupW + barGap + si * (barW + barGap);
      const y = padT + plotH - ((v - minV) / range) * plotH;
      const rect = svgEl('rect', { x, y: v >= 0 ? y : padT + plotH - ((0 - minV) / range) * plotH, width: barW, height: Math.max(1, barH), fill: s.color, rx: 3 });
      const title = svgEl('title'); title.textContent = `${s.label} · ${cat}: ${fmtNum(v)}`;
      rect.appendChild(title);
      svg.appendChild(rect);
    });
    const lbl = svgEl('text', { x: padL + ci * groupW + groupW / 2, y: H - padB + 18, 'text-anchor': 'middle', 'font-size': 11, fill: '#64748b' });
    lbl.textContent = cat;
    svg.appendChild(lbl);
  });

  container.innerHTML = '';
  container.appendChild(svg);
  renderLegend(container, seriesList);
}

/** Grafic linie simplu (o serie). */
function renderLineChart(containerId, categories, serie, opts = {}) {
  const container = document.getElementById(containerId);
  const W = container.clientWidth || 560, H = opts.height || 260;
  const padL = 60, padB = 32, padT = 16, padR = 16;
  const plotW = W - padL - padR, plotH = H - padT - padB;

  const values = serie.data;
  const maxV = Math.max(...values, 0);
  const minV = Math.min(...values, 0);
  const range = (maxV - minV) || 1;

  const svg = svgEl('svg', { width: W, height: H, viewBox: `0 0 ${W} ${H}` });
  const ticks = 4;
  for (let i = 0; i <= ticks; i++) {
    const v = minV + (range * i) / ticks;
    const y = padT + plotH - ((v - minV) / range) * plotH;
    svg.appendChild(svgEl('line', { x1: padL, x2: W - padR, y1: y, y2: y, stroke: '#e2e8f0', 'stroke-width': 1 }));
    const label = svgEl('text', { x: padL - 8, y: y + 4, 'text-anchor': 'end', 'font-size': 11, fill: '#64748b' });
    label.textContent = fmtNum(v);
    svg.appendChild(label);
  }

  const stepX = categories.length > 1 ? plotW / (categories.length - 1) : 0;
  const points = values.map((v, i) => {
    const x = padL + i * stepX;
    const y = padT + plotH - ((v - minV) / range) * plotH;
    return [x, y];
  });

  const pathD = points.map((p, i) => (i === 0 ? 'M' : 'L') + p[0] + ',' + p[1]).join(' ');
  const areaD = pathD + ` L${points[points.length - 1][0]},${padT + plotH} L${points[0][0]},${padT + plotH} Z`;
  svg.appendChild(svgEl('path', { d: areaD, fill: serie.color + '22', stroke: 'none' }));
  svg.appendChild(svgEl('path', { d: pathD, fill: 'none', stroke: serie.color, 'stroke-width': 2.5 }));

  points.forEach(([x, y], i) => {
    const c = svgEl('circle', { cx: x, cy: y, r: 3.5, fill: serie.color });
    const title = svgEl('title'); title.textContent = `${categories[i]}: ${fmtNum(values[i])}`;
    c.appendChild(title);
    svg.appendChild(c);
    const lbl = svgEl('text', { x, y: H - padB + 18, 'text-anchor': 'middle', 'font-size': 11, fill: '#64748b' });
    lbl.textContent = categories[i];
    svg.appendChild(lbl);
  });

  container.innerHTML = '';
  container.appendChild(svg);
}

/** Grafic bare orizontale (o singura serie, categorii pe axa Y). */
function renderHBarChart(containerId, items, opts = {}) {
  const container = document.getElementById(containerId);
  const rowH = 28;
  const W = container.clientWidth || 560, H = Math.max(120, items.length * rowH + 30);
  const padL = 180, padR = 110, padT = 10;
  const plotW = W - padL - padR;

  const maxV = Math.max(1, ...items.map(i => Math.abs(i.value)));
  const svg = svgEl('svg', { width: W, height: H, viewBox: `0 0 ${W} ${H}` });

  items.forEach((it, i) => {
    const y = padT + i * rowH;
    const barW = (Math.abs(it.value) / maxV) * plotW;
    const color = CHART_PALETTE[i % CHART_PALETTE.length];
    const lbl = svgEl('text', { x: padL - 8, y: y + rowH / 2 + 4, 'text-anchor': 'end', 'font-size': 11, fill: '#334155' });
    lbl.textContent = it.label.length > 26 ? it.label.slice(0, 24) + '…' : it.label;
    const titleFull = svgEl('title'); titleFull.textContent = it.label;
    lbl.appendChild(titleFull);
    svg.appendChild(lbl);

    const rect = svgEl('rect', { x: padL, y: y + 4, width: Math.max(1, barW), height: rowH - 10, fill: color, rx: 3 });
    const title = svgEl('title'); title.textContent = `${it.label}: ${fmtNum(it.value)}`;
    rect.appendChild(title);
    svg.appendChild(rect);

    const val = svgEl('text', { x: padL + barW + 6, y: y + rowH / 2 + 4, 'font-size': 11, fill: '#64748b' });
    val.textContent = fmtNum(it.value);
    svg.appendChild(val);
  });

  container.innerHTML = '';
  container.appendChild(svg);
}

function renderLegend(container, seriesList) {
  const legend = document.createElement('div');
  legend.style.cssText = 'display:flex;gap:16px;justify-content:center;margin-top:8px;font-size:12px;color:#475569';
  seriesList.forEach(s => {
    const item = document.createElement('span');
    item.style.cssText = 'display:inline-flex;align-items:center;gap:6px';
    item.innerHTML = `<span style="width:10px;height:10px;border-radius:2px;background:${s.color};display:inline-block"></span>${s.label}`;
    legend.appendChild(item);
  });
  container.appendChild(legend);
}
