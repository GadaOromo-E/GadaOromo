/* static/recorder.js
   Mic recording + preview + upload to /api/submit-audio
   Buttons must have:
     - data-record-btn  (with data-entry-type, data-entry-id, data-lang)
     - data-stop-btn
     - data-preview-audio
     - data-submit-btn
     - data-rerecord-btn
     - optional: data-trim-box + trim inputs (we’ll ignore trimming if not present)
*/

(() => {
  const $ = (sel, root=document) => root.querySelector(sel);
  const $$ = (sel, root=document) => Array.from(root.querySelectorAll(sel));

  function setStatus(entryIdOrKey, msg) {
    const el = document.querySelector(`[data-status-for="${entryIdOrKey}"]`);
    if (el) el.textContent = msg || "";
  }

  function toast(msg) {
    // Use your existing toast if present, else alert fallback
    const t = document.getElementById("pwaToast");
    if (t) {
      const msgEl = t.querySelector("[data-msg]");
      if (msgEl) msgEl.textContent = msg;
      t.style.display = "block";
      t.style.opacity = "1";
      clearTimeout(toast._t);
      toast._t = setTimeout(() => {
        t.style.opacity = "0";
        setTimeout(() => (t.style.display = "none"), 200);
      }, 2000);
      try { navigator.vibrate?.(10); } catch(_) {}
    } else {
      alert(msg);
    }
  }

  // Check support
  const hasGetUserMedia = !!(navigator.mediaDevices && navigator.mediaDevices.getUserMedia);
  const hasMediaRecorder = typeof window.MediaRecorder !== "undefined";

  if (!hasGetUserMedia) {
    // No mic support at all
    console.warn("getUserMedia not supported");
  }

  // Keep one active recorder at a time
  let active = null; // { recorder, stream, chunks, blob, url, mimeType, entryType, entryId, lang, ui... }

  function stopTracks(stream) {
    try {
      stream.getTracks().forEach(t => t.stop());
    } catch (_) {}
  }

  function pickMimeType() {
    // Prefer webm (Chrome), then ogg
    const candidates = [
      "audio/webm;codecs=opus",
      "audio/webm",
      "audio/ogg;codecs=opus",
      "audio/ogg"
    ];
    for (const m of candidates) {
      try {
        if (window.MediaRecorder && MediaRecorder.isTypeSupported && MediaRecorder.isTypeSupported(m)) return m;
      } catch (_) {}
    }
    return ""; // let browser decide
  }

  async function startRecording(btn) {
    if (!hasGetUserMedia) {
      toast("Microphone not supported in this browser.");
      return;
    }
    if (!hasMediaRecorder) {
      // iPhone Safari often ends here
      toast("Recording not supported on this browser. Try Chrome on Android or desktop.");
      return;
    }

    // If already recording something else, stop it
    if (active && active.recorder && active.recorder.state === "recording") {
      try { active.recorder.stop(); } catch (_) {}
    }

    const entryType = (btn.dataset.entryType || "").trim();
    const entryId = (btn.dataset.entryId || "").trim();
    const lang = (btn.dataset.lang || "oromo").trim();

    const key = entryId; // for status elements on home
    const key2 = `${entryType}_${entryId}`; // translate page uses this
    setStatus(key, "Requesting microphone…");
    setStatus(key2, "Requesting microphone…");

    // Find related UI in the same card/container
    const root = btn.closest(".result-box, .word-row, .card, body") || document.body;
    const stopBtn = root.querySelector("[data-stop-btn]");
    const preview = root.querySelector("[data-preview-audio]");
    const submitBtn = root.querySelector("[data-submit-btn]");
    const rerecordBtn = root.querySelector("[data-rerecord-btn]");

    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      const mimeType = pickMimeType();
      const recorder = new MediaRecorder(stream, mimeType ? { mimeType } : undefined);

      const chunks = [];
      recorder.ondataavailable = (e) => {
        if (e.data && e.data.size > 0) chunks.push(e.data);
      };

      recorder.onstart = () => {
        setStatus(key, "Recording…");
        setStatus(key2, "Recording…");
        if (btn) btn.style.display = "none";
        if (stopBtn) stopBtn.style.display = "inline-block";
        if (submitBtn) submitBtn.style.display = "none";
        if (rerecordBtn) rerecordBtn.style.display = "none";
        if (preview) preview.style.display = "none";
        toast("Recording…");
        try { navigator.vibrate?.(20); } catch(_) {}
      };

      recorder.onstop = () => {
        stopTracks(stream);

        const blob = new Blob(chunks, { type: recorder.mimeType || "audio/webm" });
        const url = URL.createObjectURL(blob);

        if (preview) {
          preview.src = url;
          preview.style.display = "block";
        }

        setStatus(key, "Recorded. Preview and submit ✅");
        setStatus(key2, "Recorded. Preview and submit ✅");

        if (stopBtn) stopBtn.style.display = "none";
        if (btn) btn.style.display = "inline-block";
        if (submitBtn) submitBtn.style.display = "inline-block";
        if (rerecordBtn) rerecordBtn.style.display = "inline-block";

        active = {
          recorder, stream, chunks, blob, url,
          mimeType: recorder.mimeType || "audio/webm",
          entryType, entryId, lang,
          ui: { btn, stopBtn, preview, submitBtn, rerecordBtn, key, key2 }
        };
        toast("Recorded ✅");
        try { navigator.vibrate?.(10); } catch(_) {}
      };

      // Save active state early
      active = { recorder, stream, chunks, blob: null, url: null, mimeType, entryType, entryId, lang,
                 ui: { btn, stopBtn, preview, submitBtn, rerecordBtn, key, key2 } };

      recorder.start();

    } catch (err) {
      console.error(err);
      setStatus(key, "Mic blocked. Allow microphone permission.");
      setStatus(key2, "Mic blocked. Allow microphone permission.");
      toast("Microphone blocked. Please allow permission in browser settings.");
    }
  }

  function stopRecording() {
    if (!active || !active.recorder) return;
    try {
      if (active.recorder.state === "recording") active.recorder.stop();
    } catch (err) {
      console.error(err);
    }
  }

  async function submitRecording() {
    if (!active || !active.blob) {
      toast("No recording found.");
      return;
    }

    const { entryType, entryId, lang, blob, mimeType, ui } = active;
    const { key, key2, submitBtn } = ui || {};

    setStatus(key, "Uploading…");
    setStatus(key2, "Uploading…");
    if (submitBtn) submitBtn.disabled = true;

    // Choose extension based on mimeType
    let ext = "webm";
    const mt = (mimeType || "").toLowerCase();
    if (mt.includes("ogg")) ext = "ogg";
    if (mt.includes("webm")) ext = "webm";

    const fd = new FormData();
    fd.append("entry_type", entryType);
    fd.append("entry_id", entryId);
    fd.append("lang", lang);

    // IMPORTANT: give filename with extension so your backend accepts it
    fd.append("audio", blob, `recording.${ext}`);

    try {
      const res = await fetch("/api/submit-audio", { method: "POST", body: fd });
      const data = await res.json().catch(() => ({}));

      if (!res.ok || !data.ok) {
        const msg = data.error || `Upload failed (${res.status})`;
        setStatus(key, msg);
        setStatus(key2, msg);
        toast(msg);
      } else {
        setStatus(key, "Submitted ✅ Waiting for admin approval.");
        setStatus(key2, "Submitted ✅ Waiting for admin approval.");
        toast("Submitted ✅");
      }
    } catch (err) {
      console.error(err);
      setStatus(key, "Upload failed. Check internet.");
      setStatus(key2, "Upload failed. Check internet.");
      toast("Upload failed. Check internet.");
    } finally {
      if (submitBtn) submitBtn.disabled = false;
    }
  }

  function rerecord() {
    if (!active) return;
    try {
      if (active.url) URL.revokeObjectURL(active.url);
    } catch (_) {}
    // Start new recording on the original button
    const btn = active.ui?.btn;
    active = null;
    if (btn) startRecording(btn);
  }

  // Wire up all buttons
  function bind() {
    $$("[data-record-btn]").forEach((btn) => {
      btn.addEventListener("click", () => startRecording(btn));
    });

    $$("[data-stop-btn]").forEach((btn) => {
      btn.addEventListener("click", () => stopRecording());
    });

    $$("[data-submit-btn]").forEach((btn) => {
      btn.addEventListener("click", () => submitRecording());
    });

    $$("[data-rerecord-btn]").forEach((btn) => {
      btn.addEventListener("click", () => rerecord());
    });
  }

  document.addEventListener("DOMContentLoaded", bind);
})();
