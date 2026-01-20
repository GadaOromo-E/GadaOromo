/* static/recorder.js (FIXED)
   Recorder-only recording:
   - Uploads to POST /recorder/api/submit-audio  ✅ (auto-approved + replace)
   - Shows Preview + Save (publish) + Re-record
   - Keeps it private: server requires recorder session, otherwise 401
   - Uses your existing data-* buttons:
       data-record-btn  (must have data-entry-type, data-entry-id, data-lang="oromo")
       data-stop-btn
       data-preview-audio
       data-submit-btn   (we treat as SAVE button)
       data-rerecord-btn
*/

(() => {
  const $ = (sel, root = document) => root.querySelector(sel);
  const $$ = (sel, root = document) => Array.from(root.querySelectorAll(sel));

  function setStatus(key, msg) {
    const el = document.querySelector(`[data-status-for="${key}"]`);
    if (el) el.textContent = msg || "";
  }

  function toast(msg) {
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
      try { navigator.vibrate?.(10); } catch (_) {}
    } else {
      alert(msg);
    }
  }

  const hasGetUserMedia = !!(navigator.mediaDevices && navigator.mediaDevices.getUserMedia);
  const hasMediaRecorder = typeof window.MediaRecorder !== "undefined";

  // One active recording at a time
  let active = null; // { recorder, stream, chunks, blob, url, mimeType, entryType, entryId, lang, ui... }

  function stopTracks(stream) {
    try { stream?.getTracks()?.forEach(t => t.stop()); } catch (_) {}
  }

  function pickMimeType() {
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
    return "";
  }

  function extFromMime(mimeType) {
    const mt = (mimeType || "").toLowerCase();
    if (mt.includes("ogg")) return "ogg";
    if (mt.includes("webm")) return "webm";
    return "webm";
  }

  async function startRecording(btn) {
    if (!hasGetUserMedia) return toast("Microphone not supported in this browser.");
    if (!hasMediaRecorder) return toast("Recording not supported here. Try Chrome on Android/Desktop.");

    // stop any current recording
    if (active?.recorder?.state === "recording") {
      try { active.recorder.stop(); } catch (_) {}
    }

    const entryType = (btn.dataset.entryType || "").trim().toLowerCase();
    const entryId = (btn.dataset.entryId || "").trim();
    const lang = (btn.dataset.lang || "oromo").trim().toLowerCase();

    if (!entryType || !entryId) return toast("Missing entry info on button (entry_type/entry_id).");
    if (lang !== "oromo") return toast("Recorder only allows Oromo audio.");

    // status keys used by your templates
    const keyWord = entryId;
    const keyCombo = `${entryType}_${entryId}`;

    setStatus(keyWord, "Requesting microphone…");
    setStatus(keyCombo, "Requesting microphone…");

    const root = btn.closest(".result-box, .word-row, .card, section, body") || document.body;
    const stopBtn = root.querySelector("[data-stop-btn]");
    const preview = root.querySelector("[data-preview-audio]");
    const saveBtn = root.querySelector("[data-submit-btn]"); // SAVE
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
        setStatus(keyWord, "Recording…");
        setStatus(keyCombo, "Recording…");

        btn.style.display = "none";
        if (stopBtn) stopBtn.style.display = "inline-block";

        if (saveBtn) {
          saveBtn.style.display = "none";
          saveBtn.disabled = false;
          saveBtn.textContent = saveBtn.dataset.saveLabel || "💾 Save";
        }
        if (rerecordBtn) rerecordBtn.style.display = "none";
        if (preview) preview.style.display = "none";

        toast("Recording…");
      };

      recorder.onstop = () => {
        stopTracks(stream);

        const finalMime = recorder.mimeType || mimeType || "audio/webm";
        const blob = new Blob(chunks, { type: finalMime });

        if (!blob || blob.size === 0) {
          setStatus(keyWord, "No audio captured. Try again.");
          setStatus(keyCombo, "No audio captured. Try again.");
          btn.style.display = "inline-block";
          if (stopBtn) stopBtn.style.display = "none";
          return;
        }

        const url = URL.createObjectURL(blob);

        if (preview) {
          preview.src = url;
          preview.style.display = "block";
          preview.load();
        }

        setStatus(keyWord, "Recorded ✅ Click Save to publish.");
        setStatus(keyCombo, "Recorded ✅ Click Save to publish.");

        if (stopBtn) stopBtn.style.display = "none";
        btn.style.display = "inline-block";
        if (saveBtn) saveBtn.style.display = "inline-block";
        if (rerecordBtn) rerecordBtn.style.display = "inline-block";

        active = {
          recorder,
          stream: null,
          chunks: [],
          blob,
          url,
          mimeType: finalMime,
          entryType,
          entryId,
          lang,
          ui: { btn, stopBtn, preview, saveBtn, rerecordBtn, keyWord, keyCombo, root }
        };

        toast("Recorded ✅");
      };

      // set active early
      active = {
        recorder,
        stream,
        chunks,
        blob: null,
        url: null,
        mimeType,
        entryType,
        entryId,
        lang,
        ui: { btn, stopBtn, preview, saveBtn, rerecordBtn, keyWord, keyCombo, root }
      };

      recorder.start();

    } catch (err) {
      console.error(err);
      setStatus(keyWord, "Mic blocked. Allow microphone permission.");
      setStatus(keyCombo, "Mic blocked. Allow microphone permission.");
      toast("Microphone blocked. Allow permission in browser settings.");
    }
  }

  function stopRecording() {
    if (!active?.recorder) return;
    try {
      if (active.recorder.state === "recording") active.recorder.stop();
    } catch (err) {
      console.error(err);
    }
  }

  async function saveRecording() {
    if (!active?.blob) return toast("No recording found.");

    const { entryType, entryId, lang, blob, mimeType, ui } = active;
    const { keyWord, keyCombo, saveBtn, root } = ui || {};

    setStatus(keyWord, "Saving…");
    setStatus(keyCombo, "Saving…");
    if (saveBtn) saveBtn.disabled = true;

    const ext = extFromMime(mimeType);

    const fd = new FormData();
    fd.append("entry_type", entryType);
    fd.append("entry_id", entryId);
    fd.append("lang", lang);
    fd.append("audio", blob, `recording.${ext}`);

    try {
      // ✅ IMPORTANT: recorder endpoint
      const res = await fetch("/recorder/api/submit-audio", { method: "POST", body: fd });
      const data = await res.json().catch(() => ({}));

      if (!res.ok || !data.ok) {
        const msg = data.error || `Save failed (${res.status})`;
        setStatus(keyWord, msg);
        setStatus(keyCombo, msg);
        toast(msg);

        // If unauthorized, likely not logged in
        if (res.status === 401) {
          toast("Recorder login required. Please login again.");
          window.location.href = "/recorder";
        }
        return;
      }

      // ✅ success
      setStatus(keyWord, "Saved ✅ Published now.");
      setStatus(keyCombo, "Saved ✅ Published now.");
      toast("Saved ✅ Published");

      // If template has an "approved audio" player, update it
      const approvedPlayer = root?.querySelector("[data-approved-audio]");
      if (approvedPlayer && data.url) {
        approvedPlayer.src = data.url;
        approvedPlayer.style.display = "block";
        approvedPlayer.load();
      }

      // Hide save + rerecord after save (optional)
      if (ui?.saveBtn) ui.saveBtn.style.display = "none";
      if (ui?.rerecordBtn) ui.rerecordBtn.style.display = "none";

      // clean blob so it won't re-submit accidentally
      active.blob = null;

    } catch (err) {
      console.error(err);
      setStatus(keyWord, "Save failed. Check internet.");
      setStatus(keyCombo, "Save failed. Check internet.");
      toast("Save failed. Check internet.");
    } finally {
      if (saveBtn) saveBtn.disabled = false;
    }
  }

  function rerecord() {
    if (!active) return;
    try {
      if (active.url) URL.revokeObjectURL(active.url);
    } catch (_) {}

    const btn = active.ui?.btn;
    active = null;
    if (btn) startRecording(btn);
  }

  function bind() {
    $$("[data-record-btn]").forEach((btn) => {
      btn.addEventListener("click", () => startRecording(btn));
    });
    $$("[data-stop-btn]").forEach((btn) => {
      btn.addEventListener("click", () => stopRecording());
    });
    // recorder: submit button is SAVE
    $$("[data-submit-btn]").forEach((btn) => {
      btn.addEventListener("click", () => saveRecording());
    });
    $$("[data-rerecord-btn]").forEach((btn) => {
      btn.addEventListener("click", () => rerecord());
    });

    // Safety cleanup
    window.addEventListener("beforeunload", () => {
      try { stopRecording(); } catch (_) {}
      try { stopTracks(active?.stream); } catch (_) {}
    });
  }

  document.addEventListener("DOMContentLoaded", bind);
})();
