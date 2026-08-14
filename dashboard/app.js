const state = {
  route: "home",
  workflows: [],
  selectedWorkflow: null,
  plan: null,
  sessions: [],
  runId: null,
  runSocket: null,
  terminalSocket: null,
  terminalCwd: "",
};

const app = document.getElementById("app");
const pageTitle = document.getElementById("page-title");
const connectionLabel = document.getElementById("connection-label");

const escapeHtml = (value) => String(value ?? "").replace(/[&<>\"]/g, (char) => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;"}[char]));
const workflowColors = {"inspect-project":"#a9e86e","create-project":"#a98cff","dockerize-project":"#6dbbff",kubernetes:"#ffad66",cicd:"#a9e86e",documentation:"#c8a1ff","debug-error":"#f17c83","ai-chat":"#6dbbff"};

async function api(path, options = {}) {
  const response = await fetch(path, { headers: { "Content-Type": "application/json" }, ...options });
  const data = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(data.detail || "Local API request failed");
  return data;
}

function showToast(message) {
  const toast = document.getElementById("toast");
  toast.textContent = message;
  toast.classList.add("show");
  window.clearTimeout(showToast.timer);
  showToast.timer = window.setTimeout(() => toast.classList.remove("show"), 2800);
}

function setRoute(route) {
  state.route = route;
  state.plan = null;
  state.selectedWorkflow = null;
  state.runId = null;
  if (state.runSocket) state.runSocket.close();
  state.runSocket = null;
  render();
}

function workflowCard(workflow) {
  const color = workflowColors[workflow.id] || "#a9e86e";
  return `<button class="workflow-card" style="--card-accent:${color}" data-workflow="${workflow.id}">
    <span class="workflow-card-top"><span class="card-icon">${workflow.icon}</span><span class="card-arrow">↗</span></span>
    <span class="card-eyebrow">${workflow.eyebrow}</span>
    <strong>${workflow.label}</strong>
    <p>${workflow.description}</p>
  </button>`;
}

function homeView() {
  const cards = state.workflows.length ? state.workflows.map(workflowCard).join("") : "<div class=\"panel panel-pad\">Loading workflows…</div>";
  return `<div class="home-grid">
    <section class="hero">
      <div class="eyebrow">Local engineering, thoughtfully orchestrated</div>
      <h1>Hello Sohail <span>👋</span></h1>
      <p class="hero-subtitle">What would you like to do today?</p>
      <form class="prompt-box" id="prompt-form"><span class="prompt-icon">✦</span><input id="prompt-input" placeholder="Ask Sohail Studio anything…" autocomplete="off" /><button class="prompt-action" aria-label="Start">↗</button></form>
      <div class="section-heading"><h2>Start with a workflow</h2><span class="hint">Plan first · approve second</span></div>
      <div class="workflow-grid">${cards}</div>
    </section>
    <aside class="activity-panel">
      <h2>Recent activity</h2>
      <p>Your local engineering memory</p>
      ${state.sessions.length ? sessionRows(state.sessions.slice(0, 3)) : `<div class="activity-empty"><div class="empty-orbit">◷</div><strong>Your workspace is ready</strong><span>Approved runs and project memory will appear here.</span></div>`}
      <div class="side-note"><strong>Visible by design</strong><p>Every command is shown with its purpose before real output streams into the workspace.</p></div>
    </aside>
  </div>`;
}

function workflowsView() {
  return `<div class="page-intro"><div class="eyebrow">Engineering workflows</div><h1>Choose a direction</h1><p>Each workflow starts with a focused plan and waits for your approval.</p></div><div class="workflow-grid">${state.workflows.map(workflowCard).join("")}</div>`;
}

