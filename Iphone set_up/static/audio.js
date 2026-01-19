/* static/audio.js
   - Voice search (🎤) fills #searchWord (home page)
   - Audio record (🎙) records + previews + uploads to POST /api/submit-audio
   - Works on BOTH index.html and translate.html
*/

(function () {
  function findStatusEl(ctx) {
    // translate.html uses "type_id"
    const key1 = `${ctx.entryType}_${ctx.entryId}`;
    let el = document.querySelector(`[data-status-for="${key1}"]`);
    if (el) return el;

    // index.html uses just numeric id
    el = document.querySelector(`[data-status-for="${ctx.entryId}"]`);
    if (el) return el;

    return null;
  }

  function setStatus(ctx, msg) {
    const el = findStatusEl(ctx);
    if (el) el.textContent = msg || "";
  }

  /* ========== Voice Search (SpeechRecognition) for Home Search ==========
     Your translate page already has startVoice(); we don't replace it.
  */
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

  /* ========== Audio Recording (MediaRecorder) ========== */
  let stream = null;
  let recorder = null;
  let chunks = [];
  let currentCtx = null;

  function pickMimeType() {
    if (!window.MediaRecorder) return "";
    if (MediaRecorder.isTypeSupported("audio/webm;codecs=opus")) return "audio/webm;codecs=opus";
    if (MediaRecorder.isTypeSupported("audio/webm")) return "audio/webm";
    if (MediaRecorder.isTypeSupported("audio/ogg;codecs=opus")) return "audio/ogg;codecs=opus";
    return "";
  }

  async function startRecording(ctx) {
    if (!navigator.mediaDevices?.getUserMedia) {
      throw new Error("Microphone not supported in this browser.");
    }

    // NOTE: mic permission requires https (or localhost)
    stream = await navigator.mediaDevices.getUserMedia({ audio: true });

    const mimeType = pickMimeType();
    chunks = [];
    recorder = new MediaRecorder(stream, mimeType ? { mimeType } : undefined);

    recorder.ondataavailable = (e) => {
      if (e.data && e.data.size > 0) chunks.push(e.data);
    };

    recorder.onstop = () => {
      const type = recorder.mimeType || "audio/webm";
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

    recorder.start();
  }

  function stopRecording() {
    try {
      if (recorder && recorder.state !== "inactive") recorder.stop();
    } catch (_) {}

    try {
      if (stream) {
        stream.getTracks().forEach((t) => t.stop());
        stream = null;
      }
    } catch (_) {}
  }

  async function upload(ctx) {
    if (!ctx.blob) {
      setStatus(ctx, "❌ No recording found.");
      return;
    }

    setStatus(ctx, "⏳ Uploading…");

    const fd = new FormData();
    fd.append("entry_type", ctx.entryType);
    fd.append("entry_id", String(ctx.entryId));
    fd.append("lang", ctx.lang);

    // IMPORTANT: backend needs a filename with extension
    fd.append("audio", ctx.blob, "recording.webm");

    const res = await fetch("/api/submit-audio", { method: "POST", body: fd });

    let data = null;
    try {
      data = await res.json();
    } catch (_) {}

    if (!res.ok || !data || !data.ok) {
      const msg = data?.error || `Upload failed (HTTP ${res.status})`;
      console.error("Upload error:", msg, data);
      setStatus(ctx, "❌ " + msg);
      return;
    }

    setStatus(ctx, "✅ Submitted! Waiting for admin approval.");
    ctx.submitBtn.style.display = "none";
  }

  function wire() {
    document.querySelectorAll("[data-record-btn]").forEach((btn) => {
      btn.addEventListener("click", async () => {
        const entryType = (btn.getAttribute("data-entry-type") || "").trim();
        const entryId = Number(btn.getAttribute("data-entry-id"));
        const lang = (btn.getAttribute("data-lang") || "oromo").trim();

        const container = btn.closest("div") || document;
        const stopBtn = container.querySelector("[data-stop-btn]");
        const submitBtn = container.querySelector("[data-submit-btn]");
        const rerecordBtn = container.querySelector("[data-rerecord-btn]");
        const previewAudio = container.querySelector("[data-preview-audio]");

        if (!stopBtn || !submitBtn || !rerecordBtn || !previewAudio) {
          alert("Recording UI elements not found near the button.");
          return;
        }

        const ctx = {
          entryType,
          entryId,
          lang,
          recordBtn: btn,
          stopBtn,
          submitBtn,
          rerecordBtn,
          previewAudio,
          blob: null,
        };
        currentCtx = ctx;

        btn.style.display = "none";
        stopBtn.style.display = "inline-block";
        submitBtn.style.display = "none";
        rerecordBtn.style.display = "none";
        previewAudio.style.display = "none";
        setStatus(ctx, "🎙 Recording…");

        try {
          await startRecording(ctx);
        } catch (err) {
          console.error(err);
          setStatus(ctx, "❌ " + (err?.message || "Recording failed"));
          btn.style.display = "inline-block";
          stopBtn.style.display = "none";
        }
      });
    });

    document.querySelectorAll("[data-stop-btn]").forEach((btn) => {
      btn.addEventListener("click", () => {
        btn.style.display = "none";
        stopRecording();
        if (currentCtx?.recordBtn) currentCtx.recordBtn.style.display = "inline-block";
      });
    });

    document.querySelectorAll("[data-rerecord-btn]").forEach((btn) => {
      btn.addEventListener("click", () => {
        if (!currentCtx?.recordBtn) return;
        currentCtx.blob = null;
        currentCtx.previewAudio.style.display = "none";
        currentCtx.submitBtn.style.display = "none";
        currentCtx.rerecordBtn.style.display = "none";
        currentCtx.recordBtn.click();
      });
    });

    document.querySelectorAll("[data-submit-btn]").forEach((btn) => {
      btn.addEventListener("click", async () => {
        if (!currentCtx) return;
        await upload(currentCtx);
      });
    });
  }

  document.addEventListener("DOMContentLoaded", wire);
})();

