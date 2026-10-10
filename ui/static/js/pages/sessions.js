// Key sessions: run the full detect -> authenticate -> derive pipeline.

import { h, icon, ICONS, api, pct, int, ms, segmented, setRangeFill, toast, css, ATTACK_LABEL } from "../util.js";
import { seriesChart, legend } from "../charts.js";

export function mountSessions(root, system) {
  const C = { cobalt: css("--cobalt"), eve: css("--eve"), eveTint: "rgba(196, 42, 87, 0.09)", ink2: css("--ink-2") };
  const runs = [];
  const form = { backend: "probabilistic", attack: "intercept_resend" };

  // ---------------------------------------------------------------- form
  const backendSeg = segmented([["probabilistic", "Probabilistic"], ["qiskit", "Qiskit Aer"]], form.backend, (v) => { form.backend = v; });
  const attack = h("select", { class: "select", id: "s-attack" },
    Object.entries(ATTACK_LABEL).map(([v, l]) => h("option", { value: v, selected: v === form.attack }, l)));
  const rangeField = (id, label, min, max, step, value, fmt, cls = "") => {
    const input = h("input", { type: "range", id, min, max, step, value, class: cls });
    const out = h("output", { for: id }, fmt(value));
    input.addEventListener("input", () => { out.textContent = fmt(input.value); setRangeFill(input); });
    setRangeFill(input);
    return { input, node: h("div", { class: "field" }, h("label", { for: id }, label), h("div", { class: "range-row" }, input, out)) };
  };
  const intensity = rangeField("s-int", "Share of photons intercepted", 5, 100, 5, 20, (v) => `${v}%`, "eve");
  const start = rangeField("s-start", "Eve arrives after", 10, 90, 5, 50, (v) => `${v}%`);
  const noise = rangeField("s-noise", "Channel noise", 0, 8, 0.5, 2, (v) => `${Number(v).toFixed(1)}%`);
  const windows = h("input", { class: "input num", type: "number", id: "s-win", min: 12, max: 200, value: 40 });
  const photons = h("select", { class: "select", id: "s-ph" },
    [1000, 2000, 4000].map((v) => h("option", { value: v, selected: v === 2000 }, int(v))));
  const seed = h("input", { class: "input num", type: "number", id: "s-seed", value: 2026 });
  const runBtn = h("button", { class: "btn btn-primary", type: "submit", style: { width: "100%" } }, icon(ICONS.run), "Run session");

  const syncAttack = () => {
    intensity.node.hidden = attack.value !== "intercept_resend";
    start.node.hidden = attack.value === "none";
  };
  attack.addEventListener("change", syncAttack);
  syncAttack();

  const formEl = h("form", { class: "panel form-stack", onsubmit: (e) => { e.preventDefault(); run(); } },
    h("h2", { style: { fontSize: "var(--fs-md)" } }, "New session"),
    h("div", { class: "field" }, h("span", { class: "label" }, "Quantum backend"), backendSeg),
    h("div", { class: "field" }, h("label", { for: "s-attack" }, "Eavesdropper"), attack),
    intensity.node, start.node, noise.node,
    h("div", { class: "form-row" },
      h("div", { class: "field" }, h("label", { for: "s-win" }, "Monitoring windows"), windows),
      h("div", { class: "field" }, h("label", { for: "s-ph" }, "Key photons"), photons)),
    h("div", { class: "field" }, h("label", { for: "s-seed" }, "Random seed"), seed,
      h("span", { class: "hint" }, "The same seed and settings reproduce the same run.")),
    runBtn);

  system.ready.then((info) => {
    if (info && !info.capabilities.qiskit) {
      backendSeg.querySelector('[data-value="qiskit"]').disabled = true;
      backendSeg.querySelector('[data-value="qiskit"]').title = "Install qiskit and qiskit-aer to enable";
    }
  });

  // ---------------------------------------------------------------- result area
  const result = h("div", { class: "panel" },
    h("div", { class: "empty" },
      h("h3", {}, "No session yet"),
      h("p", {}, "Run a session to watch the detector screen the link, then see the signed classical transcript and the final hybrid key fingerprint.")));

  const historyBody = h("tbody");
  const historyWrap = h("div", { class: "section", hidden: true },
    h("div", { class: "section-head" }, h("h2", {}, "Session history"), h("p", {}, "Sessions run since the server started. Select one to reopen it.")),
    h("div", { class: "panel table-wrap" },
      h("table", { class: "data" },
        h("thead", {}, h("tr", {},
          h("th", {}, "Time"), h("th", {}, "Outcome"), h("th", {}, "Eavesdropper"), h("th", {}, "Backend"),
          h("th", { class: "r" }, "Flagged"), h("th", { class: "r" }, "Time to detect"), h("th", {}, "Key fingerprint"))),
        historyBody)));

  root.append(
    h("header", { class: "page-head" },
      h("div", {},
        h("h1", {}, "Key sessions"),
        h("p", { class: "lede" }, "Each session screens the link with the unified detector first. Only a clean link proceeds to signed basis reconciliation, ML-KEM key exchange and hybrid key derivation."))),
    h("div", { class: "split" }, formEl, result),
    historyWrap);

  async function run() {
    runBtn.disabled = true;
    runBtn.replaceChildren(h("span", { class: "spinner" }), "Running…");
    result.classList.add("loading-veil");
    const body = {
      backend: form.backend,
      attack: attack.value,
      intensity: Number(intensity.input.value) / 100,
      attack_start: Number(start.input.value) / 100,
      noise: Number(noise.input.value) / 100,
      windows: Number(windows.value),
      photons: Number(photons.value),
      seed: Number(seed.value),
    };
    try {
      const record = await api("/api/sessions", { method: "POST", body });
      runs.unshift(record);
      render(record);
      renderHistory();
    } catch (err) {
      toast(err.message, "error");
    } finally {
      runBtn.disabled = false;
      runBtn.replaceChildren(icon(ICONS.run), "Run session");
      result.classList.remove("loading-veil");
    }
  }

  function render(r) {
    const ok = r.accepted;
    const p = r.params;
    let sub;
    if (ok) {
      sub = `${r.authenticated_messages} signed messages exchanged. ${int(r.qkd_key_bits)} QKD bits combined with an ML-KEM-768 secret.`;
    } else if (r.reason === "eavesdropping_detected") {
      sub = r.detection_delay !== null
        ? `Detected at window ${r.first_alarm_window}, ${r.detection_delay} window${r.detection_delay === 1 ? "" : "s"} after Eve arrived. No key material was released.`
        : `The detector flagged ${r.flagged} windows. No key material was released.`;
    } else sub = r.reason.replaceAll("_", " ");

    const headEl = h("div", { class: `result-head ${ok ? "accepted" : "rejected"}` },
      h("div", { class: "badge" }, icon(ok ? ICONS.shield : ICONS.alert)),
      h("div", {}, h("h2", {}, ok ? "Key established" : "Session aborted"), h("p", {}, sub)),
      h("div", { class: "right" },
        h("span", { class: `pill ${p.attack_type === "none" ? "" : "eve"}` },
          p.attack_type === "intercept_resend" ? `Intercept-resend ${Math.round(p.attack_intensity * 100)}%` : ATTACK_LABEL[p.attack_type])));

    const facts = h("dl", { class: "facts" },
      fact("QBER on key photons", ok ? pct(r.qber, 2) : "not measured"),
      fact("QKD key bits", ok ? int(r.qkd_key_bits) : "0"),
      fact("Flagged windows", `${r.flagged} of ${r.windows}`),
      fact("Final key fingerprint", r.fingerprint || "none", !!r.fingerprint));

    const qHost = h("div");
    const pHost = h("div");
    const timeline = h("div", { class: "panel-pad" },
      h("div", { class: "chart-title" }, h("h3", {}, "Screening timeline"),
        legend([{ label: "QBER", color: C.cobalt }, { label: "Eve active", color: C.eveTint, kind: "block" }, { label: "Alarm", color: C.eve, kind: "block" }])),
      qHost,
      h("div", { class: "chart-title", style: { marginTop: "10px" } }, h("h3", {}, "Unified attack probability"),
        legend([{ label: "Fusion probability", color: C.cobalt }, { label: "Decision at 0.5", color: C.ink2, kind: "dash" }])),
      pHost);

    let transcript;
    if (r.transcript && r.transcript.length) {
      transcript = h("div", { class: "panel-pad", style: { borderTop: "1px solid var(--line)" } },
        h("div", { class: "chart-title" }, h("h3", {}, "Signed classical transcript"),
          h("span", { class: "pill cobalt" }, `ML-DSA-65  transcript ${r.transcript_hash}`)),
        h("ol", { class: "steps" }, r.transcript.map((m) =>
          h("li", {},
            h("div", {}, h("span", { class: "who" }, m.sender), " ", h("span", {}, m.type.replaceAll("_", " ")),
              h("div", { class: "summary" }, m.summary)),
            h("div", { class: "sig" }, h("b", {}, "verified"), h("br"), `${int(m.signature_bytes)} byte signature`)))));
    } else {
      transcript = h("div", { class: "panel-pad", style: { borderTop: "1px solid var(--line)" } },
        h("div", { class: "callout" }, icon(ICONS.info),
          h("div", {}, h("strong", {}, "Nothing was signed. "),
            "The session stopped at the screening stage, before basis reconciliation, so no information about a key went over the classical channel.")));
    }

    const foot = h("div", { class: "panel-pad", style: { borderTop: "1px solid var(--line)", color: "var(--muted)", fontSize: "var(--fs-xs)" } },
      `Backend ${p.protocol_backend}, noise ${pct(p.noise_level, 1)}, ${p.n_windows} windows, ${int(p.final_key_photons)} key photons, seed ${p.seed}. Completed in ${ms(r.elapsed_ms)}.`);

    result.replaceChildren(headEl, facts, timeline, transcript, foot);

    const domain = [0, Math.max(1, r.history.length - 1)];
    seriesChart(qHost, {
      height: 150, yFloor: 0.06, xDomain: domain, yFormat: (v, max) => `${(v * 100).toFixed(max < 0.08 ? 1 : 0)}%`,
      series: [{ key: "qber", label: "QBER", color: C.cobalt, area: true }],
      band: { key: "truth", color: C.eveTint }, markers: { key: "detected", color: C.eve },
      ariaLabel: "QBER per monitoring window",
      tooltip: (d) => [
        { label: "QBER", value: pct(d.qber, 2), color: C.cobalt },
        { label: "Eve active", value: d.truth ? "yes" : "no" },
        { label: "Detector", value: d.detected ? "alarm" : d.reason.replaceAll("_", " ") },
      ],
    }).update(r.history);
    seriesChart(pHost, {
      height: 120, yMax: 1, yTicks: 2, xDomain: domain, yFormat: (v) => v.toFixed(1),
      series: [{ key: "fusion_probability", label: "Fusion", color: C.cobalt }],
      refLines: [{ value: 0.5, color: C.ink2, width: 1, dash: "2 4" }],
      band: { key: "truth", color: C.eveTint }, markers: { key: "detected", color: C.eve },
      ariaLabel: "Unified attack probability per window",
      tooltip: (d) => [
        { label: "Fusion probability", value: d.fusion_probability.toFixed(3), color: C.cobalt },
        { label: "Random Forest", value: d.ml_probability.toFixed(3) },
      ],
    }).update(r.history);
  }

  function fact(label, value, mono = false) {
    return h("div", { class: "fact" }, h("dt", {}, label), h("dd", { class: mono ? "mono" : "" }, value));
  }

  function renderHistory() {
    historyWrap.hidden = runs.length === 0;
    historyBody.replaceChildren(...runs.map((r) => {
      const row = h("tr", { tabindex: 0, style: { cursor: "pointer" } },
        h("td", { class: "num" }, r.created),
        h("td", {}, h("span", { class: `pill ${r.accepted ? "secure" : "eve"}` }, r.accepted ? "Key established" : "Aborted")),
        h("td", {}, r.params.attack_type === "intercept_resend"
          ? `Intercept-resend ${Math.round(r.params.attack_intensity * 100)}%`
          : ATTACK_LABEL[r.params.attack_type]),
        h("td", {}, r.params.protocol_backend === "qiskit" ? "Qiskit Aer" : "Probabilistic"),
        h("td", { class: "r" }, `${r.flagged}/${r.windows}`),
        h("td", { class: "r" }, r.detection_delay === null ? "—" : `${r.detection_delay} window${r.detection_delay === 1 ? "" : "s"}`),
        h("td", { class: "mono" }, r.fingerprint || "—"));
      const open = () => { render(r); result.scrollIntoView({ behavior: "smooth", block: "start" }); };
      row.addEventListener("click", open);
      row.addEventListener("keydown", (e) => { if (e.key === "Enter") open(); });
      return row;
    }));
  }
}
