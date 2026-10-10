// Minimal SVG time-series chart: hairline grid, 2px lines, shaded truth
// bands, detection ticks, threshold lines, and a crosshair tooltip.

import { h, showTooltip, hideTooltip } from "./util.js";

const PAD = { top: 14, right: 12, bottom: 22, left: 44 };

function niceMax(v) {
  if (v <= 0) return 1;
  const exp = Math.floor(Math.log10(v));
  const base = 10 ** exp;
  for (const m of [1, 1.2, 1.5, 2, 2.5, 3, 4, 5, 6, 8, 10]) {
    if (m * base >= v) return m * base;
  }
  return 10 * base;
}

export function seriesChart(container, opts) {
  const o = {
    height: 170,
    xKey: "window",
    series: [],
    yMin: 0,
    yMax: null,
    yFloor: 0.05,
    yFormat: (v) => v.toFixed(2),
    yTicks: 4,
    band: null,        // { key, color, label }
    markers: null,     // { key, color, label }
    refLines: [],      // [{ value, color, label }]
    xDomain: null,     // [min, max]
    tooltip: null,     // (d) => [{label, value, color}]
    tooltipHead: (d) => `Window ${d.window}`,
    ariaLabel: "Time series chart",
    ...opts,
  };

  const root = h("div", { class: "chart", role: "img", "aria-label": o.ariaLabel });
  container.append(root);
  let data = [];
  let width = 0;

  const svg = h("svg", { height: o.height });
  root.append(svg);

  const ro = new ResizeObserver(() => {
    const w = root.clientWidth;
    if (w && Math.abs(w - width) > 1) { width = w; draw(); }
  });
  ro.observe(root);

  function scales() {
    const xs = data.map((d) => d[o.xKey]);
    let [x0, x1] = o.xDomain || [Math.min(...xs), Math.max(...xs)];
    if (!Number.isFinite(x0)) { x0 = 0; x1 = 1; }
    if (x1 === x0) x1 = x0 + 1;
    let yMax = o.yMax;
    let ticks = o.yTicks;
    if (yMax === null) {
      let m = o.yFloor;
      for (const d of data) {
        for (const s of o.series) { const v = d[s.key]; if (Number.isFinite(v)) m = Math.max(m, v); }
        for (const r of o.refLines) { const v = typeof r.value === "function" ? r.value(d) : r.value; if (Number.isFinite(v)) m = Math.max(m, v); }
      }
      // nice step so ticks land on round values (e.g. 0, 5, 10, 15, 20%)
      const raw = (m * 1.05) / o.yTicks;
      const exp = 10 ** Math.floor(Math.log10(raw));
      const step = [1, 2, 2.5, 5, 10].map((k) => k * exp).find((k) => k >= raw);
      yMax = Math.ceil((m * 1.05) / step) * step;
      ticks = Math.round(yMax / step);
    }
    const iw = Math.max(10, width - PAD.left - PAD.right);
    const ih = o.height - PAD.top - PAD.bottom;
    const sx = (x) => PAD.left + ((x - x0) / (x1 - x0)) * iw;
    const sy = (y) => PAD.top + ih - ((y - o.yMin) / (yMax - o.yMin)) * ih;
    return { x0, x1, yMax, ticks, iw, ih, sx, sy };
  }

  function linePath(points) {
    let d = "";
    let pen = false;
    for (const [x, y] of points) {
      if (!Number.isFinite(y)) { pen = false; continue; }
      d += `${pen ? "L" : "M"}${x.toFixed(1)},${y.toFixed(1)}`;
      pen = true;
    }
    return d;
  }

  function draw() {
    if (!width) return;
    svg.setAttribute("viewBox", `0 0 ${width} ${o.height}`);
    svg.setAttribute("width", width);
    svg.replaceChildren();
    const { x0, x1, yMax, ticks, iw, ih, sx, sy } = scales();

    // grid + y axis
    const grid = h("g", { class: "grid" });
    const axis = h("g", { class: "axis" });
    for (let i = 0; i <= ticks; i++) {
      const v = o.yMin + ((yMax - o.yMin) * i) / ticks;
      const y = sy(v);
      if (i > 0) grid.append(h("line", { x1: PAD.left, x2: PAD.left + iw, y1: y, y2: y }));
      axis.append(h("text", { x: PAD.left - 8, y: y + 3.5, "text-anchor": "end" }, o.yFormat(v, yMax)));
    }
    // x ticks
    const span = x1 - x0;
    const step = niceMax(span / Math.max(2, Math.floor(iw / 90)));
    const first = Math.ceil(x0 / step) * step;
    for (let x = first; x <= x1; x += step) {
      axis.append(h("text", { x: sx(x), y: o.height - 5, "text-anchor": "middle" }, String(Math.round(x))));
    }

    // truth band
    const bands = h("g");
    if (o.band && data.length) {
      let start = null;
      const half = data.length > 1 ? (sx(data[1][o.xKey]) - sx(data[0][o.xKey])) / 2 : 4;
      const flush = (end) => {
        bands.append(h("rect", {
          x: Math.max(PAD.left, sx(start) - half), y: PAD.top,
          width: Math.max(1, Math.min(PAD.left + iw, sx(end) + half) - Math.max(PAD.left, sx(start) - half)),
          height: ih, fill: o.band.color,
        }));
      };
      let prev = null;
      for (const d of data) {
        if (d[o.band.key]) { if (start === null) start = d[o.xKey]; prev = d[o.xKey]; }
        else if (start !== null) { flush(prev); start = null; }
      }
      if (start !== null) flush(prev);
    }

    svg.append(bands, grid);
    svg.append(h("line", { class: "baseline", x1: PAD.left, x2: PAD.left + iw, y1: sy(o.yMin), y2: sy(o.yMin) }));

    // reference / threshold lines (may vary per point)
    for (const r of o.refLines) {
      const pts = typeof r.value === "function"
        ? data.map((d) => [sx(d[o.xKey]), sy(r.value(d))])
        : [[PAD.left, sy(r.value)], [PAD.left + iw, sy(r.value)]];
      svg.append(h("path", {
        d: linePath(pts), fill: "none", stroke: r.color, "stroke-width": r.width || 1.5,
        "stroke-dasharray": r.dash || "5 4", "stroke-linejoin": "round",
      }));
    }

    // series
    for (const s of o.series) {
      const pts = data.map((d) => [sx(d[o.xKey]), sy(d[s.key])]);
      if (s.area) {
        const valid = pts.filter((p) => Number.isFinite(p[1]));
        if (valid.length > 1) {
          const d = `${linePath(valid)}L${valid.at(-1)[0]},${sy(o.yMin)}L${valid[0][0]},${sy(o.yMin)}Z`;
          svg.append(h("path", { d, fill: s.color, opacity: 0.08 }));
        }
      }
      svg.append(h("path", {
        d: linePath(pts), fill: "none", stroke: s.color, "stroke-width": s.width || 2,
        "stroke-linejoin": "round", "stroke-linecap": "round",
        "stroke-dasharray": s.dash || null,
      }));
    }

    // detection markers: short ticks along the top edge
    if (o.markers) {
      const g = h("g");
      for (const d of data) {
        if (!d[o.markers.key]) continue;
        const x = sx(d[o.xKey]);
        g.append(h("rect", { x: x - 1.5, y: PAD.top - 10, width: 3, height: 7, rx: 1.5, fill: o.markers.color }));
      }
      svg.append(g);
    }

    svg.append(axis);

    // hover layer
    const hover = h("line", { class: "hover-line", y1: PAD.top, y2: PAD.top + ih, visibility: "hidden" });
    const dots = o.series.map((s) => h("circle", { r: 4, fill: s.color, stroke: "var(--panel)", "stroke-width": 2, visibility: "hidden" }));
    const hit = h("rect", { x: PAD.left, y: 0, width: iw, height: o.height, fill: "transparent", tabindex: 0 });
    svg.append(hover, ...dots, hit);

    const nearest = (clientX) => {
      const rect = svg.getBoundingClientRect();
      const px = clientX - rect.left;
      let best = null;
      let bestDist = Infinity;
      for (const d of data) {
        const dist = Math.abs(sx(d[o.xKey]) - px);
        if (dist < bestDist) { bestDist = dist; best = d; }
      }
      return best;
    };
    const show = (d, cx, cy) => {
      if (!d) return;
      const x = sx(d[o.xKey]);
      hover.setAttribute("x1", x); hover.setAttribute("x2", x); hover.setAttribute("visibility", "visible");
      o.series.forEach((s, i) => {
        const v = d[s.key];
        if (Number.isFinite(v)) {
          dots[i].setAttribute("cx", x); dots[i].setAttribute("cy", sy(v)); dots[i].setAttribute("visibility", "visible");
        } else dots[i].setAttribute("visibility", "hidden");
      });
      const rows = o.tooltip ? o.tooltip(d) : o.series.map((s) => ({ label: s.label, value: o.yFormat(d[s.key]), color: s.color }));
      showTooltip(cx, cy, o.tooltipHead(d), rows);
    };
    const clear = () => {
      hover.setAttribute("visibility", "hidden");
      dots.forEach((dot) => dot.setAttribute("visibility", "hidden"));
      hideTooltip();
    };
    hit.addEventListener("pointermove", (e) => show(nearest(e.clientX), e.clientX, e.clientY));
    hit.addEventListener("pointerleave", clear);
    let focusIndex = data.length - 1;
    hit.addEventListener("focus", () => {
      focusIndex = data.length - 1;
      const r = svg.getBoundingClientRect();
      const d = data[focusIndex];
      if (d) show(d, r.left + sx(d[o.xKey]), r.top + PAD.top);
    });
    hit.addEventListener("keydown", (e) => {
      if (e.key !== "ArrowLeft" && e.key !== "ArrowRight") return;
      e.preventDefault();
      focusIndex = Math.max(0, Math.min(data.length - 1, focusIndex + (e.key === "ArrowRight" ? 1 : -1)));
      const r = svg.getBoundingClientRect();
      const d = data[focusIndex];
      if (d) show(d, r.left + sx(d[o.xKey]), r.top + PAD.top);
    });
    hit.addEventListener("blur", clear);
  }

  return {
    update(next, patch = {}) {
      data = next;
      Object.assign(o, patch);
      width = root.clientWidth || width;
      draw();
    },
    destroy() { ro.disconnect(); root.remove(); },
  };
}

export function legend(items) {
  return h("div", { class: "legend" },
    items.map((it) => h("span", {},
      h("i", { class: it.kind || "", style: it.kind === "dash" ? { borderColor: it.color } : { background: it.color } }),
      it.label)));
}
