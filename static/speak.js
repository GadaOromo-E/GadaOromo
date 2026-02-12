// static/speak.js
(function () {
  function loadVoices() {
    return window.speechSynthesis ? window.speechSynthesis.getVoices() : [];
  }

  function pickVoice(voices, lang) {
    if (!voices || voices.length === 0) return null;
    const want = (lang || "").toLowerCase();

    // exact match
    let v = voices.find(x => (x.lang || "").toLowerCase() === want);
    if (v) return v;

    // match base, e.g. "en" for "en-US"
    const base = want.split("-")[0];
    v = voices.find(x => (x.lang || "").toLowerCase().startsWith(base));
    return v || null;
  }

  function speakText(text, lang) {
    if (!("speechSynthesis" in window)) {
      alert("Text-to-speech is not supported in this browser.");
      return;
    }
    const t = (text || "").trim();
    if (!t) return;

    const u = new SpeechSynthesisUtterance(t);
    const voices = loadVoices();
    const best = pickVoice(voices, lang);
    if (best) {
      u.voice = best;
      u.lang = best.lang;
    } else {
      u.lang = lang;
    }

    window.speechSynthesis.cancel();
    window.speechSynthesis.speak(u);
  }

  // These are the functions your HTML buttons call:
  window.speakEnglish = function (text) {
    speakText(text, "en-US");
  };

  // Oromo TTS usually not available, but keep it (will use any available voice)
  window.speakOromo = function (text) {
    speakText(text, "om-ET");
  };

  // Ensure voices load on Chrome
  if ("speechSynthesis" in window) {
    window.speechSynthesis.onvoiceschanged = function () {
      loadVoices();
    };
  }
})();
