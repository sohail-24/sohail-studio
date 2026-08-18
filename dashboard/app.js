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
  return `<section class="workspace-canvas surface-card"><div class="canvas-header"><div><span class="panel-kicker">Workspace canvas</span><h1>Build with context</h1></div><span class="canvas-state"><span class="state-dot"></span> Ready</span></div><div class="workspace-tabs" role="tablist">${tabs.map(([id, label]) => `<button class="workspace-tab ${state.workspaceTab === id ? "active" : ""}" data-workspace-tab="${id}" role="tab" aria-selected="${state.workspaceTab === id}">${label}</button>`).join("")}</div><div class="canvas-content">${workspaceTabContent(state.workspaceTab)}</div>${commandBar()}</section>`;
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

      <button class="execute-button" aria-label="Execute command">▶ <span>${buttonLabels[state.commandMode]}</span></button>
    </form>
    <div class="command-examples"><span>Try</span>${examples.map((example) => `<button type="button" data-command-example="${example}">${example}</button>`).join("")}</div>
  </section>`;
}

function homeView() {
  return `<div class="home-dashboard"><div class="home-columns"><div class="left-column">${knowledgeSphere()}${mentorPanel()}</div><div class="center-column">${workspaceCanvas()}</div><div class="right-column">${advancedPanel()}${homeTerminalPanel()}</div></div></div>`;
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

  // Initialize or re-attach the 3D robot if its container exists in the current view
  setTimeout(() => { initAIMentor3D(); }, 0);
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
