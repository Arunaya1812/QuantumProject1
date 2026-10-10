// Link monitor: live stream of detector windows over a WebSocket.

import { h, icon, ICONS, pct, fixed, int, segmented, setRangeFill, css, toast } from "../util.js";
import { seriesChart, legend } from "../charts.js";
import { createFiber } from "../fiber.js";

const MAX_POINTS = 120;

export function mountMonitor(root) {
  const S = {
    data: [],
    settings: { attack_type: "none", intensity: 0.3, noise: 0.02, drift: false, interval_ms: 450, photons: 250 },
    paused: false,
    connected: false,
    ws: null,
    attackStartWindow: null,
    firstAlarmWindow: null,
    lastState: null,
    events: [],
  };
  const C = {
    cobalt: css("--cobalt"), amber: css("--amber"), eve: css("--eve"),
    eveTint: "rgba(196, 42, 87, 0.09)", muted: css("--line-strong"), ink2: css("--ink-2"),
  };

  function speedSel() {
    const speed = h("select", { class: "select", "aria-label": "Window rate", style: { width: "152px" },
      onchange: () => send({ cmd: "interval", value: Number(speed.value) }) },
      h("option", { value: 900 }, "Slow stream"), h("option", { value: 450, selected: true }, "Normal stream"), h("option", { value: 160 }, "Fast stream"));
    return speed;
  }

  // ---------------------------------------------------------------- header
  const statusPill = h("span", { class: "pill" }, "Connecting…");
  const pauseBtn = h("button", { class: "btn", type: "button", onclick: togglePause }, icon(ICONS.pause), "Pause");
  const resetBtn = h("button", { class: "btn btn-ghost", type: "button", onclick: () => send({ cmd: "reset" }) }, icon(ICONS.reset), "Reset baseline");

  const head = h("header", { class: "page-head" },
    h("div", {},
      h("h1", {}, "Link monitor"),
      h("p", { class: "lede" },
        "Alice sends photons to Bob over 25 km of fibre. Every window carries 250 photons and 250 decoy pulses, and the unified detector decides whether someone is listening.")),
    h("div", { class: "head-actions" }, statusPill, resetBtn, speedSel(), pauseBtn));

  // ---------------------------------------------------------------- fibre strip
  const canvas = h("canvas", { "aria-hidden": "true" });
  const bobWhat = h("span", { class: "what" }, "Waiting for the first window");
  const fiberBox = h("div", { class: "fiber" },
    canvas,
    h("div", { class: "fiber-overlay" },
      h("div", { class: "station" }, h("span", { class: "who" }, "Alice"), h("span", { class: "what" }, "Sends 250 photons per window")),
      h("div", { class: "station right" }, h("span", { class: "who" }, "Bob"), bobWhat)));
  const fiber = createFiber(canvas);

  // ---------------------------------------------------------------- controls
  const eveSeg = segmented(
    [["none", "Off"], ["intercept_resend", "Intercept-resend"], ["pns", "Photon splitting"]],
    "none",
    (v) => send({ cmd: "attack", type: v, intensity: Number(intensity.value) / 100 }),
    "eve-mode",
  );
  const intensity = h("input", { type: "range", min: 5, max: 100, step: 5, value: 30, class: "eve", "aria-label": "Share of photons Eve intercepts" });
  const intensityOut = h("output", {}, "30%");
  intensity.addEventListener("input", () => { intensityOut.textContent = `${intensity.value}%`; setRangeFill(intensity); });
  intensity.addEventListener("change", () => send({ cmd: "intensity", value: Number(intensity.value) / 100 }));
  setRangeFill(intensity);
  const intensityGroup = h("div", { class: "group", hidden: true },
    h("span", { class: "label" }, "Intercepts"), h("div", { class: "range-row" }, intensity, intensityOut));

  const noise = h("input", { type: "range", min: 0, max: 8, step: 0.5, value: 2, "aria-label": "Natural channel noise" });
  const noiseOut = h("output", {}, "2.0%");
  noise.addEventListener("input", () => { noiseOut.textContent = `${Number(noise.value).toFixed(1)}%`; setRangeFill(noise); });
  noise.addEventListener("change", () => send({ cmd: "noise", value: Number(noise.value) / 100 }));
  setRangeFill(noise);

  const drift = h("input", { type: "checkbox", onchange: () => send({ cmd: "drift", value: drift.checked }) });

  const controls = h("div", { class: "control-bar" },
    h("div", { class: "group" }, h("span", { class: "label" }, "Eavesdropper"), eveSeg),
    intensityGroup,
    h("div", { class: "group" }, h("span", { class: "label" }, "Channel noise"), h("div", { class: "range-row" }, noise, noiseOut)),
    h("label", { class: "switch" }, drift, h("span", { class: "track" }), "Fibre drift"),
  );

  // ---------------------------------------------------------------- charts
  const qberHost = h("div");
  const gapHost = h("div");
  const probHost = h("div");
  const common = {
    band: { key: "attack_active", color: C.eveTint },
    markers: { key: "detected", color: C.eve },
  };
  const qberChart = seriesChart(qberHost, {
    ...common, height: 180, yFloor: 0.06, yFormat: (v, max) => `${(v * 100).toFixed(max < 0.08 ? 1 : 0)}%`,
    series: [{ key: "qber", label: "QBER", color: C.cobalt, area: true }],
    refLines: [{ value: (d) => d.qber_threshold, color: C.amber, label: "Adaptive threshold" }],
    ariaLabel: "Quantum bit error rate per window with adaptive threshold",
    tooltip: (d) => [
      { label: "QBER", value: pct(d.qber, 2), color: C.cobalt },
      { label: "Threshold", value: d.qber_threshold ? pct(d.qber_threshold, 2) : "calibrating", color: C.amber },
      { label: "Eve on the line", value: d.attack_active ? "yes" : "no" },
      { label: "Detector", value: d.detected ? "alarm" : (d.calibrating ? "calibrating" : "clear") },
    ],
  });
  const gapChart = seriesChart(gapHost, {
    ...common, height: 150, yFloor: 0.02, yFormat: (v, max) => v.toFixed(max < 0.1 ? 3 : 2),
    series: [{ key: "gap", label: "Signal–decoy gap", color: C.cobalt, area: true }],
    refLines: [{ value: (d) => d.gap_threshold, color: C.amber, label: "Adaptive threshold" }],
    ariaLabel: "Signal-decoy detection gap per window",
    tooltip: (d) => [
      { label: "Gap", value: fixed(d.gap, 4), color: C.cobalt },
      { label: "Threshold", value: d.gap_threshold ? fixed(d.gap_threshold, 4) : "calibrating", color: C.amber },
    ],
  });
  const probChart = seriesChart(probHost, {
    ...common, height: 150, yMax: 1, yTicks: 5, yFormat: (v) => v.toFixed(1),
    series: [
      { key: "ml_probability", label: "Random Forest", color: C.muted, width: 1.5 },
      { key: "fusion_probability", label: "Unified fusion", color: C.cobalt },
    ],
    refLines: [{ value: 0.5, color: C.ink2, label: "Decision", width: 1, dash: "2 4" }],
    ariaLabel: "Attack probability from the random forest and the unified fusion model",
    tooltip: (d) => [
      { label: "Unified fusion", value: fixed(d.fusion_probability, 3), color: C.cobalt },
      { label: "Random Forest", value: fixed(d.ml_probability, 3), color: C.muted },
      { label: "Baseline update", value: d.baseline_update_allowed ? "allowed" : "quarantined" },
    ],
  });

  const chartsPanel = h("div", { class: "panel charts-stack" },
    h("div", { class: "chart-block" },
      h("div", { class: "chart-title" }, h("h3", {}, "Quantum bit error rate"),
        legend([{ label: "QBER", color: C.cobalt }, { label: "Adaptive threshold", color: C.amber, kind: "dash" },
          { label: "Eve active", color: C.eveTint, kind: "block" }, { label: "Alarm", color: C.eve, kind: "block" }])),
      qberHost),
    h("div", { class: "chart-block" },
      h("div", { class: "chart-title" }, h("h3", {}, "Decoy-state gap"),
        legend([{ label: "Signal–decoy gap", color: C.cobalt }, { label: "Adaptive threshold", color: C.amber, kind: "dash" }])),
      gapHost),
    h("div", { class: "chart-block" },
      h("div", { class: "chart-title" }, h("h3", {}, "Attack probability"),
        legend([{ label: "Unified fusion", color: C.cobalt }, { label: "Random Forest", color: C.muted }])),
      probHost));

  // ---------------------------------------------------------------- side column
  const stateIcon = h("div", { class: "state-icon" }, icon(ICONS.gauge));
  const stateTitle = h("h2", {}, "Connecting");
  const stateText = h("p", {}, "Opening a stream to the detector.");
  const calibFill = h("i");
  const calibTrack = h("div", { class: "calib-track" }, calibFill);
  const verdict = h("div", { class: "verdict" }, h("div", { class: "state" }, stateIcon, stateTitle), stateText, calibTrack);

  const R = {};
  const readout = (key, label) => {
    R[key] = h("dd", {}, "—");
    return h("div", { class: "readout" }, h("dt", {}, label), R[key]);
  };
  const readouts = h("dl", { class: "readouts" },
    readout("qber", "QBER"), readout("gap", "Decoy gap"),
    readout("fusion", "Fusion probability"), readout("delay", "Time to detect"),
    readout("bits", "Secure key, estimated"), readout("alarms", "Flagged windows"));

  const logList = h("ol");
  const log = h("div", { class: "log" }, h("h3", {}, "Events"), logList);
  const side = h("div", { class: "panel side-col" }, h("div", {}, verdict, readouts), log);

  const grid = h("div", { class: "monitor-grid" }, chartsPanel, side);
  root.append(head, fiberBox, controls, grid);

  // ---------------------------------------------------------------- behaviour

  function addEvent(text, kind = "", windowIdx = null) {
    const time = new Date().toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit" });
    S.events.unshift({ text, kind, time, windowIdx });
    S.events = S.events.slice(0, 40);
    logList.replaceChildren(...S.events.map((e) =>
      h("li", { class: e.kind }, h("div", {}, e.text, h("span", { class: "t" }, e.windowIdx !== null ? `${e.time}  window ${e.windowIdx}` : e.time)))));
  }

  function send(msg) {
    if (S.ws && S.ws.readyState === WebSocket.OPEN) S.ws.send(JSON.stringify(msg));
  }

  function togglePause() {
    S.paused = !S.paused;
    send({ cmd: "pause", value: S.paused });
    pauseBtn.replaceChildren(icon(S.paused ? ICONS.play : ICONS.pause), S.paused ? "Resume" : "Pause");
    fiber.set({ paused: S.paused });
    setStatusPill();
    addEvent(S.paused ? "Stream paused" : "Stream resumed");
  }

  function setStatusPill() {
    statusPill.className = "pill";
    if (!S.connected) { statusPill.textContent = "Disconnected"; statusPill.classList.add("eve"); }
    else if (S.paused) { statusPill.textContent = "Paused"; statusPill.classList.add("amber"); }
    else { statusPill.replaceChildren(h("i", { class: "live-dot", style: { marginLeft: 0, boxShadow: "none" } }), "Live"); statusPill.classList.add("secure"); }
  }

  function applySettings(next, announce) {
    const prev = S.settings;
    S.settings = next;
    eveSeg.set(next.attack_type);
    intensityGroup.hidden = next.attack_type !== "intercept_resend";
    intensity.value = Math.round(next.intensity * 100);
    intensityOut.textContent = `${intensity.value}%`;
    setRangeFill(intensity);
    noise.value = (next.noise * 100).toFixed(1);
    noiseOut.textContent = `${(next.noise * 100).toFixed(1)}%`;
    setRangeFill(noise);
    drift.checked = next.drift;
    fiber.set({ attack: next.attack_type, intensity: next.intensity });
    if (!announce || !prev) return;
    const w = S.data.length ? S.data.at(-1).window + 1 : 0;
    if (prev.attack_type !== next.attack_type) {
      if (next.attack_type === "none") addEvent("Eve removed from the fibre", "secure", w);
      else addEvent(next.attack_type === "pns"
        ? "Eve starts splitting multi-photon pulses"
        : `Eve starts intercepting ${Math.round(next.intensity * 100)}% of photons`, "eve", w);
    } else if (prev.intensity !== next.intensity && next.attack_type === "intercept_resend") {
      addEvent(`Eve now intercepts ${Math.round(next.intensity * 100)}% of photons`, "eve", w);
    }
    if (prev.noise !== next.noise) addEvent(`Channel noise set to ${(next.noise * 100).toFixed(1)}%`, "cobalt", w);
    if (prev.drift !== next.drift) addEvent(next.drift ? "Fibre drift switched on" : "Fibre drift switched off", "cobalt", w);
  }

  function updateVerdict(d) {
    let state;
    if (d.calibrating) state = "calibrating";
    else if (d.detected) state = "alarm";
    else state = "secure";
    verdict.className = `verdict ${state}`;
    calibTrack.hidden = state !== "calibrating";

    if (state === "calibrating") {
      stateIcon.replaceChildren(icon(ICONS.gauge));
      stateTitle.textContent = "Calibrating baseline";
      stateText.textContent = `Window ${d.window + 1} of ${d.calibration_target}. These first windows are treated as attack-free and set both adaptive thresholds.`;
      calibFill.style.width = `${((d.window + 1) / d.calibration_target) * 100}%`;
    } else if (state === "alarm") {
      stateIcon.replaceChildren(icon(ICONS.alert));
      stateTitle.textContent = "Eavesdropper suspected";
      const why = [];
      if (d.qber_flag) why.push(`QBER ${pct(d.qber)} is above its adaptive threshold`);
      if (d.gap_flag) why.push("the decoy gap is above its threshold");
      if (!why.length) why.push("the window pattern matches an attack");
      stateText.textContent = `Fusion probability ${d.fusion_probability.toFixed(2)}: ${why.join(" and ")}. This window is excluded from the key and from baseline updates.`;
    } else {
      stateIcon.replaceChildren(icon(ICONS.shield));
      stateTitle.textContent = "Link secure";
      stateText.textContent = d.baseline_update_allowed
        ? "No anomaly in this window. The adaptive baselines are tracking the channel."
        : "No alarm, but the window looked borderline, so it was kept out of the baseline.";
    }

    if (state !== S.lastState) {
      if (state === "secure" && S.lastState === "calibrating") addEvent("Calibration complete. Thresholds are live.", "secure", d.window);
      if (state === "alarm") {
        const delay = S.attackStartWindow !== null && S.firstAlarmWindow === null ? d.window - S.attackStartWindow : null;
        const text = delay === null ? "Alarm raised"
          : delay === 0 ? "Eavesdropper detected in Eve's first window"
          : `Eavesdropper detected ${delay} window${delay === 1 ? "" : "s"} after Eve arrived`;
        addEvent(text, "eve", d.window);
      }
      if (state === "secure" && S.lastState === "alarm") addEvent("Alarm cleared", "secure", d.window);
      S.lastState = state;
    }
    const navDot = document.getElementById("nav-live");
    navDot.hidden = false;
    navDot.classList.toggle("alarm", state === "alarm");
  }

  function onWindow(d) {
    // track attack episodes for the time-to-detect readout
    const prev = S.data.at(-1);
    if (d.attack_active && (!prev || !prev.attack_active)) { S.attackStartWindow = d.window; S.firstAlarmWindow = null; }
    if (!d.attack_active) { S.attackStartWindow = null; }
    const wasFirst = d.detected && d.attack_active && S.firstAlarmWindow === null && S.attackStartWindow !== null;

    updateVerdict(d);
    if (wasFirst) S.firstAlarmWindow = d.window;

    S.data.push(d);
    if (S.data.length > MAX_POINTS) S.data.shift();
    const last = d.window;
    const domain = [Math.max(0, last - MAX_POINTS + 1), Math.max(MAX_POINTS - 1, last)];
    qberChart.update(S.data, { xDomain: domain });
    gapChart.update(S.data, { xDomain: domain });
    probChart.update(S.data, { xDomain: domain });

    R.qber.textContent = pct(d.qber, 2);
    R.gap.textContent = fixed(d.gap, 4);
    R.fusion.textContent = d.calibrating ? "—" : fixed(d.fusion_probability, 2);
    R.bits.replaceChildren(int(d.secure_bits), h("small", {}, "bits"));
    R.alarms.textContent = int(d.alarms);
    if (S.attackStartWindow !== null) {
      R.delay.replaceChildren(S.firstAlarmWindow !== null
        ? h("span", {}, String(S.firstAlarmWindow - S.attackStartWindow), h("small", {}, S.firstAlarmWindow - S.attackStartWindow === 1 ? "window" : "windows"))
        : h("span", {}, "watching…"));
    } else if (S.firstAlarmWindow === null) R.delay.textContent = "no attack";

    bobWhat.textContent = `Window ${d.window}, QBER ${pct(d.qber, 1)}, ${d.sifted} sifted bits`;
    fiber.set({ alarm: d.detected });
  }

  function connect() {
    const proto = location.protocol === "https:" ? "wss" : "ws";
    const ws = new WebSocket(`${proto}://${location.host}/ws/link`);
    S.ws = ws;
    ws.onopen = () => { S.connected = true; setStatusPill(); addEvent("Connected to the link"); if (S.paused) send({ cmd: "pause", value: true }); };
    ws.onmessage = (ev) => {
      const msg = JSON.parse(ev.data);
      if (msg.type === "window") onWindow(msg);
      else if (msg.type === "settings") { applySettings(msg.settings, true); if (msg.error) toast(msg.error, "error"); }
      else if (msg.type === "reset") {
        S.data = []; S.lastState = null; S.attackStartWindow = null; S.firstAlarmWindow = null;
        addEvent("Detector reset. Recalibrating from the next window.", "amber");
      } else if (msg.type === "error") { toast(msg.message, "error"); addEvent(msg.message, "eve"); }
    };
    ws.onclose = () => {
      S.connected = false; setStatusPill();
      stateTitle.textContent = "Disconnected";
      stateText.textContent = "The stream closed. Reconnecting in a few seconds; the detector will recalibrate.";
      verdict.className = "verdict";
      S.data = []; S.lastState = null;
      setTimeout(connect, 3000);
    };
  }

  connect();
}
