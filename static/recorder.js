/* static/recorder.js (FULL FIX + DEBUG)
   Recorder-only recording:
   - Uploads to POST /recorder/api/submit-audio (auto-approved + replace)
   - Uses credentials: "same-origin" so session cookie is sent
   - redirect:"manual" so silent login redirect doesn't look like "stuck"
   - timeout (AbortController) so it never hangs forever
   - event delegation (click handler on document) so buttons ALWAYS work
*/

(() => {
  const $ = (sel, root = document) => root.querySelector(sel);

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
      }, 2200);
    } else {
      alert(msg);
    }
  }

  function setStatus(key, msg) {
    const el = document.querySelector(`[data-status-for="${key}"]`);
    if (el) el.textContent = msg || "";
  }

  function stopTracks(stream) {
    try { stream?.getTracks()?.forEach(t => t.stop()); } catch (_) {}
  }

  function pickMimeType() {
    const candidates = [
      "audio/webm;codecs=opus",
      "audio/webm",
      "audio/ogg;codecs=opus",
      "audio/ogg",
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

  async function safeJson(res) {
    const ct = (res.headers.get("content-type") || "").toLowerCase();
    if (!ct.includes("application/json")) {
      // likely HTML login page
      await res.text().catch(() => "");
      return { ok: false, error: "Server returned non-JSON (maybe redirected to login)." };
    }
    return await res.json().catch(() => ({ ok: false, error: "Invalid JSON from server." }));
  }

  function looksLikeLogin(res) {
    const ct = (res.headers.get("content-type") || "").toLowerCase();
    if (res.status === 401 || res.status === 403) return true;
    if (res.type === "opaqueredirect") return true;
    if (res.redirected) return true;
    if (ct.includes("text/html")) return true;
    return false;
  }

  // One active session
  let active = null;

  async function startRecording(root, recordBtn) {
    console.log("🎙 startRecording clicked");

    if (!navigator.mediaDevices?.getUserMedia) return toast("Microphone not supported.");
    if (!window.MediaRecorder) return toast("Recording not supported (MediaRecorder missing).");

    // stop existing
    if (active?.recorder?.state === "recording") {
      try { active.recorder.stop(); } catch (_) {}
    }

    const entryType = (recordBtn.dataset.entryType || window.RECORDER_ENTRY?.entry_type || "").trim().toLowerCase();
    const entryId = String(recordBtn.dataset.entryId || window.RECORDER_ENTRY?.entry_id || "").trim();
    const lang = (recordBtn.dataset.lang || "oromo").trim().toLowerCase();

    if (!entryType || !entryId) return toast("Missing entry_type/entry_id on button.");
    if (lang !== "oromo") return toast("Recorder only allows Oromo audio.");

    const stopBtn = $("[data-stop-btn]", root);
    const preview = $("[data-preview-audio]", root);
    const saveBtn = $("[data-submit-btn]", root);
    const rerecordBtn = $("[data-rerecord-btn]", root);

    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      const mimeType = pickMimeType();
      const recorder = new MediaRecorder(stream, mimeType ? { mimeType } : undefined);
      const chunks = [];

      recorder.ondataavailable = (e) => {
        if (e.data && e.data.size > 0) chunks.push(e.data);
      };

      recorder.onstart = () => {
        setStatus(entryId, "Recording…");
        recordBtn.style.display = "none";
        if (stopBtn) stopBtn.style.display = "inline-block";
        if (saveBtn) saveBtn.style.display = "none";
        if (rerecordBtn) rerecordBtn.style.display = "none";
        if (preview) preview.style.display = "none";
      };

      recorder.onstop = () => {
        stopTracks(stream);

        const finalMime = recorder.mimeType || mimeType || "audio/webm";
        const blob = new Blob(chunks, { type: finalMime });

        if (!blob || blob.size === 0) {
          setStatus(entryId, "No audio captured. Try again.");
          recordBtn.style.display = "inline-block";
          if (stopBtn) stopBtn.style.display = "none";
          return;
        }

        const url = URL.createObjectURL(blob);
        if (preview) {
          preview.src = url;
          preview.style.display = "block";
          preview.load();
        }

        setStatus(entryId, "Recorded ✅ Click Submit to save.");
        if (stopBtn) stopBtn.style.display = "none";
        recordBtn.style.display = "inline-block";
        if (saveBtn) saveBtn.style.display = "inline-block";
        if (rerecordBtn) rerecordBtn.style.display = "inline-block";

        active = { entryType, entryId, lang, blob, mimeType: finalMime, url, root };
        toast("Recorded ✅");
      };

      active = { entryType, entryId, lang, blob: null, mimeType, url: null, root, recorder, stream };
      recorder.start();

    } catch (err) {
      console.error(err);
      setStatus(entryId, "Mic blocked. Allow microphone permission.");
      toast("Microphone blocked. Allow permission in browser settings.");
    }
  }

  function stopRecording() {
    console.log("⏹ stop clicked");
    if (!active?.recorder) return;
    try {
      if (active.recorder.state === "recording") active.recorder.stop();
    } catch (e) {
      console.error(e);
    }
  }

  async function saveRecording(root) {
    console.log("✅ submit clicked");

    // entry info from global (safer on recorder entry page)
    const entryType = (window.RECORDER_ENTRY?.entry_type || $("[data-record-btn]", root)?.dataset.entryType || "").trim().toLowerCase();
    const entryId = String(window.RECORDER_ENTRY?.entry_id || $("[data-record-btn]", root)?.dataset.entryId || "").trim();
    const lang = "oromo";

    if (!active?.blob) {
      toast("No recording found. Record first.");
      return;
    }
    if (!entryType || !entryId) {
      toast("Missing entry_type/entry_id.");
      return;
    }

    setStatus(entryId, "Saving…");

    const saveBtn = $("[data-submit-btn]", root);
    if (saveBtn) saveBtn.disabled = true;

    const ext = extFromMime(active.mimeType);

    const fd = new FormData();
    fd.append("entry_type", entryType);
    fd.append("entry_id", entryId);
    fd.append("lang", lang);
    fd.append("audio", active.blob, `recording.${ext}`);

    const submitUrl = window.RECORDER_ENTRY?.api_submit_url || "/recorder/api/submit-audio";

    // timeout so it never "stuck"
    const controller = new AbortController();
    const timeout = setTimeout(() => controller.abort(), 30000);

    let res;
    try {
      res = await fetch(submitUrl, {
        method: "POST",
        body: fd,
        credentials: "same-origin",
        redirect: "manual",
        cache: "no-store",
        signal: controller.signal
      });
    } catch (err) {
      clearTimeout(timeout);
      console.error(err);
      setStatus(entryId, "Save failed. Network/timeout.");
      toast("Save failed. Network/timeout.");
      if (saveBtn) saveBtn.disabled = false;
      return;
    }
    clearTimeout(timeout);

    if (looksLikeLogin(res)) {
      setStatus(entryId, "Session expired. Please login again.");
      toast("Session expired. Please login again.");
      if (saveBtn) saveBtn.disabled = false;
      window.location.href = "/recorder";
      return;
    }

    const data = await safeJson(res);

    if (!res.ok || !data.ok) {
      const msg = data?.error || `Save failed (${res.status})`;
      setStatus(entryId, msg);
      toast(msg);
      if (saveBtn) saveBtn.disabled = false;
      return;
    }

    setStatus(entryId, "Saved ✅ Published now.");
    toast("Saved ✅");

    // hide save/rerecord after successful save
    const rerecordBtn = $("[data-rerecord-btn]", root);
    if (saveBtn) saveBtn.style.display = "none";
    if (rerecordBtn) rerecordBtn.style.display = "none";

    active.blob = null;
    if (saveBtn) saveBtn.disabled = false;
  }

  function rerecord(root) {
    console.log("🔁 rerecord clicked");
    const recordBtn = $("[data-record-btn]", root);
    try { if (active?.url) URL.revokeObjectURL(active.url); } catch (_) {}
    active = null;
    if (recordBtn) startRecording(root, recordBtn);
  }

  function bind() {
    console.log("✅ recorder.js bound");

    document.addEventListener("click", (e) => {
      const recordBtn = e.target.closest("[data-record-btn]");
      const stopBtn = e.target.closest("[data-stop-btn]");
      const submitBtn = e.target.closest("[data-submit-btn]");
      const rerecordBtn = e.target.closest("[data-rerecord-btn]");

      const root = e.target.closest(".card, .result-box, section, body") || document.body;

      if (recordBtn) return startRecording(root, recordBtn);
      if (stopBtn) return stopRecording();
      if (submitBtn) return saveRecording(root);
      if (rerecordBtn) return rerecord(root);
    });

    window.addEventListener("beforeunload", () => {
      try { stopRecording(); } catch (_) {}
      try { stopTracks(active?.stream); } catch (_) {}
    });
  }

  document.addEventListener("DOMContentLoaded", bind);
})();


