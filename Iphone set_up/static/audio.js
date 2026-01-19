/* static/audio.js
   - Voice search (🎤) fills #searchWord (home page)
   - Audio record (🎙) records + previews + uploads to POST /api/submit-audio
   - Works on BOTH index.html and translate.html

   FIXES:
   - translate.html: recorder UI not in same div => robust UI lookup
   - index.html list: 🎙 buttons had no UI => this file injects ONE global recorder UI and uses it
*/

(function () {
  function findStatusEl(ctx) {
    // translate.html uses "type_id"
    const key1 = `${ctx.entryType}_${ctx.entryId}`;
    let el = document.querySelector(`[data-status-for="${key1}"]`);
    if (el) return el;

    // index.html often uses just numeric id
    el = document.querySelector(`[data-status-for="${ctx.entryId}"]`);
    if (el) return el;

    return null;
  }

  function setStatus(ctx, msg) {
    const el = findStatusEl(ctx);
    if (el) el.textContent = msg || "";
  }

  /* ========== Voice Search (SpeechRecognition) for Home Search ========== */
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
    if (MediaRecorder.isTypeSupported("audio/ogg")) return "audio/ogg";
    return "";
  }

  function stopStream() {
    try {
      if (stream) {
        stream.getTracks().forEach((t) => t.stop());
        stream = null;
      }
    } catch (_) {}
  }

  async function startRecording(ctx) {
    if (!navigator.mediaDevices?.getUserMedia) {
      throw new Error("Microphone not supported in this browser.");
    }

    stream = await navigator.mediaDevices.getUserMedia({ audio: true });

    const mimeType = pickMimeType();
    chunks = [];
    recorder = new MediaRecorder(stream, mimeType ? { mimeType } : undefined);

    recorder.ondataavailable = (e) => {
      if (e.data && e.data.size > 0) chunks.push(e.data);
    };

    recorder.onerror = (e) => {
      console.error("Recorder error:", e);
      setStatus(ctx, "❌ Recording error.");
      stopRecording();
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

    stopStream();
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

    // backend needs a filename with extension
    fd.append("audio", ctx.blob, "recording.webm");

    let res;
    try {
      res = await fetch("/api/submit-audio", { method: "POST", body: fd });
    } catch (err) {
      console.error("Fetch error:", err);
      setStatus(ctx, "❌ Network error uploading audio.");
      return;
    }

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

  /* ========== UI FINDER + GLOBAL UI INJECTION (for index.html list) ========== */

  function ensureGlobalRecorderUI() {
    // If there is already a global recorder UI, do nothing
    if (document.getElementById("globalRecorderUI")) return;

    // Only create if there are mic buttons on page
    if (!document.querySelector("[data-record-btn]")) return;

    const box = document.createElement("div");
    box.id = "globalRecorderUI";
    box.className = "card";
    box.style.marginTop = "12px";
    box.style.display = "none"; // shown only when user clicks a mic button

    box.innerHTML = `
      <h2 style="margin-top:0;">🎙 Record Oromo</h2>
      <div class="muted" style="margin-top:6px;">
        Recording will be submitted for admin approval.
      </div>

      <div class="small-actions" style="margin-top:10px;">
        <button type="button" class="btn" data-stop-btn style="display:none;">⏹ Stop</button>
      </div>

      <audio data-preview-audio controls style="width:100%; display:none; margin-top:10px;"></audio>

      <div class="small-actions" style="margin-top:10px;">
        <button type="button" class="btn primary" data-submit-btn style="display:none;">✅ Submit</button>
        <button type="button" class="btn" data-rerecord-btn style="display:none;">🔁 Re-record</button>
        <button type="button" class="btn danger" data-cancel-btn style="display:none;">✖ Close</button>
      </div>
    `;

    // Insert near bottom of container so it’s not annoying
    const container = document.querySelector(".container");
    if (container) container.appendChild(box);

    // Close button handler
    const cancelBtn = box.querySelector("[data-cancel-btn]");
    cancelBtn.addEventListener("click", () => {
      // reset UI
      box.style.display = "none";
      const stopBtn = box.querySelector("[data-stop-btn]");
      const submitBtn = box.querySelector("[data-submit-btn]");
      const rerecordBtn = box.querySelector("[data-rerecord-btn]");
      const previewAudio = box.querySelector("[data-preview-audio]");
      stopBtn.style.display = "none";
      submitBtn.style.display = "none";
      rerecordBtn.style.display = "none";
      cancelBtn.style.display = "none";
      previewAudio.style.display = "none";
      if (previewAudio) previewAudio.src = "";
      stopRecording();
    });
  }

  // Find the best UI near a button; if none exists, use global injected UI
  function findRecorderUI(btn) {
    // (1) Prefer local UI within the same section/card (search result block)
    const card = btn.closest(".result-box") || btn.closest(".card") || btn.closest("section");
    if (card) {
      const stopBtn = card.querySelector("[data-stop-btn]");
      const submitBtn = card.querySelector("[data-submit-btn]");
      const rerecordBtn = card.querySelector("[data-rerecord-btn]");
      const previewAudio = card.querySelector("[data-preview-audio]");
      if (stopBtn && submitBtn && rerecordBtn && previewAudio) {
        return { stopBtn, submitBtn, rerecordBtn, previewAudio, host: card };
      }
    }

    // (2) translate.html has a single UI (global in that page)
    const stopBtn = document.querySelector("[data-stop-btn]");
    const submitBtn = document.querySelector("[data-submit-btn]");
    const rerecordBtn = document.querySelector("[data-rerecord-btn]");
    const previewAudio = document.querySelector("[data-preview-audio]");
    if (stopBtn && submitBtn && rerecordBtn && previewAudio) {
      return { stopBtn, submitBtn, rerecordBtn, previewAudio, host: document.body };
    }

    // (3) index.html Approved Words list: use injected global recorder UI
    const global = document.getElementById("globalRecorderUI");
    if (global) {
      const stopBtn2 = global.querySelector("[data-stop-btn]");
      const submitBtn2 = global.querySelector("[data-submit-btn]");
      const rerecordBtn2 = global.querySelector("[data-rerecord-btn]");
      const previewAudio2 = global.querySelector("[data-preview-audio]");
      const cancelBtn2 = global.querySelector("[data-cancel-btn]");
      if (stopBtn2 && submitBtn2 && rerecordBtn2 && previewAudio2) {
        return { stopBtn: stopBtn2, submitBtn: submitBtn2, rerecordBtn: rerecordBtn2, previewAudio: previewAudio2, host: global, cancelBtn: cancelBtn2 };
      }
    }

    return null;
  }

  function showGlobalUIIfUsed(ui) {
    if (!ui || !ui.host) return;
    if (ui.host.id === "globalRecorderUI") {
      ui.host.style.display = "block";
      if (ui.cancelBtn) ui.cancelBtn.style.display = "inline-block";
      // scroll to it so user sees controls
      try { ui.host.scrollIntoView({ behavior: "smooth", block: "center" }); } catch (_) {}
    }
  }

  function wire() {
    ensureGlobalRecorderUI();

    document.querySelectorAll("[data-record-btn]").forEach((btn) => {
      btn.addEventListener("click", async () => {
        const entryType = (btn.getAttribute("data-entry-type") || "").trim();
        const entryIdRaw = (btn.getAttribute("data-entry-id") || "").trim();
        const entryId = Number(entryIdRaw);
        const lang = (btn.getAttribute("data-lang") || "oromo").trim();

        if (!entryType || !entryIdRaw || Number.isNaN(entryId)) {
          alert("Missing entry_type or entry_id on record button.");
          return;
        }

        const ui = findRecorderUI(btn);
        if (!ui) {
          alert("Recording UI elements not found on the page.");
          return;
        }

        showGlobalUIIfUsed(ui);

        const { stopBtn, submitBtn, rerecordBtn, previewAudio } = ui;

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

        // Reset UI for new recording
        // IMPORTANT: for tiny 🎙 buttons we do NOT hide them (so list doesn’t jump)
        if (btn.textContent && btn.textContent.includes("Record")) {
          btn.style.display = "none";
        }

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
          if (btn.textContent && btn.textContent.includes("Record")) {
            btn.style.display = "inline-block";
          }
          stopBtn.style.display = "none";
          stopStream();
        }
      });
    });

    document.querySelectorAll("[data-stop-btn]").forEach((btn) => {
      btn.addEventListener("click", () => {
        btn.style.display = "none";
        stopRecording();
        // Only show big "Record Oromo" button again (not tiny icon buttons)
        if (currentCtx?.recordBtn && currentCtx.recordBtn.textContent.includes("Record")) {
          currentCtx.recordBtn.style.display = "inline-block";
        }
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


