/* static/audio.js
   - Voice search (🎤) fills #searchWord (home page)
   - Audio record (🎙) records + previews + uploads to POST /api/submit-audio
   - Oromo ONLY (record/upload)
   - Supports MANY rows (each row has its own Stop/Submit/Preview)
*/

(function () {
  // ---------- Status helpers ----------
  function findStatusEl(entryType, entryId) {
    const key1 = `${entryType}_${entryId}`;
    let el = document.querySelector(`[data-status-for="${key1}"]`);
    if (el) return el;

    el = document.querySelector(`[data-status-for="${entryId}"]`);
    if (el) return el;

    return null;
  }

  function setStatus(entryType, entryId, msg) {
    const el = findStatusEl(entryType, entryId);
    if (el) el.textContent = msg || "";
  }

  // ---------- Voice Search (home only) ----------
  window.startVoiceSearch = function startVoiceSearch() {
    const input = document.getElementById("searchWord");
    if (!input) return alert("Search input not found.");

    const SpeechRecognition = window.SpeechRecognition || window.webkitSpeechRecognition;
    if (!SpeechRecognition) {
      alert("Voice search not supported in this browser. Try Chrome on Android/Desktop.");
      return;
    }

    const recog = new SpeechRecognition();
    recog.lang = "en-US";
    recog.interimResults = false;
    recog.maxAlternatives = 1;

    recog.onresult = (e) => {
      const text = e?.results?.[0]?.[0]?.transcript || "";
      if (text) input.value = text.trim();
      input.focus();
    };

    recog.onerror = (e) => {
      console.error("SpeechRecognition error:", e);
      alert("Voice search failed: " + (e.error || "unknown error"));
    };

    try {
      recog.start();
    } catch (err) {
      console.error(err);
      alert("Could not start voice search.");
    }
  };

  // ---------- Recording support ----------
  function pickMimeType() {
    if (!window.MediaRecorder) return { mime: "", ext: "webm" };

    if (MediaRecorder.isTypeSupported("audio/webm;codecs=opus")) return { mime: "audio/webm;codecs=opus", ext: "webm" };
    if (MediaRecorder.isTypeSupported("audio/webm")) return { mime: "audio/webm", ext: "webm" };
    if (MediaRecorder.isTypeSupported("audio/ogg;codecs=opus")) return { mime: "audio/ogg;codecs=opus", ext: "ogg" };
    if (MediaRecorder.isTypeSupported("audio/ogg")) return { mime: "audio/ogg", ext: "ogg" };

    return { mime: "", ext: "webm" };
  }

  // One active recording at a time (simplest + safest UX)
  // But you can record MANY different words one after another.
  let active = null; // { stream, recorder, chunks, ctx }

  function findScope(btn) {
    // Best: per-row container
    return (
      btn.closest(".word-row") ||
      btn.closest(".result-box") ||
      btn.closest(".card") ||
      btn.parentElement ||
      document
    );
  }

  function buildCtx(btn) {
    const entryType = (btn.getAttribute("data-entry-type") || "").trim().toLowerCase();
    const entryId = Number(btn.getAttribute("data-entry-id"));
    const lang = (btn.getAttribute("data-lang") || "oromo").trim().toLowerCase();

    if (!entryType || !entryId || !Number.isFinite(entryId)) {
      alert("Missing entry type/id on record button.");
      return null;
    }

    // Oromo ONLY
    if (lang !== "oromo") {
      alert("Only Oromo audio is allowed.");
      return null;
    }

    const scope = findScope(btn);

    // IMPORTANT: query inside the scope (not the whole card/section)
    const stopBtn = scope.querySelector("[data-stop-btn]");
    const submitBtn = scope.querySelector("[data-submit-btn]");
    const rerecordBtn = scope.querySelector("[data-rerecord-btn]");
    const previewAudio = scope.querySelector("[data-preview-audio]");

    if (!stopBtn || !submitBtn || !rerecordBtn || !previewAudio) {
      alert("Recording UI elements not found near this word. (Stop/Submit/Preview missing)");
      return null;
    }

    return {
      entryType,
      entryId,
      lang: "oromo",
      recordBtn: btn,
      stopBtn,
      submitBtn,
      rerecordBtn,
      previewAudio,
      ext: "webm",
      blob: null,
      scope,
    };
  }

  async function startRecording(ctx) {
    if (!navigator.mediaDevices?.getUserMedia) {
      throw new Error("Microphone not supported in this browser.");
    }

    // If another recording is active, stop it cleanly first
    if (active?.recorder && active.recorder.state !== "inactive") {
      try { active.recorder.stop(); } catch (_) {}
      try { active.stream?.getTracks()?.forEach(t => t.stop()); } catch (_) {}
      active = null;
    }

    const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
    const { mime, ext } = pickMimeType();
    ctx.ext = ext;

    const recorder = new MediaRecorder(stream, mime ? { mimeType: mime } : undefined);
    const chunks = [];

    recorder.ondataavailable = (e) => {
      if (e.data && e.data.size > 0) chunks.push(e.data);
    };

    recorder.onstop = () => {
      const type = recorder.mimeType || (ctx.ext === "ogg" ? "audio/ogg" : "audio/webm");
      const blob = new Blob(chunks, { type });
      ctx.blob = blob;

      const url = URL.createObjectURL(blob);
      ctx.previewAudio.src = url;
      ctx.previewAudio.style.display = "block";
      ctx.previewAudio.load();

      ctx.submitBtn.style.display = "inline-block";
      ctx.rerecordBtn.style.display = "inline-block";

      setStatus(ctx.entryType, ctx.entryId, "✅ Recording ready. Submit when you want.");
    };

    recorder.start(200);

    active = { stream, recorder, chunks, ctx };
  }

  function stopRecording(ctx) {
    if (!active || active.ctx !== ctx) return;

    try {
      if (active.recorder && active.recorder.state !== "inactive") active.recorder.stop();
    } catch (_) {}

    try {
      if (active.stream) {
        active.stream.getTracks().forEach((t) => t.stop());
      }
    } catch (_) {}

    // Keep ctx + blob; clear active recorder state
    active = null;
  }

  async function upload(ctx) {
    if (!ctx.blob) {
      setStatus(ctx.entryType, ctx.entryId, "❌ No recording found.");
      return;
    }

    setStatus(ctx.entryType, ctx.entryId, "⏳ Uploading…");

    const fd = new FormData();
    fd.append("entry_type", ctx.entryType);
    fd.append("entry_id", String(ctx.entryId));
    fd.append("lang", "oromo");

    const filename = `recording.${ctx.ext || "webm"}`;
    fd.append("audio", ctx.blob, filename);

    let res, data;
    try {
      res = await fetch("/api/submit-audio", { method: "POST", body: fd });
      try { data = await res.json(); } catch (_) { data = null; }
    } catch (err) {
      console.error(err);
      setStatus(ctx.entryType, ctx.entryId, "❌ Network error uploading audio.");
      return;
    }

    if (!res.ok || !data || !data.ok) {
      const msg = data?.error || `Upload failed (HTTP ${res.status})`;
      console.error("Upload error:", msg, data);
      setStatus(ctx.entryType, ctx.entryId, "❌ " + msg);
      return;
    }

    setStatus(ctx.entryType, ctx.entryId, "✅ Submitted! Waiting for admin approval.");
    ctx.submitBtn.style.display = "none";
  }

  function wire() {
    document.querySelectorAll("[data-record-btn]").forEach((btn) => {
      btn.addEventListener("click", async () => {
        const ctx = buildCtx(btn);
        if (!ctx) return;

        // Reset UI in this scope
        ctx.recordBtn.style.display = "none";
        ctx.stopBtn.style.display = "inline-block";
        ctx.submitBtn.style.display = "none";
        ctx.rerecordBtn.style.display = "none";
        ctx.previewAudio.style.display = "none";

        setStatus(ctx.entryType, ctx.entryId, "🎙 Recording… (allow microphone permission)");

        try {
          await startRecording(ctx);
        } catch (err) {
          console.error(err);
          setStatus(ctx.entryType, ctx.entryId, "❌ " + (err?.message || "Recording failed"));
          ctx.recordBtn.style.display = "inline-block";
          ctx.stopBtn.style.display = "none";
        }
      });
    });

    document.querySelectorAll("[data-stop-btn]").forEach((stopBtn) => {
      stopBtn.addEventListener("click", () => {
        // Stop belongs to the same scope as the stop button
        const scope = stopBtn.closest(".word-row") || stopBtn.closest(".result-box") || stopBtn.closest(".card") || document;
        const recordBtn = scope.querySelector("[data-record-btn]");
        if (!recordBtn) return;

        const ctx = buildCtx(recordBtn);
        if (!ctx) return;

        stopBtn.style.display = "none";
        stopRecording(ctx);

        // After stop, show record button again (user can re-record or submit)
        ctx.recordBtn.style.display = "inline-block";
      });
    });

    document.querySelectorAll("[data-rerecord-btn]").forEach((btn) => {
      btn.addEventListener("click", () => {
        const scope = btn.closest(".word-row") || btn.closest(".result-box") || btn.closest(".card") || document;
        const recordBtn = scope.querySelector("[data-record-btn]");
        if (!recordBtn) return;

        const ctx = buildCtx(recordBtn);
        if (!ctx) return;

        ctx.blob = null;
        ctx.previewAudio.style.display = "none";
        ctx.submitBtn.style.display = "none";
        ctx.rerecordBtn.style.display = "none";
        ctx.recordBtn.click();
      });
    });

    document.querySelectorAll("[data-submit-btn]").forEach((btn) => {
      btn.addEventListener("click", async () => {
        const scope = btn.closest(".word-row") || btn.closest(".result-box") || btn.closest(".card") || document;
        const recordBtn = scope.querySelector("[data-record-btn]");
        if (!recordBtn) return;

        const ctx = buildCtx(recordBtn);
        if (!ctx) return;

        await upload(ctx);
      });
    });
  }

  document.addEventListener("DOMContentLoaded", wire);
})();




