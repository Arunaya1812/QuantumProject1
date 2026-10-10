import { h, api } from "./util.js";
import { mountMonitor } from "./pages/monitor.js";
import { mountSessions } from "./pages/sessions.js";
import { mountInspector } from "./pages/inspector.js";
import { mountEvaluation } from "./pages/evaluation.js";
import { mountPqc } from "./pages/pqc.js";

const PAGES = {
  monitor: { mount: mountMonitor, title: "Link monitor" },
  sessions: { mount: mountSessions, title: "Key sessions" },
  inspector: { mount: mountInspector, title: "Protocol inspector" },
  evaluation: { mount: mountEvaluation, title: "Detector evaluation" },
  pqc: { mount: mountPqc, title: "Post-quantum auth" },
};

const mounted = new Map();
export const system = { ready: null };

function route() {
  const name = (location.hash.replace(/^#\/?/, "") || "monitor").split("?")[0];
  const key = PAGES[name] ? name : "monitor";
  document.querySelectorAll(".page").forEach((p) => { p.hidden = p.dataset.page !== key; });
  document.querySelectorAll(".nav a").forEach((a) => {
    if (a.dataset.route === key) a.setAttribute("aria-current", "page");
    else a.removeAttribute("aria-current");
  });
  const page = document.getElementById(`page-${key}`);
  if (!mounted.has(key)) {
    const api = PAGES[key].mount(page, system) || {};
    mounted.set(key, api);
  }
  const pageApi = mounted.get(key);
  if (pageApi.onShow) pageApi.onShow();
  document.title = `${PAGES[key].title} · Basis`;
}

async function loadEnvironment() {
  const list = document.getElementById("env-list");
  try {
    const info = await api("/api/system");
    const items = [];
    const m = info.model || {};
    if (m.available) {
      const base = m.base_model || {};
      items.push(h("li", { class: "env-item ok" },
        m.kind === "stacked_fusion"
          ? `Unified detector: ${base.n_estimators}-tree forest with stacked fusion`
          : `Random Forest detector (${base.n_estimators} trees)`));
    } else {
      items.push(h("li", { class: "env-item off" }, "No trained detector in models/"));
    }
    items.push(h("li", { class: `env-item ${info.capabilities.qiskit ? "ok" : "off"}` },
      info.capabilities.qiskit ? "Qiskit Aer available" : "Qiskit not installed"));
    items.push(h("li", { class: `env-item ${info.capabilities.pqc ? "ok" : "off"}` },
      info.capabilities.pqc ? "ML-DSA-65 and ML-KEM-768 ready" : "pqcrypto not installed"));
    list.replaceChildren(...items);
    return info;
  } catch (err) {
    list.replaceChildren(h("li", { class: "env-item off" }, "Backend unreachable"));
    return null;
  }
}

system.ready = loadEnvironment();
window.addEventListener("hashchange", route);
route();
