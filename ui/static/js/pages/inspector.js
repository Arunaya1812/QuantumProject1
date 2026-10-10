// Protocol inspector: BB84 photon by photon, plus decoy-state statistics.

import { h, icon, ICONS, api, pct, int, segmented, setRangeFill, toast } from "../util.js";

const BAR = { "0°": "M3 10h14", "90°": "M10 3v14", "45°": "M4.5 15.5l11-11", "135°": "M4.5 4.5l11 11" };
const BASIS = { "+": "M10 3.5v13M3.5 10h13", x: "M5 5l10 10M15 5L5 15" };
const glyph = (d) => h("svg", { viewBox: "0 0 20 20", "aria-hidden": "true" }, h("path", { d }));
const basisName = (b) => (b === "+" ? "rectilinear (+)" : "diagonal (×)");
const polFor = (basis, bit) => ({ "+0": "0°", "+1": "90°", x0: "45°", x1: "135°" }[`${basis}${bit}`]);

export function mountInspector(root) {
  const tabs = h("div", { class: "tabs", role: "tablist" });
  const walkPanel = h("div", { role: "tabpanel" });
  const decoyPanel = h("div", { role: "tabpanel", hidden: true });
  const mkTab = (label, panel, selected) => {
    const b = h("button", { role: "tab", type: "button", "aria-selected": String(selected) }, label);
    b.addEventListener("click", () => {
      tabs.querySelectorAll("button").forEach((x) => x.setAttribute("aria-selected", "false"));
      b.setAttribute("aria-selected", "true");
      walkPanel.hidden = panel !== walkPanel;
      decoyPanel.hidden = panel !== decoyPanel;
      if (panel === decoyPanel && !decoyLoaded) runDecoy();
    });
    return b;
  };
  tabs.append(mkTab("Photon walkthrough", walkPanel, true), mkTab("Decoy states", decoyPanel, false));

  root.append(
    h("header", { class: "page-head" },
      h("div", {},
        h("h1", {}, "Protocol inspector"),
        h("p", { class: "lede" }, "Follow individual photons through BB84: encoding, Eve's interference, Bob's measurement, sifting and the public error check."))),
    tabs, walkPanel, decoyPanel);

  // ================================================================ walkthrough
  const W = { photons: 32, attack: "intercept_resend", selected: null, data: null };
  const countSeg = segmented([["16", "16"], ["32", "32"], ["64", "64"]], "32", (v) => { W.photons = Number(v); });
  const eveSeg = segmented([["none", "No Eve"], ["intercept_resend", "Eve intercepts"]], W.attack, (v) => { W.attack = v; intGroup.hidden = v === "none"; }, "eve-mode");
  const intRange = h("input", { type: "range", min: 10, max: 100, step: 10, value: 100, class: "eve", "aria-label": "Share intercepted" });
  const intOut = h("output", {}, "100%");
  intRange.addEventListener("input", () => { intOut.textContent = `${intRange.value}%`; setRangeFill(intRange); });
  setRangeFill(intRange);
  const intGroup = h("div", { class: "group" }, h("span", { class: "label" }, "Intercepts"), h("div", { class: "range-row" }, intRange, intOut));
  const noiseRange = h("input", { type: "range", min: 0, max: 10, step: 1, value: 0, "aria-label": "Channel noise" });
  const noiseOut = h("output", {}, "0%");
  noiseRange.addEventListener("input", () => { noiseOut.textContent = `${noiseRange.value}%`; setRangeFill(noiseRange); });
  setRangeFill(noiseRange);
  const seedInput = h("input", { class: "input num", type: "number", value: 84, style: { width: "86px" }, "aria-label": "Seed" });
  const sendBtn = h("button", { class: "btn btn-primary", type: "button", onclick: runTrace }, icon(ICONS.run), "Send photons");

  const controls = h("div", { class: "control-bar", style: { paddingTop: 0, marginBottom: "18px" } },
    h("div", { class: "group" }, h("span", { class: "label" }, "Photons"), countSeg),
    h("div", { class: "group" }, eveSeg),
    intGroup,
    h("div", { class: "group" }, h("span", { class: "label" }, "Noise"), h("div", { class: "range-row", style: { width: "130px" } }, noiseRange, noiseOut)),
    h("div", { class: "group" }, h("span", { class: "label" }, "Seed"), seedInput),
    h("div", { class: "spacer" }),
    sendBtn);

  const tapeHost = h("div", { class: "panel panel-pad" });
  const detail = h("div", { class: "panel panel-pad" });
  const summary = h("div", { class: "panel panel-pad" });
  walkPanel.append(controls, tapeHost,
    h("div", { class: "pqc-grid", style: { marginTop: "18px" } }, detail, summary));

  const ROWS = ["Alice bit", "Alice basis", "Polarisation", "Eve", "Bob basis", "Bob bit", "Bases match", "Error check"];

  function cell(content, cls = "") { return h("div", { class: `tcell ${cls}` }, content); }

  function renderTape(data) {
    const labels = h("div", { class: "tape-labels" }, h("div", { class: "idx" }), ROWS.map((r) => h("div", { class: "tape-row-label" }, r)));
    const cols = data.rows.map((r) => {
      let check;
      if (!r.kept) check = cell("", "dim");
      else if (r.sampled) check = cell(r.error ? glyph(BASIS.x) : glyph("M4 10.5l4 4 8-9"), `${r.error ? "err" : "ok"} sample`);
      else check = cell("key", "kept");
      const col = h("button", { type: "button", class: "tcol", "aria-pressed": String(W.selected === r.index), "aria-label": `Photon ${r.index}` },
        h("div", { class: "idx" }, String(r.index)),
        cell(String(r.alice_bit)),
        cell(glyph(BASIS[r.alice_basis])),
        cell(glyph(BAR[r.polarisation]), "kept"),
        r.eve_basis ? cell(glyph(BASIS[r.eve_basis]), "eve") : cell("·", "dim"),
        cell(glyph(BASIS[r.bob_basis])),
        cell(String(r.bob_bit), r.kept && r.error ? "eve" : ""),
        r.kept ? cell(glyph("M4 10.5l4 4 8-9"), "ok") : cell("", "dim"),
        check);
      col.addEventListener("click", () => select(r.index));
      return col;
    });
    tapeHost.replaceChildren(
      h("div", { class: "section-head", style: { marginBottom: "14px" } },
        h("h2", {}, "Photon tape"),
        h("p", {}, "Select a photon to see what happened to it. An amber outline marks bits revealed for the error check.")),
      h("div", { class: "tape-wrap" }, h("div", { class: "tape-grid" }, labels, h("div", { class: "tape" }, cols))));
  }

  async function select(index) {
    W.selected = index;
    tapeHost.querySelectorAll(".tcol").forEach((c, i) => c.setAttribute("aria-pressed", String(i === index)));
    const r = W.data.rows[index];
    const lines = [];
    lines.push(`Alice encodes ${r.alice_bit} in the ${basisName(r.alice_basis)} basis, a ${r.polarisation} photon.`);
    if (r.noise_flip) lines.push("Channel noise flips the bit on the way.");
    if (r.eve_basis) {
      lines.push(r.eve_basis === r.alice_basis
        ? `Eve measures in the same basis, reads ${r.eve_bit} and re-sends a copy. She learns the bit without disturbing it.`
        : `Eve guesses the ${basisName(r.eve_basis)} basis, reads ${r.eve_bit} and re-sends a ${polFor(r.eve_basis, r.eve_bit)} photon. The original state is destroyed.`);
    }
    lines.push(`Bob measures in the ${basisName(r.bob_basis)} basis and reads ${r.bob_bit}.`);
    if (!r.kept) lines.push("Their bases differ, so the bit is discarded during sifting.");
    else if (r.sampled) lines.push(r.error ? "Bases match and the bit is revealed for the error check. It disagrees with Alice's bit, which counts toward the QBER." : "Bases match and the bit is revealed for the error check. It agrees, so it adds no error.");
    else lines.push(r.error ? "Bases match and the bit enters the key, but it differs from Alice's. Error correction has to fix it." : "Bases match and the bit becomes part of the raw key.");

    const circuitBox = h("div", {}, h("p", { style: { color: "var(--muted)", fontSize: "var(--fs-sm)" } }, "Loading circuit…"));
    detail.replaceChildren(
      h("div", { class: "section-head" }, h("h2", {}, `Photon ${index}`),
        h("span", { class: `pill ${!r.kept ? "" : r.error ? "eve" : "secure"}` }, !r.kept ? "Discarded" : r.error ? "Error" : r.sampled ? "Checked" : "Key bit")),
      h("ol", { class: "steps" }, lines.map((l) => h("li", {}, h("div", { style: { gridColumn: "2 / 4" } }, l)))),
      h("div", { style: { marginTop: "14px" } }, h("h3", { style: { fontSize: "var(--fs-sm)", marginBottom: "8px" } }, "Bob's measurement as a Qiskit circuit"), circuitBox));

    const inBasis = r.eve_basis || r.alice_basis;
    const inBit = r.eve_basis ? r.eve_bit : r.alice_bit;
    try {
      const c = await api(`/api/circuit?bit=${inBit}&prep=${encodeURIComponent(inBasis)}&measure=${encodeURIComponent(r.bob_basis)}&flipped=${!r.eve_basis && r.noise_flip}`);
      if (W.selected !== index) return;
      circuitBox.replaceChildren(c.available
        ? h("pre", { class: "circuit" }, c.text)
        : h("div", { class: "callout" }, icon(ICONS.info), "Install qiskit and qiskit-aer to render circuits."));
    } catch (err) { circuitBox.replaceChildren(h("p", {}, err.message)); }
  }

  function renderSummary(s) {
    const marked = (key, other) => [...key].map((b, i) => (b !== other[i] ? h("span", { class: "x" }, b) : b));
    summary.replaceChildren(
      h("div", { class: "section-head" }, h("h2", {}, "Result"),
        h("span", { class: `pill ${s.qber > 0.11 ? "eve" : "secure"}` }, `QBER ${pct(s.qber, 1)}`)),
      h("dl", { class: "kv" },
        h("dt", {}, "Photons sent"), h("dd", {}, int(s.photons)),
        h("dt", {}, "Intercepted by Eve"), h("dd", {}, int(s.intercepted)),
        h("dt", {}, "Kept after sifting"), h("dd", {}, `${s.sifted} (${pct(s.sifted / s.photons, 0)})`),
        h("dt", {}, "Revealed for checking"), h("dd", {}, `${s.sample_size} bits, ${s.sample_errors} wrong`),
        h("dt", {}, "Remaining key"), h("dd", {}, `${s.key_alice.length} bits, ${s.key_mismatches} mismatched`)),
      h("div", { class: "keys", style: { marginTop: "16px" } },
        h("div", { class: "krow" }, h("span", {}, "Alice"), h("span", { class: "bits" }, s.key_alice || "—")),
        h("div", { class: "krow" }, h("span", {}, "Bob"), h("span", { class: "bits" }, marked(s.key_bob, s.key_alice)))),
      h("div", { class: "callout", style: { marginTop: "16px" } }, icon(ICONS.info),
        h("div", {}, "With every photon intercepted, Eve picks the wrong basis half the time and Bob then reads a random bit, so roughly ",
          h("strong", {}, "25% of sifted bits"), " disagree. Partial interception scales this down, which is why stealthy attacks are hard to see on QBER alone.")));
  }

  async function runTrace() {
    sendBtn.disabled = true;
    try {
      const data = await api("/api/trace", {
        method: "POST",
        body: {
          photons: W.photons, attack: W.attack, intensity: Number(intRange.value) / 100,
          noise: Number(noiseRange.value) / 100, seed: Number(seedInput.value),
        },
      });
      W.data = data;
      renderTape(data);
      renderSummary(data.summary);
      const firstKept = data.rows.find((r) => r.kept && r.eve_basis) || data.rows.find((r) => r.kept) || data.rows[0];
      select(firstKept.index);
    } catch (err) { toast(err.message, "error"); }
    finally { sendBtn.disabled = false; }
  }

  // ================================================================ decoy
  let decoyLoaded = false;
  const distRange = h("input", { type: "range", min: 5, max: 100, step: 5, value: 25, "aria-label": "Fibre length" });
  const distOut = h("output", {}, "25 km");
  distRange.addEventListener("input", () => { distOut.textContent = `${distRange.value} km`; setRangeFill(distRange); });
  distRange.addEventListener("change", runDecoy);
  setRangeFill(distRange);
  const decoyBody = h("div");
  decoyPanel.append(
    h("div", { class: "control-bar", style: { paddingTop: 0, marginBottom: "18px" } },
      h("div", { class: "group" }, h("span", { class: "label" }, "Fibre length"), h("div", { class: "range-row", style: { width: "220px" } }, distRange, distOut)),
      h("div", { class: "spacer" }),
      h("button", { class: "btn", type: "button", onclick: runDecoy }, icon(ICONS.reset), "Resimulate")),
    decoyBody);

  async function runDecoy() {
    decoyLoaded = true;
    decoyBody.classList.add("loading-veil");
    try {
      const d = await api("/api/decoy", { method: "POST", body: { distance: Number(distRange.value), pulses: 40000, seed: Date.now() % 100000 } });
      const max = Math.max(d.normal.rates.signal, d.pns.rates.signal, d.normal.rates.decoy, d.pns.rates.decoy) * 1.05;
      const bar = (label, value, cls) => h("div", { class: "bar-row" },
        h("span", {}, label),
        h("div", { class: "track" }, h("i", { class: cls, style: { width: `${(value / max) * 100}%` } })),
        h("span", { class: "v" }, `${(value * 100).toFixed(2)}%`));
      const ratioN = d.normal.rates.decoy / d.normal.rates.signal;
      const ratioP = d.pns.rates.decoy / d.pns.rates.signal;
      decoyBody.replaceChildren(h("div", { class: "pqc-grid" },
        h("div", { class: "panel panel-pad" },
          h("div", { class: "section-head" }, h("h2", {}, "Detection rate by pulse type"),
            h("p", {}, `${int(d.pulses)} pulses per condition, ${d.distance_km} km`)),
          h("div", { class: "bars-h" },
            bar("Signal, clean", d.normal.rates.signal, ""),
            bar("Signal, PNS", d.pns.rates.signal, "eve"),
            bar("Decoy, clean", d.normal.rates.decoy, ""),
            bar("Decoy, PNS", d.pns.rates.decoy, "eve")),
          h("div", { class: "legend", style: { marginTop: "14px" } },
            h("span", {}, h("i", { class: "block", style: { background: "var(--cobalt)" } }), "Clean channel"),
            h("span", {}, h("i", { class: "block", style: { background: "var(--eve)" } }), "Under photon-number splitting"))),
        h("div", { class: "panel panel-pad" },
          h("div", { class: "section-head" }, h("h2", {}, "What the detector sees")),
          h("dl", { class: "kv" },
            h("dt", {}, "Signal–decoy gap, clean"), h("dd", {}, d.normal.gap.toFixed(4)),
            h("dt", {}, "Signal–decoy gap, PNS"), h("dd", { style: { color: "var(--eve)" } }, d.pns.gap.toFixed(4)),
            h("dt", {}, "Decoy-to-signal ratio, clean"), h("dd", {}, ratioN.toFixed(3)),
            h("dt", {}, "Decoy-to-signal ratio, PNS"), h("dd", {}, ratioP.toFixed(3)),
            h("dt", {}, "Channel transmittance"), h("dd", {}, d.transmittance.toExponential(2)),
            h("dt", {}, "Mean photons, signal and decoy"), h("dd", {}, `${d.mu.signal} and ${d.mu.decoy}`)),
          h("div", { class: "callout", style: { marginTop: "16px" } }, icon(ICONS.info),
            h("div", {}, "In this model Eve blocks single-photon pulses and forwards multi-photon ones, which leaves QBER untouched. Decoy pulses rarely hold two photons, so the ",
              h("strong", {}, "signal and decoy detection rates pull apart"), ". That gap is the feature the detector watches for PNS.")))));
    } catch (err) { toast(err.message, "error"); }
    finally { decoyBody.classList.remove("loading-veil"); }
  }

  runTrace();
}
