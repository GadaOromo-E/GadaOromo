(function(){
  const log = document.getElementById("aiLog");
  const input = document.getElementById("aiInput");
  const sendBtn = document.getElementById("aiSend");
  const statusEl = document.getElementById("aiStatus");

  function appendLine(who, text){
    const prefix = who === "me" ? "🧑‍🎓 You: " : "🤖 Gadaa AI: ";
    log.textContent += prefix + text + "\n\n";
    log.scrollTop = log.scrollHeight;
  }

  function setStatus(t){ if(statusEl) statusEl.textContent = t || ""; }

  async function sendMessage(msg){
    const m = (msg || "").trim();
    if(!m) return;

    appendLine("me", m);
    setStatus("Thinking…");

    try{
      const res = await fetch("/api/gadaa-ai", {
        method: "POST",
        headers: {"Content-Type":"application/json"},
        body: JSON.stringify({message: m})
      });

      const data = await res.json().catch(()=> ({}));
      if(!res.ok || !data.ok){
        const err = data.error || ("Error " + res.status);
        appendLine("ai", err);
        setStatus("");
        return;
      }

      const reply = data.reply || {};
      if(reply.type === "card" && reply.card){
        const c = reply.card;
        appendLine("ai", `${c.title}\nEN: ${c.english}\nOM: ${c.oromo}`);

        if(Array.isArray(c.examples)){
          appendLine("ai", "Examples:\n- " + c.examples.join("\n- "));
        }
        if(Array.isArray(c.quiz)){
          appendLine("ai", c.quiz.join("\n"));
        }

        if(c.audio && c.audio.oromo){
          appendLine("ai", "🎧 Oromo audio is available on the word page (search it on Home/Translate).");
        }
      }else{
        appendLine("ai", reply.text || "(no reply)");
      }

      setStatus("");
    }catch(e){
      console.error(e);
      appendLine("ai", "Network error. Please try again.");
      setStatus("");
    }
  }

  function wire(){
    sendBtn?.addEventListener("click", ()=> sendMessage(input.value));
    input?.addEventListener("keydown", (e)=>{
      if(e.key === "Enter"){
        e.preventDefault();
        sendBtn.click();
      }
    });

    document.querySelectorAll("[data-pick]").forEach(chip=>{
      chip.addEventListener("click", ()=>{
        const v = chip.getAttribute("data-pick");
        if(v) sendMessage(v);
      });
    });

    appendLine("ai", "Hi! I’m Gadaa AI (free demo). Type a word/phrase, or try: quiz me");
  }

  document.addEventListener("DOMContentLoaded", wire);
})();
