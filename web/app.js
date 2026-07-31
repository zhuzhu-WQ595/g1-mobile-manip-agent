const chatLog = document.querySelector("#chatLog");
const traceLog = document.querySelector("#traceLog");
const form = document.querySelector("#chatForm");
const input = document.querySelector("#messageInput");
const sendBtn = document.querySelector("#sendBtn");
const resetBtn = document.querySelector("#resetBtn");
const serverStatus = document.querySelector("#serverStatus");
const traceCount = document.querySelector("#traceCount");

let traceTurn = 0;
let totalToolCalls = 0;
let isSending = false;

const starterPrompts = [
  { label: "查看工作区摘要", text: "get workspace summary" },
  { label: "查看计划状态", text: "plans" },
  { label: "统计 Python 文件", text: "count python files" },
  { label: "预览 README", text: "show first 5 lines of README.md" },
];

function addMessage(role, text, className = "") {
  const item = document.createElement("article");
  item.className = `message ${role} ${className}`.trim();

  const label = document.createElement("span");
  label.className = "message-label";
  label.textContent = role === "user" ? "You" : "Agent";

  const body = document.createElement("div");
  body.textContent = text;

  item.append(label, body);
  chatLog.appendChild(item);
  chatLog.scrollTop = chatLog.scrollHeight;
}

function renderStarter() {
  const starter = document.createElement("section");
  starter.className = "starter";
  starter.innerHTML = `
    <div class="starter-title">可以先验证一个 Agent 能力</div>
    <p class="starter-text">选择一个示例，观察模型是否调用正确工具、参数是否正确、结果是否写回。</p>
  `;

  const actions = document.createElement("div");
  actions.className = "starter-actions";
  for (const prompt of starterPrompts) {
    const button = document.createElement("button");
    button.className = "starter-action";
    button.type = "button";
    button.textContent = prompt.label;
    button.dataset.text = prompt.text;
    actions.appendChild(button);
  }
  starter.appendChild(actions);
  chatLog.appendChild(starter);
}

function updateSendState() {
  sendBtn.disabled = isSending || input.value.trim().length === 0;
}

function formatValue(value) {
  if (value == null || value === "") return "(empty)";
  if (typeof value === "string") return value;
  return JSON.stringify(value, null, 2);
}

function createTraceSection(labelText, value) {
  const section = document.createElement("div");
  section.className = "trace-section";

  const label = document.createElement("div");
  label.className = "trace-section-label";
  label.textContent = labelText;

  const pre = document.createElement("pre");
  pre.textContent = formatValue(value);

  section.append(label, pre);
  return section;
}

function renderTrace(events = []) {
  traceTurn += 1;
  totalToolCalls += events.length;
  traceCount.textContent = `${totalToolCalls} 次`;
  traceLog.querySelector(".empty")?.remove();

  const turn = document.createElement("section");
  turn.className = "trace-turn";

  const heading = document.createElement("div");
  heading.className = "trace-turn-title";
  heading.textContent = `第 ${traceTurn} 轮 · ${events.length} 个工具`;
  turn.appendChild(heading);

  if (events.length === 0) {
    const empty = document.createElement("div");
    empty.className = "trace-turn-empty";
    empty.textContent = "本轮没有工具调用";
    turn.appendChild(empty);
    traceLog.prepend(turn);
    return;
  }

  for (const event of events) {
    const item = document.createElement("section");
    item.className = "trace-item";

    const title = document.createElement("div");
    title.className = "trace-title";

    const name = document.createElement("span");
    const resource = event.resource_id ? ` · ${event.resource_id}` : "";
    name.textContent = `${event.tool || "unknown_tool"}${resource}`;

    const badge = document.createElement("span");
    const failedStatuses = new Set(["failed", "cancelled", "timed_out", "error"]);
    badge.className = `badge ${failedStatuses.has(event.status) ? "error" : ""}`.trim();
    badge.textContent = event.status || "unknown";

    title.append(name, badge);
    item.append(
      title,
      createTraceSection("参数", event.arguments || {}),
      createTraceSection("结果", event.result || ""),
    );
    turn.appendChild(item);
  }

  traceLog.prepend(turn);
}

function resetTrace() {
  traceTurn = 0;
  totalToolCalls = 0;
  traceCount.textContent = "0 次";
  traceLog.textContent = "";

  const empty = document.createElement("div");
  empty.className = "empty";
  empty.textContent = "暂无工具调用";
  traceLog.appendChild(empty);
}

function setStatus(text, state) {
  serverStatus.textContent = text;
  serverStatus.className = `status-pill ${state || ""}`.trim();
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
  if (isSending) return;
  addMessage("user", text);
  input.value = "";
  input.focus();
  isSending = true;
  updateSendState();
  sendBtn.textContent = "处理中";

  try {
    const result = await postJson("/api/chat", { message: text });
    addMessage("agent", result.answer || "(empty response)");
    renderTrace(result.events || []);
  } catch (error) {
    addMessage("agent", error.message, "error");
    renderTrace([]);
  } finally {
    isSending = false;
    sendBtn.textContent = "发送";
    updateSendState();
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

input.addEventListener("input", updateSendState);

document.querySelectorAll(".quick").forEach((button) => {
  button.addEventListener("click", () => sendMessage(button.dataset.text));
});

chatLog.addEventListener("click", (event) => {
  const button = event.target.closest(".starter-action");
  if (!button) return;
  sendMessage(button.dataset.text);
});

resetBtn.addEventListener("click", async () => {
  try {
    await postJson("/api/reset");
    chatLog.textContent = "";
    resetTrace();
    addMessage("agent", "对话已重置。可以继续验证工具调用、计划执行或结果写回。");
    renderStarter();
  } catch (error) {
    addMessage("agent", error.message, "error");
  }
});

async function checkHealth() {
  try {
    const response = await fetch("/api/health");
    setStatus(response.ok ? "在线" : "异常", response.ok ? "online" : "offline");
  } catch {
    setStatus("离线", "offline");
  }
}

resetTrace();
addMessage("agent", "界面已就绪。你可以输入自然语言指令，也可以用左侧快捷指令验证 Agent 的工具调用链路。");
renderStarter();
updateSendState();
checkHealth();
