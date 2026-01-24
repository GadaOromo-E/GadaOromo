/* static/recorder.js (fully updated)
   Recorder-only recording:
   - Records Oromo audio and uploads to POST /recorder/api/submit-audio (auto-approved + replace)
   - Delete LIVE Oromo audio: POST /recorder/api/delete-audio
   - Shows Preview + Save (publish) + Re-record
   - Fixes "Saving… stuck" by:
       ✅ sending cookies with fetch (credentials: same-origin)
       ✅ preventing silent redirects (redirect: manual)
       ✅ handling non-JSON responses safely (login HTML)
       ✅ adding a 30s timeout (AbortController)
       ✅ cache: no-store (helps with PWA/service-worker oddities)
*/

(() => {
  const $ = (sel, root = document) => root.querySelector(sel);
  const $$ = (sel, root = document) => Array.from(root.querySelectorAll(sel));

  // If you use CSRF (Flask-WTF), add:
  // <meta name="csrf-token" content="{{ csrf_token() }}">
  const CSRF_TOKEN =
    document.querySelector('meta[name="csrf-token"]')?.getAttribute("content") || null;

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

  let active = null; // one active recording at a time

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
    return ""; // fallback: let browser choose
  }

  function extFromMime(mimeType) {
    const mt = (mimeType || "").toLowerCase();
    if (mt.includes("ogg")) return "ogg";
    if (mt.includes("webm")) return "webm";
    // Some browsers may produce mp4/m4a; but your backend allowlist controls final accept.
    return "webm";
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
    if (!ct.includes("application/json")) {
      // likely login HTML or text error
      await res.text().catch(() => "");
      return { ok: false, error: "Server returned non-JSON response." };
    }
    return await res.json().catch(() => ({ ok: false, error: "Invalid JSON response from server." }));
  }

  function getApiUrls() {
    const cfg = window.RECORDER_ENTRY || {};
    return {
      submit: cfg.api_submit_url || "/recorder/api/submit-audio",
      del: cfg.api_delete_url || "/recorder/api/delete-audio",
    };
    // If needed later: audioGet: cfg.api_audio_get_url || "/recorder/api/audio"
  }

  async function startRecording(btn) {
    if (!hasGetUserMedia) return toast("Microphone not supported in this browser.");
    if (!hasMediaRecorder) return toast("Recording not supported here. Try Chrome on Android/Desktop.");

    // Stop current recording if running
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

    try {
      const stream = await navigator.mediaDevices.getUserMedia({
        audio: {
          echoCancellation: true,
          noiseSuppression: true,
          autoGainControl: true
        }
      });

      // If mic track ends (common on iOS), show message instead of silent stop
      const track = stream.getAudioTracks()?.[0];
      if (track) {
        track.addEventListener("ended", () => {
          setStatus(entryId, "⚠️ Microphone stopped. Please try again.");
          toast("Microphone stopped.");
          try { stopTracks(stream); } catch (_) {}
          // restore UI
          btn.style.display = "inline-block";
          if (stopBtn) stopBtn.style.display = "none";
        });
      }

      const mimeType = pickMimeType();
      let recorder;
      try {
        recorder = new MediaRecorder(stream, mimeType ? { mimeType } : undefined);
      } catch (e) {
        // fallback: let browser decide if mimeType config fails
        recorder = new MediaRecorder(stream);
      }

      const chunks = [];

      recorder.ondataavailable = (e) => {
        if (e.data && e.data.size > 0) chunks.push(e.data);
      };

      recorder.onerror = (e) => {
        console.error("Recorder error:", e);
        setStatus(entryId, "❌ Recorder error. Try again.");
        toast("Recorder error.");
        stopTracks(stream);
        btn.style.display = "inline-block";
        if (stopBtn) stopBtn.style.display = "none";
      };

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

        // Revoke old preview URL if any
        try { if (active?.url) URL.revokeObjectURL(active.url); } catch (_) {}

        const url = URL.createObjectURL(blob);

        if (preview) {
          preview.src = url;
          preview.style.display = "block";
          preview.load();
        }

        setStatus(entryId, "Recorded ✅ Click Save to publish.");

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
          ui: { btn, stopBtn, preview, saveBtn, rerecordBtn }
        };

        toast("Recorded ✅");
      };

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
        ui: { btn, stopBtn, preview, saveBtn, rerecordBtn }
      };

      // Start WITHOUT timeslice for stability (prevents instant-stop issues on some browsers)
      recorder.start();

      // Optional sanity check
      setTimeout(() => {
        try {
          if (recorder.state !== "recording") {
            console.warn("Recorder not recording:", recorder.state);
          }
        } catch (_) {}
      }, 300);

    } catch (err) {
      console.error(err);
      setStatus(entryId, "Mic blocked. Allow microphone permission.");
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

    // timeout so it never gets stuck forever
    const controller = new AbortController();
    const t = setTimeout(() => controller.abort(), 30000); // 30s

    let res;
    try {
      res = await fetch(submit, {
        method: "POST",
        body: fd,
        headers,
        credentials: "same-origin", // ✅ send recorder session cookie
        redirect: "manual",         // ✅ prevent silent login redirect
        cache: "no-store",
        signal: controller.signal
      });
    } catch (err) {
      console.error(err);
      const msg = err?.name === "AbortError"
        ? "Save timed out (30s). Server may be slow."
        : "Save failed. Check internet.";
      setStatus(entryId, msg);
      toast(msg);
      return;
    } finally {
      clearTimeout(t);
    }

    if (looksLikeLoginRedirect(res)) {
      const msg = "Session expired / not authorized. Please log in again.";
      setStatus(entryId, msg);
      toast(msg);
      window.location.href = "/recorder";
      return;
    }

    const data = await safeJson(res);

    if (!res.ok || !data.ok) {
      const msg = data.error || `Save failed (${res.status})`;
      setStatus(entryId, msg);
      toast(msg);
      if (res.status === 401) window.location.href = "/recorder";
      return;
    }

    setStatus(entryId, data.message || "Saved ✅ Published now.");
    toast("Saved ✅ Published");

    if (data.url) updateLivePlayer(data.url);

    // Hide buttons after success
    if (ui?.saveBtn) ui.saveBtn.style.display = "none";
    if (ui?.rerecordBtn) ui.rerecordBtn.style.display = "none";

    // Clear blob so it won't re-submit the same audio
    active.blob = null;
  }

  function rerecord() {
    if (!active) return;
    try { if (active.url) URL.revokeObjectURL(active.url); } catch (_) {}
    const btn = active.ui?.btn;
    active = null;
    if (btn) startRecording(btn);
  }

  async function deleteLiveAudio(btn) {
    const entryType = (btn.dataset.entryType || window.RECORDER_ENTRY?.entry_type || "").trim().toLowerCase();
    const entryId = String(btn.dataset.entryId || window.RECORDER_ENTRY?.entry_id ?? "").trim();
    const lang = (btn.dataset.lang || "oromo").trim().toLowerCase();

    if (!entryType || !entryId) return toast("Missing entry info for delete.");
    if (lang !== "oromo") return toast("Only Oromo audio can be deleted here.");
    if (!confirm("Delete LIVE Oromo audio for this entry?")) return;

    const { del } = getApiUrls();

    const fd = new FormData();
    fd.append("entry_type", entryType);
    fd.append("entry_id", entryId);
    fd.append("lang", lang);

    const liveStatus = document.getElementById("liveStatus");
    if (liveStatus) liveStatus.textContent = "Deleting…";

    const headers = {};
    if (CSRF_TOKEN) headers["X-CSRFToken"] = CSRF_TOKEN;

    // timeout
    const controller = new AbortController();
    const t = setTimeout(() => controller.abort(), 30000);

    let res;
    try {
      res = await fetch(del, {
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
      const msg = err?.name === "AbortError"
        ? "Delete timed out (30s)."
        : "Delete failed. Check internet.";
      if (liveStatus) liveStatus.textContent = msg;
      toast(msg);
      return;
    } finally {
      clearTimeout(t);
    }

    if (looksLikeLoginRedirect(res)) {
      const msg = "Session expired / not authorized. Please log in again.";
      if (liveStatus) liveStatus.textContent = msg;
      toast(msg);
      window.location.href = "/recorder";
      return;
    }

    const data = await safeJson(res);

    if (!res.ok || !data.ok) {
      const msg = data.error || `Delete failed (${res.status})`;
      if (liveStatus) liveStatus.textContent = msg;
      toast(msg);
      if (res.status === 401) window.location.href = "/recorder";
      return;
    }

    if (liveStatus) liveStatus.textContent = "Deleted ✅";
    toast("Deleted ✅");
    updateLivePlayer("");
  }

  function bind() {
    $$("[data-record-btn]").forEach((btn) =>
      btn.addEventListener("click", () => startRecording(btn))
    );
    $$("[data-stop-btn]").forEach((btn) =>
      btn.addEventListener("click", () => stopRecording())
    );
    $$("[data-submit-btn]").forEach((btn) =>
      btn.addEventListener("click", () => saveRecording())
    );
    $$("[data-rerecord-btn]").forEach((btn) =>
      btn.addEventListener("click", () => rerecord())
    );

    const delBtn = document.getElementById("deleteLiveBtn");
    if (delBtn) delBtn.addEventListener("click", () => deleteLiveAudio(delBtn));

    window.addEventListener("beforeunload", () => {
      try { stopRecording(); } catch (_) {}
      try { stopTracks(active?.stream); } catch (_) {}
    });
  }

  document.addEventListener("DOMContentLoaded", bind);
})();



