/* static/audio.js (PUBLIC mic recorder - FIXED STOP BUTTON)
   - Voice search (home) fills #searchWord
   - Record Oromo pronunciation per result row, submit to POST /api/submit-audio
   FIXES:
     ✅ Stop button always appears (creates one if missing)
     ✅ Safety show Stop on recorder.onstart
     ✅ Better widget detection (result-box / word-row / card)
     ✅ Upload timeout (prevents stuck)
*/

(function () {
  console.log("✅ audio.js LOADED", new Date().toISOString());

  // One active recording at a time
  const active = {
    recorder: null,
    stream: null,
    widget: null,
    chunks: [],
    entryId: "",
    stopping: false,
  };

  const CSRF_TOKEN =
    document.querySelector('meta[name="csrf-token"]')?.getAttribute("content") || null;

  function $(root, sel) {
    return root ? root.querySelector(sel) : null;
  }

  function findWidget(el) {
    return (
      el.closest(".result-box") ||
      el.closest(".word-row") ||
      el.closest(".card") ||
      el.closest("section") ||
      document.body
    );
  }

  function readInfo(widget, btn) {
    const entryType = (btn?.dataset.entryType || widget.dataset.entryType || "").trim().toLowerCase();
    const entryId   = (btn?.dataset.entryId   || widget.dataset.entryId   || "").trim();
    const lang      = (btn?.dataset.lang      || widget.dataset.lang      || "oromo").trim().toLowerCase();
    return { entryType, entryId, lang };
  }

  function setStatus(widget, entryId, msg) {
    const local = $(widget, "[data-status]");
    if (local) local.textContent = msg || "";

    if (entryId) {
      const globalEl = document.querySelector(`[data-status-for="${entryId}"]`);
      if (globalEl) globalEl.textContent = msg || "";
    }
  }

  function pickMime() {
    if (!window.MediaRecorder) return { mime: "", ext: "webm" };
    if (MediaRecorder.isTypeSupported("audio/webm;codecs=opus")) return { mime: "audio/webm;codecs=opus", ext: "webm" };
    if (MediaRecorder.isTypeSupported("audio/webm")) return { mime: "audio/webm", ext: "webm" };
    if (MediaRecorder.isTypeSupported("audio/ogg;codecs=opus")) return { mime: "audio/ogg;codecs=opus", ext: "ogg" };
    if (MediaRecorder.isTypeSupported("audio/ogg")) return { mime: "audio/ogg", ext: "ogg" };
    return { mime: "", ext: "webm" };
  }

  function stopTracks(stream) {
    try { stream?.getTracks()?.forEach(t => t.stop()); } catch (_) {}
  }

  function resetActive() {
    active.recorder = null;
    active.stream = null;
    active.widget = null;
    active.chunks = [];
    active.entryId = "";
    active.stopping = false;
  }

  // Ensure Stop button exists inside widget
  function ensureStopButton(widget, info, recordBtn) {
    let stopBtn = $(widget, "[data-stop-btn]");
    if (stopBtn) return stopBtn;

    // Create a stop button if missing
    stopBtn = document.createElement("button");
    stopBtn.type = "button";
    stopBtn.className = "btn";
    stopBtn.setAttribute("data-stop-btn", "");
    stopBtn.textContent = "⏹ Stop";
    stopBtn.style.padding = "8px 10px";
    stopBtn.style.display = "none";

    // Put it right after the record button if possible
    if (recordBtn && recordBtn.parentNode) {
      recordBtn.parentNode.insertBefore(stopBtn, recordBtn.nextSibling);
    } else {
      widget.appendChild(stopBtn);
    }

    return stopBtn;
  }

  function resetRowUI(widget) {
    const rb = $(widget, "[data-record-btn]");
    const sb = $(widget, "[data-stop-btn]");
    const submitBtn = $(widget, "[data-submit-btn]");
    const rerecordBtn = $(widget, "[data-rerecord-btn]");
    const preview = $(widget, "[data-preview-audio]");

    if (rb) rb.style.display = "inline-block";
    if (sb) sb.style.display = "none";
    if (submitBtn) submitBtn.style.display = "none";
    if (rerecordBtn) rerecordBtn.style.display = "none";
    if (preview) preview.style.display = "none";
  }

  function requestStop(reasonText) {
    if (!active.recorder || active.recorder.state === "inactive") {
      stopTracks(active.stream);
      resetActive();
      return;
    }
    if (active.stopping) return;
    active.stopping = true;

    if (active.widget) setStatus(active.widget, active.entryId, reasonText || "⏹ Stopping…");

    try {
      active.recorder.stop();
    } catch (_) {
      stopTracks(active.stream);
      resetActive();
    }
  }

  async function startRecording(widget, recordBtn) {
    if (!navigator.mediaDevices?.getUserMedia) throw new Error("Microphone not supported in this browser.");
    if (!window.MediaRecorder) throw new Error("Recording not supported in this browser.");

    const info = readInfo(widget, recordBtn);
    if (!info.entryType || !info.entryId) throw new Error("Missing entry info (entry_type/entry_id).");
    if (info.lang !== "oromo") throw new Error("Only Oromo audio is allowed.");

    // Stop any existing recording first
    if (active.recorder && active.recorder.state !== "inactive") {
      requestStop("⏹ Stopped (new recording started).");
      await new Promise(r => setTimeout(r, 250));
    }

    const { mime, ext } = pickMime();
    widget.dataset.ext = ext;

    // Set active session early (so Stop can work even if async)
    active.widget = widget;
    active.entryId = info.entryId;

    const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
    const recorder = new MediaRecorder(stream, mime ? { mimeType: mime } : undefined);

    active.recorder = recorder;
    active.stream = stream;
    active.chunks = [];
    active.stopping = false;

    recorder.ondataavailable = (e) => {
      if (e.data && e.data.size > 0) active.chunks.push(e.data);
    };

    recorder.onerror = () => {
      setStatus(widget, info.entryId, "❌ Recorder error.");
      stopTracks(stream);
      resetRowUI(widget);
      resetActive();
    };

    recorder.onstart = () => {
      // EXTRA SAFETY: ensure stop is visible
      const sb = $(widget, "[data-stop-btn]");
      if (sb) sb.style.display = "inline-block";
      setStatus(widget, info.entryId, "🎙 Recording…");
    };

    recorder.onstop = () => {
      const chunks = active.chunks.slice();
      const ext2 = widget.dataset.ext || "webm";
      const mime2 = recorder.mimeType || (ext2 === "ogg" ? "audio/ogg" : "audio/webm");

      stopTracks(stream);

      const blob = new Blob(chunks, { type: mime2 });
      if (!blob || blob.size === 0) {
        setStatus(widget, info.entryId, "⚠️ No audio captured. Try again.");
        resetRowUI(widget);
        resetActive();
        return;
      }

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

      const rb = $(widget, "[data-record-btn]");
      const sb = $(widget, "[data-stop-btn]");
      if (rb) rb.style.display = "inline-block";
      if (sb) sb.style.display = "none";

      setStatus(widget, info.entryId, "✅ Recording ready. Click Submit.");
      resetActive();
    };

    recorder.start(); // no timeslice (more stable)
  }

  async function safeJson(res) {
    const ct = (res.headers.get("content-type") || "").toLowerCase();
    if (!ct.includes("application/json")) {
      await res.text().catch(() => "");
      return { ok: false, error: "Server returned non-JSON response." };
    }
    return await res.json().catch(() => ({ ok: false, error: "Invalid JSON response from server." }));
  }

  function looksLikeLoginRedirect(res) {
    const ct = (res.headers.get("content-type") || "").toLowerCase();
    if (res.status === 401 || res.status === 403) return true;
    if (res.type === "opaqueredirect") return true;
    if (res.redirected) return true;
    if (ct.includes("text/html")) return true;
    return false;
  }

  async function upload(widget, btn) {
    const info = readInfo(widget, btn);

    if (!info.entryType || !info.entryId) {
      setStatus(widget, info.entryId, "❌ Missing entry info (entry_type/entry_id).");
      return;
    }
    if (info.lang !== "oromo") {
      setStatus(widget, info.entryId, "❌ Only Oromo audio is allowed.");
      return;
    }

    const blob = widget._recordedBlob;
    if (!blob) {
      setStatus(widget, info.entryId, "❌ No recording found.");
      return;
    }

    setStatus(widget, info.entryId, "⏳ Uploading…");

    const fd = new FormData();
    fd.append("entry_type", info.entryType);
    fd.append("entry_id", info.entryId);
    fd.append("lang", "oromo");

    const ext = widget.dataset.ext || "webm";
    fd.append("audio", blob, `recording.${ext}`);

    const headers = {};
    if (CSRF_TOKEN) headers["X-CSRFToken"] = CSRF_TOKEN;

    // timeout so upload can’t hang forever
    const controller = new AbortController();
    const t = setTimeout(() => controller.abort(), 30000);

    let res;
    try {
      res = await fetch("/api/submit-audio", {
        method: "POST",
        body: fd,
        headers,
        credentials: "same-origin",
        redirect: "manual",
        cache: "no-store",
        signal: controller.signal
      });
    } catch (e) {
      const msg = e?.name === "AbortError" ? "❌ Upload timed out (30s)." : "❌ Network error uploading audio.";
      console.error(e);
      setStatus(widget, info.entryId, msg);
      return;
    } finally {
      clearTimeout(t);
    }

    if (looksLikeLoginRedirect(res)) {
      setStatus(widget, info.entryId, "⚠️ Not authorized. Please log in and try again.");
      return;
    }

    const data = await safeJson(res);

    if (!res.ok || !data || !data.ok) {
      const msg = data?.error || `Upload failed (HTTP ${res.status})`;
      console.error("Upload error:", msg, data);
      setStatus(widget, info.entryId, "❌ " + msg);
      return;
    }

    setStatus(widget, info.entryId, "✅ Submitted! Waiting for admin approval.");

    const rb = $(widget, "[data-record-btn]");
    const sb = $(widget, "[data-stop-btn]");
    const submitBtn = $(widget, "[data-submit-btn]");
    const rerecordBtn = $(widget, "[data-rerecord-btn]");

    if (rb) rb.style.display = "none";
    if (sb) sb.style.display = "none";
    if (submitBtn) submitBtn.style.display = "none";
    if (rerecordBtn) rerecordBtn.style.display = "none";

    widget._recordedBlob = null;
  }

  // Voice search (home)
  window.startVoiceSearch = function () {
    const input = document.getElementById("searchWord");
    if (!input) return alert("Search input not found.");

    const SpeechRecognition = window.SpeechRecognition || window.webkitSpeechRecognition;
    if (!SpeechRecognition) return alert("Voice search not supported. Try Chrome on Android/Desktop.");

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
      console.error(e);
      alert("Voice search failed: " + (e.error || "unknown error"));
    };

    try { recog.start(); } catch (e) { console.error(e); alert("Could not start voice search."); }
  };

  function wire() {
    document.addEventListener("click", async (e) => {
      const recordBtn = e.target.closest("[data-record-btn]");
      const stopBtn = e.target.closest("[data-stop-btn]");
      const submitBtn = e.target.closest("[data-submit-btn]");
      const rerecordBtn = e.target.closest("[data-rerecord-btn]");

      if (recordBtn) {
        const widget = findWidget(recordBtn);
        const info = readInfo(widget, recordBtn);

        // Ensure stop exists + show it
        const sb = ensureStopButton(widget, info, recordBtn);

        // UI
        recordBtn.style.display = "none";
        if (sb) sb.style.display = "inline-block";

        const preview = $(widget, "[data-preview-audio]");
        if (preview) preview.style.display = "none";

        const sbtn = $(widget, "[data-submit-btn]");
        const rbtn = $(widget, "[data-rerecord-btn]");
        if (sbtn) sbtn.style.display = "none";
        if (rbtn) rbtn.style.display = "none";

        setStatus(widget, info.entryId, "🎙 Recording…");

        try {
          await startRecording(widget, recordBtn);
        } catch (err) {
          console.error(err);
          setStatus(widget, info.entryId, "❌ " + (err?.message || "Recording failed"));
          recordBtn.style.display = "inline-block";
          if (sb) sb.style.display = "none";
          requestStop();
        }
        return;
      }

      if (stopBtn) {
        const widget = findWidget(stopBtn);
        const info = readInfo(widget, stopBtn);

        if (active.recorder && active.recorder.state !== "inactive") {
          requestStop("⏹ Stopped.");
        } else {
          setStatus(widget, info.entryId, "⏹ Stopped.");
          resetRowUI(widget);
        }
        return;
      }

      if (rerecordBtn) {
        const widget = findWidget(rerecordBtn);
        const info = readInfo(widget, rerecordBtn);

        widget._recordedBlob = null;
        const preview = $(widget, "[data-preview-audio]");
        if (preview) preview.style.display = "none";

        const sbtn = $(widget, "[data-submit-btn]");
        const rbtn = $(widget, "[data-rerecord-btn]");
        if (sbtn) sbtn.style.display = "none";
        if (rbtn) rbtn.style.display = "none";

        setStatus(widget, info.entryId, "");
        const rb = $(widget, "[data-record-btn]");
        if (rb) rb.click();
        return;
      }

      if (submitBtn) {
        const widget = findWidget(submitBtn);
        await upload(widget, submitBtn);
        return;
      }
    });

    window.addEventListener("beforeunload", () => {
      try { requestStop("⏹ Stopped."); } catch (_) {}
      stopTracks(active.stream);
    });
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", wire);
  } else {
    wire();
  }
})();


