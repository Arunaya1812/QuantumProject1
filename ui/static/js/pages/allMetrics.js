// "All metrics" tab: every number the project reports, in one place, with
// CSV export for the report.

import { h, icon, ICONS, api, pct, fixed, int, ms, segmented, toast } from "../util.js";

const DETECTORS = [
  ["static", "Static threshold"],
  ["adaptive", "Adaptive threshold"],
  ["ml", "Random Forest"],
  ["unified", "Unified fusion"],
];

// [key, label, format, higherIsBetter, hint]
const FULL_METRICS = [
  ["accuracy", "Accuracy", "ratio", true, "Share of all windows classified correctly"],
  ["balanced_accuracy", "Balanced accuracy", "ratio", true, "Mean of recall and specificity; robust to class imbalance"],
  ["precision", "Precision", "ratio", true, "Of the windows flagged, how many were real attacks"],
  ["recall_detection_rate", "Recall (detection rate)", "ratio", true, "Of the attack windows, how many were flagged"],
  ["specificity", "Specificity", "ratio", true, "Of the normal windows, how many stayed unflagged"],
  ["f1_score", "F1 score", "ratio", true, "Harmonic mean of precision and recall"],
  ["f2_score", "F2 score", "ratio", true, "Like F1 but weights recall twice as much"],
  ["matthews_correlation_coefficient", "MCC", "ratio", true, "Correlation between truth and prediction, -1 to 1"],
  ["roc_auc", "ROC-AUC", "ratio", true, "Ranking quality across all thresholds"],
  ["pr_auc", "PR-AUC", "ratio", true, "Precision-recall area; stricter than ROC-AUC on imbalanced data"],
  ["false_positive_rate", "False positive rate", "ratio", false, "Normal windows wrongly flagged"],
  ["false_negative_rate", "False negative rate", "ratio", false, "Attack windows missed"],
  ["negative_predictive_value", "Negative predictive value", "ratio", true, "Of the windows passed as normal, how many were normal"],
  ["false_alarms_per_1000_normal_windows", "False alarms per 1,000 normal windows", "per1k", false, "Operational alarm load"],
];
const CM = [["tp", "True positives"], ["tn", "True negatives"], ["fp", "False positives"], ["fn", "False negatives"]];
const DELAY = [
  ["evaluated_attack_timelines", "Attack timelines evaluated", "int", null],
  ["missed_attack_timelines", "Attack timelines missed", "int", false],
  ["median_delay_windows", "Median time to detect (windows)", "num1", false],
  ["mean_delay_windows", "Mean time to detect (windows)", "num2", false],
  ["maximum_delay_windows", "Worst-case time to detect (windows)", "int", false],
];

const fmt = (v, kind) => {
  if (v === null || v === undefined || Number.isNaN(v)) return "—";
  if (kind === "ratio") return fixed(v, 4);
  if (kind === "per1k") return fixed(v, 2);
  if (kind === "int") return int(v);
  if (kind === "num1") return fixed(v, 1);
  if (kind === "num2") return fixed(v, 2);
  return String(v);
};

