const state = {
  route: "home",
  workflows: [],
  selectedWorkflow: null,
  plan: null,
  sessions: [],
  runId: null,
  runSocket: null,
  terminalSocket: null,
  chatSocket: null,
  terminalCwd: "",
  terminalBuffer: "",
  terminalRenderer: null,
  terminalPreviewRenderer: null,
  terminalRenderedLength: 0,
  terminalPreviewRenderedLength: 0,
  terminalConnection: "Available",
  terminalStatus: "Idle",
  terminalCaptureIndex: null,
  pendingTerminalInputs: [],
  terminalBannerAdded: false,
  terminalEngine: null,
  agentOperations: [],
  selectedAgentOperation: "inspect",
  agentRunId: null,
  agentRunSocket: null,
  agentConsoleInput: "",
  agentContext: null,
  agentChoices: {
    components: [],
    compose: true,
    composeAction: "keep",
    organization: "automatic",
    cicdAction: "analyze",
    cicdPlatform: "jenkins",
  },
  agentOutput: "",
  agentStatus: "Idle",
  agentCommand: "",
  agentInputs: { target: "", goal: "", plan_dir: "", spec_dir: "", output_dir: "" },
  agentDryRun: false,
  agentOverwrite: false,
  chatConnection: "Available",
  chatStatus: "Idle",
  chatCaptureIndex: null,
  pendingChatInputs: [],
  workspaceTab: "overview",
  advancedOpen: true,
  provider: "ollama",
  model: "devops-qwen:latest",
  commandMode: "terminal",
  chatHistory: [],
};

const aiModels = {
  ollama: ["devops-qwen:latest", "qwen3.5", "llama3", "mistral"],
  gemini: ["gemini-pro", "gemini-flash"]
};

const app = document.getElementById("app");
const pageTitle = document.getElementById("page-title");
const connectionLabel = document.getElementById("connection-label");

