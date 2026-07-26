/*
 * WattWise -- Wattson chat widget, shared by index.html and results.html.
 * Expects these elements to exist in the DOM: #chat-log, #chat-input, #chat-send.
 * Optionally reads window.WATTSON_BOT_NAME (falls back to "Wattson") and
 * window.WATTSON_GREETING for the first message shown.
 */

(function () {
  const chatLog = document.getElementById("chat-log");
  const chatInput = document.getElementById("chat-input");
  const chatSend = document.getElementById("chat-send");
  if (!chatLog || !chatInput || !chatSend) return; // widget not present on this page

  const BOT_NAME = window.WATTSON_BOT_NAME || "Wattson";

  function addMessage(text, sender) {
    const div = document.createElement("div");
    div.className = "chat-msg " + (sender === "user" ? "user" : "bot");
    div.textContent = text;
    chatLog.appendChild(div);
    chatLog.scrollTop = chatLog.scrollHeight;
    return div;
  }

  function showTyping() {
    const div = document.createElement("div");
    div.className = "chat-msg bot typing-indicator";
    div.innerHTML = '<span class="typing-dots"><span></span><span></span><span></span></span>';
    chatLog.appendChild(div);
    chatLog.scrollTop = chatLog.scrollHeight;
    return div;
  }

  async function sendMessage(prefilled) {
    const message = (prefilled !== undefined ? prefilled : chatInput.value).trim();
    if (!message) return;

    addMessage(message, "user");
    chatInput.value = "";
    chatSend.disabled = true;

    const typingEl = showTyping();

    try {
      const res = await fetch("/chat", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ message: message }),
      });
      const data = await res.json();
      typingEl.remove();
      addMessage(data.reply, "assistant");
    } catch (err) {
      typingEl.remove();
      addMessage("Something went wrong reaching the server.", "assistant");
    } finally {
      chatSend.disabled = false;
      chatInput.focus();
    }
  }

  chatSend.addEventListener("click", function () { sendMessage(); });
  chatInput.addEventListener("keydown", function (e) {
    if (e.key === "Enter") sendMessage();
  });

  // Suggestion chips: <div class="chip" data-q="...">
  document.querySelectorAll(".chip[data-q]").forEach(function (chip) {
    chip.addEventListener("click", function () {
      sendMessage(chip.getAttribute("data-q"));
    });
  });

  if (window.WATTSON_GREETING && chatLog.children.length === 0) {
    addMessage(window.WATTSON_GREETING, "assistant");
  }
})();
