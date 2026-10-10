// Post-quantum auth: ML-DSA-65 signed envelopes (with tamper and replay
// checks) and the ML-KEM-768 half of the hybrid key.

import { h, icon, ICONS, api, int, ms, toast } from "../util.js";

const SAMPLES = {
  basis_reconciliation: { photons: 2000, matching_bases: 1004 },
  qber_estimate: { sample_size: 502, qber: 0.0219 },
  error_correction_syndrome: { algorithm: "simulated-reconciliation", raw_bits: 502, bob_pre_correction_errors: 11 },
  privacy_amplification: { kdf: "HKDF-SHA-256", output_bytes: 32 },
};

export function mountPqc(root) {
  root.append(h("header", { class: "page-head" },
    h("div", {},
      h("h1", {}, "Post-quantum authentication"),
      h("p", { class: "lede" }, "BB84 needs an authenticated classical channel. Every reconciliation message is signed with ML-DSA-65, and the final key mixes QKD bits with an ML-KEM-768 secret."))));

  // ---------------------------------------------------------------- signing
  const type = h("select", { class: "select", id: "p-type" },
    Object.keys(SAMPLES).map((k) => h("option", { value: k }, k.replaceAll("_", " "))));
  const payload = h("textarea", { class: "input", id: "p-payload", rows: 4, spellcheck: "false" }, JSON.stringify(SAMPLES.basis_reconciliation, null, 2));
  type.addEventListener("change", () => { payload.value = JSON.stringify(SAMPLES[type.value], null, 2); });
  const tamper = h("input", { type: "checkbox" });
  const replay = h("input", { type: "checkbox" });
  const signBtn = h("button", { class: "btn btn-primary", type: "submit" }, icon(ICONS.run), "Sign and send");
  const signOut = h("div", { style: { marginTop: "18px" } });

  const signPanel = h("form", { class: "panel panel-pad", onsubmit: (e) => { e.preventDefault(); sign(); } },
    h("div", { class: "section-head" }, h("h2", {}, "Signed reconciliation message"), h("span", { class: "pill cobalt" }, "ML-DSA-65, FIPS 204")),
    h("div", { style: { display: "grid", gap: "14px" } },
      h("div", { class: "field" }, h("label", { for: "p-type" }, "Message"), type),
      h("div", { class: "field" }, h("label", { for: "p-payload" }, "Payload (JSON)"), payload),
      h("div", { style: { display: "flex", gap: "18px", flexWrap: "wrap", alignItems: "center" } },
        h("label", { class: "switch" }, tamper, h("span", { class: "track" }), "Change the payload in transit"),
        h("label", { class: "switch" }, replay, h("span", { class: "track" }), "Replay it afterwards"),
        h("span", { style: { flex: 1 } }), signBtn)),
    signOut);

  async function sign() {
    let body;
    try { body = JSON.parse(payload.value); } catch { toast("The payload is not valid JSON", "error"); return; }
    signBtn.disabled = true;
    try {
      const r = await api("/api/pqc/signature", { method: "POST", body: { message_type: type.value, payload: body, tamper: tamper.checked, replay: replay.checked } });
      const banners = [h("div", { class: `verify-banner ${r.accepted ? "ok" : "bad"}` },
        icon(r.accepted ? ICONS.check : ICONS.x),
        h("div", {}, r.accepted ? "Bob accepted the message" : "Bob rejected the message",
          h("span", {}, r.accepted
            ? "The signature matches Alice's public key, the session ID and the expected sequence number."
            : r.tamper_note ? `Signature check failed because the ${r.tamper_note}.` : "Signature check failed.")))];
      if (r.replay_attempted) {
        banners.push(h("div", { class: `verify-banner ${r.replay_accepted ? "ok" : "bad"}`, style: { marginTop: "8px" } },
          icon(r.replay_accepted ? ICONS.check : ICONS.x),
          h("div", {}, r.replay_accepted ? "Replay accepted" : "Replay rejected",
            h("span", {}, r.replay_accepted ? "This should not happen." : `The same envelope arrived again with sequence ${r.sequence}, which Bob has already consumed.`))));
      }
      signOut.replaceChildren(
        ...banners,
        h("dl", { class: "kv", style: { marginTop: "16px" } },
          h("dt", {}, "Public key"), h("dd", {}, `${int(r.public_key_bytes)} bytes, fingerprint `, h("code", {}, r.public_key_fingerprint)),
          h("dt", {}, "Signature"), h("dd", {}, `${int(r.signature_bytes)} bytes over ${int(r.signed_bytes)} bytes of canonical JSON`),
          h("dt", {}, "Key generation"), h("dd", {}, ms(r.keygen_ms)),
          h("dt", {}, "Sign"), h("dd", {}, ms(r.sign_ms)),
          h("dt", {}, "Verify"), h("dd", {}, ms(r.verify_ms)),
          h("dt", {}, "Session"), h("dd", { class: "mono" }, r.session_id)),
        h("div", { style: { marginTop: "14px" } },
          h("h3", { style: { fontSize: "var(--fs-sm)", marginBottom: "6px" } }, "Exactly what Alice signed"),
          h("div", { class: "envelope" }, r.canonical_message),
          h("p", { style: { fontSize: "var(--fs-xs)", color: "var(--muted)", marginTop: "6px" } }, "Signature starts ", h("code", {}, `${r.signature_preview}…`))));
    } catch (err) { toast(err.message, "error"); }
    finally { signBtn.disabled = false; }
  }

  // ---------------------------------------------------------------- KEM
  const kemOut = h("div", { style: { marginTop: "16px" } });
  const kemBtn = h("button", { class: "btn", type: "button", onclick: kem }, icon(ICONS.run), "Run ML-KEM exchange");
  const arrow = () => h("svg", { viewBox: "0 0 20 20", "aria-hidden": "true", html: '<path d="M4 10h12M12 6l4 4-4 4"/>' });
  const kemPanel = h("div", { class: "panel panel-pad" },
    h("div", { class: "section-head" }, h("h2", {}, "Hybrid session key"), h("span", { class: "pill cobalt" }, "ML-KEM-768, FIPS 203")),
    h("div", { class: "flow" },
      h("div", { style: { display: "grid", gap: "8px" } },
        h("div", { class: "node" }, h("b", {}, "QKD bits"), h("span", {}, "sifted, error-checked")),
        h("div", { class: "node" }, h("b", {}, "ML-KEM secret"), h("span", {}, "32 bytes from Alice"))),
      arrow(),
      h("div", { class: "node" }, h("b", {}, "HKDF-SHA-256"), h("span", {}, "salted with the signed transcript hash")),
      arrow(),
      h("div", { class: "node out" }, h("b", {}, "256-bit key"), h("span", {}, "safe if either half holds"))),
    h("p", { style: { color: "var(--ink-2)", fontSize: "var(--fs-sm)", marginTop: "14px" } },
      "An attacker would need to break both the quantum channel and the lattice KEM to recover the key."),
    h("div", { style: { marginTop: "14px" } }, kemBtn),
    kemOut);

  async function kem() {
    kemBtn.disabled = true;
    try {
      const r = await api("/api/pqc/kem", { method: "POST" });
      const sig = await api("/api/pqc/signature", { method: "POST", body: { message_type: "privacy_amplification", payload: SAMPLES.privacy_amplification } });
      const sizes = [
        ["ML-DSA public key", sig.public_key_bytes],
        ["ML-DSA signature", sig.signature_bytes],
        ["ML-KEM public key", r.public_key_bytes],
        ["ML-KEM ciphertext", r.ciphertext_bytes],
      ];
      const max = Math.max(...sizes.map((s) => s[1]));
      kemOut.replaceChildren(
        h("div", { class: `verify-banner ${r.secrets_match ? "ok" : "bad"}` }, icon(r.secrets_match ? ICONS.check : ICONS.x),
          h("div", {}, r.secrets_match ? "Alice and Bob hold the same secret" : "Secrets differ",
            h("span", {}, `Shared secret fingerprint ${r.shared_secret_fingerprint}, hybrid key fingerprint ${r.hybrid_key_fingerprint}`))),
        h("dl", { class: "kv", style: { marginTop: "16px" } },
          h("dt", {}, "Key generation"), h("dd", {}, ms(r.keygen_ms)),
          h("dt", {}, "Encapsulate"), h("dd", {}, ms(r.encaps_ms)),
          h("dt", {}, "Decapsulate"), h("dd", {}, ms(r.decaps_ms))),
        h("h3", { style: { fontSize: "var(--fs-sm)", margin: "18px 0 10px" } }, "What goes over the wire"),
        h("div", { class: "bars-h" }, sizes.map(([label, v]) => h("div", { class: "bar-row", style: { gridTemplateColumns: "130px minmax(0,1fr) 80px" } },
          h("span", {}, label), h("div", { class: "track" }, h("i", { style: { width: `${(v / max) * 100}%` } })), h("span", { class: "v" }, `${int(v)} B`)))));
    } catch (err) { toast(err.message, "error"); }
    finally { kemBtn.disabled = false; }
  }

  root.append(h("div", { class: "pqc-grid" }, signPanel, kemPanel));
  sign();
  kem();
}
