const chatLog = document.querySelector("#chatLog");
const traceLog = document.querySelector("#traceLog");
const form = document.querySelector("#chatForm");
const input = document.querySelector("#messageInput");
const sendBtn = document.querySelector("#sendBtn");
const resetBtn = document.querySelector("#resetBtn");
const serverStatus = document.querySelector("#serverStatus");

function addMessage(role, text, className = "") {
  const item = document.createElement("article");
  item.className = `message ${role} ${className}`.trim();
  const label = document.createElement("span");
  label.className = "message-label";
  label.textContent = role === "user" ? "你" : "Agent";
  const body = document.createElement("div");
  body.textContent = text;
  item.append(label, body);
  chatLog.appendChild(item);
  chatLog.scrollTop = chatLog.scrollHeight;
}

function renderTrace(events) {
  traceLog.textContent = "";
  if (!events || events.length === 0) {
    const empty = document.createElement("div");
    empty.className = "empty";
    empty.textContent = "本轮没有工具调用";
    traceLog.appendChild(empty);
    return;
  }

  for (const event of events) {
    const item = document.createElement("section");
    item.className = "trace-item";

    const title = document.createElement("div");
    title.className = "trace-title";
    const name = document.createElement("span");
    name.textContent = event.tool;
    const badge = document.createElement("span");
    badge.className = `badge ${event.status === "error" ? "error" : ""}`.trim();
    badge.textContent = event.status || "ok";
    title.append(name, badge);

    const pre = document.createElement("pre");
    pre.textContent = JSON.stringify({ arguments: event.arguments, result: event.result }, null, 2);

    item.append(title, pre);
    traceLog.appendChild(item);
  }
}

async function postJson(url, payload = {}) {
  const response = await fetch(url, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  const data = await response.json();
  if (!response.ok) {
    throw new Error(data.error || `HTTP ${response.status}`);
  }
  return data;
}

async function sendMessage(text) {
  addMessage("user", text);
  input.value = "";
  input.focus();
  sendBtn.disabled = true;
  sendBtn.textContent = "处理中";
  try {
    const result = await postJson("/api/chat", { message: text });
    addMessage("agent", result.answer || "(empty response)");
    renderTrace(result.events);
  } catch (error) {
    addMessage("agent", error.message, "error");
  } finally {
    sendBtn.disabled = false;
    sendBtn.textContent = "发送";
  }
}

form.addEventListener("submit", (event) => {
  event.preventDefault();
  const text = input.value.trim();
  if (text) sendMessage(text);
});

input.addEventListener("keydown", (event) => {
  if (event.key === "Enter" && (event.ctrlKey || event.metaKey)) {
    form.requestSubmit();
  }
});

document.querySelectorAll(".quick").forEach((button) => {
  button.addEventListener("click", () => sendMessage(button.dataset.text));
});

resetBtn.addEventListener("click", async () => {
  await postJson("/api/reset");
  chatLog.textContent = "";
  renderTrace([]);
  addMessage("agent", "对话已重置。", "");
});

async function checkHealth() {
  try {
    const response = await fetch("/api/health");
    serverStatus.textContent = response.ok ? "在线" : "异常";
  } catch {
    serverStatus.textContent = "离线";
  }
}

renderTrace([]);
addMessage("agent", "界面已就绪。可以输入 list files、read README.md，或直接描述你的需求。");
checkHealth();