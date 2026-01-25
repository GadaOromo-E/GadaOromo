(() => {
  const root = document;
  const $ = (sel) => root.querySelector(sel);

  const recordBtn = $("[data-record-btn]");
  const stopBtn = $("[data-stop-btn]");
  const submitBtn = $("[data-submit-btn]");
  const preview = $("[data-preview-audio]");
  const statusEl = $("[data-status]");

  let stream = null;
  let recorder = null;
  let chunks = [];
  let blob = null;

  function setStatus(msg) {
    if (statusEl) statusEl.textContent = msg || "";
  }

  function stopTracks() {
    try { stream?.getTracks()?.forEach(t => t.stop()); } catch (_) {}
    stream = null;
  }

  function pickMime() {
    if (!window.MediaRecorder) return "";
    const cands = ["audio/webm;codecs=opus", "audio/webm", "audio/ogg;codecs=opus", "audio/ogg"];
    for (const m of cands) {
      try { if (MediaRecorder.isTypeSupported(m)) return m; } catch (_) {}
    }
    return "";
  }

  async function start() {
    blob = null;
    chunks = [];
    setStatus("Requesting mic…");

    stream = await navigator.mediaDevices.getUserMedia({ audio: true });
    const mime = pickMime();
    recorder = new MediaRecorder(stream, mime ? { mimeType: mime } : undefined);

    recorder.ondataavailable = (e) => {
      if (e.data && e.data.size > 0) chunks.push(e.data);
    };

    recorder.onstart = () => {
      setStatus("Recording…");
      recordBtn.style.display = "none";
      stopBtn.style.display = "inline-block";
      submitBtn.style.display = "none";
      preview.style.display = "none";
    };

    recorder.onstop = () => {
      stopTracks();
      const finalMime = recorder.mimeType || mime || "audio/webm";
      blob = new Blob(chunks, { type: finalMime });

      if (!blob || blob.size === 0) {
        setStatus("No audio captured.");
        recordBtn.style.display = "inline-block";
        stopBtn.style.display = "none";
        return;
      }

      const url = URL.createObjectURL(blob);
      preview.src = url;
      preview.style.display = "block";
      preview.load();

      setStatus("Recorded ✅ click Save");
      recordBtn.style.display = "inline-block";
      stopBtn.style.display = "none";
      submitBtn.style.display = "inline-block";
    };

    recorder.start();
  }

  function stop() {
    try {
      if (recorder && recorder.state === "recording") recorder.stop();
    } catch (_) {}
  }

  async function save() {
    if (!blob) {
      setStatus("No recording to save.");
      return;
    }
    submitBtn.disabled = true;
    setStatus("Uploading…");

    const entryType = recordBtn.dataset.entryType;
    const entryId = recordBtn.dataset.entryId;
    const lang = "oromo";

    const fd = new FormData();
    fd.append("entry_type", entryType);
    fd.append("entry_id", entryId);
    fd.append("lang", lang);
    fd.append("audio", blob, "recording.webm");

    const url = (window.RECORDER_TEST && window.RECORDER_TEST.submit_url) || "/recorder/api/submit-audio";

    let res;
    try {
      res = await fetch(url, {
        method: "POST",
        body: fd,
        credentials: "same-origin",
        cache: "no-store",
      });
    } catch (e) {
      console.error(e);
      setStatus("Network error.");
      submitBtn.disabled = false;
      return;
    }

    const ct = (res.headers.get("content-type") || "").toLowerCase();
    const data = ct.includes("application/json") ? await res.json().catch(() => ({})) : {};

    if (!res.ok || !data.ok) {
      setStatus((data && data.error) ? data.error : ("Save failed: HTTP " + res.status));
      submitBtn.disabled = false;
      return;
    }

    setStatus("Saved ✅ " + (data.url || ""));
    submitBtn.style.display = "none";
    submitBtn.disabled = false;
  }

  recordBtn?.addEventListener("click", () => start().catch(err => {
    console.error(err);
    setStatus("Mic blocked / error.");
  }));
  stopBtn?.addEventListener("click", stop);
  submitBtn?.addEventListener("click", save);
})();