const escapeHtml = (value) => String(value ?? "").replace(/[&<>\"]/g, (char) => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;"}[char]));
const renderMarkdown = (value) => {
  let source = String(value ?? "").replace(/\\([\\*_`#[\]()])/g, "$1");
  const codeBlocks = [];
  source = source.replace(/```([^\n]*)\n([\s\S]*?)```/g, (_match, language, code) => {
    const className = language.trim() ? ` class="language-${escapeHtml(language.trim())}"` : "";
    const token = `@@SOHAIL_CODE_${codeBlocks.length}@@`;
    codeBlocks.push(`<pre><code${className}>${escapeHtml(code.replace(/\n$/, ""))}</code></pre>`);
    return token;
  });

  const inline = (line) => line
    .replace(/`([^`]+)`/g, "<code>$1</code>")
    .replace(/\*\*(.+?)\*\*/g, "<strong>$1</strong>")
    .replace(/__(.+?)__/g, "<strong>$1</strong>")
    .replace(/\*([^*\n]+)\*/g, "<em>$1</em>")
    .replace(/_([^_\n]+)_/g, "<em>$1</em>");

  const escaped = escapeHtml(source);
  const html = [];
  let listType = null;
  const closeList = () => {
    if (listType) html.push(`</${listType}>`);
    listType = null;
  };
  escaped.split("\n").forEach((line) => {
    const codeToken = line.match(/^@@SOHAIL_CODE_(\d+)@@$/);
    if (codeToken) { closeList(); html.push(codeBlocks[Number(codeToken[1])]); return; }
    const unordered = line.match(/^\s*[-*]\s+(.+)$/);
    const ordered = line.match(/^\s*\d+[.)]\s+(.+)$/);
    if (unordered || ordered) {
      const nextType = unordered ? "ul" : "ol";
      if (listType !== nextType) { closeList(); listType = nextType; html.push(`<${listType}>`); }
      html.push(`<li>${inline(unordered ? unordered[1] : ordered[1])}</li>`);
      return;
    }
    closeList();
    if (!line.trim()) { html.push("<br>"); return; }
    const heading = line.match(/^(#{1,3})\s+(.+)$/);
    if (heading) {
      const level = Math.min(4, heading[1].length + 1);
      html.push(`<h${level}>${inline(heading[2])}</h${level}>`);
      return;
    }
    html.push(`${inline(line)}<br>`);
  });
  closeList();
  return html.join("").replace(/@@SOHAIL_CODE_(\d+)@@/g, (_match, index) => codeBlocks[Number(index)] || "");
};
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
  if (route === "terminal") {
    state.terminalEngine = null;
    if (state.terminalSocket) state.terminalSocket.close();
    if (state.agentRunSocket) state.agentRunSocket.close();
    state.terminalSocket = null;
    state.agentRunSocket = null;
  }
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

function recentsTaskPanel() {
  return `<section class="recents-task-panel surface-card">
    <div class="panel-heading"><h2>Recents task</h2></div>
  </section>`;
}

function mentorCard(icon, title, copy, action = "Open") {
  return `<button class="mentor-card" data-mentor="${title}"><span class="mentor-icon">${icon}</span><span class="mentor-copy"><strong>${title}</strong><small>${copy}</small></span><span class="mentor-arrow">↗</span></button>`;
}

function mentorPanel() {
  return `<section class="mentor-panel"><div class="panel-heading"><div><span class="panel-kicker">Senior platform engineer</span><h2>AI Mentor</h2></div><span class="neutral-badge">Guide</span></div>
  <div class="mentor-actions">
    <button id="mentor-play-btn" class="mentor-play-btn" type="button" aria-label="Play AI Mentor greeting">▶ Play</button>
  </div>
  <div class="mentor-robot-container">
    <button id="mentor-robot-btn" class="mentor-robot-btn" aria-label="Open AI Mentor" title="Open AI Mentor">
      <div class="mentor-robot-wrapper">
        <div id="mentor-3d-container" class="mentor-robot-3d" aria-label="Interactive AI Mentor 3D robot"></div>
      </div>
    </button>
  </div>
  <div class="mentor-suggestion">
    <button class="mentor-suggestion-btn" data-route="chat">Inspect repository first →</button>
  </div></section>`;
}

function workspaceCanvas() {
  const messagesHtml = state.chatHistory.map((msg, index) => {
    const isUser = msg.role === "user";
    const roleName = isUser ? "You" : "Sohail Studio";
    return `<div class="chat-message ${isUser ? 'user' : 'assistant'}">
      <div class="chat-message-role">${escapeHtml(roleName)}:</div>
      <div class="chat-message-content" data-chat-index="${index}">${renderMarkdown(msg.content)}</div>
    </div>`;
  }).join("");

  return `<section class="workspace-canvas surface-card">
    <div class="chat-workspace-header">
      <h1>sohail studio</h1>
    </div>
    <div class="chat-history-content" id="chat-history-content">
      ${messagesHtml}
    </div>
    ${commandBar()}
  </section>`;
}

function homeTerminalPanel() {
  const preview = state.terminalBuffer ? "Raw PTY connected\nOpen terminal to view live output." : "Sohail Studio terminal\nWaiting for a command…";
  return `<section class="terminal-panel surface-card"><div class="terminal-panel-header"><div><span class="panel-kicker">Execution engine</span><h2>Terminal</h2></div><div class="terminal-header-actions"><span class="terminal-connection"><span class="neutral-dot"></span><span id="terminal-connection-label">${escapeHtml(state.terminalConnection)}</span></span><button class="quiet-icon" title="Collapse terminal">⌃</button></div></div><div class="terminal-status-row"><span class="terminal-idle" id="terminal-home-status">${escapeHtml(state.terminalStatus)}</span><span>Real shell PTY bridge</span></div><div class="terminal-preview" id="terminal-preview" aria-label="Terminal preview">${escapeHtml(preview)}</div><div class="terminal-panel-footer"><span>Real shell PTY bridge</span><button class="text-button" data-route="terminal">Open terminal ↗</button></div></section>`;
}

function commandBar() {
  const examples = ["pwd", "ls", "whoami", "cd backend", "command-that-does-not-exist"];

  const placeholders = {
    chat: "Ask Sohail Studio...",
    terminal: "Type a terminal command...",
    inspect: "What should I inspect?",
    workflow: "Describe the workflow..."
  };

  const buttonLabels = {
    chat: "Send",
    terminal: "Send",
    inspect: "Inspect",
    workflow: "Generate Plan"
  };

  return `<section class="command-bar-section">
    <div class="command-modes">
      <button class="command-mode-btn ${state.commandMode === 'chat' ? 'active' : ''}" data-cmd-mode="chat">+ Chat</button>
      <button class="command-mode-btn ${state.commandMode === 'terminal' ? 'active' : ''}" data-cmd-mode="terminal">⌘ Terminal</button>
      <button class="command-mode-btn ${state.commandMode === 'inspect' ? 'active' : ''}" data-cmd-mode="inspect">🔍 Inspect</button>
      <button class="command-mode-btn ${state.commandMode === 'workflow' ? 'active' : ''}" data-cmd-mode="workflow">⚙ Workflow</button>
    </div>
    <form class="command-bar" id="prompt-form" style="margin-top: 8px;">
      <span class="command-spark">✦</span>
      <input id="prompt-input" placeholder="${placeholders[state.commandMode]}" autocomplete="off" />

      <button class="execute-button" aria-label="Execute command">▶ <span>${buttonLabels[state.commandMode]}</span></button>
    </form>
    <div class="command-examples"><span>Try</span>${examples.map((example) => `<button type="button" data-command-example="${example}">${example}</button>`).join("")}</div>
  </section>`;
}

function homeView() {
  return `<div class="home-dashboard"><div class="home-columns"><div class="left-column">${recentsTaskPanel()}${mentorPanel()}</div><div class="center-column">${workspaceCanvas()}</div><div class="right-column">${knowledgeSphere()}${homeTerminalPanel()}</div></div></div>`;
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
  if (!state.terminalEngine) return terminalEngineChooser();
  const engineTabs = `<div class="terminal-engine-tabs" role="tablist" aria-label="Terminal engine"><button class="terminal-engine-tab ${state.terminalEngine === "pty" ? "active" : ""}" data-terminal-engine="pty">Raw PTY</button><button class="terminal-engine-tab ${state.terminalEngine === "agent" ? "active" : ""}" data-terminal-engine="agent">Sohail-Agent</button></div>`;
  const body = state.terminalEngine === "agent" ? agentTerminalView() : rawTerminalView();
  return `<div class="page-intro"><div class="eyebrow">Execution engine</div><h1>Terminal</h1><p>Choose a local shell or the existing Sohail-Agent engineering CLI.</p></div>${engineTabs}${body}`;
}

function terminalEngineChooser() {
  return `<div class="page-intro"><div class="eyebrow">Execution engine</div><h1>Terminal</h1><p>Choose how you want to work in this local workspace.</p></div><section class="terminal-engine-picker"><div class="terminal-engine-picker-heading"><span class="panel-kicker">Terminal</span><h2>Choose execution engine</h2><p>Your choice stays inside Sohail Studio and can be changed at any time.</p></div><div class="terminal-engine-picker-grid"><button type="button" class="terminal-engine-card" data-terminal-engine="pty"><span class="terminal-engine-card-icon">›_</span><span><strong>Raw PTY</strong><small>Real zsh terminal</small></span><span class="terminal-engine-card-arrow">→</span></button><button type="button" class="terminal-engine-card" data-terminal-engine="agent"><span class="terminal-engine-card-icon">✦</span><span><strong>Sohail-Agent</strong><small>AI engineering workflows</small></span><span class="terminal-engine-card-arrow">→</span></button></div></section>`;
}

function rawTerminalView() {
  return `<section class="terminal-shell"><div class="terminal-toolbar"><div class="terminal-toolbar-title"><span class="terminal-dots"><i></i><i></i><i></i></span><strong>sohail-studio / raw pty</strong></div><div class="terminal-toolbar-status"><span class="status-dot"></span><span id="terminal-status">Connecting…</span><button class="quiet-icon" data-route="home" title="Collapse terminal">⌃</button></div></div><div class="terminal-execution-row"><span>Execution status</span><strong>Interactive zsh</strong><span>Command output is live</span></div><div class="terminal-screen" id="terminal-screen" aria-label="Raw PTY terminal"></div><form class="terminal-input-row" id="terminal-form"><span>›</span><input class="terminal-input" id="terminal-input" placeholder="Type a command and press Enter" autocomplete="off" /><span class="terminal-hint">Ctrl+C supported</span></form></section>`;
}

function agentTerminalView() {
  const operation = state.agentOperations.find((item) => item.id === state.selectedAgentOperation) || state.agentOperations[0];
  const requires = operation?.requires || [];
  const field = (key, label, placeholder) => `<label class="agent-field"><span>${label}</span><input data-agent-input="${key}" value="${escapeHtml(state.agentInputs[key])}" placeholder="${placeholder}" autocomplete="off" /></label>`;
  const fields = [
    requires.includes("target") ? field("target", "Project path", "/Users/sohal/Projects/my-app") : "",
    requires.includes("goal") ? field("goal", "Planning goal", "Build a local-first service") : "",
    requires.includes("plan_dir") ? field("plan_dir", "Plan directory", "./project-plan") : "",
    requires.includes("spec_dir") ? field("spec_dir", "Specification directory", "./specifications") : "",
    ["plan", "blueprint"].includes(operation?.id) ? field("output_dir", "Output directory", operation.id === "plan" ? "./project-plan" : "./blueprints") : "",
  ].join("");
  const cards = state.agentOperations.map((item) => `<button type="button" class="agent-operation-card ${item.id === state.selectedAgentOperation ? "active" : ""}" data-agent-operation="${item.id}"><strong>${item.label}</strong><span>${item.description}</span></button>`).join("");
  const components = state.agentContext?.components || [];
  const componentChoices = components.length ? components.map((component) => `<label class="agent-choice"><input type="checkbox" data-agent-choice="component" value="${escapeHtml(component.name)}" ${state.agentChoices.components.includes(component.name) ? "checked" : ""} /><span><strong>${escapeHtml(component.name)}</strong><small>${escapeHtml(component.framework || component.stack?.primary || "Detected component")} · ${escapeHtml(component.package_manager || "package manager")}</small></span></label>`).join("") : `<p class="agent-guidance">Run Inspect first to discover independently buildable components from repository manifests.</p>`;
  const composeDetected = Boolean(state.agentContext?.has_docker_compose);
  const composeChoices = composeDetected ? `<div class="agent-inline-choices"><label><input type="radio" name="compose-action" data-agent-choice="composeAction" value="keep" ${state.agentChoices.composeAction === "keep" ? "checked" : ""} /> Keep existing unchanged</label><label><input type="radio" name="compose-action" data-agent-choice="composeAction" value="analyze" ${state.agentChoices.composeAction === "analyze" ? "checked" : ""} /> Analyze existing</label><label><input type="radio" name="compose-action" data-agent-choice="composeAction" value="improve" ${state.agentChoices.composeAction === "improve" ? "checked" : ""} /> Improve existing</label><label><input type="radio" name="compose-action" data-agent-choice="composeAction" value="generate" ${state.agentChoices.composeAction === "generate" ? "checked" : ""} /> Generate new</label></div><p class="agent-guidance">Existing Docker Compose configuration detected.</p>` : `<p class="agent-guidance">Docker Compose not detected.</p><div class="agent-inline-choices"><label><input type="radio" name="compose-action" data-agent-choice="composeAction" value="generate" checked /> Generate new</label></div>`;
  const guidedQuestions = operation?.id === "dockerize" ? `<section class="agent-question-block"><h4>Dockerization target</h4><p>Choose components from the shared inspection context.</p><div class="agent-choice-grid">${componentChoices}</div><h4>Docker Compose</h4>${composeChoices}</section>` : operation?.id === "kubernetes" ? `<section class="agent-question-block"><h4>Kubernetes targets</h4><p>Use the same inspected components for manifest generation.</p><div class="agent-choice-grid">${componentChoices}</div><h4>Manifest organization</h4><div class="agent-inline-choices"><label><input type="radio" name="organization" data-agent-choice="organization" value="automatic" ${state.agentChoices.organization === "automatic" ? "checked" : ""} /> Automatic / recommended</label><label><input type="radio" name="organization" data-agent-choice="organization" value="single" ${state.agentChoices.organization === "single" ? "checked" : ""} /> Single manifest</label><label><input type="radio" name="organization" data-agent-choice="organization" value="separate" ${state.agentChoices.organization === "separate" ? "checked" : ""} /> Separate resource files</label></div></section>` : operation?.id === "cicd" ? `<section class="agent-question-block"><h4>Detected CI/CD</h4><p>${state.agentContext?.ci_cd_files?.length ? `✓ ${escapeHtml(state.agentContext.ci_cd_files.join(", "))}` : "No existing CI/CD configuration detected."}</p><div class="agent-inline-choices"><label><input type="radio" name="cicd-action" data-agent-choice="cicdAction" value="analyze" ${state.agentChoices.cicdAction === "analyze" ? "checked" : ""} /> Analyze existing</label><label><input type="radio" name="cicd-action" data-agent-choice="cicdAction" value="improve" ${state.agentChoices.cicdAction === "improve" ? "checked" : ""} /> Improve existing</label><label><input type="radio" name="cicd-action" data-agent-choice="cicdAction" value="generate" ${state.agentChoices.cicdAction === "generate" ? "checked" : ""} /> Generate new</label><label><input type="radio" name="cicd-action" data-agent-choice="cicdAction" value="keep" ${state.agentChoices.cicdAction === "keep" ? "checked" : ""} /> Keep unchanged</label></div><h4>CI/CD platform</h4><div class="agent-inline-choices"><label><input type="radio" name="cicd-platform" data-agent-choice="cicdPlatform" value="jenkins" ${state.agentChoices.cicdPlatform === "jenkins" ? "checked" : ""} /> Jenkins</label><label><input type="radio" name="cicd-platform" data-agent-choice="cicdPlatform" value="github-actions" ${state.agentChoices.cicdPlatform === "github-actions" ? "checked" : ""} /> GitHub Actions</label><label><input type="radio" name="cicd-platform" data-agent-choice="cicdPlatform" value="both" ${state.agentChoices.cicdPlatform === "both" ? "checked" : ""} /> Both</label></div></section>` : "";
  const output = state.agentOutput || "Select an operation, provide its required inputs, and run the existing Sohail-Agent capability.";
  const consoleBusy = ["Running", "Starting"].includes(state.agentStatus);
  const nextActions = state.selectedAgentOperation === "inspect" && state.agentStatus === "Completed" ? `<div class="agent-next-actions"><strong>Inspection complete.</strong><span>Choose the next engineering operation from the controls above or continue here:</span><button type="button" data-agent-operation="dockerize">Dockerize</button><button type="button" data-agent-operation="kubernetes">Kubernetes</button><button type="button" data-agent-operation="cicd">CI/CD</button></div>` : "";
  return `<section class="agent-shell"><div class="agent-shell-header"><div><span class="panel-kicker">Existing engineering CLI</span><h2>Sohail-Agent</h2><p class="agent-prompt">What would you like to do?</p></div><span class="agent-status" id="agent-status">${escapeHtml(state.agentStatus)}</span></div><div class="agent-operation-grid">${cards}</div><form class="agent-form" id="agent-form"><div class="agent-workspace-heading"><div><span class="panel-kicker">Operation workspace</span><h3>${escapeHtml(operation?.label || "Choose an operation")}</h3></div><span>Guided workflow</span></div><div class="agent-fields">${fields}</div>${guidedQuestions}<div class="agent-options"><label><input type="checkbox" id="agent-dry-run" ${state.agentDryRun ? "checked" : ""} /> Dry run</label><label><input type="checkbox" id="agent-overwrite" ${state.agentOverwrite ? "checked" : ""} /> Allow overwrite</label><button class="primary-button" id="agent-run-button" type="submit" ${consoleBusy ? "disabled" : ""}>Run ${escapeHtml(operation?.label || "operation")} →</button></div></form>${nextActions}<section class="agent-live-terminal"><div class="agent-live-terminal-header"><div><span class="panel-kicker">Live execution</span><h3>Sohail-Agent Terminal</h3></div><div class="agent-live-terminal-meta"><span id="agent-command">${escapeHtml(state.agentCommand || "Waiting for a run")}</span><span id="agent-live-status">${escapeHtml(state.agentStatus)}</span></div></div><pre class="agent-output" id="agent-output">${escapeHtml(output)}</pre><form class="agent-console-form" id="agent-console-form"><span class="agent-console-prompt">$</span><input id="agent-console-input" value="${escapeHtml(state.agentConsoleInput)}" placeholder="sohail-agent --help" autocomplete="off" ${consoleBusy ? "disabled" : ""} /><button class="quiet-button" type="submit" ${consoleBusy ? "disabled" : ""}>Run CLI</button></form><p class="agent-console-note">Only the existing <code>sohail-agent</code> CLI is accepted here; use Raw PTY for shell commands.</p></section></section>`;
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


function createAIMentorRobot() {
  const robotGroup = new THREE.Group();
  robotGroup.name = "robotGroup";

  const whiteMat = new THREE.MeshStandardMaterial({ color: 0xf4f8ff, metalness: 0.32, roughness: 0.24 });
  const whiteSoftMat = new THREE.MeshStandardMaterial({ color: 0xd8e4f3, metalness: 0.22, roughness: 0.3 });
  const faceMat = new THREE.MeshStandardMaterial({ color: 0x071226, metalness: 0.65, roughness: 0.2 });
  const navyMat = new THREE.MeshStandardMaterial({ color: 0x0d1934, metalness: 0.68, roughness: 0.26 });
  const jointMat = new THREE.MeshStandardMaterial({ color: 0x101d38, metalness: 0.82, roughness: 0.23 });
  const blueMat = new THREE.MeshStandardMaterial({ color: 0x1974f5, metalness: 0.38, roughness: 0.2, emissive: 0x051b5b, emissiveIntensity: 0.35 });
  const cyanMat = new THREE.MeshStandardMaterial({ color: 0x27dbff, metalness: 0.18, roughness: 0.18, emissive: 0x00a9df, emissiveIntensity: 1.45 });
  const cyanBasicMat = new THREE.MeshBasicMaterial({ color: 0x20dfff });

  function roundedBoxGeometry(width, height, depth, radius) {
    const x = width / 2;
    const y = height / 2;
    const r = Math.min(radius, x, y);
    const shape = new THREE.Shape();
    shape.moveTo(-x + r, -y);
    shape.lineTo(x - r, -y);
    shape.quadraticCurveTo(x, -y, x, -y + r);
    shape.lineTo(x, y - r);
    shape.quadraticCurveTo(x, y, x - r, y);
    shape.lineTo(-x + r, y);
    shape.quadraticCurveTo(-x, y, -x, y - r);
    shape.lineTo(-x, -y + r);
    shape.quadraticCurveTo(-x, -y, -x + r, -y);
    const geometry = new THREE.ExtrudeGeometry(shape, {
      depth,
      bevelEnabled: true,
      bevelSegments: 3,
      bevelSize: Math.min(r * 0.45, depth * 0.35),
      bevelThickness: Math.min(r * 0.45, depth * 0.35),
      curveSegments: 8,
      steps: 1
    });
    geometry.translate(0, 0, -depth / 2);
    geometry.computeVertexNormals();
    return geometry;
  }

  function roundedMesh(width, height, depth, radius, material) {
    return new THREE.Mesh(roundedBoxGeometry(width, height, depth, radius), material);
  }

  function addCylinder(parent, radius, height, material, position, rotation = {}) {
    const mesh = new THREE.Mesh(new THREE.CylinderGeometry(radius, radius, height, 24), material);
    mesh.position.set(position[0], position[1], position[2]);
    mesh.rotation.set(rotation.x || 0, rotation.y || 0, rotation.z || 0);
    parent.add(mesh);
    return mesh;
  }

  function addFinger(handGroup, x, y, z, rotationZ = 0) {
    const finger = addCylinder(handGroup, 0.045, 0.22, jointMat, [x, y, z], { z: rotationZ });
    finger.scale.x = 0.92;
    return finger;
  }

  function addEye(parent, x) {
    const eye = new THREE.Group();
    eye.name = x < 0 ? "leftEye" : "rightEye";
    eye.position.set(x, 0.1, 0.535);
    const socket = roundedMesh(0.29, 0.31, 0.035, 0.1, navyMat);
    socket.position.z = -0.01;
    eye.add(socket);
    const ring = new THREE.Mesh(new THREE.TorusGeometry(0.115, 0.026, 10, 24), cyanMat);
    ring.scale.y = 1.13;
    eye.add(ring);
    const iris = new THREE.Mesh(new THREE.SphereGeometry(0.075, 18, 12), cyanMat);
    iris.scale.set(1, 1.18, 0.3);
    iris.position.z = 0.035;
    eye.add(iris);
    const pupil = new THREE.Mesh(new THREE.SphereGeometry(0.027, 12, 8), faceMat);
    pupil.position.set(0.015, -0.005, 0.062);
    pupil.scale.z = 0.35;
    eye.add(pupil);
    const glint = new THREE.Mesh(new THREE.SphereGeometry(0.018, 10, 8), new THREE.MeshBasicMaterial({ color: 0xffffff }));
    glint.position.set(-0.035, 0.045, 0.074);
    eye.add(glint);
    parent.add(eye);
    return eye;
  }

  // Head: rounded shell, bezel, glossy screen, expressive eyes, brows, and a curved smile.
  const headGroup = new THREE.Group();
  headGroup.name = "headGroup";
  headGroup.position.y = 1.25;
  const headShell = roundedMesh(1.72, 1.2, 0.92, 0.22, whiteMat);
  headShell.name = "headShell";
  headGroup.add(headShell);
  const faceBezel = roundedMesh(1.46, 0.9, 0.07, 0.17, blueMat);
  faceBezel.position.z = 0.475;
  faceBezel.name = "faceBezel";
  headGroup.add(faceBezel);
  const faceScreen = roundedMesh(1.35, 0.79, 0.075, 0.15, faceMat);
  faceScreen.position.z = 0.53;
  faceScreen.name = "faceScreen";
  headGroup.add(faceScreen);
  addEye(headGroup, -0.34);
  addEye(headGroup, 0.34);

  const browMat = new THREE.MeshBasicMaterial({ color: 0x4fe6ff });
  [-0.34, 0.34].forEach((x) => {
    const brow = new THREE.Mesh(new THREE.TorusGeometry(0.16, 0.018, 8, 20, Math.PI), browMat);
    brow.position.set(x, 0.285, 0.565);
    brow.rotation.z = x < 0 ? -0.12 : 0.12;
    headGroup.add(brow);
  });
  const smileCurve = new THREE.CatmullRomCurve3([
    new THREE.Vector3(-0.22, -0.18, 0.57),
    new THREE.Vector3(-0.12, -0.25, 0.57),
    new THREE.Vector3(0, -0.28, 0.57),
    new THREE.Vector3(0.12, -0.25, 0.57),
    new THREE.Vector3(0.22, -0.18, 0.57)
  ]);
  const smile = new THREE.Mesh(new THREE.TubeGeometry(smileCurve, 18, 0.025, 8, false), cyanMat);
  smile.name = "mouth";
  headGroup.add(smile);

  // Headphones and antenna-like side details add silhouette without relying on textures.
  [-1, 1].forEach((side) => {
    const ear = new THREE.Group();
    ear.name = side < 0 ? "leftEar" : "rightEar";
    ear.position.set(side * 0.9, 0.03, 0);
    addCylinder(ear, 0.22, 0.16, blueMat, [0, 0, 0], { z: Math.PI / 2 });
    const earRing = new THREE.Mesh(new THREE.TorusGeometry(0.14, 0.022, 10, 24), cyanMat);
    earRing.rotation.y = Math.PI / 2;
    ear.add(earRing);
    addCylinder(ear, 0.045, 0.34, whiteSoftMat, [0, 0.31, 0]);
    headGroup.add(ear);
  });
  robotGroup.add(headGroup);

  // Mechanical neck with a luminous collar.
  const neckGroup = new THREE.Group();
  neckGroup.name = "neckGroup";
  neckGroup.position.y = 0.67;
  addCylinder(neckGroup, 0.2, 0.2, jointMat, [0, 0, 0]);
  addCylinder(neckGroup, 0.15, 0.08, whiteSoftMat, [0, 0.12, 0]);
  const neckRing = new THREE.Mesh(new THREE.TorusGeometry(0.26, 0.027, 10, 28), cyanMat);
  neckRing.rotation.x = Math.PI / 2;
  neckRing.position.y = 0.08;
  neckGroup.add(neckRing);
  robotGroup.add(neckGroup);

  // Rounded body, chest screen, and a geometric AI emblem.
  const bodyGroup = new THREE.Group();
  bodyGroup.name = "bodyGroup";
  bodyGroup.position.y = 0.05;
  const bodyShell = roundedMesh(1.34, 1.06, 0.78, 0.22, whiteMat);
  bodyShell.name = "bodyShell";
  bodyGroup.add(bodyShell);
  const chestPanel = roundedMesh(0.86, 0.58, 0.055, 0.12, navyMat);
  chestPanel.position.set(0, 0.04, 0.42);
  chestPanel.name = "chestPanel";
  bodyGroup.add(chestPanel);
  const panelLine = new THREE.Mesh(new THREE.TorusGeometry(0.39, 0.012, 6, 4), cyanBasicMat);
  panelLine.scale.set(1.34, 0.82, 1);
  panelLine.position.set(0, 0.04, 0.455);
  panelLine.rotation.z = Math.PI / 4;
  bodyGroup.add(panelLine);
  const emblemMat = new THREE.MeshBasicMaterial({ color: 0x4aa1ff });
  const emblemA1 = roundedMesh(0.065, 0.32, 0.035, 0.02, emblemMat);
  emblemA1.position.set(-0.2, 0.04, 0.47); emblemA1.rotation.z = -0.22; bodyGroup.add(emblemA1);
  const emblemA2 = roundedMesh(0.065, 0.32, 0.035, 0.02, emblemMat);
  emblemA2.position.set(-0.04, 0.04, 0.47); emblemA2.rotation.z = 0.22; bodyGroup.add(emblemA2);
  const emblemCross = roundedMesh(0.15, 0.045, 0.035, 0.018, emblemMat);
  emblemCross.position.set(-0.12, 0.03, 0.48); bodyGroup.add(emblemCross);
  const emblemI = roundedMesh(0.065, 0.32, 0.035, 0.02, emblemMat);
  emblemI.position.set(0.15, 0.04, 0.47); bodyGroup.add(emblemI);
  [-0.46, 0.46].forEach((x) => {
    const vent = roundedMesh(0.035, 0.28, 0.025, 0.015, cyanMat);
    vent.position.set(x, 0.03, 0.415);
    bodyGroup.add(vent);
  });
  robotGroup.add(bodyGroup);

  function createArm(name, side, raised) {
    const armGroup = new THREE.Group();
    armGroup.name = name;
    armGroup.position.set(side * (raised ? 0.96 : 0.78), raised ? 0.42 : 0.28, 0.58);
    armGroup.scale.setScalar(1.12);
    const shoulderGroup = new THREE.Group();
    shoulderGroup.name = `${name === "leftArmGroup" ? "left" : "right"}ShoulderGroup`;
    const shoulder = new THREE.Mesh(new THREE.SphereGeometry(0.23, 24, 16), whiteSoftMat);
    shoulder.scale.set(1, 0.9, 1.08);
    shoulderGroup.add(shoulder);
    const shoulderRing = new THREE.Mesh(new THREE.TorusGeometry(0.14, 0.023, 8, 20), cyanMat);
    shoulderRing.rotation.y = Math.PI / 2;
    shoulderGroup.add(shoulderRing);

    const upperArmGroup = new THREE.Group();
    upperArmGroup.name = `${name === "leftArmGroup" ? "left" : "right"}UpperArmGroup`;
    upperArmGroup.rotation.z = raised ? 0.85 : (side < 0 ? -0.45 : 0.45);
    const upperArm = roundedMesh(0.24, 0.44, 0.3, 0.09, whiteMat);
    upperArm.position.y = raised ? 0.22 : -0.22;
    upperArmGroup.add(upperArm);
    const upperAccent = new THREE.Mesh(new THREE.TorusGeometry(0.095, 0.018, 8, 18), cyanMat);
    upperAccent.rotation.x = Math.PI / 2;
    upperAccent.position.y = raised ? 0.22 : -0.22;
    upperArmGroup.add(upperAccent);

    const forearmGroup = new THREE.Group();
    forearmGroup.name = `${name === "leftArmGroup" ? "left" : "right"}ForearmGroup`;
    forearmGroup.position.set(raised ? -0.08 : 0, raised ? 0.43 : -0.43, 0);
    forearmGroup.rotation.z = raised ? 0.1 : side * -0.73;
    const elbow = new THREE.Mesh(new THREE.SphereGeometry(0.13, 18, 12), jointMat);
    forearmGroup.add(elbow);
    const forearm = roundedMesh(0.22, 0.42, 0.28, 0.08, whiteMat);
    forearm.position.y = raised ? 0.19 : -0.19;
    forearmGroup.add(forearm);
    const forearmAccent = new THREE.Mesh(new THREE.TorusGeometry(0.085, 0.017, 8, 18), cyanMat);
    forearmAccent.rotation.x = Math.PI / 2;
    forearmAccent.position.y = raised ? 0.19 : -0.19;
    forearmGroup.add(forearmAccent);

    const handGroup = new THREE.Group();
    handGroup.name = `${name === "leftArmGroup" ? "left" : "right"}HandGroup`;
    handGroup.position.set(raised ? -0.1 : 0, raised ? 0.42 : -0.42, 0);
    const palm = roundedMesh(0.3, 0.27, 0.25, 0.08, jointMat);
    handGroup.add(palm);
    const fingerY = raised ? 0.22 : -0.22;
    [-0.09, 0, 0.09].forEach((x, index) => addFinger(handGroup, x, fingerY, 0, raised ? (index - 1) * 0.09 : (1 - index) * 0.09));
    addFinger(handGroup, side < 0 ? 0.17 : -0.17, raised ? 0.02 : -0.02, 0, side < 0 ? -0.55 : 0.55);
    const palmAccent = new THREE.Mesh(new THREE.TorusGeometry(0.085, 0.014, 8, 18), cyanMat);
    palmAccent.rotation.x = Math.PI / 2;
    palmAccent.position.z = 0.13;
    handGroup.add(palmAccent);

    // Keep the full arm articulated: shoulder -> upper arm -> forearm -> hand.
    shoulderGroup.add(upperArmGroup);
    upperArmGroup.add(forearmGroup);
    forearmGroup.add(handGroup);
    armGroup.add(shoulderGroup);
    return { armGroup, shoulderGroup, upperArmGroup, forearmGroup, handGroup };
  }

  const leftArm = createArm("leftArmGroup", -1, false);
  const rightArm = createArm("rightArmGroup", 1, false);
  robotGroup.add(leftArm.armGroup, rightArm.armGroup);

  // A rounded hover pod replaces legs and gives the robot its floating silhouette.
  const lowerHoverGroup = new THREE.Group();
  lowerHoverGroup.name = "lowerHoverGroup";
  lowerHoverGroup.position.y = -0.79;
  const dock = new THREE.Mesh(new THREE.CylinderGeometry(0.42, 0.38, 0.13, 32), jointMat);
  dock.position.y = 0.2;
  lowerHoverGroup.add(dock);
  const hoverPod = new THREE.Mesh(new THREE.SphereGeometry(0.58, 32, 20, 0, Math.PI * 2, 0, Math.PI / 2), blueMat);
  hoverPod.scale.set(1, 0.78, 1);
  hoverPod.rotation.x = Math.PI;
  lowerHoverGroup.add(hoverPod);
  const hoverRing = new THREE.Mesh(new THREE.TorusGeometry(0.47, 0.035, 12, 32), cyanMat);
  hoverRing.rotation.x = Math.PI / 2;
  hoverRing.position.y = 0.08;
  lowerHoverGroup.add(hoverRing);
  const underside = new THREE.Mesh(new THREE.SphereGeometry(0.38, 24, 12), cyanMat);
  underside.scale.set(1, 0.15, 1);
  underside.position.y = -0.25;
  lowerHoverGroup.add(underside);
  robotGroup.add(lowerHoverGroup);

  robotGroup.scale.setScalar(0.72);
  robotGroup.position.y = -0.16;
  robotGroup.userData.parts = {
    headGroup,
    neckGroup,
    bodyGroup,
    leftArmGroup: leftArm.armGroup,
    leftShoulderGroup: leftArm.shoulderGroup,
    leftUpperArmGroup: leftArm.upperArmGroup,
    leftForearmGroup: leftArm.forearmGroup,
    leftHandGroup: leftArm.handGroup,
    rightArmGroup: rightArm.armGroup,
    rightShoulderGroup: rightArm.shoulderGroup,
    rightUpperArmGroup: rightArm.upperArmGroup,
    rightForearmGroup: rightArm.forearmGroup,
    rightHandGroup: rightArm.handGroup,
    lowerHoverGroup
  };
  return robotGroup;
}

let mentor3DScene = null;

function initAIMentor3D() {
  const container = document.getElementById("mentor-3d-container");
  if (!container || !window.THREE) return;

  if (mentor3DScene) {
    // If scene exists but isn't in DOM, re-attach canvas
    if (!container.contains(mentor3DScene.renderer.domElement)) {
        container.appendChild(mentor3DScene.renderer.domElement);
        // Force resize update to fix aspect ratio/size
        mentor3DScene.camera.aspect = container.clientWidth / container.clientHeight;
        mentor3DScene.camera.updateProjectionMatrix();
        mentor3DScene.renderer.setSize(container.clientWidth, container.clientHeight);

        // Re-attach the click prevention to the new parent button
        const btn = container.closest('button');
        if (btn) {
          btn.addEventListener('click', (e) => {
            if (mentor3DScene.hasDragged) {
              e.preventDefault();
              e.stopPropagation();
            }
          });
        }
    }
    return;
  }

  // 1. Scene Setup
  const scene = new THREE.Scene();

  // 2. Camera Setup
  const camera = new THREE.PerspectiveCamera(45, container.clientWidth / container.clientHeight, 0.1, 1000);
  camera.position.z = 4.2;

  // 3. Renderer Setup
  const renderer = new THREE.WebGLRenderer({ alpha: true, antialias: true });
  renderer.setSize(container.clientWidth, container.clientHeight);
  renderer.setPixelRatio(window.devicePixelRatio);
  container.appendChild(renderer.domElement);

  // 4. Soft studio lighting keeps the white shell readable without flooding the card.
  scene.add(new THREE.HemisphereLight(0xbfd8ff, 0x081126, 1.65));
  const keyLight = new THREE.DirectionalLight(0xffffff, 1.55);
  keyLight.position.set(1.5, 2.5, 3);
  scene.add(keyLight);
  const rimLight = new THREE.DirectionalLight(0x1ecbff, 0.75);
  rimLight.position.set(-2, 1.2, -2.5);
  scene.add(rimLight);
  const fillLight = new THREE.PointLight(0x2b6fff, 0.4, 8);
  fillLight.position.set(0, -1, 2);
  scene.add(fillLight);

  // 5. Code-built AI Mentor Robot
  const group = new THREE.Group();
  scene.add(group);

  const robot = createAIMentorRobot();
  group.add(robot);

  // Store references for animation/interaction and keep the model hierarchy future-ready.
  const parts = robot.userData.parts;
  mentor3DScene = {
    scene,
    camera,
    renderer,
    container,
    group,
    robot,
    parts,
    hasDragged: false,
    hovered: false,
    animation: { startedAt: -10, busy: false, rotationStart: 0 },
    baseScale: 0.72
  };

  // 6. Interaction: Drag to rotate & Hover effects
  let isDragging = false;
  let previousMousePosition = { x: 0, y: 0 };
  const raycaster = new THREE.Raycaster();
  const mouse = new THREE.Vector2();

  const onPointerDown = (e) => {
    // Manual drag always wins; stop an automatic greeting cleanly if the user takes over.
    if (mentor3DScene.animation.busy) {
      mentor3DScene.animation.busy = false;
      mentor3DScene.animation.startedAt = -10;
    }
    isDragging = true;
    mentor3DScene.hasDragged = false; // Reset on down
    const touch = e.touches && e.touches[0];
    previousMousePosition = { x: e.clientX ?? touch?.clientX ?? 0, y: e.clientY ?? touch?.clientY ?? 0 };
  };

  const onPointerMove = (e) => {
    const touch = e.touches && e.touches[0];
    const clientX = e.clientX ?? touch?.clientX;
    const clientY = e.clientY ?? touch?.clientY;

    // Hover logic
    if (clientX != null && clientY != null && container.clientWidth > 0) {
      const rect = renderer.domElement.getBoundingClientRect();
      mouse.x = ((clientX - rect.left) / rect.width) * 2 - 1;
      mouse.y = -((clientY - rect.top) / rect.height) * 2 + 1;

      raycaster.setFromCamera(mouse, camera);
      const intersects = raycaster.intersectObject(robot, true);
      mentor3DScene.hovered = intersects.length > 0;
      renderer.domElement.style.cursor = mentor3DScene.hovered ? 'pointer' : 'default';
    }

    if (!isDragging || clientX == null) return;

    const deltaMove = {
      x: clientX - previousMousePosition.x
    };

    if (Math.abs(deltaMove.x) > 2) {
      mentor3DScene.hasDragged = true; // Significant movement
    }

    // Rotate around Y axis
    group.rotation.y += deltaMove.x * 0.01;

    previousMousePosition = { x: clientX, y: previousMousePosition.y };
  };

  const onPointerUp = (e) => {
    isDragging = false;
  };

  const onPointerLeave = () => {
    if (!isDragging) mentor3DScene.hovered = false;
    renderer.domElement.style.cursor = 'default';
  };

  renderer.domElement.addEventListener('mousedown', onPointerDown);
  renderer.domElement.addEventListener('mousemove', onPointerMove);
  window.addEventListener('mouseup', onPointerUp);

  renderer.domElement.addEventListener('touchstart', onPointerDown, { passive: true });
  renderer.domElement.addEventListener('touchmove', onPointerMove, { passive: true });
  renderer.domElement.addEventListener('mouseleave', onPointerLeave);
  window.addEventListener('touchend', onPointerUp);

  // Prevent parent button click if drag occurred
  const btn = container.closest('button');
  if (btn) {
    btn.addEventListener('click', (e) => {
      if (mentor3DScene.hasDragged) {
        e.preventDefault();
        e.stopPropagation();
      }
    });
  }

  // Handle window resize
  const resizeObserver = new ResizeObserver(() => {
    if (container.clientWidth > 0 && container.clientHeight > 0) {
      camera.aspect = container.clientWidth / container.clientHeight;
      camera.updateProjectionMatrix();
      renderer.setSize(container.clientWidth, container.clientHeight);
    }
  });
  resizeObserver.observe(container);

  // 7. Animation loop: idle float, hover response, and the click greeting sequence.
  const clock = new THREE.Clock();
  const leftUpperArmRestRotation = parts.leftUpperArmGroup.rotation.z;
  const leftForearmRestRotation = parts.leftForearmGroup.rotation.z;
  const leftHandRestRotation = parts.leftHandGroup.rotation.z;
  const clamp01 = (value) => Math.max(0, Math.min(1, value));
  const smoothstep = (value) => value * value * (3 - 2 * value);
  const easeInOut = (value) => value < 0.5 ? 4 * value * value * value : 1 - Math.pow(-2 * value + 2, 3) / 2;
  const resetWavePose = () => {
    parts.leftArmGroup.rotation.z = 0;
    parts.leftShoulderGroup.rotation.z = 0;
    parts.leftUpperArmGroup.rotation.z = leftUpperArmRestRotation;
    parts.leftForearmGroup.rotation.z = leftForearmRestRotation;
    parts.leftHandGroup.rotation.z = leftHandRestRotation;
  };

  mentor3DScene.playGreeting = () => {
    if (mentor3DScene.animation.busy) return;
    mentor3DScene.animation.startedAt = clock.getElapsedTime();
    mentor3DScene.animation.rotationStart = group.rotation.y;
    mentor3DScene.animation.busy = true;
  };

  function animate() {
    requestAnimationFrame(animate);

    const delta = clock.getDelta();
    const time = clock.elapsedTime;
    const greetingTime = time - mentor3DScene.animation.startedAt;
    let jumpOffset = 0;
    resetWavePose();

    if (mentor3DScene.animation.busy) {
      // One complete root rotation, followed by a soft jump and an articulated wave.
      const rotationProgress = easeInOut(clamp01(greetingTime / 1.35));
      group.rotation.y = mentor3DScene.animation.rotationStart + Math.PI * 2 * rotationProgress;

      if (greetingTime < 1.25) {
        jumpOffset = -smoothstep(clamp01(greetingTime / 0.2)) * 0.025;
      } else {
        const jumpProgress = clamp01((greetingTime - 1.25) / 1.15);
        jumpOffset = Math.sin(jumpProgress * Math.PI) * 0.3;
      }

      if (greetingTime > 1.7) {
        const waveProgress = clamp01((greetingTime - 1.8) / 1.04);
        const waveEnvelope = Math.sin(waveProgress * Math.PI);
        const waveSwing = Math.sin(waveProgress * Math.PI * 4) * waveEnvelope;
        const raiseEnvelope = smoothstep(clamp01(waveProgress / 0.40));
        parts.leftShoulderGroup.rotation.z = -2.02 * raiseEnvelope * (1 - smoothstep(clamp01((waveProgress - 1.20) / 0.95)));
        parts.leftUpperArmGroup.rotation.z = leftUpperArmRestRotation - 0.20 * raiseEnvelope * (1 - smoothstep(clamp01((waveProgress - 0.70) / 0.75)));
        parts.leftForearmGroup.rotation.z = leftForearmRestRotation + waveSwing *  1.20;
        parts.leftHandGroup.rotation.z = leftHandRestRotation + Math.PI / 2 + waveSwing * 0.90;
      }

      if (greetingTime > 3.05) {
        mentor3DScene.animation.busy = false;
        mentor3DScene.animation.startedAt = -10;
        resetWavePose();
      }
    }

    // Drag owns rotation; these animations only adjust vertical position and articulated parts.
    robot.position.y = -0.16 + Math.sin(time * 1.8) * 0.065 + jumpOffset;
    robot.scale.lerp(new THREE.Vector3(mentor3DScene.hovered ? 0.76 : mentor3DScene.baseScale, mentor3DScene.hovered ? 0.76 : mentor3DScene.baseScale, mentor3DScene.hovered ? 0.76 : mentor3DScene.baseScale), Math.min(delta * 8, 1));
    parts.headGroup.rotation.z = Math.sin(time * 1.2) * 0.012;
    parts.lowerHoverGroup.rotation.y += delta * 0.55;
    parts.lowerHoverGroup.position.y = -0.79 + Math.sin(time * 1.8 + 0.6) * 0.014;

    renderer.render(scene, camera);
  }

  animate();
}
function render() {
  const route = state.route;
  disposeTerminalRenderers();
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
  if (route === "home" || (route === "terminal" && state.terminalEngine === "pty")) initTerminalRenderers();
  bindView();
  if (route === "run" && state.runId) connectRun(state.runId);
  if (route === "home" || (route === "terminal" && state.terminalEngine === "pty")) connectTerminal();
  if (route === "terminal" && state.terminalEngine === "agent" && state.agentRunId) connectAgentRun(state.agentRunId);
  if (state.commandMode === "chat") connectChat();

  // Initialize or re-attach the 3D robot if its container exists in the current view
  setTimeout(() => { initAIMentor3D(); }, 0);
}

function bindView() {
  document.querySelectorAll("[data-route]").forEach((item) => item.addEventListener("click", () => {
    if (item.dataset.route === "terminal") state.commandMode = "terminal";
    setRoute(item.dataset.route);
  }));
  document.querySelectorAll("[data-workflow]").forEach((item) => item.addEventListener("click", () => {
    state.selectedWorkflow = state.workflows.find((workflow) => workflow.id === item.dataset.workflow);
    state.route = "plan";
    render();
  }));
  document.querySelectorAll("[data-workspace-tab]").forEach((item) => item.addEventListener("click", () => {
    state.workspaceTab = item.dataset.workspaceTab;
    render();
  }));

  document.querySelectorAll("[data-cmd-mode]").forEach((item) => item.addEventListener("click", () => {
    state.commandMode = item.dataset.cmdMode;
    render();
  }));
  document.querySelectorAll("[data-terminal-engine]").forEach((item) => item.addEventListener("click", () => {
    state.terminalEngine = item.dataset.terminalEngine;
    if (state.terminalEngine === "pty") {
      state.agentRunId = null;
      if (state.agentRunSocket) state.agentRunSocket.close();
      state.agentRunSocket = null;
    } else if (state.terminalSocket) {
      state.terminalSocket.close();
      state.terminalSocket = null;
    }
    render();
  }));
  document.querySelectorAll("[data-agent-operation]").forEach((item) => item.addEventListener("click", () => {
    state.selectedAgentOperation = item.dataset.agentOperation;
    if (state.agentChoices.components.length === 0 && state.agentContext?.components?.length) state.agentChoices.components = state.agentContext.components.map((component) => component.name);
    render();
  }));
  document.querySelectorAll("[data-agent-input]").forEach((item) => item.addEventListener("input", () => {
    state.agentInputs[item.dataset.agentInput] = item.value;
  }));
  document.querySelectorAll("[data-agent-choice]").forEach((item) => item.addEventListener("change", () => {
    const choice = item.dataset.agentChoice;
    if (choice === "component") {
      state.agentChoices.components = Array.from(document.querySelectorAll('[data-agent-choice="component"]:checked')).map((input) => input.value);
    } else if (choice === "compose") state.agentChoices.compose = item.value === "true";
    else state.agentChoices[choice] = item.value;
  }));
  document.querySelectorAll("[data-command-example]").forEach((item) => item.addEventListener("click", () => {
    const input = document.getElementById("prompt-input");
    if (input) { input.value = item.dataset.commandExample; input.focus(); }
  }));
  const promptForm = document.getElementById("prompt-form");
  if (promptForm) {
    promptForm.addEventListener("submit", (event) => {
      event.preventDefault();
      const input = document.getElementById("prompt-input");
      const val = input.value.trim();
      if (!val) return;
      input.value = "";
      if (state.commandMode === "chat") sendChatMessage(val);
      else sendTerminalCommand(val, true);
    });
  }

  const mentorRobotBtn = document.getElementById("mentor-robot-btn");
  const playMentorAnimation = () => {
    if (mentor3DScene && mentor3DScene.playGreeting) mentor3DScene.playGreeting();
  };
  if (mentorRobotBtn) {
    mentorRobotBtn.addEventListener("click", playMentorAnimation);
  }
  const mentorPlayBtn = document.getElementById("mentor-play-btn");
  if (mentorPlayBtn) mentorPlayBtn.addEventListener("click", playMentorAnimation);

  const planForm = document.getElementById("plan-form");
  if (planForm) planForm.addEventListener("submit", submitPlan);
  const approveButton = document.getElementById("approve-run");
  if (approveButton) approveButton.addEventListener("click", approveRun);
  const terminalForm = document.getElementById("terminal-form");
  if (terminalForm) terminalForm.addEventListener("submit", sendTerminalInput);
  const terminalInput = document.getElementById("terminal-input");
  if (terminalInput) terminalInput.addEventListener("keydown", (event) => {
    if (event.key !== "Enter") return;
    event.preventDefault();
    sendTerminalInput(event);
  });
  const agentForm = document.getElementById("agent-form");
  if (agentForm) agentForm.addEventListener("submit", submitAgentRun);
  if (state.selectedAgentOperation === "dockerize") {
    const agentOptions = document.querySelector("#agent-form .agent-options");
    if (agentOptions && !document.getElementById("agent-compose-choice")) {
      const composeChoice = document.createElement("div");
      composeChoice.id = "agent-compose-choice";
      composeChoice.className = "agent-compose-choice agent-inline-choices";
      composeChoice.innerHTML = `<span>Docker Compose:</span><label><input type="radio" name="compose" value="true" ${state.agentChoices.compose ? "checked" : ""} /> Yes</label><label><input type="radio" name="compose" value="false" ${!state.agentChoices.compose ? "checked" : ""} /> No</label>`;
      agentOptions.parentNode.insertBefore(composeChoice, agentOptions);
      composeChoice.querySelectorAll("input").forEach((input) => input.addEventListener("change", () => { state.agentChoices.compose = input.value === "true"; }));
    }
  }
  const agentConsoleForm = document.getElementById("agent-console-form");
  if (agentConsoleForm) agentConsoleForm.addEventListener("submit", submitAgentConsole);
}

async function submitAgentRun(event) {
  event.preventDefault();
  const liveInputs = { ...state.agentInputs };
  document.querySelectorAll("[data-agent-input]").forEach((input) => {
    liveInputs[input.dataset.agentInput] = input.value;
  });
  state.agentInputs = liveInputs;
  const dryRun = document.getElementById("agent-dry-run");
  const overwrite = document.getElementById("agent-overwrite");
  state.agentDryRun = Boolean(dryRun?.checked);
  state.agentOverwrite = Boolean(overwrite?.checked);
  state.agentStatus = "Starting";
  state.agentOutput = "";
  state.agentCommand = "";
  state.agentRunId = null;
  if (state.agentRunSocket) state.agentRunSocket.close();
  try {
    if (state.selectedAgentOperation === "inspect" && liveInputs.target) {
      try { state.agentContext = await api(`/api/agent/context?target=${encodeURIComponent(liveInputs.target)}`); } catch (contextError) { state.agentContext = null; }
    }
    const result = await api("/api/agent/runs", { method: "POST", body: JSON.stringify({ operation: state.selectedAgentOperation, target: liveInputs.target, goal: liveInputs.goal, plan_dir: liveInputs.plan_dir, spec_dir: liveInputs.spec_dir, output_dir: liveInputs.output_dir, dry_run: state.agentDryRun, overwrite: state.agentOverwrite, components: state.agentChoices.components, compose: state.agentChoices.compose, compose_action: state.agentChoices.composeAction, organization: state.agentChoices.organization, cicd_action: state.agentChoices.cicdAction, cicd_platform: state.agentChoices.cicdPlatform }) });
    state.agentRunId = result.run_id;
    state.agentStatus = "Running";
    render();
  } catch (error) {
    state.agentStatus = "Error";
    state.agentOutput = error.message;
    render();
  }
}

async function submitAgentConsole(event) {
  event.preventDefault();
  const input = document.getElementById("agent-console-input");
  const command = input?.value.trim() || "";
  if (!command) return;
  state.agentConsoleInput = "";
  state.agentStatus = "Starting";
  state.agentOutput = "";
  state.agentCommand = `$ ${command}`;
  state.agentRunId = null;
  if (state.agentRunSocket) state.agentRunSocket.close();
  try {
    const result = await api("/api/agent/console", { method: "POST", body: JSON.stringify({ command }) });
    state.agentRunId = result.run_id;
    state.agentStatus = "Running";
    render();
  } catch (error) {
    state.agentStatus = "Error";
    state.agentOutput = error.message;
    render();
  }
}

function connectAgentRun(runId) {
  if (state.agentRunSocket && [WebSocket.CONNECTING, WebSocket.OPEN].includes(state.agentRunSocket.readyState)) return;
  const protocol = window.location.protocol === "https:" ? "wss" : "ws";
  const socket = new WebSocket(`${protocol}://${window.location.host}/ws/agent-runs/${runId}`);
  state.agentRunSocket = socket;
  socket.onmessage = (event) => handleAgentRunEvent(JSON.parse(event.data));
  socket.onclose = () => { state.agentRunSocket = null; if (state.agentStatus === "Running") state.agentStatus = "Exited"; syncAgentView(); };
  socket.onerror = () => { state.agentStatus = "Error"; syncAgentView(); };
}

function handleAgentRunEvent(event) {
  if (event.type === "command") { state.agentCommand = event.command; state.agentStatus = "Running"; }
  if (event.type === "output") state.agentOutput += event.message || "";
  if (event.type === "complete") {
    state.agentStatus = event.status === "completed" ? "Completed" : "Failed";
    state.agentOutput += `\n[${state.agentStatus} · exit code ${event.exit_code}]\n`;
    render();
    return;
  }
  if (event.type === "error") { state.agentStatus = "Error"; state.agentOutput += `\n${event.message}\n`; }
  syncAgentView();
}

function syncAgentView() {
  const status = document.getElementById("agent-status");
  const command = document.getElementById("agent-command");
  const liveStatus = document.getElementById("agent-live-status");
  const output = document.getElementById("agent-output");
  const runButton = document.getElementById("agent-run-button");
  const consoleInput = document.getElementById("agent-console-input");
  const consoleButton = document.querySelector("#agent-console-form button[type=submit]");
  if (status) status.textContent = state.agentStatus;
  if (command) command.textContent = state.agentCommand || "Waiting for a run";
  if (liveStatus) liveStatus.textContent = state.agentStatus;
  if (output) { output.textContent = state.agentOutput || "Select an operation, provide its required inputs, and run the existing Sohail-Agent capability."; output.scrollTop = output.scrollHeight; }
  const busy = ["Running", "Starting"].includes(state.agentStatus);
  if (runButton) runButton.disabled = busy;
  if (consoleInput) consoleInput.disabled = busy;
  if (consoleButton) consoleButton.disabled = busy;
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
  if (state.terminalSocket && [WebSocket.CONNECTING, WebSocket.OPEN].includes(state.terminalSocket.readyState)) {
    syncTerminalView();
    return;
  }
  const protocol = window.location.protocol === "https:" ? "wss" : "ws";
  const socket = new WebSocket(`${protocol}://${window.location.host}/ws/terminal`);
  state.terminalSocket = socket;
  socket.onopen = () => {
    state.terminalConnection = "Available";
    state.terminalStatus = "Idle";
    if (!state.terminalBannerAdded) {
      state.terminalBuffer = "Sohail Studio terminal\r\n";
      state.terminalBannerAdded = true;
    }
    syncTerminalView();
    while (state.pendingTerminalInputs.length && socket.readyState === WebSocket.OPEN) {
      socket.send(JSON.stringify({ action: "input", data: state.pendingTerminalInputs.shift() }));
    }
    document.getElementById("terminal-input")?.focus();
  };
  socket.onmessage = (event) => {
    const data = JSON.parse(event.data);
    if (data.type === "output" || data.type === "system") appendTerminalOutput(data.message || "");
    if (data.type === "status") {
      state.terminalConnection = data.status === "running" ? "Available" : data.status;
      if (data.status === "running" && state.terminalStatus !== "Running") state.terminalStatus = "Idle";
      syncTerminalView();
    }
    if (data.type === "error") {
      state.terminalStatus = "Error";
      appendTerminalOutput(`\r\n${data.message}\r\n`);
    }
  };
  socket.onclose = () => {
    state.terminalSocket = null;
    state.terminalConnection = "Disconnected";
    state.terminalStatus = "Exited";
    syncTerminalView();
  };
  socket.onerror = () => {
    state.terminalConnection = "Error";
    state.terminalStatus = "Error";
    syncTerminalView();
  };
  syncTerminalView();
}

function sendTerminalInput(event) {
  event.preventDefault();
  const input = document.getElementById("terminal-input");
  if (!input || !input.value.trim()) return;
  sendTerminalCommand(input.value, false);
  input.value = "";
}

function sendTerminalCommand(command, showInChat) {
  const data = `${command}\n`;
  state.terminalStatus = "Running";
  if (showInChat) {
    state.chatHistory.push({ role: "user", content: command });
    state.chatHistory.push({ role: "assistant", content: "" });
    state.terminalCaptureIndex = state.chatHistory.length - 1;
    render();
    const content = document.getElementById("chat-history-content");
    if (content) content.scrollTop = content.scrollHeight;
  } else {
    state.terminalCaptureIndex = null;
    syncTerminalView();
  }
  if (state.terminalSocket && state.terminalSocket.readyState === WebSocket.OPEN) {
    state.terminalSocket.send(JSON.stringify({ action: "input", data }));
  } else {
    state.pendingTerminalInputs.push(data);
    connectTerminal();
  }
}

function appendTerminalOutput(message) {
  state.terminalBuffer += message;
  if (state.terminalCaptureIndex !== null) {
    state.chatHistory[state.terminalCaptureIndex].content += message;
  }
  syncTerminalView();
}

function connectChat() {
  if (state.chatSocket && [WebSocket.CONNECTING, WebSocket.OPEN].includes(state.chatSocket.readyState)) {
    syncTerminalView();
    return;
  }
  const protocol = window.location.protocol === "https:" ? "wss" : "ws";
  const socket = new WebSocket(`${protocol}://${window.location.host}/ws/chat`);
  state.chatSocket = socket;
  state.chatConnection = "Starting";
  state.chatStatus = "Starting";
  syncTerminalView();
  socket.onopen = () => {
    state.chatConnection = "Available";
    state.chatStatus = "Idle";
    syncTerminalView();
    while (state.pendingChatInputs.length && socket.readyState === WebSocket.OPEN) {
      socket.send(JSON.stringify({ action: "input", data: state.pendingChatInputs.shift() }));
    }
  };
  socket.onmessage = (event) => {
    const data = JSON.parse(event.data);
    if (data.type === "output") appendChatOutput(data.message || "");
    if (data.type === "system") appendChatOutput(data.message || "");
    if (data.type === "status") {
      state.chatConnection = ["ready", "running"].includes(data.status) ? "Available" : data.status;
      if (["ready", "running"].includes(data.status) && state.chatStatus !== "Running") state.chatStatus = "Idle";
      syncTerminalView();
    }
    if (data.type === "complete") {
      state.chatStatus = "Idle";
      syncTerminalView();
    }
    if (data.type === "error") {
      state.chatStatus = "Error";
      appendChatOutput(`\r\n${data.message}\r\n`);
    }
  };
  socket.onclose = () => {
    state.chatSocket = null;
    state.chatConnection = "Disconnected";
    state.chatStatus = "Exited";
    syncTerminalView();
  };
  socket.onerror = () => {
    state.chatConnection = "Error";
    state.chatStatus = "Error";
    syncTerminalView();
  };
}

function sendChatMessage(message) {
  const data = `${message}\n`;
  state.chatStatus = "Running";
  state.chatHistory.push({ role: "user", content: message });
  state.chatHistory.push({ role: "assistant", content: "" });
  state.chatCaptureIndex = state.chatHistory.length - 1;
  render();
  const content = document.getElementById("chat-history-content");
  if (content) content.scrollTop = content.scrollHeight;
  if (state.chatSocket && state.chatSocket.readyState === WebSocket.OPEN) {
    state.chatSocket.send(JSON.stringify({ action: "input", data }));
  } else {
    state.pendingChatInputs.push(data);
    connectChat();
  }
}

function appendChatOutput(message) {
  if (state.chatCaptureIndex !== null) {
    state.chatHistory[state.chatCaptureIndex].content += message;
  }
  syncTerminalView();
}

function syncTerminalView() {
  const screen = document.getElementById("terminal-screen");
  const preview = document.getElementById("terminal-preview");
  const status = document.getElementById("terminal-status");
  const homeStatus = document.getElementById("terminal-home-status");
  const connection = document.getElementById("terminal-connection-label");
  const buffer = state.terminalBuffer;
  const activeStatus = state.terminalStatus;
  const activeConnection = state.terminalConnection;
  const captureIndex = state.commandMode === "chat" ? state.chatCaptureIndex : state.terminalCaptureIndex;
  syncTerminalRenderer("terminalRenderer", "terminalRenderedLength");
  syncTerminalRenderer("terminalPreviewRenderer", "terminalPreviewRenderedLength");
  if (screen && !state.terminalRenderer) screen.textContent = buffer;
  if (preview && !state.terminalPreviewRenderer) preview.textContent = buffer ? "Raw PTY connected\nOpen terminal to view live output." : "Sohail Studio terminal\nWaiting for a command…";
  if (status) status.textContent = activeStatus;
  if (homeStatus) homeStatus.textContent = activeStatus;
  if (connection) connection.textContent = activeConnection;
  if (captureIndex !== null) {
    const content = document.querySelector(`[data-chat-index="${captureIndex}"]`);
    if (content) {
      content.innerHTML = renderMarkdown(state.chatHistory[captureIndex].content);
      const history = document.getElementById("chat-history-content");
      if (history) history.scrollTop = history.scrollHeight;
    }
  }
}

function disposeTerminalRenderers() {
  if (state.terminalRenderer) state.terminalRenderer.dispose();
  if (state.terminalPreviewRenderer) state.terminalPreviewRenderer.dispose();
  state.terminalRenderer = null;
  state.terminalPreviewRenderer = null;
  state.terminalRenderedLength = 0;
  state.terminalPreviewRenderedLength = 0;
}

function createTerminalRenderer(element, { preview = false } = {}) {
  if (!element || typeof window.Terminal !== "function") return null;
  const terminal = new window.Terminal({
    convertEol: true,
    cursorBlink: !preview,
    disableStdin: preview,
    fontFamily: '"SFMono-Regular", Consolas, "Liberation Mono", monospace',
    fontSize: preview ? 10 : 13,
    scrollback: 5000,
    theme: { background: "#08090c", foreground: "#c9cfd8", cursor: "#c9cfd8" },
  });
  terminal.open(element);
  return terminal;
}

function initTerminalRenderers() {
  disposeTerminalRenderers();
  const screen = document.getElementById("terminal-screen");
  if (screen) state.terminalRenderer = createTerminalRenderer(screen);
  syncTerminalView();
}

function syncTerminalRenderer(rendererKey, lengthKey) {
  const renderer = state[rendererKey];
  if (!renderer) return;
  if (state[lengthKey] > state.terminalBuffer.length) state[lengthKey] = 0;
  const pending = state.terminalBuffer.slice(state[lengthKey]);
  if (pending) {
    renderer.write(pending);
    state[lengthKey] = state.terminalBuffer.length;
  }
}

async function loadSessions() { try { state.sessions = await api("/api/sessions"); if (state.route === "home" || state.route === "sessions") render(); } catch (_) {} }
async function boot() {
  try {
    const [workflows, agentOperations] = await Promise.all([api("/api/workflows"), api("/api/agent/operations"), loadSessions()]);
    state.workflows = workflows;
    state.agentOperations = agentOperations;
    state.selectedAgentOperation = agentOperations[0]?.id || "inspect";
    connectionLabel.textContent = "Local API connected";
  } catch (error) { connectionLabel.textContent = "API unavailable"; showToast(error.message); }
  render();
}

document.querySelectorAll(".nav-item").forEach((item) => item.addEventListener("click", () => setRoute(item.dataset.route)));
boot();
