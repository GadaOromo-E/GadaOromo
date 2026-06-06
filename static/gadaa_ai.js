(function () {
  "use strict";

  const log      = document.getElementById("aiLog");
  const input    = document.getElementById("aiInput");
  const sendBtn  = document.getElementById("aiSend");

  let currentSession = {};

  // ── Markdown-lite renderer ──────────────────────────────────────────────────
  function mdToHtml(text) {
    return (text || "")
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/\*\*(.+?)\*\*/g, "<strong>$1</strong>")
      .replace(/\*(.+?)\*/g, "<em>$1</em>")
      .replace(/\n/g, "<br>");
  }

  // ── Add a chat bubble ───────────────────────────────────────────────────────
  function addBubble(who, html, audioUrl) {
    const row = document.createElement("div");
    row.className = "ai-bubble-row " + who;

    const avatar = document.createElement("div");
    avatar.className = "ai-avatar";
    avatar.textContent = who === "me" ? "🧑" : "🤖";

    const bubble = document.createElement("div");
    bubble.className = "ai-bubble";
    bubble.innerHTML = html;

    if (who === "ai" && audioUrl) {
      const btn = document.createElement("button");
      btn.className = "ai-play-btn";
      btn.title = "Play audio";
      btn.textContent = "🔊";
      const url = audioUrl;
      btn.onclick = function () {
        try { new Audio(url).play(); } catch (e) { /* ignore */ }
      };
      bubble.appendChild(btn);
    }

    row.appendChild(avatar);
    row.appendChild(bubble);
    log.appendChild(row);
    log.scrollTop = log.scrollHeight;
  }

  // ── Typing indicator ────────────────────────────────────────────────────────
  function showTyping() {
    const row = document.createElement("div");
    row.className = "ai-bubble-row ai";
    row.id = "aiTypingRow";

    const avatar = document.createElement("div");
    avatar.className = "ai-avatar";
    avatar.textContent = "🤖";

    const typing = document.createElement("div");
    typing.className = "ai-typing";
    for (var i = 0; i < 3; i++) {
      const dot = document.createElement("div");
      dot.className = "ai-dot";
      typing.appendChild(dot);
    }

    row.appendChild(avatar);
    row.appendChild(typing);
    log.appendChild(row);
    log.scrollTop = log.scrollHeight;
  }

  function removeTyping() {
    const el = document.getElementById("aiTypingRow");
    if (el) el.remove();
  }

  // ── Send a message ──────────────────────────────────────────────────────────
  async function sendMessage(msg) {
    const m = (msg || "").trim();
    if (!m) return;

    input.value = "";
    sendBtn.disabled = true;
    addBubble("me", mdToHtml(m), null);
    showTyping();

    try {
      const res = await fetch("/api/gadaa-ai", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ message: m, session: currentSession }),
      });

      const data = await res.json().catch(function () { return {}; });
      removeTyping();

      if (!res.ok || !data.ok) {
        addBubble("ai", data.error || "Error " + res.status, null);
        return;
      }

      currentSession = data.session || {};
      addBubble("ai", mdToHtml(data.reply || "(no reply)"), data.audio_url || null);
    } catch (e) {
      removeTyping();
      addBubble("ai", "Network error. Please try again.", null);
    } finally {
      sendBtn.disabled = false;
      input.focus();
    }
  }

  // ── Wire up UI ──────────────────────────────────────────────────────────────
  function wire() {
    if (sendBtn) {
      sendBtn.addEventListener("click", function () { sendMessage(input.value); });
    }
    if (input) {
      input.addEventListener("keydown", function (e) {
        if (e.key === "Enter") { e.preventDefault(); sendMessage(input.value); }
      });
    }

    // Welcome message
    addBubble("ai", "Nagaa! 👋 Type a word or sentence in Oromo or English.", null);

    if (input) input.focus();
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", wire);
  } else {
    wire();
  }
})();
