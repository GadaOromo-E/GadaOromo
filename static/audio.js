/* static/audio.js
   - Voice search (🎤) fills #searchWord (home page)
   - Audio record (🎙) records + previews + uploads to POST /api/submit-audio
   - Oromo ONLY (record/upload)
   - Supports MANY pending submissions (frontend does not block)
   - FIX: Each recorder widget is isolated (no global currentCtx problems)
*/

(function () {
  // Only one active recording session at a time (browser limitation), but many can be submitted.
  let active = {
    recorder: null,
    stream: null,
    widget: null, // current widget element
    chunks: [],
  };

  function $(root, sel) {
    return root ? root.querySelector(sel) : null;
  }

  function setStatus(widget, msg) {
    const el = $(widget, "[data-status]");
    if (el) el.textContent = msg || "";
  }

  function pickMimeType() {
    if (!window.MediaRecorder) return { mime: "", ext: "webm" };
    if (MediaRecorder.isTypeSupported("audio/webm;codecs=opus")) return { mime: "audio/webm;codecs=opus", ext: "webm" };
    if (MediaRecorder.isTypeSupported("audio/webm")) return { mime: "audio/webm", ext: "webm" };
    if (MediaRecorder.isTypeSupported("audio/ogg;codecs=opus")) return { mime: "audio/ogg;codecs=opus", ext: "ogg" };
    if (MediaRecorder.isTypeSupported("audio/ogg")) return { mime: "audio/ogg", ext: "ogg" };
    return { mime: "", ext: "webm" };
  }

  function stopActiveRecordingUI() {
    // stop recorder + mic tracks
    try {
      if (active.recorder && active.recorder.state !== "inactive") active.recorder.stop();
    } catch (_) {}

    try {
      if (active.stream) {
        active.stream.getTracks().forEach((t) => t.stop());
      }
    } catch (_) {}

    active.recorder = null;
    active.stream = null;
    active.chunks = [];
    active.widget = null;
  }

  async function startRecording(widget) {
    if (!navigator.mediaDevices?.getUserMedia) {
      throw new Error("Microphone not supported in this browser.");
    }

    // If something is already recording, stop it cleanly (so user can continue)
    if (active.recorder && active.recorder.state !== "inactive") {
      setStatus(active.widget, "⏹ Stopped (new recording started elsewhere).");
      stopActiveRecordingUI();
    }

    const { mime, ext } = pickMimeType();
    widget.dataset.ext = ext;

    const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
    const recorder = new MediaRecorder(stream, mime ? { mimeType: mime } : undefined);

    active.stream = stream;
    active.recorder = recorder;
    active.widget = widget;
    active.chunks = [];

    recorder.ondataavailable = (e) => {
      if (e.data && e.data.size > 0) active.chunks.push(e.data);
    };

    recorder.onstop = () => {
      const ext2 = widget.dataset.ext || "webm";
      const type = recorder.mimeType || (ext2 === "ogg" ? "audio/ogg" : "audio/webm");
      const blob = new Blob(active.chunks, { type });

      // store blob on widget itself so submit works even after you record other words
      widget._recordedBlob = blob;

      const preview = $(widget, "[data-preview-audio]");
      if (preview) {
        const url = URL.createObjectURL(blob);
        preview.src = url;
        preview.style.display = "block";
        preview.load();
      }

      const submitBtn = $(widget, "[data-submit-btn]");
      const rerecordBtn = $(widget, "[data-rerecord-btn]");
      if (submitBtn) submitBtn.style.display = "inline-block";
      if (rerecordBtn) rerecordBtn.style.display = "inline-block";

      setStatus(widget, "✅ Recording ready. Submit when you want.");

      // show record again (so user can move on)
      const recordBtn = $(widget, "[data-record-btn]");
      const stopBtn = $(widget, "[data-stop-btn]");
      if (recordBtn) recordBtn.style.display = "inline-block";
      if (stopBtn) stopBtn.style.display = "none";

      // cleanup active session
      stopActiveRecordingUI();
    };

    recorder.start(200);
  }

  async function upload(widget) {
    const blob = widget._recordedBlob;
    if (!blob) {
      setStatus(widget, "❌ No recording found.");
      return;
    }

    const entryType = (widget.dataset.entryType || "").trim().toLowerCase();
    const entryId = (widget.dataset.entryId || "").trim();
    const lang = (widget.dataset.lang || "oromo").trim().toLowerCase();

    if (!entryType || !entryId) {
      setStatus(widget, "❌ Missing entry info (entry_type/entry_id).");
      return;
    }

    // Oromo ONLY
    if (lang !== "oromo") {
      setStatus(widget, "❌ Only Oromo audio is allowed.");
      return;
    }

    setStatus(widget, "⏳ Uploading…");

    const fd = new FormData();
    fd.append("entry_type", entryType);
    fd.append("entry_id", entryId);
    fd.append("lang", "oromo");

    const ext = widget.dataset.ext || "webm";
    fd.append("audio", blob, `recording.${ext}`);

    let res, data;
    try {
      res = await fetch("/api/submit-audio", { method: "POST", body: fd });
      try { data = await res.json(); } catch (_) { data = null; }
    } catch (err) {
      console.error(err);
      setStatus(widget, "❌ Network error uploading audio.");
      return;
    }

    if (!res.ok || !data || !data.ok) {
      const msg = data?.error || `Upload failed (HTTP ${res.status})`;
      console.error("Upload error:", msg, data);
      setStatus(widget, "❌ " + msg);
      return;
    }

    setStatus(widget, "✅ Submitted! Waiting for admin approval.");

    // keep the blob so they can submit other words; but hide submit button for this one
    const submitBtn = $(widget, "[data-submit-btn]");
    if (submitBtn) submitBtn.style.display = "none";
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

  // ---------- Event Delegation: works for MANY widgets ----------
  function wire() {
    document.addEventListener("click", async (e) => {
      const recordBtn = e.target.closest("[data-record-btn]");
      const stopBtn = e.target.closest("[data-stop-btn]");
      const submitBtn = e.target.closest("[data-submit-btn]");
      const rerecordBtn = e.target.closest("[data-rerecord-btn]");

      if (recordBtn) {
        const widget = recordBtn.closest("[data-audio-widget]");
        if (!widget) {
          alert("Recorder widget wrapper not found (data-audio-widget).");
          return;
        }

        // Oromo only
        const lang = (widget.dataset.lang || "oromo").toLowerCase();
        if (lang !== "oromo") {
          setStatus(widget, "❌ Only Oromo audio is allowed.");
          return;
        }

        // UI states
        recordBtn.style.display = "none";
        const st = $(widget, "[data-stop-btn]");
        if (st) st.style.display = "inline-block";

        const preview = $(widget, "[data-preview-audio]");
        if (preview) preview.style.display = "none";

        const sbtn = $(widget, "[data-submit-btn]");
        const rbtn = $(widget, "[data-rerecord-btn]");
        if (sbtn) sbtn.style.display = "none";
        if (rbtn) rbtn.style.display = "none";

        setStatus(widget, "🎙 Recording… (allow microphone permission)");

        try {
          await startRecording(widget);
        } catch (err) {
          console.error(err);
          setStatus(widget, "❌ " + (err?.message || "Recording failed"));
          recordBtn.style.display = "inline-block";
          if (st) st.style.display = "none";
          stopActiveRecordingUI();
        }
        return;
      }

      if (stopBtn) {
        const widget = stopBtn.closest("[data-audio-widget]");
        if (!widget) return;

        // stop only if this widget is active
        if (active.widget === widget && active.recorder && active.recorder.state !== "inactive") {
          try { active.recorder.stop(); } catch (_) {}
        } else {
          setStatus(widget, "⏹ Stopped.");
        }

        // release mic tracks no matter what
        try {
          if (active.stream) active.stream.getTracks().forEach((t) => t.stop());
        } catch (_) {}

        stopBtn.style.display = "none";
        const rb = $(widget, "[data-record-btn]");
        if (rb) rb.style.display = "inline-block";
        return;
      }

      if (rerecordBtn) {
        const widget = rerecordBtn.closest("[data-audio-widget]");
        if (!widget) return;

        widget._recordedBlob = null;

        const preview = $(widget, "[data-preview-audio]");
        if (preview) preview.style.display = "none";

        const sbtn = $(widget, "[data-submit-btn]");
        const rbtn = $(widget, "[data-rerecord-btn]");
        if (sbtn) sbtn.style.display = "none";
        if (rbtn) rbtn.style.display = "none";

        const rb = $(widget, "[data-record-btn]");
        if (rb) rb.click();
        return;
      }

      if (submitBtn) {
        const widget = submitBtn.closest("[data-audio-widget]");
        if (!widget) return;
        await upload(widget);
        return;
      }
    });
  }

  document.addEventListener("DOMContentLoaded", wire);
})();



