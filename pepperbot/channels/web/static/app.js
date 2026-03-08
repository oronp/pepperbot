// pepperbot web UI — plain JS, no framework
(function () {
  "use strict";

  function showSection(id) {
    document.querySelectorAll(".section").forEach((s) => s.classList.remove("active"));
    document.querySelectorAll("nav a[data-section]").forEach((a) => a.classList.remove("active"));
    const section = document.getElementById(id);
    if (section) section.classList.add("active");
    const link = document.querySelector(`nav a[data-section="${id}"]`);
    if (link) link.classList.add("active");
    if (id === "usage") loadUsage();
    if (id === "profile") loadProfile();
    if (id === "settings") loadSettings();
  }

  document.querySelectorAll("nav a[data-section]").forEach((a) => {
    a.addEventListener("click", (e) => {
      e.preventDefault();
      showSection(a.dataset.section);
    });
  });

  let ws = null;
  let streamingEl = null;

  function connectWS() {
    const proto = location.protocol === "https:" ? "wss" : "ws";
    ws = new WebSocket(`${proto}://${location.host}/ws`);

    ws.onmessage = (event) => {
      const data = JSON.parse(event.data);
      if (data.type === "chunk") {
        if (!streamingEl) {
          streamingEl = appendMessage("", "bot streaming");
        }
        streamingEl.textContent += data.content;
        scrollToBottom();
      } else if (data.type === "message") {
        if (streamingEl) {
          streamingEl.textContent = data.content;
          streamingEl.classList.remove("streaming");
          streamingEl = null;
        } else {
          appendMessage(data.content, "bot");
        }
        scrollToBottom();
      } else if (data.type === "done") {
        if (streamingEl) {
          streamingEl.classList.remove("streaming");
          streamingEl = null;
        }
        setSendEnabled(true);
      }
    };

    ws.onclose = () => { setTimeout(connectWS, 2000); };
  }

  function appendMessage(text, cls) {
    const el = document.createElement("div");
    el.className = `msg ${cls}`;
    el.textContent = text;
    document.getElementById("messages").appendChild(el);
    scrollToBottom();
    return el;
  }

  function scrollToBottom() {
    const msgs = document.getElementById("messages");
    msgs.scrollTop = msgs.scrollHeight;
  }

  function setSendEnabled(enabled) {
    document.getElementById("send-btn").disabled = !enabled;
    document.getElementById("chat-input").disabled = !enabled;
  }

  document.getElementById("send-btn").addEventListener("click", sendMessage);
  document.getElementById("chat-input").addEventListener("keydown", (e) => {
    if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); sendMessage(); }
  });

  function sendMessage() {
    const input = document.getElementById("chat-input");
    const text = input.value.trim();
    if (!text || !ws || ws.readyState !== WebSocket.OPEN) return;
    appendMessage(text, "user");
    ws.send(JSON.stringify({ type: "message", content: text }));
    input.value = "";
    setSendEnabled(false);
  }

  async function loadUsage() {
    const resp = await fetch("/api/usage");
    const data = await resp.json();
    const tbody = document.querySelector("#usage-table tbody");
    tbody.innerHTML = "";
    if (data.length === 0) {
      tbody.innerHTML = '<tr><td colspan="5" style="text-align:center;color:#999">No usage data yet.</td></tr>';
      return;
    }
    data.forEach((row) => {
      const tr = document.createElement("tr");
      tr.innerHTML = `<td>${row.provider}</td><td>${row.model}</td><td>${row.input_tokens.toLocaleString()}</td><td>${row.output_tokens.toLocaleString()}</td><td>${row.requests}</td>`;
      tbody.appendChild(tr);
    });
  }

  async function loadProfile() {
    const resp = await fetch("/api/profile");
    const data = await resp.json();
    document.getElementById("soul-editor").value = data.content || "";
  }

  document.getElementById("save-profile-btn").addEventListener("click", async () => {
    const content = document.getElementById("soul-editor").value;
    const resp = await fetch("/api/profile", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ content }),
    });
    const statusEl = document.getElementById("profile-status");
    statusEl.textContent = resp.ok ? "Saved." : "Error saving.";
    statusEl.className = resp.ok ? "status" : "status err";
    setTimeout(() => (statusEl.textContent = ""), 2000);
  });

  async function loadSettings() {
    const resp = await fetch("/api/settings");
    const data = await resp.json();
    document.getElementById("settings-json").value = JSON.stringify(data, null, 2);
  }

  document.getElementById("save-settings-btn").addEventListener("click", async () => {
    const raw = document.getElementById("settings-json").value;
    let body;
    try { body = JSON.parse(raw); } catch {
      const el = document.getElementById("settings-status");
      el.textContent = "Invalid JSON.";
      el.className = "status err";
      return;
    }
    const resp = await fetch("/api/settings", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
    const statusEl = document.getElementById("settings-status");
    const data = await resp.json();
    statusEl.textContent = resp.ok ? "Saved." : `Error: ${data.error || "unknown"}`;
    statusEl.className = resp.ok ? "status" : "status err";
    setTimeout(() => (statusEl.textContent = ""), 3000);
  });

  connectWS();
  showSection("chat");
})();
