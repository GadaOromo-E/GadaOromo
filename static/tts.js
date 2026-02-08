// static/tts.js
window.speakEnglish = function(text){
  console.log("speakEnglish:", text);

  if (!("speechSynthesis" in window)) {
    alert("TTS not supported.");
    return;
  }
  if (!text || !text.trim()) {
    alert("No English text.");
    return;
  }

  const u = new SpeechSynthesisUtterance(text);
  u.lang = "en-US";
  speechSynthesis.cancel();
  speechSynthesis.speak(u);
};

window.speakOromo = function(text){
  console.log("speakOromo:", text);

  if (!("speechSynthesis" in window)) {
    alert("TTS not supported.");
    return;
  }
  if (!text || !text.trim()) {
    alert("No Oromo text.");
    return;
  }

  const u = new SpeechSynthesisUtterance(text);
  u.lang = "om-ET";
  speechSynthesis.cancel();
  speechSynthesis.speak(u);
};
