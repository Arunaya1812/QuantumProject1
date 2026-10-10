// Detector evaluation: reads the Phase 5 / Qiskit / Phase 4 outputs and can
// re-run the project's own evaluation scripts.

import { h, icon, ICONS, api, pct, fixed, int, toast } from "../util.js";
import { mountAllMetrics } from "./allMetrics.js";

const DETECTORS = [
  ["static", "Static threshold"],
  ["adaptive", "Adaptive threshold"],
  ["ml", "Random Forest"],
  ["unified", "Unified fusion"],
];

const METRICS = [
  ["accuracy", "Accuracy"],
  ["precision", "Precision"],
  ["recall_detection_rate", "Recall"],
  ["f1_score", "F1"],
  ["matthews_correlation_coefficient", "MCC"],
  ["roc_auc", "ROC-AUC"],
];

export function mountEvaluation(root, system) {
  const tabs = h("div", { class: "tabs", role: "tablist" });
  const panels = {};
  const tabDefs = [["results", "Held-out results"], ["all", "All metrics"], ["qiskit", "Qiskit validation"], ["model", "Model"], ["run", "Run evaluations"]];
  let current = "results";
  for (const [key, label] of tabDefs) {
    panels[key] = h("div", { role: "tabpanel", hidden: key !== current });
    const b = h("button", { type: "button", role: "tab", "aria-selected": String(key === current) }, label);
    b.addEventListener("click", () => {
      current = key;
      tabs.querySelectorAll("button").forEach((x) => x.setAttribute("aria-selected", String(x === b)));
      Object.entries(panels).forEach(([k, p]) => { p.hidden = k !== key; });
      if (key === "run") refreshJobs();
      if (key === "all" && bundle) allMetrics.render(bundle);
    });
    tabs.append(b);
  }

  const updated = h("span", { class: "pill" }, "Loading…");
  root.append(
    h("header", { class: "page-head" },
      h("div", {},
        h("h1", {}, "Detector evaluation"),
        h("p", { class: "lede" }, "How the static, adaptive, Random Forest and unified detectors compare on timelines none of them were trained on.")),
      h("div", { class: "head-actions" }, updated)),
    tabs, ...Object.values(panels));

  let bundle = null;
  const openRunTab = () => [...tabs.querySelectorAll("button")].find((b) => b.textContent === "Run evaluations").click();
  const allMetrics = mountAllMetrics(panels.all, { openRunTab });

  async function load() {
    try {
      bundle = await api("/api/evaluation");
      updated.textContent = bundle.phase5_updated ? `Results from ${bundle.phase5_updated}` : "No results yet";
      renderResults();
      renderQiskit();
      if (current === "all") allMetrics.render(bundle);
    } catch (err) { toast(err.message, "error"); }
  }

  // ---------------------------------------------------------------- results
  function emptyState(panel, title, text) {
    panel.replaceChildren(h("div", { class: "panel" }, h("div", { class: "empty" },
      h("h3", {}, title), h("p", {}, text),
      h("button", { class: "btn btn-primary", type: "button", onclick: () => openRunTab() }, "Open run evaluations"))));
  }

  function metricCell(v, best) {
    return h("td", { class: "r" }, h("div", { class: "metric-cell" },
      h("span", { style: { fontWeight: best ? 650 : 450 } }, fixed(v, 3)),
      h("div", { class: "mini" }, h("i", { style: { width: `${Math.max(0, Math.min(1, v)) * 100}%` } }))));
  }

  function metricsTable(metrics) {
    const best = {};
    for (const [k] of METRICS) best[k] = Math.max(...DETECTORS.map(([d]) => metrics[d]?.[k] ?? -1));
    return h("div", { class: "panel table-wrap" }, h("table", { class: "data" },
      h("thead", {}, h("tr", {}, h("th", {}, "Detector"), METRICS.map(([, l]) => h("th", { class: "r" }, l)),
        h("th", { class: "r" }, "False alarms / 1k"))),
      h("tbody", {}, DETECTORS.filter(([d]) => metrics[d]).map(([d, label]) => h("tr", { class: d === "unified" ? "emph" : "" },
        h("td", {}, label),
        METRICS.map(([k]) => metricCell(metrics[d][k], metrics[d][k] === best[k])),
        h("td", { class: "r" }, fixed(metrics[d].false_alarms_per_1000_normal_windows, 1)))))));
  }

  function confusion(metrics) {
    return h("div", { class: "cm-grid" }, DETECTORS.filter(([d]) => metrics[d]).map(([d, label]) => {
      const cm = metrics[d].confusion_matrix;
      const total = cm.tn + cm.fp + cm.fn + cm.tp;
      const shade = (v, good) => {
        const a = 0.08 + 0.5 * (v / total);
        return { background: good ? `rgba(35, 66, 207, ${a})` : `rgba(196, 42, 87, ${Math.min(0.6, 0.06 + 2 * v / total)})`, color: "var(--ink)" };
      };
      return h("div", { class: "panel cm" },
        h("h4", {}, label, h("span", {}, `${int(total)} windows`)),
        h("table", {},
          h("tr", {}, h("th"), h("th", {}, "Pred. normal"), h("th", {}, "Pred. attack")),
          h("tr", {}, h("th", { class: "rowh" }, "Normal"), h("td", { style: shade(cm.tn, true) }, int(cm.tn)), h("td", { style: shade(cm.fp, false) }, int(cm.fp))),
          h("tr", {}, h("th", { class: "rowh" }, "Attack"), h("td", { style: shade(cm.fn, false) }, int(cm.fn)), h("td", { style: shade(cm.tp, true) }, int(cm.tp)))));
    }));
  }

  function delayTable(delays) {
    return h("div", { class: "panel table-wrap" }, h("table", { class: "data" },
      h("thead", {}, h("tr", {}, h("th", {}, "Detector"), h("th", { class: "r" }, "Attack timelines"), h("th", { class: "r" }, "Missed entirely"),
        h("th", { class: "r" }, "Median delay"), h("th", { class: "r" }, "Mean delay"), h("th", { class: "r" }, "Worst case"))),
      h("tbody", {}, DETECTORS.filter(([d]) => delays[d]).map(([d, label]) => {
        const x = delays[d];
        return h("tr", { class: d === "unified" ? "emph" : "" },
          h("td", {}, label), h("td", { class: "r" }, x.evaluated_attack_timelines),
          h("td", { class: "r", style: { color: x.missed_attack_timelines ? "var(--eve)" : "" } }, x.missed_attack_timelines),
          h("td", { class: "r" }, `${fixed(x.median_delay_windows, 0)} windows`),
          h("td", { class: "r" }, `${fixed(x.mean_delay_windows, 2)} windows`),
          h("td", { class: "r" }, `${x.maximum_delay_windows} windows`));
      }))));
  }

  function mcnemarNote(m, firstLabel = "Random Forest") {
    if (!m) return null;
    const significant = m.p_value < 0.05;
    return h("div", { class: "callout" }, icon(ICONS.info), h("div", {},
      h("strong", {}, `Unified vs ${firstLabel}: `),
      `${m.second_only_correct} windows only Unified got right, ${m.first_only_correct} only ${firstLabel} got right. Exact McNemar p = ${m.p_value.toFixed(3)}, so the difference `,
      h("strong", {}, significant ? "is statistically significant" : "is not statistically significant"),
      " on this test set."));
  }

  function renderResults() {
    const panel = panels.results;
    const r = bundle.phase5;
    if (!r) {
      emptyState(panel, "No Phase 5 results found", "outputs/phase5_evaluation_report.json is missing. Run the unified detector evaluation to generate it.");
      return;
    }
    const u = r.metrics.unified;
    const du = r.detection_delay.unified;
    const design = r.evaluation_design;
    const stat = (value, unit, label) => h("div", { class: "readout", style: { borderBottom: 0 } },
      h("dt", {}, label), h("dd", { class: "hero-num" }, value, unit ? h("small", {}, unit) : null));

    const scoreline = h("div", { class: "panel" },
      h("div", { class: "panel-pad", style: { borderBottom: "1px solid var(--line)" } },
        h("p", { style: { color: "var(--ink-2)" } },
          `Unified fusion on ${design.untouched_test_timelines} untouched test timelines (${int(design.test_windows)} windows). `,
          `Fusion was trained on out-of-fold predictions from ${design.development_timelines} development timelines, and every window of a timeline stays in one split.`)),
      h("dl", { class: "readouts scoreline" },
        stat(fixed(u.f1_score, 3), null, "F1 score"),
        stat(fixed(u.false_alarms_per_1000_normal_windows, 1), "per 1k", "False alarms"),
        stat(String(du.missed_attack_timelines), `of ${du.evaluated_attack_timelines}`, "Attacks missed"),
        stat(fixed(du.median_delay_windows, 0), "windows", "Median time to detect")));

    const lit = bundle.literature && bundle.literature.length
      ? h("div", { class: "section" },
        h("div", { class: "section-head" }, h("h2", {}, "Published work, for context"),
          h("p", {}, "Different protocols, attacks and datasets. These numbers are not a head-to-head comparison.")),
        h("div", { class: "panel table-wrap" }, h("table", { class: "data" },
          h("thead", {}, h("tr", {}, h("th", {}, "Reference"), h("th", {}, "Task"), h("th", { class: "r" }, "Accuracy"), h("th", { class: "r" }, "F1"), h("th", {}, "Why it is not directly comparable"))),
          h("tbody", {}, bundle.literature.map((row) => h("tr", {},
            h("td", {}, row.source ? h("a", { href: row.source, target: "_blank", rel: "noopener" }, row.reference) : row.reference),
            h("td", {}, row.protocol_task),
            h("td", { class: "r" }, row.reported_accuracy || "—"),
            h("td", { class: "r" }, row.reported_f1 || "—"),
            h("td", { style: { color: "var(--ink-2)" } }, row.comparability)))))))
      : null;

    const figs = bundle.figures.length
      ? h("div", { class: "section" },
        h("div", { class: "section-head" }, h("h2", {}, "Figures from outputs/"), h("p", {}, "Generated by the evaluation scripts. Open one to view it full size.")),
        h("div", { class: "figures" }, bundle.figures.map((f) => h("a", { class: "panel figure", href: `/figures/${f}`, target: "_blank", rel: "noopener", style: { textDecoration: "none", color: "inherit" } },
          h("img", { src: `/figures/${f}?t=${encodeURIComponent(bundle.phase5_updated || "")}`, alt: f.replace(/_/g, " ").replace(".png", ""), loading: "lazy" }),
          h("figcaption", {}, f)))))
      : null;

    panel.replaceChildren(
      scoreline,
      h("div", { class: "section" }, h("div", { class: "section-head" }, h("h2", {}, "All detectors on the same windows"),
        h("p", {}, "Bars show each value on a 0 to 1 scale. Bold marks the best in each column.")), metricsTable(r.metrics)),
      h("div", { class: "section" }, h("div", { class: "section-head" }, h("h2", {}, "Confusion matrices"), h("p", {}, "Blue cells are correct decisions, red cells are mistakes.")), confusion(r.metrics)),
      h("div", { class: "section" }, h("div", { class: "section-head" }, h("h2", {}, "Time to detect"), h("p", {}, "Windows between Eve's arrival and the first alarm, per attacked timeline.")),
        delayTable(r.detection_delay), h("div", { style: { marginTop: "12px" } }, mcnemarNote(r.paired_mcnemar_unified_vs_ml))),
      r.claim_boundary ? h("div", { class: "section" }, h("div", { class: "callout" }, icon(ICONS.info), h("div", {}, h("strong", {}, "Scope of the claim. "), r.claim_boundary))) : null,
      lit, figs);
  }

  // ---------------------------------------------------------------- qiskit
  function renderQiskit() {
    const panel = panels.qiskit;
    const q = bundle.qiskit;
    if (!q) {
      emptyState(panel, "No Qiskit comparison yet", "outputs/phase5_qiskit_evaluation.json is missing. The comparison runs every detector on matched probabilistic and Qiskit Aer timelines.");
      return;
    }
    const p = q.results.probabilistic;
    const k = q.results.hybrid_qiskit;
    const d = q.evaluation_design;
    const row = (det, label) => h("tr", { class: det === "unified" ? "emph" : "" },
      h("td", {}, label),
      h("td", { class: "r" }, fixed(p.metrics[det].accuracy, 3)), h("td", { class: "r" }, fixed(k.metrics[det].accuracy, 3)),
      h("td", { class: "r" }, fixed(p.metrics[det].f1_score, 3)), h("td", { class: "r" }, fixed(k.metrics[det].f1_score, 3)),
      h("td", { class: "r" }, fixed(p.metrics[det].false_alarms_per_1000_normal_windows, 1)),
      h("td", { class: "r" }, fixed(k.metrics[det].false_alarms_per_1000_normal_windows, 1)));
    panel.replaceChildren(
      h("div", { class: "panel panel-pad" },
        h("dl", { class: "kv" },
          h("dt", {}, "Timelines per backend"), h("dd", {}, d.timelines_per_backend),
          h("dt", {}, "Windows per timeline"), h("dd", {}, d.windows_per_timeline),
          h("dt", {}, "Photons per window"), h("dd", {}, d.photons_per_window),
          h("dt", {}, "Noise levels"), h("dd", {}, d.noise_levels.map((n) => pct(n, 0)).join(", ")),
          h("dt", {}, "Qiskit execution"), h("dd", {}, d.qiskit_execution),
          h("dt", {}, "Decoy pulses"), h("dd", {}, d.decoy_execution),
          h("dt", {}, "Runtime"), h("dd", {}, `${fixed(p.runtime_seconds, 1)} s probabilistic, ${fixed(k.runtime_seconds, 1)} s Qiskit`))),
      h("div", { class: "section" },
        h("div", { class: "section-head" }, h("h2", {}, "Same scenarios and seeds on both backends")),
        h("div", { class: "panel table-wrap" }, h("table", { class: "data" },
          h("thead", {},
            h("tr", {}, h("th"), h("th", { class: "r", colspan: 2 }, "Accuracy"), h("th", { class: "r", colspan: 2 }, "F1"), h("th", { class: "r", colspan: 2 }, "False alarms / 1k")),
            h("tr", {}, h("th", {}, "Detector"), ...Array(3).fill(0).flatMap(() => [h("th", { class: "r" }, "Probabilistic"), h("th", { class: "r" }, "Qiskit")]))),
          h("tbody", {}, DETECTORS.map(([det, label]) => row(det, label)))))),
      h("div", { class: "section" }, mcnemarNote(k.mcnemar_unified_vs_ml, "Random Forest (Qiskit)")),
      h("div", { class: "section" }, h("div", { class: "callout" }, icon(ICONS.info), h("div", {}, h("strong", {}, "How to read this. "), q.honest_interpretation))));
  }

  // ---------------------------------------------------------------- model
  system.ready.then((info) => {
    const m = info && info.model;
    const panel = panels.model;
    if (!m || !m.available) {
      panel.replaceChildren(h("div", { class: "panel" }, h("div", { class: "empty" }, h("h3", {}, "No trained model"), h("p", {}, "Train the unified detector to populate this page."))));
      return;
    }
    const max = Math.max(...m.feature_importances.map((f) => f.importance));
    const meta = m.training_metadata || {};
    panel.replaceChildren(h("div", { class: "pqc-grid" },
      h("div", { class: "panel panel-pad" },
        h("div", { class: "section-head" }, h("h2", {}, "What the forest relies on"), h("p", {}, "Impurity-based feature importance")),
        h("div", { class: "bars-h" }, m.feature_importances.map((f) => h("div", { class: "bar-row", style: { gridTemplateColumns: "150px minmax(0,1fr) 56px" } },
          h("code", {}, f.feature),
          h("div", { class: "track" }, h("i", { style: { width: `${(f.importance / max) * 100}%` } })),
          h("span", { class: "v" }, pct(f.importance, 1)))))),
      h("div", { class: "panel panel-pad" },
        h("div", { class: "section-head" }, h("h2", {}, "Model card")),
        h("dl", { class: "kv" },
          h("dt", {}, "File"), h("dd", { class: "mono" }, m.path),
          h("dt", {}, "Last trained"), h("dd", {}, m.modified),
          h("dt", {}, "Base model"), h("dd", {}, `${m.base_model.type}, ${m.base_model.n_estimators} trees, depth ${m.base_model.max_depth}`),
          m.fusion_model ? [h("dt", {}, "Fusion model"), h("dd", {}, m.fusion_model.type)] : null,
          m.fusion_model ? [h("dt", {}, "Fusion inputs"), h("dd", {}, m.fusion_model.columns.map((c) => h("code", { style: { display: "inline-block", marginRight: "8px" } }, c)))] : null,
          m.fusion_model?.config ? [h("dt", {}, "Quarantine guard"), h("dd", {}, `Windows with RF probability at or above ${m.fusion_model.config.guard_probability} never update the baselines`)] : null,
          meta.development_timeline_count ? [h("dt", {}, "Training split"), h("dd", {}, `${meta.development_timeline_count} development, ${meta.test_timeline_count} test timelines`)] : null,
          meta.fusion_training ? [h("dt", {}, "Fusion training"), h("dd", {}, meta.fusion_training)] : null))));
  });

  // ---------------------------------------------------------------- jobs
  const jobsHost = h("div", { class: "jobs" });
  panels.run.append(
    h("div", { class: "callout", style: { marginBottom: "14px" } }, icon(ICONS.info),
      h("div", {}, "These buttons run the project's own scripts on this machine and write to outputs/. Results on the other tabs refresh when a run finishes.")),
    jobsHost);
  const pollers = new Map();

  async function refreshJobs() {
    try {
      const catalog = await api("/api/jobs");
      jobsHost.replaceChildren(...catalog.map((j) => {
        const log = h("div", { class: "job-log", hidden: true });
        const btn = h("button", { class: "btn", type: "button", disabled: j.running }, j.running ? "Running…" : "Run");
        const node = h("div", { class: "panel job" },
          h("div", {}, h("div", { style: { fontWeight: 600 } }, j.label), h("div", { class: "note" }, j.note)),
          btn, log);
        btn.addEventListener("click", async () => {
          try {
            const job = await api(`/api/jobs/${j.kind}`, { method: "POST" });
            btn.disabled = true; btn.replaceChildren(h("span", { class: "spinner" }), "Running…");
            poll(job.id, btn, log);
          } catch (err) { toast(err.message, "error"); }
        });
        if (j.running && j.job_id) { btn.replaceChildren(h("span", { class: "spinner" }), "Running…"); poll(j.job_id, btn, log); }
        return node;
      }));
    } catch (err) { toast(err.message, "error"); }
  }

  function poll(id, btn, log) {
    clearInterval(pollers.get(id));
    log.hidden = false;
    const tick = async () => {
      try {
        const job = await api(`/api/jobs/${id}`);
        log.textContent = job.log.join("\n");
        log.scrollTop = log.scrollHeight;
        if (job.status !== "running") {
          clearInterval(pollers.get(id));
          btn.disabled = false;
          btn.textContent = job.status === "done" ? "Run again" : "Retry";
          toast(job.status === "done" ? `${job.label}: finished` : `${job.label}: failed`, job.status === "done" ? "" : "error");
          if (job.status === "done") { allMetrics.invalidate(); load(); }
        }
      } catch { clearInterval(pollers.get(id)); }
    };
    pollers.set(id, setInterval(tick, 1200));
    tick();
  }

  load();
  return { onShow: () => { if (bundle) load(); } };
}
