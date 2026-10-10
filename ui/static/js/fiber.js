// The fibre strip: photons travel from Alice to Bob as polarisation bars
// ( — | / \ ). With intercept-resend, Eve re-prepares a share of photons
// (they turn crimson). With photon-number splitting, multi-photon pulses
// lose a photon to Eve while the rest continue undisturbed.

import { css } from "./util.js";

const ANGLES = [0, 90, 45, 135];

export function createFiber(canvas) {
  const ctx = canvas.getContext("2d");
  const reduce = window.matchMedia("(prefers-reduced-motion: reduce)");
  const state = {
    attack: "none",
    intensity: 0.3,
    alarm: false,
    paused: false,
    photons: [],
    splits: [],
    pulses: [],
    lastSpawn: 0,
    lastTime: 0,
    width: 0,
    height: 0,
  };
  let colors = {};

  function readColors() {
    colors = {
      ink: css("--ink"), ink2: css("--ink-2"), muted: css("--muted"),
      line: css("--line-strong"), cobalt: css("--cobalt"), eve: css("--eve"),
      secure: css("--secure"), panel: css("--panel"), panel3: css("--panel-3"),
    };
  }

  function resize() {
    const dpr = Math.min(2, window.devicePixelRatio || 1);
    const rect = canvas.getBoundingClientRect();
    state.width = rect.width;
    state.height = rect.height;
    canvas.width = Math.round(rect.width * dpr);
    canvas.height = Math.round(rect.height * dpr);
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    if (reduce.matches) drawStatic();
  }

  const geom = () => {
    const y = state.height * 0.66;
    const a = 64;
    const b = state.width - 64;
    return { y, a, b, eve: a + (b - a) * 0.52 };
  };

  function spawn() {
    const { a } = geom();
    const multi = Math.random() < 0.18; // weak coherent pulses sometimes carry >1 photon
    state.photons.push({
      x: a + 18,
      angle: ANGLES[(Math.random() * 4) | 0],
      multi,
      tampered: false,
      passedEve: false,
    });
  }

  function step(dt) {
    const { y, a, b, eve } = geom();
    const speed = Math.max(120, (b - a) / 2.6);
    state.lastSpawn += dt;
    const every = 0.11;
    while (state.lastSpawn > every) { state.lastSpawn -= every; spawn(); }

    for (const p of state.photons) {
      p.x += speed * dt;
      if (!p.passedEve && p.x >= eve) {
        p.passedEve = true;
        if (state.attack === "intercept_resend" && Math.random() < state.intensity) {
          p.tampered = true;
          p.angle = ANGLES[(Math.random() * 4) | 0];
          state.pulses.push({ x: eve, y, r: 6, life: 1, color: colors.eve });
        } else if (state.attack === "pns" && p.multi) {
          p.multi = false;
          state.splits.push({ x: eve, y, t: 0 });
        }
      }
    }
    state.photons = state.photons.filter((p) => {
      if (p.x < b - 16) return true;
      state.pulses.push({ x: b - 16, y, r: 4, life: 0.6, color: p.tampered ? colors.eve : colors.cobalt });
      return false;
    });
    for (const s of state.splits) s.t += dt * 1.6;
    state.splits = state.splits.filter((s) => s.t < 1);
    for (const pu of state.pulses) { pu.life -= dt * 2.2; pu.r += dt * 26; }
    state.pulses = state.pulses.filter((pu) => pu.life > 0);
  }

  function roundRect(x, y, w, hgt, r) {
    ctx.beginPath();
    ctx.moveTo(x + r, y);
    ctx.arcTo(x + w, y, x + w, y + hgt, r);
    ctx.arcTo(x + w, y + hgt, x, y + hgt, r);
    ctx.arcTo(x, y + hgt, x, y, r);
    ctx.arcTo(x, y, x + w, y, r);
    ctx.closePath();
  }

  function drawBar(x, y, angle, color, len = 13, width = 3) {
    const rad = (-angle * Math.PI) / 180;
    const dx = (Math.cos(rad) * len) / 2;
    const dy = (Math.sin(rad) * len) / 2;
    ctx.strokeStyle = color;
    ctx.lineWidth = width;
    ctx.lineCap = "round";
    ctx.beginPath();
    ctx.moveTo(x - dx, y - dy);
    ctx.lineTo(x + dx, y + dy);
    ctx.stroke();
  }

  function drawScene() {
    const { y, a, b, eve } = geom();
    ctx.clearRect(0, 0, state.width, state.height);

    // fibre: cladding + core
    ctx.strokeStyle = colors.panel3;
    ctx.lineWidth = 12;
    ctx.lineCap = "round";
    ctx.beginPath(); ctx.moveTo(a, y); ctx.lineTo(b, y); ctx.stroke();
    ctx.strokeStyle = colors.line;
    ctx.lineWidth = 1.5;
    ctx.beginPath(); ctx.moveTo(a, y); ctx.lineTo(b, y); ctx.stroke();

    // distance ticks every 5 km (25 km link)
    ctx.fillStyle = colors.muted;
    ctx.font = "500 10.5px 'Schibsted Grotesk', system-ui, sans-serif";
    ctx.textAlign = "center";
    const kmStep = (b - a) > 420 ? 5 : 25;
    for (let km = 0; km <= 25; km += kmStep) {
      const x = a + 44 + ((b - a - 88) * km) / 25;
      ctx.fillRect(x - 0.5, y + 12, 1, 4);
      ctx.fillText(`${km} km`, x, y + 28);
    }

    // Eve tap
    if (state.attack !== "none") {
      ctx.strokeStyle = colors.eve;
      ctx.lineWidth = 1.5;
      ctx.setLineDash([3, 3]);
      ctx.beginPath(); ctx.moveTo(eve, y - 8); ctx.lineTo(eve, y - 40); ctx.stroke();
      ctx.setLineDash([]);
      ctx.fillStyle = colors.eve;
      roundRect(eve - 26, y - 64, 52, 24, 7);
      ctx.fill();
      ctx.fillStyle = "#fff";
      ctx.font = "650 12px 'Schibsted Grotesk', system-ui, sans-serif";
      ctx.fillText("Eve", eve, y - 48);
      ctx.fillStyle = colors.eve;
      ctx.font = "500 10.5px 'Schibsted Grotesk', system-ui, sans-serif";
      const tag = state.attack === "pns" ? "splitting pulses" : `re-sending ${Math.round(state.intensity * 100)}%`;
      ctx.fillText(tag, eve, y - 70);
    }

    // PNS: stolen photons travel up the tap to Eve's store
    for (const s of state.splits) {
      const sy = y - 10 - s.t * 30;
      drawBar(eve, sy, 90, colors.eve, 9, 2.5);
    }

    // photons
    for (const p of state.photons) {
      const color = p.tampered ? colors.eve : colors.cobalt;
      drawBar(p.x, y, p.angle, color);
      if (p.multi) drawBar(p.x - 7, y, p.angle, color, 9, 2);
    }

    // pulses (absorption / interception rings)
    for (const pu of state.pulses) {
      ctx.globalAlpha = Math.max(0, pu.life);
      ctx.strokeStyle = pu.color;
      ctx.lineWidth = 1.5;
      ctx.beginPath(); ctx.arc(pu.x, pu.y, pu.r, 0, Math.PI * 2); ctx.stroke();
      ctx.globalAlpha = 1;
    }

    // terminals
    const term = (x, label, ring) => {
      ctx.fillStyle = colors.ink;
      roundRect(x - 18, y - 18, 36, 36, 9);
      ctx.fill();
      if (ring) {
        ctx.strokeStyle = ring;
        ctx.lineWidth = 2;
        roundRect(x - 22, y - 22, 44, 44, 12);
        ctx.stroke();
      }
      ctx.fillStyle = "#fff";
      ctx.font = "650 13px 'Schibsted Grotesk', system-ui, sans-serif";
      ctx.textAlign = "center";
      ctx.fillText(label, x, y + 4.5);
    };
    term(a, "A", null);
    term(b, "B", state.alarm ? colors.eve : null);
  }

  function drawStatic() {
    readColors();
    const { a, b, eve } = geom();
    state.photons = [];
    for (let x = a + 30; x < b - 24; x += 34) {
      state.photons.push({
        x, angle: ANGLES[((x / 34) | 0) % 4], multi: false,
        tampered: state.attack === "intercept_resend" && x > eve && ((x / 34) | 0) % 3 === 0,
      });
    }
    state.pulses = [];
    state.splits = [];
    drawScene();
  }

  function frame(t) {
    const dt = state.lastTime ? Math.min(0.05, (t - state.lastTime) / 1000) : 0;
    state.lastTime = t;
    if (!reduce.matches) {
      if (!state.paused && !document.hidden) step(dt);
      drawScene();
    }
    requestAnimationFrame(frame);
  }

  readColors();
  new ResizeObserver(resize).observe(canvas);
  resize();
  requestAnimationFrame(frame);

  return {
    set(next) {
      Object.assign(state, next);
      if (reduce.matches) drawStatic();
    },
  };
}