function downloadCsv(filename, header, rows) {
  const esc = (v) => {
    const s = v === null || v === undefined ? "" : String(v);
    return /[",\n]/.test(s) ? `"${s.replace(/"/g, '""')}"` : s;
  };
  const text = [header, ...rows].map((r) => r.map(esc).join(",")).join("\n");
  const url = URL.createObjectURL(new Blob([text], { type: "text/csv" }));
  const a = h("a", { href: url, download: filename });
  document.body.append(a);
  a.click();
  a.remove();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}

const csvBtn = (onclick) =>
  h("button", { class: "btn btn-sm", type: "button", onclick },
    icon('<path d="M10 3v10M6 9l4 4 4-4M4 16h12"/>'), "Download CSV");

function scenarioLabel(s) {
  if (s.attack_type === "none") return "No attack";
  if (s.attack_type === "pns") return "Photon-number splitting";
  return `Intercept-resend ${Math.round(s.intensity * 100)}%`;
}

export function mountAllMetrics(root, { openRunTab }) {
  let source = "phase5";
  let bundle = null;
  let scenarios = null;
  let scenarioPromise = null;

  const fullHost = h("div");
  const scenarioHost = h("div");
  const phase4Host = h("div");

  const sourceSeg = segmented(
    [["phase5", "Held-out test set"], ["probabilistic", "Qiskit study: probabilistic"], ["hybrid_qiskit", "Qiskit study: Qiskit Aer"]],
    source,
    (v) => { source = v; renderFull(); },
  );

  root.append(
    h("div", { class: "callout", style: { marginBottom: "18px" } }, icon(ICONS.info),
      h("div", {}, "Every metric the evaluation scripts produce, side by side for all four detectors. Each table has a CSV download for the report.")),
    h("section", {},
      h("div", { class: "section-head" },
        h("h2", {}, "Classification metrics"),
        h("div", { class: "head-actions" }, sourceSeg)),
      fullHost),
    h("section", { class: "section" },
      h("div", { class: "section-head" },
        h("h2", {}, "By attack scenario"),
        h("p", {}, "Recall and time to detect per attack, false alarms on the normal windows of the same timelines.")),
      scenarioHost),
    h("section", { class: "section" },
      h("div", { class: "section-head" },
        h("h2", {}, "Cryptography and key rate"),
        h("p", {}, "From the Phase 4 benchmark.")),
      phase4Host),
  );

  function emptyPanel(title, text, withRun = true) {
    return h("div", { class: "panel" }, h("div", { class: "empty" },
      h("h3", {}, title), h("p", {}, text),
      withRun ? h("button", { class: "btn btn-primary", type: "button", onclick: openRunTab }, "Open run evaluations") : null));
  }

  // ---------------------------------------------------------------- full table
  function sourceData() {
    if (source === "phase5") {
      const r = bundle.phase5;
      return r ? { metrics: r.metrics, delay: r.detection_delay, mcnemar: r.paired_mcnemar_unified_vs_ml, label: "held_out" } : null;
    }
    const q = bundle.qiskit && bundle.qiskit.results[source];
    return q ? { metrics: q.metrics, delay: q.detection_delay, mcnemar: q.mcnemar_unified_vs_ml, label: source } : null;
  }

  function renderFull() {
    const d = sourceData();
    if (!d) {
      fullHost.replaceChildren(source === "phase5"
        ? emptyPanel("No held-out results yet", "Run the unified detector evaluation to produce outputs/phase5_evaluation_report.json.")
        : emptyPanel("No Qiskit study yet", "Run the Qiskit backend comparison to produce outputs/phase5_qiskit_evaluation.json."));
      return;
    }
    const dets = DETECTORS.filter(([k]) => d.metrics[k]);
    const best = (key, higher, src) => {
      const vals = dets.map(([k]) => src[k]?.[key]).filter((v) => v !== null && v !== undefined);
      if (!vals.length || higher === null) return null;
      return higher ? Math.max(...vals) : Math.min(...vals);
    };

    const head = h("tr", {}, h("th", {}, "Metric"), dets.map(([, l]) => h("th", { class: "r" }, l)));
    const groupRow = (label) => h("tr", {}, h("td", { colspan: dets.length + 1, style: { background: "var(--panel-2)", fontWeight: 600, color: "var(--ink-2)", fontSize: "var(--fs-xs)" } }, label));
    const valueCell = (v, kind, isBest) => h("td", { class: "r", style: isBest ? { fontWeight: 700, color: "var(--cobalt-2)" } : {} }, fmt(v, kind));

    const body = [];
    const csv = [];
    body.push(groupRow("Window-level classification"));
    for (const [key, label, kind, higher, hint] of FULL_METRICS) {
      const b = best(key, higher, d.metrics);
      body.push(h("tr", {},
        h("td", { title: hint }, label, h("div", { style: { fontSize: "var(--fs-xs)", color: "var(--muted)" } }, hint)),
        dets.map(([k]) => valueCell(d.metrics[k][key], kind, d.metrics[k][key] === b))));
      csv.push([label, ...dets.map(([k]) => d.metrics[k][key])]);
    }
    body.push(groupRow("Confusion counts"));
    for (const [key, label] of CM) {
      body.push(h("tr", {}, h("td", {}, label), dets.map(([k]) => valueCell(d.metrics[k].confusion_matrix[key], "int", false))));
      csv.push([label, ...dets.map(([k]) => d.metrics[k].confusion_matrix[key])]);
    }
    if (d.delay) {
      body.push(groupRow("Time to detect (per attacked timeline)"));
      for (const [key, label, kind, higher] of DELAY) {
        const src = Object.fromEntries(dets.map(([k]) => [k, d.delay[k] || {}]));
        const b = best(key, higher, src);
        body.push(h("tr", {}, h("td", {}, label), dets.map(([k]) => valueCell(src[k][key], kind, higher !== null && src[k][key] === b))));
        csv.push([label, ...dets.map(([k]) => src[k][key])]);
      }
    }

    const m = d.mcnemar;
    fullHost.replaceChildren(
      h("div", { class: "panel table-wrap" }, h("table", { class: "data" }, h("thead", {}, head), h("tbody", {}, body))),
      h("div", { style: { display: "flex", gap: "12px", alignItems: "center", justifyContent: "space-between", flexWrap: "wrap", marginTop: "10px" } },
        h("p", { style: { color: "var(--muted)", fontSize: "var(--fs-xs)" } },
          "Blue bold marks the best detector on each row. ",
          m ? `Unified vs Random Forest, exact McNemar p = ${m.p_value.toFixed(3)} (${m.second_only_correct} windows only Unified got right, ${m.first_only_correct} only RF).` : ""),
        csvBtn(() => downloadCsv(`metrics_${d.label}.csv`, ["metric", ...dets.map(([, l]) => l)], csv))));
  }

  // ---------------------------------------------------------------- scenarios
  async function loadScenarios() {
    if (!scenarioPromise) {
      scenarioHost.replaceChildren(h("div", { class: "panel" }, h("div", { class: "empty" },
        h("span", { class: "spinner" }), h("p", {}, "Scoring every detector on the held-out timelines…"))));
      scenarioPromise = api("/api/evaluation/scenarios").catch((err) => ({ available: false, reason: err.message }));
    }
    scenarios = await scenarioPromise;
    renderScenarios();
  }

  function renderScenarios() {
    const s = scenarios;
    if (!s || !s.available) {
      scenarioHost.replaceChildren(emptyPanel("Breakdown unavailable",
        `${s && s.reason ? s.reason + ". " : ""}Run the unified detector evaluation first; it creates the dataset and model this needs.`));
      return;
    }
    const attackRows = s.scenarios.filter((r) => r.attack_type !== "none");

    const cell = (v, kind, good) => h("td", { class: "r", style: good === false ? { color: "var(--eve)", fontWeight: 600 } : {} }, v === undefined || v === null ? "—" : kind === "pct" ? pct(v, 1) : kind === "int" ? String(v) : fixed(v, 0));

    const recallTable = h("table", { class: "data" },
      h("thead", {},
        h("tr", {}, h("th"), h("th", { class: "r" }), h("th", { class: "r", colspan: 4 }, "Recall (attack windows caught)"), h("th", { class: "r", colspan: 4 }, "Median windows to first alarm")),
        h("tr", {}, h("th", {}, "Scenario"), h("th", { class: "r" }, "Timelines"),
          DETECTORS.map(([, l]) => h("th", { class: "r" }, l.split(" ")[0])),
          DETECTORS.map(([, l]) => h("th", { class: "r" }, l.split(" ")[0])))),
      h("tbody", {}, attackRows.map((r) => {
        const recalls = DETECTORS.map(([k]) => r.detectors[k].recall);
        const top = Math.max(...recalls);
        return h("tr", {},
          h("td", {}, scenarioLabel(r), h("div", { style: { fontSize: "var(--fs-xs)", color: "var(--muted)" } }, `${r.attack_windows} attack windows`)),
          h("td", { class: "r" }, r.timelines),
          DETECTORS.map(([k]) => {
            const v = r.detectors[k].recall;
            return h("td", { class: "r", style: v === top ? { fontWeight: 700, color: "var(--cobalt-2)" } : v < 0.5 ? { color: "var(--eve)" } : {} }, pct(v, 1));
          }),
          DETECTORS.map(([k]) => {
            const e = r.detectors[k];
            const missedAll = e.missed_timelines && e.missed_timelines === r.timelines;
            return h("td", { class: "r", style: missedAll ? { color: "var(--eve)" } : {} },
              missedAll ? "never" : `${fixed(e.median_delay, 0)}${e.missed_timelines ? ` (${e.missed_timelines} missed)` : ""}`);
          }));
      })));

    const faTable = h("table", { class: "data" },
      h("thead", {}, h("tr", {}, h("th", {}, "Normal windows from"), h("th", { class: "r" }, "Windows"), DETECTORS.map(([, l]) => h("th", { class: "r" }, l)))),
      h("tbody", {}, s.scenarios.map((r) => h("tr", {},
        h("td", {}, r.attack_type === "none" ? "No-attack timelines" : `${scenarioLabel(r)} timelines, before Eve`),
        h("td", { class: "r" }, int(r.normal_windows)),
        DETECTORS.map(([k]) => cell(r.detectors[k].false_alarm_rate, "pct"))))));

    const csvRows = s.scenarios.flatMap((r) => DETECTORS.map(([k, l]) => [
      scenarioLabel(r), l, r.timelines, r.attack_windows, r.normal_windows,
      r.detectors[k].recall ?? "", r.detectors[k].median_delay ?? "", r.detectors[k].missed_timelines ?? "", r.detectors[k].false_alarm_rate ?? "",
    ]));

    scenarioHost.replaceChildren(
      h("div", { class: "panel table-wrap" }, recallTable),
      h("div", { class: "panel table-wrap", style: { marginTop: "12px" } }, faTable),
      h("div", { style: { display: "flex", gap: "12px", alignItems: "flex-start", justifyContent: "space-between", flexWrap: "wrap", marginTop: "10px" } },
        h("p", { style: { color: "var(--muted)", fontSize: "var(--fs-xs)", maxWidth: "80ch" } },
          `Computed live from the ${s.test_timelines} held-out test timelines (${int(s.test_windows)} windows) using the model trained ${s.model_updated} and data generated ${s.data_updated}. `,
          "Same split, features and thresholds as train_phase5_unified.py. Red marks recall under 50%.",
          s.data_newer_than_model ? h("strong", { style: { color: "var(--amber)" } }, " The dataset was regenerated after this model was trained, so these totals can differ slightly from the held-out report above. Retrain to line them up.") : null),
        csvBtn(() => downloadCsv("metrics_by_scenario.csv",
          ["scenario", "detector", "timelines", "attack_windows", "normal_windows", "recall", "median_delay_windows", "missed_timelines", "false_alarm_rate"], csvRows))));
  }

  // ---------------------------------------------------------------- phase 4
  function renderPhase4() {
    const p4 = bundle.phase4;
    const stress = bundle.stress;
    if (!p4 && !stress) {
      phase4Host.replaceChildren(emptyPanel("No Phase 4 benchmark yet",
        "Run the Phase 4 quick benchmark to measure ML-DSA and ML-KEM latency and the secure key rate under different noise levels and attacks."));
      return;
    }
    const parts = [];
    if (p4 && p4.pqc_latency) {
      const l = p4.pqc_latency;
      const rows = [
        ["Classical message without PQC", l.without_pqc_median_ms],
        ["ML-DSA-65 sign and verify", l.ml_dsa_sign_verify_median_ms],
        ["Authentication overhead per message", l.pqc_authentication_overhead_ms],
        ["ML-KEM-768 keygen, encapsulate, decapsulate", l.ml_kem_roundtrip_median_ms],
      ];
      parts.push(h("div", { class: "panel table-wrap" }, h("table", { class: "data" },
        h("thead", {}, h("tr", {}, h("th", {}, "Post-quantum operation"), h("th", { class: "r" }, `Median over ${l.rounds} rounds`))),
        h("tbody", {}, rows.map(([label, v]) => h("tr", {}, h("td", {}, label), h("td", { class: "r" }, ms(v))))))));
    }
    if (p4 && p4.qiskit_comparison && p4.qiskit_comparison.length) {
      parts.push(h("div", { class: "panel table-wrap", style: { marginTop: "12px" } }, h("table", { class: "data" },
        h("thead", {}, h("tr", {}, h("th", {}, "QBER check"), h("th", { class: "r" }, "Probabilistic"), h("th", { class: "r" }, "Qiskit"), h("th", { class: "r" }, "Difference"), h("th", { class: "r" }, "Circuits"))),
        h("tbody", {}, p4.qiskit_comparison.map((r) => h("tr", {},
          h("td", {}, r.attack_type === "none" ? "No attack" : "Full intercept-resend"),
          h("td", { class: "r" }, pct(r.probabilistic_qber, 2)), h("td", { class: "r" }, pct(r.qiskit_qber, 2)),
          h("td", { class: "r" }, pct(r.absolute_qber_difference, 2)), h("td", { class: "r" }, int(r.qiskit_circuits))))))));
    }
    if (stress && stress.length) {
      const num = (v) => Number(v);
      parts.push(h("div", { class: "panel table-wrap", style: { marginTop: "12px" } }, h("table", { class: "data" },
        h("thead", {}, h("tr", {},
          h("th", {}, "Noise"), h("th", {}, "Attack"), h("th", { class: "r" }, "Accuracy"), h("th", { class: "r" }, "Detection rate"),
          h("th", { class: "r" }, "False positive rate"), h("th", { class: "r" }, "Est. secure bits"), h("th", { class: "r" }, "Key rate (bits/photon)"))),
        h("tbody", {}, stress.map((r) => h("tr", {},
          h("td", {}, pct(num(r.noise_level), 0)),
          h("td", {}, r.attack_type === "none" ? "None" : r.attack_type === "pns" ? "PNS" : `Intercept-resend ${Math.round(num(r.attack_intensity) * 100)}%`),
          h("td", { class: "r" }, fixed(num(r.accuracy), 3)),
          h("td", { class: "r" }, r.attack_type === "none" ? "—" : pct(num(r.detection_rate), 1)),
          h("td", { class: "r" }, pct(num(r.false_positive_rate), 1)),
          h("td", { class: "r" }, int(num(r.estimated_secure_key_bits))),
          h("td", { class: "r" }, fixed(num(r.estimated_secure_key_rate), 4))))))));
      parts.push(h("div", { style: { display: "flex", justifyContent: "flex-end", marginTop: "10px" } },
        csvBtn(() => downloadCsv("phase4_stress.csv", Object.keys(stress[0]), stress.map((r) => Object.values(r))))));
    }
    parts.push(h("div", { class: "callout", style: { marginTop: "12px" } }, icon(ICONS.info),
      h("div", {}, h("strong", {}, "Detector numbers from Phase 4 are left out on purpose. "),
        "benchmark_phase4.py scores the Random Forest on its full dataset, including timelines it was trained on, so cite the held-out Phase 5 table instead.")));
    phase4Host.replaceChildren(...parts);
  }

  return {
    render(next) {
      bundle = next;
      renderFull();
      renderPhase4();
      loadScenarios();
    },
    invalidate() { scenarioPromise = null; },
  };
}
