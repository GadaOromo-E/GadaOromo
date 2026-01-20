/* static/recorder.js
   Recorder-only recording:
   - Uploads to POST /recorder/api/submit-audio  ✅ (auto-approved + replace)
   - Delete LIVE Oromo audio: POST /recorder/api/delete-audio ✅
   - Shows Preview + Save (publish) + Re-record
   - Server requires recorder session, otherwise 401
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
    return "";
  }

  function extFromMime(mimeType) {
    const mt = (mimeType || "").toLowerCase();
    if (mt.includes("ogg")) return "ogg";
    if (mt.includes("webm")) return "webm";
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

  async function startRecording(btn) {
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

      active = { recorder, stream, chunks, blob: null, url: null, mimeType, entryType, entryId, lang, ui: { btn, stopBtn, preview, saveBtn, rerecordBtn } };
      recorder.start();

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

    const submitUrl = (window.RECORDER_ENTRY && window.RECORDER_ENTRY.api_submit_url) || "/recorder/api/submit-audio";

    try {
      const res = await fetch(submitUrl, { method: "POST", body: fd });
      const data = await res.json().catch(() => ({}));

      if (!res.ok || !data.ok) {
        const msg = data.error || `Save failed (${res.status})`;
        setStatus(entryId, msg);
        toast(msg);
        if (res.status === 401) window.location.href = "/recorder";
        return;
      }

      setStatus(entryId, "Saved ✅ Published now.");
      toast("Saved ✅ Published");

      if (data.url) updateLivePlayer(data.url);

      if (ui?.saveBtn) ui.saveBtn.style.display = "none";
      if (ui?.rerecordBtn) ui.rerecordBtn.style.display = "none";

      active.blob = null;

    } catch (err) {
      console.error(err);
      setStatus(entryId, "Save failed. Check internet.");
      toast("Save failed. Check internet.");
    } finally {
      if (ui?.saveBtn) ui.saveBtn.disabled = false;
    }
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

    const delUrl = (window.RECORDER_ENTRY && window.RECORDER_ENTRY.api_delete_url) || "/recorder/api/delete-audio";

    const fd = new FormData();
    fd.append("entry_type", entryType);
    fd.append("entry_id", entryId);
    fd.append("lang", lang);

    const liveStatus = document.getElementById("liveStatus");
    if (liveStatus) liveStatus.textContent = "Deleting…";

    try {
      const res = await fetch(delUrl, { method: "POST", body: fd });
      const data = await res.json().catch(() => ({}));

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

    } catch (err) {
      console.error(err);
      if (liveStatus) liveStatus.textContent = "Delete failed. Check internet.";
      toast("Delete failed. Check internet.");
    }
  }

  function bind() {
    $$("[data-record-btn]").forEach((btn) => btn.addEventListener("click", () => startRecording(btn)));
    $$("[data-stop-btn]").forEach((btn) => btn.addEventListener("click", () => stopRecording()));
    $$("[data-submit-btn]").forEach((btn) => btn.addEventListener("click", () => saveRecording()));
    $$("[data-rerecord-btn]").forEach((btn) => btn.addEventListener("click", () => rerecord()));

    const delBtn = document.getElementById("deleteLiveBtn");
    if (delBtn) delBtn.addEventListener("click", () => deleteLiveAudio(delBtn));

    window.addEventListener("beforeunload", () => {
      try { stopRecording(); } catch (_) {}
      try { stopTracks(active?.stream); } catch (_) {}
    });
  }

  document.addEventListener("DOMContentLoaded", bind);
})();


