/* static/audio.js
   - Voice search (🎤) fills #searchWord (home page)
   - Audio record (🎙) records + previews + uploads to POST /api/submit-audio
   - Oromo ONLY (record/upload)
   - Works on BOTH index.html and translate.html
*/

(function () {
  // ========= Status helpers =========
  function findStatusEl(ctx) {
    // translate.html uses: data-status-for="word_12" or "phrase_99"
    const key1 = `${ctx.entryType}_${ctx.entryId}`;
    let el = document.querySelector(`[data-status-for="${key1}"]`);
    if (el) return el;

    // index.html list uses: data-status-for="{{ w[0] }}" (numeric id)
    el = document.querySelector(`[data-status-for="${ctx.entryId}"]`);
    if (el) return el;

    return null;
  }

  function setStatus(ctx, msg) {
    const el = findStatusEl(ctx);
    if (el) el.textContent = msg || "";
  }

  // ========= Voice Search (home only) =========
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

  // ========= Audio Recording (Oromo only) =========
  let stream = null;
  let recorder = null;
  let chunks = [];
  let currentCtx = null;

  function stopActiveRecordingSilently() {
    try {
      if (recorder && recorder.state !== "inactive") recorder.stop();
    } catch (_) {}

    try {
      if (stream) {
        stream.getTracks().forEach((t) => t.stop());
        stream = null;
      }
    } catch (_) {}

    recorder = null;
    chunks = [];
  }

  function pickMimeType() {
    if (!window.MediaRecorder) return { mime: "", ext: "webm" };

    if (MediaRecorder.isTypeSupported("audio/webm;codecs=opus")) return { mime: "audio/webm;codecs=opus", ext: "webm" };
    if (MediaRecorder.isTypeSupported("audio/webm")) return { mime: "audio/webm", ext: "webm" };
    if (MediaRecorder.isTypeSupported("audio/ogg;codecs=opus")) return { mime: "audio/ogg;codecs=opus", ext: "ogg" };
    if (MediaRecorder.isTypeSupported("audio/ogg")) return { mime: "audio/ogg", ext: "ogg" };

    return { mime: "", ext: "webm" };
  }

  function isSecureContextForMic() {
    // mic generally requires https or localhost
    return window.isSecureContext || location.hostname === "localhost" || location.hostname === "127.0.0.1";
  }

  async function startRecording(ctx) {
    if (!navigator.mediaDevices?.getUserMedia) {
      throw new Error("Microphone not supported in this browser.");
    }
    if (!window.MediaRecorder) {
      throw new Error("Recording not supported (MediaRecorder missing). Try Chrome/Edge.");
    }
    if (!isSecureContextForMic()) {
      throw new Error("Microphone requires HTTPS (or localhost).");
    }

    // stop any previous recording safely
    stopActiveRecordingSilently();

    stream = await navigator.mediaDevices.getUserMedia({ audio: true });

    const { mime, ext } = pickMimeType();
    ctx.ext = ext;

    chunks = [];
    recorder = new MediaRecorder(stream, mime ? { mimeType: mime } : undefined);

    recorder.ondataavailable = (e) => {
      if (e.data && e.data.size > 0) chunks.push(e.data);
    };

    recorder.onstop = () => {
      const type = recorder?.mimeType || (ctx.ext === "ogg" ? "audio/ogg" : "audio/webm");
      const blob = new Blob(chunks, { type });
      ctx.blob = blob;

      const url = URL.createObjectURL(blob);
      ctx.previewAudio.src = url;
      ctx.previewAudio.style.display = "block";
      ctx.previewAudio.load();

      ctx.submitBtn.style.display = "inline-block";
      ctx.rerecordBtn.style.display = "inline-block";

      setStatus(ctx, "✅ Recording ready. Submit when you want.");
    };

    recorder.start(200);
  }

  function stopRecording(ctx) {
    try {
      if (recorder && recorder.state !== "inactive") recorder.stop();
    } catch (_) {}

    try {
      if (stream) {
        stream.getTracks().forEach((t) => t.stop());
        stream = null;
      }
    } catch (_) {}

    // UI after stop
    if (ctx) {
      ctx.stopBtn.style.display = "none";
      ctx.recordBtn.style.display = "inline-block";
    }
  }

  async function upload(ctx) {
    if (!ctx.blob) {
      setStatus(ctx, "❌ No recording found.");
      return;
    }

    // Oromo ONLY
    if ((ctx.lang || "").toLowerCase() !== "oromo") {
      setStatus(ctx, "❌ Only Oromo audio is allowed.");
      return;
    }

    setStatus(ctx, "⏳ Uploading…");

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
      setStatus(ctx, "❌ Network error uploading audio.");
      return;
    }

    if (!res.ok || !data || !data.ok) {
      const msg = data?.error || `Upload failed (HTTP ${res.status})`;
      console.error("Upload error:", msg, data);
      setStatus(ctx, "❌ " + msg);
      return;
    }

    setStatus(ctx, "✅ Submitted! Waiting for admin approval.");
    ctx.submitBtn.style.display = "none";
  }

  // ========= IMPORTANT FIX: scope UI to the clicked record button =========
  function getScopedRoot(btn) {
    // try nearest block that contains the whole recording UI
    return (
      btn.closest(".result-box") ||
      btn.closest(".word-row") ||
      btn.closest(".card") ||
      btn.parentElement ||
      document
    );
  }

  function buildCtxFromRecordBtn(btn) {
    const entryType = (btn.getAttribute("data-entry-type") || "").trim();
    const entryId = Number(btn.getAttribute("data-entry-id"));
    const lang = (btn.getAttribute("data-lang") || "oromo").trim().toLowerCase();

    if (!entryType || !entryId) {
      alert("Recording button is missing entry info.");
      return null;
    }

    // Oromo ONLY
    if (lang !== "oromo") {
      alert("Only Oromo audio is allowed.");
      return null;
    }

    const root = getScopedRoot(btn);

    // find elements ONLY near this button (not first one on page)
    const stopBtn = root.querySelector(":scope [data-stop-btn]");
    const submitBtn = root.querySelector(":scope [data-submit-btn]");
    const rerecordBtn = root.querySelector(":scope [data-rerecord-btn]");
    const previewAudio = root.querySelector(":scope [data-preview-audio]");

    // Some places (word list) only have mic button + status. That’s OK.
    // If UI elements are missing, we show a clear error.
    if (!stopBtn || !submitBtn || !rerecordBtn || !previewAudio) {
      alert(
        "Recording UI elements not found near this mic button.\n\n" +
        "Fix: ensure each mic button has its Stop + Preview + Submit + Re-record elements in the same block."
      );
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
      blob: null,
      ext: "webm",
    };
  }

  function wire() {
    // Record
    document.querySelectorAll("[data-record-btn]").forEach((btn) => {
      btn.addEventListener("click", async () => {
        const ctx = buildCtxFromRecordBtn(btn);
        if (!ctx) return;

        // close previous session UI if any
        if (currentCtx && currentCtx !== ctx) {
          try {
            currentCtx.stopBtn.style.display = "none";
            currentCtx.recordBtn.style.display = "inline-block";
          } catch (_) {}
        }

        currentCtx = ctx;

        ctx.recordBtn.style.display = "none";
        ctx.stopBtn.style.display = "inline-block";
        ctx.submitBtn.style.display = "none";
        ctx.rerecordBtn.style.display = "none";
        ctx.previewAudio.style.display = "none";
        setStatus(ctx, "🎙 Recording… allow microphone permission");

        try {
          await startRecording(ctx);
        } catch (err) {
          console.error(err);
          const msg = err?.message || "Recording failed";
          setStatus(ctx, "❌ " + msg);

          ctx.recordBtn.style.display = "inline-block";
          ctx.stopBtn.style.display = "none";
          stopActiveRecordingSilently();
        }
      });
    });

    // Stop
    document.querySelectorAll("[data-stop-btn]").forEach((btn) => {
      btn.addEventListener("click", () => {
        if (!currentCtx) return;
        stopRecording(currentCtx);
      });
    });

    // Re-record
    document.querySelectorAll("[data-rerecord-btn]").forEach((btn) => {
      btn.addEventListener("click", () => {
        if (!currentCtx?.recordBtn) return;

        currentCtx.blob = null;
        currentCtx.previewAudio.style.display = "none";
        currentCtx.submitBtn.style.display = "none";
        currentCtx.rerecordBtn.style.display = "none";

        // start again
        currentCtx.recordBtn.click();
      });
    });

    // Submit
    document.querySelectorAll("[data-submit-btn]").forEach((btn) => {
      btn.addEventListener("click", async () => {
        if (!currentCtx) return;
        await upload(currentCtx);
      });
    });
  }

  document.addEventListener("DOMContentLoaded", wire);
})();