function planView() {
  const workflow = state.selectedWorkflow;
  if (!workflow) return workflowsView();
  const isPlaceholder = !workflow.cli_backed;
  return `<button class="back-button" data-route="${state.route === "plan" ? "workflows" : "home"}">← Back to workflows</button>
    <div class="page-intro"><div class="eyebrow">${workflow.eyebrow}</div><h1>${workflow.label}</h1><p>${workflow.description}</p></div>
    ${isPlaceholder ? `<div class="panel placeholder-panel"><div class="empty-orbit">✦</div><h2>Foundation placeholder</h2><p>This workflow is wired into the Studio navigation and approval model. Its agent implementation will arrive in a future iteration.</p><button class="secondary-button" data-route="home">Return home</button></div>` : `<div class="plan-layout">
      <section class="panel panel-pad"><h2 class="panel-title">First, choose a local project folder</h2><form id="plan-form"><label class="field-label" for="target-input">Project path</label><input class="field-input" id="target-input" placeholder="/Users/sohal/Projects/my-app" value="${escapeHtml(state.plan?.target || "")}" required /><div class="approval-callout"><b>Read the plan before running.</b> Sohail Studio will call the existing Sohail-Agent-CLI only after you approve the steps on the right.</div><div class="button-row"><button class="primary-button" type="submit">Create plan →</button></div></form></section>
      <aside class="panel panel-pad"><h2 class="panel-title">How this works</h2><div class="plan-list"><div class="plan-step"><span class="step-number">1</span><span>Give the assistant one focused context.</span></div><div class="plan-step"><span class="step-number">2</span><span>Review the exact intended actions.</span></div><div class="plan-step"><span class="step-number">3</span><span>Approve before any process starts.</span></div></div></aside>
    </div>`}`;
}

function approvedPlanView() {
  const workflow = state.selectedWorkflow;
  const plan = state.plan;
  return `<button class="back-button" data-route="workflows">← Change workflow</button><div class="page-intro"><div class="eyebrow">Review required</div><h1>Your execution plan</h1><p>Nothing has run yet. Confirm the scope, then start the approved command.</p></div>
    <div class="plan-layout"><section class="panel panel-pad"><h2 class="panel-title">${workflow.label}</h2><div class="plan-list">${plan.steps.map((step, index) => `<div class="plan-step"><span class="step-number">${index + 1}</span><span>${step}</span></div>`).join("")}</div><div class="button-row"><button class="secondary-button" data-route="workflows">Edit</button><button class="primary-button" id="approve-run">Approve & run →</button></div></section><aside class="panel panel-pad"><h2 class="panel-title">Scope</h2><div class="info-list"><div class="info-row"><span>Target</span><strong>${escapeHtml(plan.target)}</strong></div><div class="info-row"><span>Engine</span><strong>Sohail-Agent-CLI</strong></div><div class="info-row"><span>Mode</span><strong>Local only</strong></div><div class="info-row"><span>Approval</span><strong>Required</strong></div></div></aside></div>`;
}

function runView() {
  const workflow = state.selectedWorkflow;
  return `<div class="page-intro"><div class="eyebrow">Live execution</div><h1>${workflow?.label || "Workflow run"}</h1><p>Watch the real CLI process as it runs. Output is never simulated.</p></div><div class="run-layout"><section class="panel console-panel"><div class="console-head"><strong>Execution stream</strong><span class="console-status"><span class="status-dot"></span><span id="run-status">Connecting…</span></span></div><div class="console-output" id="console-output"><span class="console-command">Waiting for the local process…</span></div></section><div class="button-row"><button class="secondary-button" data-route="terminal">Open terminal</button><button class="secondary-button" data-route="home">Back to home</button></div></div>`;
}

function terminalView() {
  return `<div class="page-intro"><div class="eyebrow">Execution engine</div><h1>Terminal</h1><p>A real local PTY, embedded as a first-class part of the workspace.</p></div><div class="terminal-shell"><div class="terminal-toolbar"><div style="display:flex;align-items:center"><span class="terminal-dots"><i></i><i></i><i></i></span><strong>sohail-studio / terminal</strong></div><span id="terminal-status">Connecting…</span></div><div class="terminal-screen" id="terminal-screen"></div><form class="terminal-input-row" id="terminal-form"><span>›</span><input class="terminal-input" id="terminal-input" placeholder="Type a command and press Enter" autocomplete="off" /><span class="terminal-hint">Ctrl+C supported</span></form></div>`;
}

