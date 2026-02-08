// static/speak.js
(function () {
  function speakEnglishById(id) {
    const el = document.getElementById(id);
    if (!el) return alert("English text not found.");
    const text = (el.innerText || "").trim();
    if (!text) return alert("Nothing to speak.");

    if (!("speechSynthesis" in window)) {
      alert("Text-to-speech not supported in this browser.");
      return;
    }

    const u = new SpeechSynthesisUtterance(text);
    u.lang = "en-US";
    window.speechSynthesis.cancel();
    window.speechSynthesis.speak(u);
  }

  function playAudioById(id) {
    const audio = document.getElementById(id);
    if (!audio) return alert("No Oromo audio available yet.");
    audio.play().catch(() => alert("Audio play failed (browser blocked autoplay)."));
  }

  // Make global functions usable from onclick=""
  window.speakEnglish = function () {
    speakEnglishById("enText");
  };

  window.playOromo = function () {
    playAudioById("oromoAudio");
  };
})();
