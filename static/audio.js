/* static/audio.js
   Public recording:
   - Records Oromo pronunciation and uploads to POST /api/submit-audio
   - Stores entry info on the widget when recording starts
   - Robust widget detection
   - Keeps your voice search startVoiceSearch()
   - Accessibility cleanup only: live status, labels, hidden state
*/

(function () {
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
      document.body
    );
  }

  function ensureStatusA11y(el) {
    if (!el) return;
    if (!el.hasAttribute("role")) el.setAttribute("role", "status");
    if (!el.hasAttribute("aria-live")) el.setAttribute("aria-live", "polite");
    if (!el.hasAttribute("aria-atomic")) el.setAttribute("aria-atomic", "true");
  }

  function ensureButtonA11y(btn, label) {
    if (!btn) return;
    if (label && !btn.hasAttribute("aria-label")) btn.setAttribute("aria-label", label);
  }

  function ensurePreviewA11y(preview) {
    if (!preview) return;
    if (!preview.hasAttribute("aria-label")) {
      preview.setAttribute("aria-label", "Recorded audio preview");
    }
  }

  function setWidgetInfo(widget, info) {
    if (!widget || !info) return;
    widget._entryInfo = info;
    widget.dataset.entryType = info.entryType || widget.dataset.entryType || "";
    widget.dataset.entryId = info.entryId || widget.dataset.entryId || "";
    widget.dataset.lang = info.lang || widget.dataset.lang || "oromo";
  }

  function readInfo(widget, btn) {
    const fromBtn = {
      entryType: (btn?.dataset.entryType || "").trim().toLowerCase(),
      entryId: (btn?.dataset.entryId || "").trim(),
      lang: (btn?.dataset.lang || "").trim().toLowerCase(),
    };

    const fromWidget = {
      entryType: (widget?.dataset.entryType || "").trim().toLowerCase(),
      entryId: (widget?.dataset.entryId || "").trim(),
      lang: (widget?.dataset.lang || "").trim().toLowerCase(),
    };

    const fromStored = widget?._entryInfo || {};

    const entryType =
      fromBtn.entryType ||
      fromWidget.entryType ||
      (fromStored.entryType || "").trim().toLowerCase();

    const entryId =
      fromBtn.entryId ||
      fromWidget.entryId ||
      String(fromStored.entryId || "").trim();

    const lang =
      fromBtn.lang ||
      fromWidget.lang ||
      (fromStored.lang || "oromo").trim().toLowerCase();

    return { entryType, entryId, lang };
  }

  function setStatus(widget, entryId, msg) {
    const local = $(widget, "[data-status]");
    if (local) {
      ensureStatusA11y(local);
      local.textContent = msg || "";
    }

    if (entryId) {
      const globalEl = document.querySelector(`[data-status-for="${entryId}"]`);
      if (globalEl) {
        ensureStatusA11y(globalEl);
        globalEl.textContent = msg || "";
      }
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
    try {
      stream?.getTracks()?.forEach((t) => t.stop());
    } catch (_) {}
  }

  function resetActive() {
    active.recorder = null;
    active.stream = null;
    active.widget = null;
    active.chunks = [];
    active.entryId = "";
    active.stopping = false;
  }

  function resetRowUI(widget) {
    const rb = $(widget, "[data-record-btn]");
    const sb = $(widget, "[data-stop-btn]");
    const submitBtn = $(widget, "[data-submit-btn]");
    const rerecordBtn = $(widget, "[data-rerecord-btn]");
    const preview = $(widget, "[data-preview-audio]");

    ensureButtonA11y(rb, "Record Oromo pronunciation");
    ensureButtonA11y(sb, "Stop recording Oromo pronunciation");
    ensureButtonA11y(submitBtn, "Submit Oromo recording");
    ensureButtonA11y(rerecordBtn, "Record Oromo pronunciation again");
    ensurePreviewA11y(preview);

    if (rb) rb.style.display = "inline-block";
    if (sb) sb.style.display = "none";
    if (submitBtn) submitBtn.style.display = "none";
    if (rerecordBtn) rerecordBtn.style.display = "none";
    if (preview) {
      preview.style.display = "none";
      preview.hidden = true;
    }

    if (widget) widget.setAttribute("aria-busy", "false");
  }

  function requestStop(reasonText) {
    if (!active.recorder || active.recorder.state === "inactive") {
      stopTracks(active.stream);
      if (active.widget) active.widget.setAttribute("aria-busy", "false");
      resetActive();
      return;
    }
    if (active.stopping) return;
    active.stopping = true;

    if (active.widget) {
      active.widget.setAttribute("aria-busy", "true");
      setStatus(active.widget, active.entryId, reasonText || "⏹ Stopping…");
    }

    try {
      active.recorder.stop();
    } catch (_) {
      stopTracks(active.stream);
      if (active.widget) active.widget.setAttribute("aria-busy", "false");
      resetActive();
    }
  }

  async function startRecording(widget, recordBtn) {
    if (!navigator.mediaDevices?.getUserMedia) throw new Error("Microphone not supported in this browser.");
    if (!window.MediaRecorder) throw new Error("Recording not supported in this browser.");

    const info = readInfo(widget, recordBtn);

    if (!info.entryType || !info.entryId) {
      throw new Error("Missing entry info (entry_type/entry_id).");
    }
    if ((info.lang || "oromo") !== "oromo") {
      throw new Error("Only Oromo audio is allowed.");
    }

    setWidgetInfo(widget, info);

    if (active.recorder && active.recorder.state !== "inactive") {
      requestStop("⏹ Stopped (new recording started).");
      await new Promise((r) => setTimeout(r, 250));
    }

    const stopBtn = $(widget, "[data-stop-btn]");
    if (stopBtn) stopBtn.style.display = "inline-block";

    const { mime, ext } = pickMime();
    widget.dataset.ext = ext;
    widget.setAttribute("aria-busy", "true");

    const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
    const recorder = new MediaRecorder(stream, mime ? { mimeType: mime } : undefined);

    active.recorder = recorder;
    active.stream = stream;
    active.widget = widget;
    active.chunks = [];
    active.entryId = info.entryId;
    active.stopping = false;

    recorder.ondataavailable = (e) => {
      if (e.data && e.data.size > 0) active.chunks.push(e.data);
    };

    recorder.onerror = () => {
      setStatus(widget, info.entryId, "❌ Recorder error.");
      stopTracks(stream);
      widget.setAttribute("aria-busy", "false");
      resetRowUI(widget);
      resetActive();
    };

    recorder.onstop = () => {
      const chunks = active.chunks.slice();
      const ext2 = widget.dataset.ext || "webm";
      const mime2 = recorder.mimeType || (ext2 === "ogg" ? "audio/ogg" : "audio/webm");

      stopTracks(stream);

      const blob = new Blob(chunks, { type: mime2 });
      if (!blob || blob.size === 0) {
        setStatus(widget, info.entryId, "⚠️ No audio captured. Try again.");
        widget.setAttribute("aria-busy", "false");
        resetRowUI(widget);
        resetActive();
        return;
      }

      widget._recordedBlob = blob;

      const preview = $(widget, "[data-preview-audio]");
      if (preview) {
        ensurePreviewA11y(preview);
        const url = URL.createObjectURL(blob);
        preview.src = url;
        preview.style.display = "block";
        preview.hidden = false;
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
      widget.setAttribute("aria-busy", "false");
      resetActive();
    };

    recorder.start();
  }

  async function safeJson(res) {
    const ct = (res.headers.get("content-type") || "").toLowerCase();
    if (!ct.includes("application/json")) {
      await res.text().catch(() => "");
      return { ok: false, error: "Server returned non-JSON response." };
    }
    return await res.json().catch(() => ({ ok: false, error: "Invalid JSON response." }));
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

    const blob = widget._recordedBlob;
    if (!blob) {
      setStatus(widget, info.entryId, "❌ No recording found.");
      return;
    }

    widget.setAttribute("aria-busy", "true");
    setStatus(widget, info.entryId, "⏳ Uploading…");

    const fd = new FormData();
    fd.append("entry_type", info.entryType);
    fd.append("entry_id", info.entryId);
    fd.append("lang", "oromo");

    const ext = widget.dataset.ext || "webm";
    fd.append("audio", blob, `recording.${ext}`);

    const headers = {};
    if (CSRF_TOKEN) headers["X-CSRFToken"] = CSRF_TOKEN;

    let res;
    try {
      res = await fetch("/api/submit-audio", {
        method: "POST",
        body: fd,
        credentials: "same-origin",
        cache: "no-store",
        headers,
      });
    } catch (e) {
      console.error(e);
      widget.setAttribute("aria-busy", "false");
      setStatus(widget, info.entryId, "❌ Network error uploading audio.");
      return;
    }

    if (looksLikeLoginRedirect(res)) {
      widget.setAttribute("aria-busy", "false");
      setStatus(widget, info.entryId, "⚠️ Not authorized / session expired. Please log in and try again.");
      return;
    }

    const data = await safeJson(res);

    if (!res.ok || !data?.ok) {
      const msg = data?.error || `Upload failed (HTTP ${res.status})`;
      widget.setAttribute("aria-busy", "false");
      setStatus(widget, info.entryId, "❌ " + msg);
      return;
    }

    widget.setAttribute("aria-busy", "false");
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

  function findVoiceInputTarget() {
    return (
      document.getElementById("dictionaryQuery") ||
      document.getElementById("textInput") ||
      document.getElementById("searchWord")
    );
  }

  function findSpeechLangForInput(inputEl) {
    if (!inputEl) return "en-US";
    const srcSelect = document.getElementById("sourceLangSelect");
    if (srcSelect && srcSelect.options && srcSelect.selectedIndex >= 0) {
      const opt = srcSelect.options[srcSelect.selectedIndex];
      const speech = (opt && (opt.getAttribute("data-speech-lang") || "")).trim();
      if (speech) return speech;
    }
    return "en-US";
  }

  window.startVoiceSearch = function () {
    const input = findVoiceInputTarget();
    if (!input) {
      console.error("startVoiceSearch selector mismatch: no input target found (#dictionaryQuery, #textInput, #searchWord).");
      alert("Voice input is temporarily unavailable on this page.");
      return;
    }

    const SpeechRecognition = window.SpeechRecognition || window.webkitSpeechRecognition;
    if (!SpeechRecognition) return alert("Voice input is not supported in this browser. Try Chrome.");

    const recog = new SpeechRecognition();
    recog.lang = findSpeechLangForInput(input);
    recog.interimResults = false;
    recog.maxAlternatives = 1;

    recog.onresult = (e) => {
      const text = e?.results?.[0]?.[0]?.transcript || "";
      if (text) input.value = text.trim();
      input.focus();
    };

    recog.onerror = (e) => {
      const err = (e && e.error) ? String(e.error) : "unknown";

      if (err === "aborted") return;
      if (err === "no-speech") {
        console.log("Voice input: no speech detected.");
        return;
      }
      if (err === "network") {
        console.log("Voice input: transient network issue.");
        return;
      }
      if (err === "audio-capture") {
        alert("No microphone detected.");
        return;
      }
      if (err === "not-allowed" || err === "service-not-allowed") {
        alert("Please allow microphone access.");
        return;
      }

      console.error("Speech recognition error:", err, e);
    };

    try {
      recog.start();
    } catch (e) {
      console.error(e);
      alert("Could not start voice search.");
    }
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

        setWidgetInfo(widget, info);

        const rb = $(widget, "[data-record-btn]");
        const sb = $(widget, "[data-stop-btn]");
        const preview = $(widget, "[data-preview-audio]");
        const sbtn = $(widget, "[data-submit-btn]");
        const rbtn = $(widget, "[data-rerecord-btn]");

        ensureButtonA11y(rb, "Record Oromo pronunciation");
        ensureButtonA11y(sb, "Stop recording Oromo pronunciation");
        ensureButtonA11y(sbtn, "Submit Oromo recording");
        ensureButtonA11y(rbtn, "Record Oromo pronunciation again");
        ensurePreviewA11y(preview);

        recordBtn.style.display = "none";
        if (sb) sb.style.display = "inline-block";

        if (preview) {
          preview.style.display = "none";
          preview.hidden = true;
        }

        if (sbtn) sbtn.style.display = "none";
        if (rbtn) rbtn.style.display = "none";

        setStatus(widget, info.entryId, "🎙 Recording…");

        try {
          await startRecording(widget, recordBtn);
        } catch (err) {
          console.error(err);
          setStatus(widget, info.entryId, "❌ " + (err?.message || "Recording failed"));
          if (rb) rb.style.display = "inline-block";
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
        if (preview) {
          preview.style.display = "none";
          preview.hidden = true;
        }

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
      }
    });

    window.addEventListener("beforeunload", () => {
      try {
        requestStop("⏹ Stopped.");
      } catch (_) {}
      stopTracks(active.stream);
    });
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", wire);
  } else {
    wire();
  }
})();