function sessionRows(sessions) {
  return `<div class="session-list">${sessions.map((session) => `<div class="session-row"><div><strong>${escapeHtml(session.workflow || "Workflow run")}</strong><span>${escapeHtml(session.target || "Local workspace")}</span></div><span class="session-status">${escapeHtml(session.status || "saved")}</span></div>`).join("")}</div>`;
}

function sessionsView() {
  return `<div class="page-intro"><div class="eyebrow">Project memory</div><h1>Sessions</h1><p>Local execution summaries and inspection memory stored on this machine.</p></div>${state.sessions.length ? sessionRows(state.sessions) : `<div class="panel placeholder-panel"><div class="empty-orbit">◷</div><h2>No sessions yet</h2><p>Once you approve a workflow, its result will be saved locally here.</p></div>`}`;
}

function placeholderView(title, copy) {
  return `<div class="page-intro"><div class="eyebrow">Sohail Studio</div><h1>${title}</h1><p>${copy}</p></div><div class="panel placeholder-panel"><div class="empty-orbit">✦</div><h2>Coming in the next layer</h2><p>The navigation and local-first contracts are ready. This surface is intentionally small until its underlying engineering workflow is connected.</p><button class="primary-button" data-route="home">Back to home</button></div>`;
}

function render() {
  const route = state.route;
  document.querySelectorAll(".nav-item").forEach((item) => item.classList.toggle("active", item.dataset.route === (["plan", "approved-plan", "run"].includes(route) ? "workflows" : route)));
  const titles = { home: "Home", workflows: "Workflows", plan: "Plan", "approved-plan": "Plan", run: "Run", terminal: "Terminal", sessions: "Sessions", settings: "Settings", chat: "AI Chat" };
  pageTitle.textContent = titles[route] || "Home";
  if (route === "home") app.innerHTML = homeView();
  else if (route === "workflows") app.innerHTML = workflowsView();
  else if (route === "plan") app.innerHTML = planView();
  else if (route === "approved-plan") app.innerHTML = approvedPlanView();
  else if (route === "run") app.innerHTML = runView();
  else if (route === "terminal") app.innerHTML = terminalView();
  else if (route === "sessions") app.innerHTML = sessionsView();
  else if (route === "chat") app.innerHTML = placeholderView("AI Chat", "Bring a question, a tradeoff, or a design decision.");
  else app.innerHTML = placeholderView("Settings", "Keep local paths, shell preferences, and integrations explicit.");
  bindView();
  if (route === "run" && state.runId) connectRun(state.runId);
  if (route === "terminal") connectTerminal();
}

function bindView() {
  document.querySelectorAll("[data-route]").forEach((item) => item.addEventListener("click", () => setRoute(item.dataset.route)));
  document.querySelectorAll("[data-workflow]").forEach((item) => item.addEventListener("click", () => {
    state.selectedWorkflow = state.workflows.find((workflow) => workflow.id === item.dataset.workflow);
    state.route = "plan";
    render();
  }));
  const promptForm = document.getElementById("prompt-form");
  if (promptForm) promptForm.addEventListener("submit", (event) => { event.preventDefault(); setRoute("chat"); });
  const planForm = document.getElementById("plan-form");
  if (planForm) planForm.addEventListener("submit", submitPlan);
  const approveButton = document.getElementById("approve-run");
  if (approveButton) approveButton.addEventListener("click", approveRun);
  const terminalForm = document.getElementById("terminal-form");
  if (terminalForm) terminalForm.addEventListener("submit", sendTerminalInput);
}

