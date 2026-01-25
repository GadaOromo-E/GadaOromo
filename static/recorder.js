/* static/recorder.js (FIXED + HARDENED)
   - Fixes dead/stuck button (syntax + binding issues)
   - Event delegation: works even with PWA caching / late script load
   - Still uses your save logic (credentials + timeout + redirect handling)
*/

(() => {
  console.log("✅ recorder.js LOADED", new Date().toISOString());

  const CSRF_TOKEN =
    document.querySelector('meta[name="csrf-token"]')?.getAttribute("content") || null;

  const AUTO_RELOAD_AFTER_SAVE = true;

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
      }, 2400);
      try { navigator.vibrate?.(10); } catch (_) {}
    } else {
      alert(msg);
    }
  }

  let active = null;

  function setStatus(keyOrId, msg) {
    const k = String(keyOrId ?? "").trim();
    let el = document.querySelector(`[data-status-for="${k}"]`);
    if (el) { el.textContent = msg || ""; return; }

    const t = active?.entryType;
    if (t && k) {
      el = document.querySelector(`[data-status-for="${t}_${k}"]`);
      if (el) { el.textContent = msg || ""; return; }
    }
  }

  const hasGetUserMedia = !!(navigator.mediaDevices && navigator.mediaDevices.getUserMedia);
  const hasMediaRecorder = typeof window.MediaRecorder !== "undefined";

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

  function looksLikeLoginRedirect(res) {
    const ct = (res.headers.get("content-type") || "").toLowerCase();
    if (res.status === 401 || res.status === 403) return true;
    if (res.type === "opaqueredirect") return true;
    if (res.redirected) return true;
    if (ct.includes("text/html")) return true;
    return false;
  }

  async function safeJson(res) {
    const ct = (res.headers.get("content-type") || "").toLowerCase();
    const text = await res.text().catch(() => "");
    if (!ct.includes("application/json")) {
      return { ok: false, error: text || "Server returned non-JSON response (maybe login redirect)." };
    }
    try { return JSON.parse(text); }
    catch { return { ok: false, error: "Invalid JSON response from server." }; }
  }

  function getApiUrls() {
    const cfg = window.RECORDER_ENTRY || {};
    return {
      submit: cfg.api_submit_url || "/recorder/api/submit-audio",
      del: cfg.api_delete_url || "/recorder/api/delete-audio",
    };
  }

  function updateLivePlayer(url) {
    const card = document.getElementById("liveAudioCard");
    const source = document.getElementById("liveAudioSource");
    const audioEl = document.getElementById("liveAudio");
    if (!card || !source || !audioEl) return;

    if (url) {
      card.style.display = "block";
      source.src = url;
      audioEl.load();
    } else {
      source.src = "";
      audioEl.load();
      card.style.display = "none";
    }
  }

  async function startRecording(btn) {
    console.log("🎙 startRecording");

    if (!hasGetUserMedia) return toast("Microphone not supported in this browser.");
    if (!hasMediaRecorder) return toast("Recording not supported here. Try Chrome on Android/Desktop.");

    if (active?.recorder?.state === "recording") {
      try { active.recorder.stop(); } catch (_) {}
    }

    const entryType = (btn.dataset.entryType || "").trim().toLowerCase();
    const entryId = (btn.dataset.entryId || "").trim();
    const lang = (btn.dataset.lang || "oromo").trim().toLowerCase();

    if (!entryType || !entryId) return toast("Missing entry info (entry_type/entry_id).");
    if (lang !== "oromo") return toast("Recorder only allows Oromo audio.");

    const root = btn.closest(".result-box, .word-row, .card, section, body") || document.body;
    const stopBtn = root.querySelector("[data-stop-btn]");
    const preview = root.querySelector("[data-preview-audio]");
    const saveBtn = root.querySelector("[data-submit-btn]");
    const rerecordBtn = root.querySelector("[data-rerecord-btn]");

    setStatus(entryId, "Requesting microphone…");

    try {
      const stream = await navigator.mediaDevices.getUserMedia({
        audio: { echoCancellation: true, noiseSuppression: true, autoGainControl: true }
      });

      const mimeType = pickMimeType();
      let recorder;
      try { recorder = new MediaRecorder(stream, mimeType ? { mimeType } : undefined); }
      catch { recorder = new MediaRecorder(stream); }

      const chunks = [];
      recorder.ondataavailable = (e) => { if (e.data && e.data.size > 0) chunks.push(e.data); };

      recorder.onstart = () => {
        setStatus(entryId, "Recording…");
        btn.style.display = "none";
        if (stopBtn) stopBtn.style.display = "inline-block";
        if (saveBtn) { saveBtn.style.display = "none"; saveBtn.disabled = false; }
        if (rerecordBtn) rerecordBtn.style.display = "none";
        if (preview) preview.style.display = "none";
        toast("Recording…");
      };

      recorder.onstop = () => {
        stopTracks(stream);
        const finalMime = recorder.mimeType || mimeType || "audio/webm";
        const blob = new Blob(chunks, { type: finalMime });

        if (!blob || blob.size === 0) {
          setStatus(entryId, "No audio captured. Try again.");
          btn.style.display = "inline-block";
          if (stopBtn) stopBtn.style.display = "none";
          return;
        }

        try { if (active?.url) URL.revokeObjectURL(active.url); } catch (_) {}
        const url = URL.createObjectURL(blob);

        if (preview) {
          preview.src = url;
          preview.style.display = "block";
          preview.load();
        }

        setStatus(entryId, "Recorded ✅ Click Submit to save.");
        if (stopBtn) stopBtn.style.display = "none";
        btn.style.display = "inline-block";
        if (saveBtn) saveBtn.style.display = "inline-block";
        if (rerecordBtn) rerecordBtn.style.display = "inline-block";

        active = { recorder, blob, url, mimeType: finalMime, entryType, entryId, lang, root,
          ui: { btn, stopBtn, preview, saveBtn, rerecordBtn } };

        toast("Recorded ✅");
      };

      active = { recorder, stream, chunks, blob: null, url: null, mimeType, entryType, entryId, lang, root,
        ui: { btn, stopBtn, preview, saveBtn, rerecordBtn } };

      recorder.start();
    } catch (err) {
      console.error(err);
      setStatus(entryId, "Mic blocked. Allow microphone permission.");
      toast("Microphone blocked. Allow permission.");
    }
  }

  function stopRecording() {
    console.log("⏹ stopRecording");
    if (!active?.recorder) return;
    try { if (active.recorder.state === "recording") active.recorder.stop(); } catch (e) { console.error(e); }
  }

  async function saveRecording() {
    console.log("✅ saveRecording");
    if (!active?.blob) return toast("No recording found.");

    const { entryType, entryId, lang, blob, mimeType, ui, root } = active;
    setStatus(entryId, "Saving…");
    if (ui?.saveBtn) ui.saveBtn.disabled = true;

    const ext = extFromMime(mimeType);

    const fd = new FormData();
    fd.append("entry_type", entryType);
    fd.append("entry_id", entryId);
    fd.append("lang", lang);
    fd.append("audio", blob, `recording.${ext}`);

    const { submit } = getApiUrls();
    const headers = {};
    if (CSRF_TOKEN) headers["X-CSRFToken"] = CSRF_TOKEN;

    const controller = new AbortController();
    const t = setTimeout(() => controller.abort(), 30000);

    let res;
    try {
      res = await fetch(submit, {
        method: "POST",
        body: fd,
        headers,
        credentials: "same-origin",
        redirect: "manual",
        cache: "no-store",
        signal: controller.signal
      });
    } catch (err) {
      console.error(err);
      const msg = err?.name === "AbortError" ? "Save timed out (30s)." : "Save failed. Check internet.";
      setStatus(entryId, msg);
      toast(msg);
      if (ui?.saveBtn) ui.saveBtn.disabled = false;
      clearTimeout(t);
      return;
    } finally {
      clearTimeout(t);
    }

    if (looksLikeLoginRedirect(res)) {
      setStatus(entryId, "Session expired. Please log in again.");
      toast("Session expired.");
      window.location.href = "/recorder";
      return;
    }

    const data = await safeJson(res);

    if (!res.ok || !data.ok) {
      const msg = data.error || `Save failed (${res.status})`;
      setStatus(entryId, msg);
      toast(msg);
      if (ui?.saveBtn) ui.saveBtn.disabled = false;
      return;
    }

    setStatus(entryId, data.message || "Saved ✅");
    toast("Saved ✅");

    const preview = ui?.preview || root?.querySelector("[data-preview-audio]");
    if (data.url && preview) {
      const bust = (data.url.includes("?") ? "&" : "?") + "t=" + Date.now();
      preview.src = data.url + bust;
      preview.style.display = "block";
      preview.load();
    }
    if (data.url) updateLivePlayer(data.url);

   // ✅ Hide ALL recording controls after success (so user doesn't think it's not saved)
if (ui?.saveBtn) ui.saveBtn.style.display = "none";
if (ui?.rerecordBtn) ui.rerecordBtn.style.display = "none";
if (ui?.stopBtn) ui.stopBtn.style.display = "none";
if (ui?.btn) {
  ui.btn.style.display = "none";         // hide record button
  ui.btn.disabled = true;
}


    active.blob = null;

    if (AUTO_RELOAD_AFTER_SAVE) setTimeout(() => window.location.reload(), 800);
  }

  function rerecord() {
    console.log("🔁 rerecord");
    if (!active) return;
    try { if (active.url) URL.revokeObjectURL(active.url); } catch (_) {}
    const btn = active.ui?.btn;
    active = null;
    if (btn) startRecording(btn);
  }

  // ✅ KEY FIX: Event delegation (no bind/DOMContentLoaded issues)
  document.addEventListener("click", (e) => {
    const rec = e.target.closest("[data-record-btn]");
    if (rec) { e.preventDefault(); e.stopPropagation(); return startRecording(rec); }

    const stop = e.target.closest("[data-stop-btn]");
    if (stop) { e.preventDefault(); e.stopPropagation(); return stopRecording(); }

    const sub = e.target.closest("[data-submit-btn]");
    if (sub) { e.preventDefault(); e.stopPropagation(); return saveRecording(); }

    const rr = e.target.closest("[data-rerecord-btn]");
    if (rr) { e.preventDefault(); e.stopPropagation(); return rerecord(); }
  }, true);

  window.addEventListener("beforeunload", () => {
    try { stopRecording(); } catch (_) {}
    try { stopTracks(active?.stream); } catch (_) {}
  });

})();


