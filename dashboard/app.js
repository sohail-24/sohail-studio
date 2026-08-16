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
  workspaceTab: "overview",
  advancedOpen: true,
  provider: "ollama",
  model: "qwen3.5",
  commandMode: "chat",
};

const aiModels = {
  ollama: ["qwen3.5", "llama3", "mistral"],
  gemini: ["gemini-pro", "gemini-flash"]
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

const knowledgeNodes = ["Docker", "Kubernetes", "Python", "FastAPI", "Git", "CI/CD", "Sessions", "Docs"];

function knowledgeSphere() {
  return `<section class="sphere-card surface-card">
    <div class="panel-heading"><div><span class="panel-kicker">Workspace memory</span><h2>Engineering Knowledge Sphere</h2></div><button class="quiet-icon" title="Sphere info">i</button></div>
    <div class="sphere-stage" aria-label="Engineering knowledge sphere placeholder">
      <div class="sphere-orbit orbit-one"></div><div class="sphere-orbit orbit-two"></div><div class="sphere-orbit orbit-three"></div>
      <div class="sphere-core"><span>SOHAIL</span><small>STUDIO</small></div>
      ${knowledgeNodes.map((node, index) => `<button class="sphere-node node-${index + 1}" title="Filter by ${node}">${node}</button>`).join("")}
    </div>
    <div class="sphere-footer"><span>● Learning graph</span><span>Drag · zoom · filter</span></div>
  </section>`;
}

function mentorCard(icon, title, copy, action = "Open") {
  return `<button class="mentor-card" data-mentor="${title}"><span class="mentor-icon">${icon}</span><span class="mentor-copy"><strong>${title}</strong><small>${copy}</small></span><span class="mentor-arrow">↗</span></button>`;
}

function mentorPanel() {
  return `<section class="mentor-panel surface-card"><div class="panel-heading"><div><span class="panel-kicker">Senior platform engineer</span><h2>AI Mentor</h2></div><span class="neutral-badge">Guide</span></div>
  <svg class="mentor-avatar-svg" viewBox="0 0 100 120" xmlns="http://www.w3.org/2000/svg">
    <path class="body" d="M20,120 Q20,80 50,80 Q80,80 80,120 Z" />
    <circle class="head" cx="50" cy="45" r="25" />
    <path d="M40,40 Q50,55 60,40" />
    <circle cx="42" cy="35" r="3" fill="#5a7bd5" />
    <circle cx="58" cy="35" r="3" fill="#5a7bd5" />
    <path d="M25,95 L10,120 M75,95 L90,120" stroke-dasharray="2 4" />
  </svg>
  <p class="panel-description">Signals and suggestions for the work in front of you. Not a chat.</p><div class="mentor-list">
    ${mentorCard("↗", "Next recommendation", "Inspect the repository before planning changes.")}
    ${mentorCard("▣", "Project summary", "No project context loaded yet.")}
    ${mentorCard("+", "Missing files", "Surface deployment gaps when a project is open.")}
    ${mentorCard("□", "Docker suggestions", "Container readiness checks will appear here.")}
    ${mentorCard("◇", "Kubernetes suggestions", "Review manifests and runtime assumptions.")}
    ${mentorCard("⌁", "Documentation", "Keep project knowledge easy to hand off.")}
    ${mentorCard("!", "Security notes", "Watch for secrets, permissions, and drift.")}
  </div></section>`;
}

function workspaceTabContent(tab) {
  const content = {
    overview: `<div class="canvas-welcome"><div class="welcome-mark">S</div><div><span class="panel-kicker">Workspace canvas</span><h2>Welcome to your engineering workspace</h2><p>Choose a workflow or describe the task you want to plan. Your project context will live here.</p></div></div><div class="canvas-grid"><section class="canvas-card current-task-card"><div class="card-title-row"><span class="canvas-icon">◉</span><h3>Current Task</h3><span class="empty-label">Waiting</span></div><strong>No active task</strong><p>Approved work will appear here with a clear owner, purpose, and scope.</p></section><section class="canvas-card"><div class="card-title-row"><span class="canvas-icon">✓</span><h3>Execution Plan</h3><span class="empty-label">3 steps</span></div><div class="plan-preview"><span><b>01</b> Understand project context</span><span><b>02</b> Review the proposed plan</span><span><b>03</b> Approve before execution</span></div></section><section class="canvas-card"><div class="card-title-row"><span class="canvas-icon">◷</span><h3>Recent Activity</h3><span class="empty-label">Local</span></div><p class="empty-card-copy">Completed workflows and session memory will be listed here.</p></section><section class="canvas-card"><div class="card-title-row"><span class="canvas-icon">≡</span><h3>Documentation Preview</h3><span class="empty-label">Markdown</span></div><div class="document-lines"><i></i><i></i><i></i><i class="short"></i></div></section></div>`,
    plan: `<div class="tab-placeholder"><span class="placeholder-icon">✓</span><h2>Execution plans</h2><p>Plans will be reviewed here before the CLI is approved to run.</p><div class="placeholder-meta"><span>Approval required</span><span>Transparent commands</span></div></div>`,
    files: `<div class="tab-placeholder"><span class="placeholder-icon">▣</span><h2>Generated files</h2><p>Files created by approved workflows will appear in a reviewable workspace view.</p></div>`,
    logs: `<div class="tab-placeholder"><span class="placeholder-icon">›_</span><h2>Execution logs</h2><p>Command output and exit codes will stay visible and local.</p></div>`,
    documentation: `<div class="tab-placeholder"><span class="placeholder-icon">≡</span><h2>Documentation preview</h2><p>Project documentation will be composed as a readable Markdown preview.</p></div>`,
    architecture: `<div class="architecture-preview"><div class="architecture-node">Workspace</div><span class="architecture-line"></span><div class="architecture-branches"><div class="architecture-node">Source</div><div class="architecture-node">Runtime</div><div class="architecture-node">Delivery</div></div><p>Architecture relationships will be drawn from project memory.</p></div>`,
    diff: `<div class="tab-placeholder"><span class="placeholder-icon">±</span><h2>Workspace Diff</h2><p>Changes generated by the AI will be previewed here.</p></div>`,
    timeline: `<div class="tab-placeholder"><span class="placeholder-icon">◷</span><h2>Project Timeline</h2><p>Historical steps and context progression.</p></div>`,
  };
  return content[tab] || content.overview;
}

function workspaceCanvas() {
  const tabs = [["overview", "Overview"], ["plan", "Plan"], ["files", "Files"], ["logs", "Logs"], ["documentation", "Documentation"], ["architecture", "Architecture"], ["diff", "Diff"], ["timeline", "Timeline"]];
  return `<section class="workspace-canvas surface-card"><div class="canvas-header"><div><span class="panel-kicker">Workspace canvas</span><h1>Build with context</h1></div><span class="canvas-state"><span class="state-dot"></span> Ready</span></div><div class="workspace-tabs" role="tablist">${tabs.map(([id, label]) => `<button class="workspace-tab ${state.workspaceTab === id ? "active" : ""}" data-workspace-tab="${id}" role="tab" aria-selected="${state.workspaceTab === id}">${label}</button>`).join("")}</div><div class="canvas-content">${workspaceTabContent(state.workspaceTab)}</div></section>`;
}

function advancedPanel() {
  const providerOpen = state.advancedOpen ? "" : "collapsed";
  const models = aiModels[state.provider] || [];
  return `<section class="advanced-panel surface-card ${providerOpen}">
    <div class="advanced-heading"><div><span class="panel-kicker">AI settings</span><h2>Advanced Panel</h2></div><button class="collapse-button" id="advanced-toggle" aria-label="Toggle advanced panel">${state.advancedOpen ? "⌃" : "⌄"}</button></div>
    <div class="advanced-content">
      <div class="setting-group">
        <label>AI Provider</label>
        <div class="provider-list">
          <button class="provider-option ${state.provider === 'ollama' ? 'selected' : ''}" data-provider="ollama"><span class="provider-radio"></span><span><strong>Ollama</strong><small>Connected</small></span><span class="provider-status connected">●</span></button>
          <button class="provider-option ${state.provider === 'gemini' ? 'selected' : ''}" data-provider="gemini"><span class="provider-radio"></span><span><strong>Gemini</strong><small>Not configured</small></span><span class="provider-status">○</span></button>
        </div>
      </div>
      <div class="setting-grid">
        <label>Model
          <select id="model-select" class="select-like" style="appearance: none; background: transparent; border: none; outline: none; width: 100%; color: inherit;">
            ${models.map(m => `<option value="${m}" ${state.model === m ? 'selected' : ''}>${m}</option>`).join('')}
          </select>
        </label>
        <label>Temperature<span class="range-like"><i style="width:42%"></i></span><small class="range-value">0.4</small></label>
        <label>Workspace<span class="select-like">~/my-project <b>⌄</b></span></label>
        <label>Planning mode<span class="select-like">Review first <b>⌄</b></span></label>
        <label>Execution mode<span class="select-like">Approval required <b>⌄</b></span></label>
        <label>Memory<span class="select-like">Session memory <b>⌄</b></span></label>
        <label>Context<span class="select-like">Auto <b>⌄</b></span></label>
        <label>Theme<span class="select-like">Dark <b>⌄</b></span></label>
      </div>
    </div>
  </section>`;
}

function homeTerminalPanel() {
  return `<section class="terminal-panel surface-card"><div class="terminal-panel-header"><div><span class="panel-kicker">Execution engine</span><h2>Terminal</h2></div><div class="terminal-header-actions"><span class="terminal-connection"><span class="neutral-dot"></span>Available</span><button class="quiet-icon" title="Collapse terminal">⌃</button></div></div><div class="terminal-status-row"><span class="terminal-idle">Idle</span><span>No approved command</span></div><div class="terminal-preview"><div class="terminal-line terminal-muted">Sohail Studio terminal</div><div class="terminal-line"><span class="terminal-prompt">$</span> Waiting for an approved command…</div><div class="terminal-line terminal-muted">Output will stream here when execution begins.</div></div><div class="terminal-panel-footer"><span>PTY bridge ready</span><button class="text-button" data-route="terminal">Open terminal ↗</button></div></section>`;
}

function commandBar() {
  const examples = ["Inspect project", "Generate Docker", "Generate Kubernetes", "Generate CI/CD", "Review Repository", "Generate README"];

  const placeholders = {
    chat: "Ask Sohail Studio...",
    terminal: "Type a terminal command...",
    inspect: "What should I inspect?",
    workflow: "Describe the workflow..."
  };

  const buttonLabels = {
    chat: "Send",
    terminal: "Execute",
    inspect: "Inspect",
    workflow: "Generate Plan"
  };

  return `<section class="command-bar-section">
    <div class="command-modes">
      <button class="command-mode-btn ${state.commandMode === 'chat' ? 'active' : ''}" data-cmd-mode="chat">✦ Chat</button>
      <button class="command-mode-btn ${state.commandMode === 'terminal' ? 'active' : ''}" data-cmd-mode="terminal">⌘ Terminal</button>
      <button class="command-mode-btn ${state.commandMode === 'inspect' ? 'active' : ''}" data-cmd-mode="inspect">🔍 Inspect</button>
      <button class="command-mode-btn ${state.commandMode === 'workflow' ? 'active' : ''}" data-cmd-mode="workflow">⚙ Workflow</button>
    </div>
    <form class="command-bar" id="prompt-form" style="margin-top: 8px;">
      <span class="command-spark">✦</span>
      <input id="prompt-input" placeholder="${placeholders[state.commandMode]}" autocomplete="off" />
      <span class="token-count">128 / 8192</span>
      <button class="execute-button" aria-label="Execute command">▶ <span>${buttonLabels[state.commandMode]}</span></button>
    </form>
    <div class="command-examples"><span>Try</span>${examples.map((example) => `<button type="button" data-command-example="${example}">${example}</button>`).join("")}</div>
  </section>`;
}

function homeView() {
  return `<div class="home-dashboard"><div class="home-columns"><div class="left-column">${knowledgeSphere()}${mentorPanel()}</div><div class="center-column">${workspaceCanvas()}</div><div class="right-column">${advancedPanel()}${homeTerminalPanel()}</div></div>${commandBar()}</div>`;
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
  return `<div class="page-intro"><div class="eyebrow">Execution engine</div><h1>Terminal</h1><p>A real local PTY, embedded as a first-class part of the workspace.</p></div><section class="terminal-shell"><div class="terminal-toolbar"><div class="terminal-toolbar-title"><span class="terminal-dots"><i></i><i></i><i></i></span><strong>sohail-studio / terminal</strong></div><div class="terminal-toolbar-status"><span class="status-dot"></span><span id="terminal-status">Connecting…</span><button class="quiet-icon" data-route="home" title="Collapse terminal">⌃</button></div></div><div class="terminal-execution-row"><span>Execution status</span><strong>Interactive shell</strong><span>Command output is live</span></div><div class="terminal-screen" id="terminal-screen"></div><form class="terminal-input-row" id="terminal-form"><span>›</span><input class="terminal-input" id="terminal-input" placeholder="Type a command and press Enter" autocomplete="off" /><span class="terminal-hint">Ctrl+C supported</span></form></section>`;
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

  const providerEl = document.getElementById("status-ai-provider");
  if (providerEl) { providerEl.textContent = state.provider.charAt(0).toUpperCase() + state.provider.slice(1); }
  const modelEl = document.getElementById("status-ai-model");
  if (modelEl) { modelEl.textContent = state.model; }

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
  document.querySelectorAll("[data-workspace-tab]").forEach((item) => item.addEventListener("click", () => {
    state.workspaceTab = item.dataset.workspaceTab;
    render();
  }));
  const advancedToggle = document.getElementById("advanced-toggle");
  if (advancedToggle) advancedToggle.addEventListener("click", () => { state.advancedOpen = !state.advancedOpen; render(); });
  document.querySelectorAll("[data-provider]").forEach((item) => item.addEventListener("click", () => {
    state.provider = item.dataset.provider;
    state.model = aiModels[state.provider][0];
    render();
  }));
  const modelSelect = document.getElementById("model-select");
  if (modelSelect) {
    modelSelect.addEventListener("change", (e) => {
      state.model = e.target.value;
      render();
    });
  }
  document.querySelectorAll("[data-cmd-mode]").forEach((item) => item.addEventListener("click", () => {
    state.commandMode = item.dataset.cmdMode;
    render();
  }));
  document.querySelectorAll("[data-command-example]").forEach((item) => item.addEventListener("click", () => {
    const input = document.getElementById("prompt-input");
    if (input) { input.value = item.dataset.commandExample; input.focus(); }
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
    state.plan = await api("/api/workflows/plan", { method: "POST", body: JSON.stringify({ workflow: state.selectedWorkflow.id, target, provider: state.provider, model: state.model }) });
    state.route = "approved-plan";
    render();
  } catch (error) { showToast(error.message); }
}

async function approveRun() {
  try {
    const result = await api("/api/runs", { method: "POST", body: JSON.stringify({ workflow: state.selectedWorkflow.id, target: state.plan.target, approved: true, provider: state.provider, model: state.model }) });
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