async function submitPlan(event) {
  event.preventDefault();
  const target = document.getElementById("target-input").value.trim();
  try {
    state.plan = await api("/api/workflows/plan", { method: "POST", body: JSON.stringify({ workflow: state.selectedWorkflow.id, target }) });
    state.route = "approved-plan";
    render();
  } catch (error) { showToast(error.message); }
}

async function approveRun() {
  try {
    const result = await api("/api/runs", { method: "POST", body: JSON.stringify({ workflow: state.selectedWorkflow.id, target: state.plan.target, approved: true }) });
    state.runId = result.run_id;
    state.route = "run";
    render();
  } catch (error) { showToast(error.message); }
}

function connectRun(runId) {
  const protocol = window.location.protocol === "https:" ? "wss" : "ws";
  const socket = new WebSocket(`${protocol}://${window.location.host}/ws/runs/${runId}`);
  state.runSocket = socket;
  socket.onmessage = (event) => handleRunEvent(JSON.parse(event.data));
  socket.onerror = () => { const status = document.getElementById("run-status"); if (status) status.textContent = "Connection error"; };
}

function handleRunEvent(event) {
  const output = document.getElementById("console-output");
  const status = document.getElementById("run-status");
  if (!output) return;
  if (event.type === "command") {
    output.innerHTML += `<span class="console-command">Running: ${escapeHtml(event.command)}<small>${escapeHtml(event.purpose)}</small></span>`;
    if (status) status.textContent = "Running";
  } else if (event.type === "output") {
    output.textContent += event.message;
    output.scrollTop = output.scrollHeight;
  } else if (event.type === "complete") {
    const success = event.status === "completed";
    output.innerHTML += `<span class="${success ? "console-success" : "console-error"}">\n✓ ${success ? "Completed" : "Failed"} · exit code ${event.exit_code}\n</span>`;
    if (status) status.textContent = success ? "Completed" : "Failed";
    loadSessions();
  } else if (event.type === "error") {
    output.innerHTML += `<span class="console-error">\n${escapeHtml(event.message)}\n</span>`;
    if (status) status.textContent = "Error";
  }
}

function connectTerminal() {
  const screen = document.getElementById("terminal-screen");
  const status = document.getElementById("terminal-status");
  if (!screen) return;
  const protocol = window.location.protocol === "https:" ? "wss" : "ws";
  const socket = new WebSocket(`${protocol}://${window.location.host}/ws/terminal`);
  state.terminalSocket = socket;
  socket.onopen = () => { status.textContent = "PTY connected · local shell"; screen.textContent += "Sohail Studio terminal\r\n"; };
  socket.onmessage = (event) => { const data = JSON.parse(event.data); if (data.message) { screen.textContent += data.message; screen.scrollTop = screen.scrollHeight; } };
  socket.onclose = () => { if (status) status.textContent = "Disconnected"; };
  socket.onerror = () => { if (status) status.textContent = "WebSocket error"; };
  document.getElementById("terminal-input")?.focus();
}

function sendTerminalInput(event) {
  event.preventDefault();
  const input = document.getElementById("terminal-input");
  if (!input || !state.terminalSocket || state.terminalSocket.readyState !== WebSocket.OPEN) return;
  state.terminalSocket.send(JSON.stringify({ action: "input", data: `${input.value}\n` }));
  input.value = "";
}

async function loadSessions() { try { state.sessions = await api("/api/sessions"); if (state.route === "home" || state.route === "sessions") render(); } catch (_) {} }
async function boot() {
  try {
    const [workflows] = await Promise.all([api("/api/workflows"), loadSessions()]);
    state.workflows = workflows;
    connectionLabel.textContent = "Local API connected";
  } catch (error) { connectionLabel.textContent = "API unavailable"; showToast(error.message); }
  render();
}

document.querySelectorAll(".nav-item").forEach((item) => item.addEventListener("click", () => setRoute(item.dataset.route)));
boot();
