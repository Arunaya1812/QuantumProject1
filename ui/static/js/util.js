// Small DOM + formatting helpers shared by every page.

export function h(tag, attrs = {}, ...children) {
  const isSvg = ["svg", "path", "line", "rect", "circle", "g", "text", "polyline", "polygon"].includes(tag);
  const node = isSvg
    ? document.createElementNS("http://www.w3.org/2000/svg", tag)
    : document.createElement(tag);
  for (const [key, value] of Object.entries(attrs || {})) {
    if (value === undefined || value === null || value === false) continue;
    if (key === "class") node.setAttribute("class", value);
    else if (key === "style" && typeof value === "object") Object.assign(node.style, value);
    else if (key.startsWith("on") && typeof value === "function") node.addEventListener(key.slice(2), value);
    else if (key === "html") node.innerHTML = value;
    else if (value === true) node.setAttribute(key, "");
    else node.setAttribute(key, value);
  }
  for (const child of children.flat(Infinity)) {
    if (child === null || child === undefined || child === false) continue;
    node.append(child instanceof Node ? child : document.createTextNode(String(child)));
  }
  return node;
}

export const icon = (paths, cls = "") =>
  h("svg", { viewBox: "0 0 20 20", class: cls, "aria-hidden": "true", html: paths });

export const ICONS = {
  shield: '<path d="M10 2.5l6 2.5v5c0 3.6-2.6 6.3-6 7.5-3.4-1.2-6-3.9-6-7.5V5z"/><path d="M7.3 10l2 2 3.6-3.8"/>',
  alert: '<path d="M10 3l8 14H2z"/><path d="M10 8.5v3.5M10 14.6v.1"/>',
  gauge: '<path d="M3.5 14a7 7 0 1113 0"/><path d="M10 13l3-4"/>',
  play: '<path d="M6 4l10 6-10 6z"/>',
  pause: '<path d="M7 4v12M13 4v12"/>',
  reset: '<path d="M4 10a6 6 0 106-6H7"/><path d="M7 1.5L4.5 4 7 6.5"/>',
  check: '<path d="M4 10.5l4 4 8-9"/>',
  x: '<path d="M5 5l10 10M15 5L5 15"/>',
  info: '<circle cx="10" cy="10" r="7.5"/><path d="M10 9v5M10 6.2v.1"/>',
  key: '<circle cx="7" cy="10" r="3.2"/><path d="M10.2 10H18M15 10v3M17.5 10v2"/>',
  arrow: '<path d="M4 10h12M12 6l4 4-4 4"/>',
  run: '<path d="M6 4l10 6-10 6z"/>',
};

export const pct = (v, digits = 1) =>
  v === null || v === undefined || Number.isNaN(v) ? "—" : `${(v * 100).toFixed(digits)}%`;

export const fixed = (v, digits = 3) =>
  v === null || v === undefined || Number.isNaN(Number(v)) ? "—" : Number(v).toFixed(digits);

export const int = (v) =>
  v === null || v === undefined ? "—" : Math.round(v).toLocaleString("en-US");

export const ms = (v) => (v < 1 ? `${(v * 1000).toFixed(0)} µs` : `${v.toFixed(v < 10 ? 2 : 1)} ms`);

export const ATTACK_LABEL = {
  none: "No attack",
  intercept_resend: "Intercept-resend",
  pns: "Photon-number splitting",
};

export async function api(path, { method = "GET", body } = {}) {
  const response = await fetch(path, {
    method,
    headers: body ? { "Content-Type": "application/json" } : undefined,
    body: body ? JSON.stringify(body) : undefined,
  });
  let data = null;
  try { data = await response.json(); } catch { /* empty */ }
  if (!response.ok) {
    const detail = data && data.detail ? data.detail : `${response.status} ${response.statusText}`;
    throw new Error(typeof detail === "string" ? detail : JSON.stringify(detail));
  }
  return data;
}

export function toast(message, kind = "") {
  const zone = document.getElementById("toasts");
  const node = h("div", { class: `toast ${kind}` }, message);
  zone.append(node);
  setTimeout(() => node.remove(), kind === "error" ? 6000 : 3200);
}

// ---------------------------------------------------------------- tooltip

const tip = () => document.getElementById("tooltip");

export function showTooltip(x, y, head, rows) {
  const node = tip();
  node.replaceChildren(
    h("div", { class: "tt-head" }, head),
    ...rows.map((r) =>
      h("div", { class: "tt-row" },
        r.color ? h("i", { class: "tt-sw", style: { background: r.color } }) : null,
        h("span", {}, r.label),
        h("b", {}, r.value))
    ),
  );
  node.hidden = false;
  const rect = node.getBoundingClientRect();
  let left = x + 14;
  let top = y + 14;
  if (left + rect.width > window.innerWidth - 8) left = x - rect.width - 14;
  if (top + rect.height > window.innerHeight - 8) top = y - rect.height - 14;
  node.style.left = `${Math.max(8, left)}px`;
  node.style.top = `${Math.max(8, top)}px`;
}

export function hideTooltip() { tip().hidden = true; }

export function setRangeFill(input) {
  const min = Number(input.min || 0);
  const max = Number(input.max || 100);
  const fill = ((Number(input.value) - min) / (max - min)) * 100;
  input.style.setProperty("--fill", `${fill}%`);
}

export function segmented(options, value, onChange, cls = "") {
  const wrap = h("div", { class: `segmented ${cls}`, role: "group" });
  const buttons = options.map(([val, label]) =>
    h("button", {
      type: "button", "data-value": val, "aria-pressed": String(val === value),
      onclick: () => { set(val); onChange(val); },
    }, label));
  function set(v) { buttons.forEach((b) => b.setAttribute("aria-pressed", String(b.dataset.value === v))); }
  wrap.append(...buttons);
  wrap.set = set;
  return wrap;
}

export function css(name) {
  return getComputedStyle(document.documentElement).getPropertyValue(name).trim();
}
