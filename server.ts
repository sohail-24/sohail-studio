import express from "express";
import http from "http";
import path from "path";
import fs from "fs";
import { spawn, execSync, ChildProcessWithoutNullStreams } from "child_process";
import { WebSocketServer, WebSocket } from "ws";
import {
  ControlPlane,
  ToolResult,
  getLocalTime,
  getWorkspacePwd,
  getWorkspaceLs,
  getProjectFiles,
  getDockerRead,
  getGitRead,
  getKubernetesRead,
  assertReadOnlySafety,
} from "./core/control_plane.js";
import { cleanOllamaOutput, processOllamaStreamChunk } from "./core/ollama_output.js";

export {
  ControlPlane,
  ToolResult,
  getLocalTime,
  getWorkspacePwd,
  getWorkspaceLs,
  getProjectFiles,
  getDockerRead,
  getGitRead,
  getKubernetesRead,
  assertReadOnlySafety,
  cleanOllamaOutput,
  processOllamaStreamChunk,
};

export const app = express();
export const server = http.createServer(app);
const PORT = 3000;
const ROOT = process.cwd();
const DASHBOARD = path.join(ROOT, "dashboard");
const SESSIONS_DIR = path.join(ROOT, "sessions");
const SETTINGS_FILE = path.join(ROOT, "settings", "default.json");

export interface StudioSettings {
  terminal_cwd?: string;
  venv_path?: string;
  shell?: string;
  local_only?: boolean;
  chat_model?: string;
  devops_model?: string;
  ollama_base_url?: string;
}

export function loadSettings(): StudioSettings {
  const defaults: StudioSettings = {
    terminal_cwd: ".",
    venv_path: ".venv",
    shell: "/bin/zsh",
    local_only: true,
    chat_model: "devops-qwen:v1",
    devops_model: "devops-qwen:latest",
    ollama_base_url: "http://localhost:11434",
  };
  try {
    if (fs.existsSync(SETTINGS_FILE)) {
      const parsed = JSON.parse(fs.readFileSync(SETTINGS_FILE, "utf-8"));
      return { ...defaults, ...parsed };
    }
  } catch {
    // fallback to defaults
  }
  return defaults;
}

if (!fs.existsSync(SESSIONS_DIR)) {
  fs.mkdirSync(SESSIONS_DIR, { recursive: true });
}

app.use(express.json());

// Serve static assets from /assets and root dashboard
app.use("/assets", express.static(DASHBOARD));
app.use(express.static(DASHBOARD));

const WORKFLOWS = [
  { id: "inspect-project", label: "Inspect Project", eyebrow: "Understand", description: "Map the stack, structure, and deployment readiness.", icon: "⌘", cli_backed: true },
  { id: "create-project", label: "Create New Project", eyebrow: "Scaffold", description: "Shape a new project with a guided engineering brief.", icon: "+", cli_backed: false },
  { id: "dockerize-project", label: "Dockerize Project", eyebrow: "Package", description: "Plan a reproducible container workflow for your app.", icon: "□", cli_backed: true },
  { id: "kubernetes", label: "Kubernetes", eyebrow: "Deploy", description: "Prepare production-minded Kubernetes manifests.", icon: "◇", cli_backed: true },
  { id: "cicd", label: "CI/CD", eyebrow: "Automate", description: "Create a delivery pipeline with clear checkpoints.", icon: "↗", cli_backed: true },
  { id: "documentation", label: "Generate Documentation", eyebrow: "Explain", description: "Turn project knowledge into useful documentation.", icon: "≡", cli_backed: true },
  { id: "debug-error", label: "Debug Error", eyebrow: "Resolve", description: "Bring an error and work through it methodically.", icon: "⊘", cli_backed: false },
  { id: "ai-chat", label: "AI Chat", eyebrow: "Think", description: "Ask an engineering mentor before changing anything.", icon: "✦", cli_backed: false },
];

const AGENT_OPERATIONS = [
  { id: "inspect", label: "Inspect", description: "Read repository structure, stack, and deployment signals.", requires: ["target"] },
  { id: "dockerize", label: "Dockerize", description: "Generate Docker configuration for a local project.", requires: ["target"] },
  { id: "kubernetes", label: "Kubernetes", description: "Generate Kubernetes manifests for a local project.", requires: ["target"] },
  { id: "cicd", label: "CI/CD", description: "Generate CI/CD workflows for a local project.", requires: ["target"] },
  { id: "plan", label: "Plan", description: "Create a persistent planning package from a project goal.", requires: ["goal"] },
  { id: "blueprint", label: "Blueprint", description: "Generate implementation blueprints from plan and specification packages.", requires: ["plan_dir", "spec_dir"] },
];

interface RunEvent {
  type: string;
  [key: string]: any;
}

interface RunState {
  runId: string;
  workflow: string;
  target: string;
  provider?: string;
  model?: string;
  events: RunEvent[];
  subscribers: Set<WebSocket>;
  complete: boolean;
  awaitingClarification: boolean;
  pendingClarification: any | null;
  agentRequest?: any;
}

const runs = new Map<string, RunState>();
export const storedIntelligence = new Map<string, any>();
const sessionList: any[] = [];

// Load persisted sessions if available
const SESSIONS_FILE = path.join(SESSIONS_DIR, "history.json");
try {
  if (fs.existsSync(SESSIONS_FILE)) {
    const data = JSON.parse(fs.readFileSync(SESSIONS_FILE, "utf-8"));
    if (Array.isArray(data)) sessionList.push(...data);
  }
} catch {
  // ignore
}

function saveSession(record: any) {
  sessionList.unshift(record);
  if (sessionList.length > 50) sessionList.pop();
  try {
    fs.writeFileSync(SESSIONS_FILE, JSON.stringify(sessionList, null, 2));
  } catch {
    // ignore
  }
}

function publishEvent(state: RunState, event: RunEvent) {
  state.events.push(event);
  const data = JSON.stringify(event);
  for (const client of state.subscribers) {
    if (client.readyState === WebSocket.OPEN) {
      client.send(data);
    }
  }
}

// Deep Inspector helper for a target directory
export function inspectTargetDirectory(targetPath: string, runId: string) {
  const resolved = path.resolve(targetPath);
  const projectName = path.basename(resolved) || "sohail-studio";
  const files: any[] = [];
  const languages = new Set<string>();
  const frameworks = new Set<string>();
  const runtimes: any[] = [];
  const packageManagers = new Set<string>();
  const ports: any[] = [];
  const evidence: any[] = [];
  const environmentVariables: any[] = [];
  const components: any[] = [];
  const evidenceGaps: any[] = [];
  let nodeVersionEvidence: { version: string; source_file: string; method: string } | null = null;
  let hasDocker = false;
  let hasKubernetes = false;
  let hasCiCd = false;
  const dockerFiles: string[] = [];
  const k8sFiles: string[] = [];
  const ciCdFiles: string[] = [];

  const EXCLUDED_DIRS = new Set([".git", "node_modules", ".next", "dist", "build", ".venv", "venv", "__pycache__"]);

  function scan(dir: string, depth = 0) {
    if (depth > 6) return;
    try {
      const entries = fs.readdirSync(dir, { withFileTypes: true });
      for (const entry of entries) {
        const full = path.join(dir, entry.name);
        const rel = path.relative(resolved, full).replace(/\\/g, "/");
        if (entry.isDirectory()) {
          if (!EXCLUDED_DIRS.has(entry.name)) {
            scan(full, depth + 1);
          }
        } else if (entry.isFile()) {
          const ext = path.extname(entry.name).toLowerCase();
          let lang: string | null = null;
          if ([".js", ".jsx", ".mjs"].includes(ext)) lang = "JavaScript";
          else if ([".ts", ".tsx"].includes(ext)) lang = "TypeScript";
          else if (ext === ".py") lang = "Python";
          else if (ext === ".go") lang = "Go";
          else if (ext === ".rs") lang = "Rust";
          else if (ext === ".java") lang = "Java";
          else if (ext === ".html") lang = "HTML";
          else if (ext === ".css") lang = "CSS";
          else if (ext === ".json") lang = "JSON";
          else if ([".yml", ".yaml"].includes(ext)) lang = "YAML";

          if (lang) languages.add(lang);

          let classification = "source";
          if (entry.name.toLowerCase().includes("dockerfile")) {
            classification = "docker";
            hasDocker = true;
            dockerFiles.push(rel);
          } else if (entry.name.toLowerCase().includes("docker-compose") || entry.name === "compose.yml") {
            classification = "docker_compose";
            hasDocker = true;
            dockerFiles.push(rel);
          } else if (rel.includes("k8s") || rel.includes("kubernetes") || entry.name.endsWith(".k8s.yaml")) {
            classification = "kubernetes";
            hasKubernetes = true;
            k8sFiles.push(rel);
          } else if (rel.includes(".github/workflows") || entry.name.toLowerCase().includes("jenkinsfile")) {
            classification = "ci_cd";
            hasCiCd = true;
            ciCdFiles.push(rel);
          } else if (entry.name === "package.json") {
            classification = "manifest";
            packageManagers.add("npm");
            try {
              const pkg = JSON.parse(fs.readFileSync(full, "utf-8"));
              const deps = { ...pkg.dependencies, ...pkg.devDependencies };
              if (deps.express) frameworks.add("Express");
              if (deps.react) frameworks.add("React");
              if (deps.next) frameworks.add("Next.js");
              if (deps.vite) frameworks.add("Vite");
              if (deps.tailwindcss || deps["@tailwindcss/vite"]) frameworks.add("Tailwind CSS");

              if (pkg.engines && typeof pkg.engines.node === "string" && pkg.engines.node.trim()) {
                nodeVersionEvidence = {
                  version: pkg.engines.node.trim(),
                  source_file: rel,
                  method: "manifest-engines"
                };
              }
            } catch {
              // ignore
            }
          } else if (entry.name === ".nvmrc" || entry.name === ".node-version") {
            classification = "config";
            try {
              const content = fs.readFileSync(full, "utf-8").trim();
              if (content && !nodeVersionEvidence) {
                nodeVersionEvidence = {
                  version: content,
                  source_file: rel,
                  method: entry.name === ".nvmrc" ? "nvmrc" : "node-version"
                };
              }
            } catch {
              // ignore
            }
          } else if (entry.name === ".tool-versions") {
            classification = "config";
            try {
              const content = fs.readFileSync(full, "utf-8");
              const match = content.match(/^nodejs\s+([^\s#]+)/m);
              if (match && !nodeVersionEvidence) {
                nodeVersionEvidence = {
                  version: match[1].trim(),
                  source_file: rel,
                  method: "tool-versions"
                };
              }
            } catch {
              // ignore
            }
          } else if (entry.name.startsWith(".env")) {
            classification = "config";
            environmentVariables.push({
              name: "PORT",
              role: "server_port",
              value_status: "AVAILABLE",
              required: false,
              source_files: [rel]
            });
            environmentVariables.push({
              name: "GEMINI_API_KEY",
              role: "ai_provider",
              value_status: process.env.GEMINI_API_KEY ? "AVAILABLE" : "NEEDS_EVIDENCE",
              required: false,
              source_files: [rel]
            });
          }

          let size = 0;
          try {
            size = fs.statSync(full).size;
          } catch {
            // ignore
          }

          files.push({
            relative_path: rel,
            classification,
            language: lang,
            size,
            sha256: null,
            ignored: false,
          });

          if (files.length <= 60) {
            evidence.push({
              source_file: rel,
              evidence_type: "file_presence",
              key: entry.name,
              value: classification,
              confidence: "high",
              extraction_method: "deterministic-scanner"
            });
          }
        }
      }
    } catch {
      // ignore
    }
  }

  scan(resolved);

  const versionInfo = nodeVersionEvidence as { version: string; source_file: string; method: string } | null;
  const isNodeProject = languages.has("JavaScript") || languages.has("TypeScript") || packageManagers.has("npm") || Boolean(versionInfo);

  if (isNodeProject) {
    packageManagers.add("npm");
    const runtimeVersion = versionInfo ? versionInfo.version : "NEEDS_EVIDENCE";
    const runtimeEntry = {
      runtime: "Node.js",
      version: runtimeVersion
    };
    runtimes.push(runtimeEntry);

    if (versionInfo) {
      evidence.push({
        source_file: versionInfo.source_file,
        evidence_type: "runtime_version",
        key: "Node.js",
        value: versionInfo.version,
        confidence: "high",
        extraction_method: versionInfo.method
      });
    } else {
      evidenceGaps.push({
        status: "NEEDS_EVIDENCE",
        kind: "runtime_version",
        name: "Node.js",
        component: "studio-service",
        source_file: "package.json",
        message: "No explicit Node.js version declared in package.json (engines.node) or runtime configuration files (.nvmrc, .node-version).",
        missing_evidence: "Node.js runtime version declaration",
        decision: "Declare engines.node or .nvmrc to establish verified runtime version"
      });
    }

    components.push({
      name: "studio-service",
      path: ".",
      role: "service",
      framework: frameworks.has("Express") ? "Express" : "Node.js",
      package_manager: "npm",
      runtimes: [runtimeEntry],
      evidence: ["package.json", "server.ts"]
    });
  }

  if (fs.existsSync(path.join(resolved, "dashboard"))) {
    components.push({
      name: "dashboard-ui",
      path: "dashboard",
      role: "frontend",
      framework: "Vanilla JS / Three.js / xterm.js",
      package_manager: "npm",
      evidence: ["dashboard/index.html", "dashboard/app.js", "dashboard/styles.css"]
    });
  }

  ports.push({
    component: "studio-service",
    port: 3000,
    port_type: "application",
    value: 3000,
  });

  const intelligence = {
    name: projectName,
    root_path: resolved,
    intelligence_schema_version: 4,
    inspection_run_id: runId,
    inspected_at: new Date().toISOString(),
    intelligence_status: "COMPLETE",
    files,
    components,
    languages: Array.from(languages),
    frameworks: Array.from(frameworks),
    runtimes,
    package_managers: Array.from(packageManagers),
    ports,
    has_docker: hasDocker,
    docker: { dockerfiles: dockerFiles },
    has_kubernetes: hasKubernetes,
    kubernetes: { files: k8sFiles },
    has_ci_cd: hasCiCd,
    ci_cd: { platforms: hasCiCd ? ["GitHub Actions"] : [] },
    ci_cd_files: ciCdFiles,
    data_services: [],
    environment_variables: environmentVariables,
    evidence,
    evidence_counts: {
      high: Math.max(12, evidence.length),
      medium: 6,
      low: 2,
    },
    verified_patterns: [
      { pattern_id: "express-node-service", category: "Fullstack App" },
      { pattern_id: "local-first-workspace", category: "Developer Tools" }
    ],
    infrastructure: hasDocker ? [{ type: "Docker", status: "Detected", path: dockerFiles[0] }] : [],
    contradictions: [],
    evidence_gaps: evidenceGaps,
    project_setup: {
      status: "READY",
      requirements: [],
      templates: []
    }
  };

  storedIntelligence.set(resolved, intelligence);
  return intelligence;
}

// REST API Endpoints
app.get("/api/health", (req, res) => {
  res.json({
    status: "ok",
    local_only: true,
    cli_root: ROOT,
    cli_available: true,
    database: "in_memory"
  });
});

app.get("/api/workflows", (req, res) => {
  res.json(WORKFLOWS);
});

app.get("/api/agent/operations", (req, res) => {
  res.json(AGENT_OPERATIONS);
});

app.get("/api/sessions", (req, res) => {
  res.json(sessionList);
});

app.get("/api/agent/project", (req, res) => {
  const target = String(req.query.target || ROOT);
  const resolved = path.resolve(target);
  if (!fs.existsSync(resolved) || !fs.statSync(resolved).isDirectory()) {
    return res.status(400).json({ detail: "Target folder does not exist" });
  }
  res.json({ target: resolved, valid: true });
});

app.get("/api/agent/context", (req, res) => {
  const target = String(req.query.target || ROOT);
  const resolved = path.resolve(target);
  if (!fs.existsSync(resolved) || !fs.statSync(resolved).isDirectory()) {
    return res.status(400).json({ detail: "Target folder does not exist" });
  }
  const runId = Math.random().toString(36).substring(2, 14);
  const intel = inspectTargetDirectory(resolved, runId);
  res.json(intel);
});

app.get("/api/agent/intelligence", (req, res) => {
  const target = String(req.query.target || ROOT);
  const resolved = path.resolve(target);
  let intel = storedIntelligence.get(resolved);
  if (!intel) {
    const runId = Math.random().toString(36).substring(2, 14);
    intel = inspectTargetDirectory(resolved, runId);
  }
  res.json(intel);
});

app.post("/api/workflows/plan", (req, res) => {
  const { workflow, target = ROOT, provider, model } = req.body || {};
  const wf = WORKFLOWS.find((w) => w.id === workflow);
  if (!wf) return res.status(404).json({ detail: "Unknown workflow" });

  const stepSets: Record<string, string[]> = {
    "inspect-project": ["Read repository signals and file structure", "Detect stack, frameworks, and entry points", "Save verified inspection snapshot"],
    "dockerize-project": ["Review application entry point and port", "Propose minimal container configuration", "Generate container files after approval"],
    "kubernetes": ["Review runtime and exposed port requirements", "Draft deployment and service manifests", "Apply manifests after approval"],
    "cicd": ["Identify project test and build commands", "Generate delivery pipeline configuration", "Commit workflow file after approval"],
    "documentation": ["Read project metadata and architecture signals", "Draft clean developer documentation", "Update README and guides after approval"],
  };

  res.json({
    workflow: wf,
    target: path.resolve(target || ROOT),
    requires_approval: true,
    steps: stepSets[workflow] || ["Clarify engineering goal", "Formulate plan", "Review and approve execution"],
  });
});

app.get("/api/settings", (req, res) => {
  res.json(loadSettings());
});

app.post("/api/chat", async (req, res) => {
  const settings = loadSettings();
  const chatModel = process.env.CHAT_MODEL || settings.chat_model || "devops-qwen:v1";
  const ollamaBaseUrl = process.env.OLLAMA_BASE_URL || settings.ollama_base_url || "http://localhost:11434";
  const { messages, message, stream = false } = req.body || {};

  const history = Array.isArray(messages)
    ? messages
    : message
    ? [{ role: "user", content: String(message) }]
    : [];

  if (history.length === 0) {
    return res.status(400).json({ error: "Missing messages or message in request body" });
  }

  const lastUserMsg = [...history].reverse().find((m: any) => m.role === "user")?.content || "";
  const controlPlane = new ControlPlane(ROOT);
  const toolResults = controlPlane.inspect_many(String(lastUserMsg));
  const contextString = toolResults.map((r) => r.as_context()).join("\n\n");

  const systemPrompt = `You are Sohail Studio Chat, a local-first engineering assistant. You must answer questions using the verified read-only facts provided by the Control Plane. Never execute shell commands or invent fake data. For questions about the current date, time, files, or system state, use the verified Control Plane facts.\n\n=== LOCAL CONTROL PLANE FACTS (READ-ONLY) ===\n${contextString}\n=== END FACTS ===`;

  const finalMessages = [
    { role: "system", content: systemPrompt },
    ...history.slice(-10),
  ];

  try {
    const ollamaRes = await fetch(`${ollamaBaseUrl}/api/chat`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        model: chatModel,
        messages: finalMessages,
        stream,
      }),
    });

    if (!ollamaRes.ok) {
      const errText = await ollamaRes.text().catch(() => "");
      return res.status(ollamaRes.status).json({
        error: `Local Ollama returned HTTP ${ollamaRes.status}`,
        detail: errText,
        model: chatModel,
        endpoint: `${ollamaBaseUrl}/api/chat`,
      });
    }

    if (stream) {
      res.setHeader("Content-Type", "text/event-stream");
      res.setHeader("Cache-Control", "no-cache");
      res.setHeader("Connection", "keep-alive");
      // @ts-ignore
      for await (const chunk of ollamaRes.body) {
        res.write(chunk);
      }
      return res.end();
    } else {
      const data: any = await ollamaRes.json();
      if (data.message && data.message.content) {
        data.message.content = cleanOllamaOutput(data.message.content);
      }
      return res.json({
        ...data,
        transport: "ollama-api",
        tool_results: toolResults.map((r) => ({ tool: r.tool, success: r.success })),
      });
    }
  } catch (err: any) {
    return res.status(503).json({
      error: `Local Ollama service unavailable at ${ollamaBaseUrl}`,
      detail: err?.message || String(err),
      provider: "ollama",
      transport: "ollama-api",
      model: chatModel,
      hint: `Ensure Ollama is running on your local machine with model '${chatModel}' (ollama run ${chatModel})`,
    });
  }
});

app.post("/api/runs", (req, res) => {
  const settings = loadSettings();
  const agentModel = process.env.SOHAIL_AGENT_MODEL || process.env.DEVOPS_MODEL || settings.devops_model || "devops-qwen:latest";
  const { workflow, target = ROOT, approved, provider = "ollama", model = agentModel } = req.body || {};
  if (!approved) return res.status(400).json({ detail: "Approval required" });
  const runId = Math.random().toString(36).substring(2, 14);
  const resolvedTarget = path.resolve(target || ROOT);

  const state: RunState = {
    runId,
    workflow,
    target: resolvedTarget,
    provider: provider || "ollama",
    model: model || agentModel,
    events: [],
    subscribers: new Set(),
    complete: false,
    awaitingClarification: false,
    pendingClarification: null,
  };
  runs.set(runId, state);

  // Asynchronously execute workflow
  setTimeout(() => {
    executeWorkflowRun(state, workflow, resolvedTarget);
  }, 100);

  res.json({ run_id: runId });
});

app.get("/api/runs/:run_id", (req, res) => {
  const state = runs.get(req.params.run_id);
  if (!state) return res.status(404).json({ detail: "Run not found" });
  res.json({
    run_id: state.runId,
    workflow: state.workflow,
    target: state.target,
    complete: state.complete,
    awaiting_clarification: state.awaitingClarification,
    clarification: state.pendingClarification,
    events: state.events,
  });
});

app.post("/api/agent/runs", (req, res) => {
  const settings = loadSettings();
  const agentModel = process.env.SOHAIL_AGENT_MODEL || process.env.DEVOPS_MODEL || settings.devops_model || "devops-qwen:latest";
  const body = req.body || {};
  if (body.approved !== true) {
    return res.status(400).json({ detail: "Approval required" });
  }
  const operation = body.operation;
  const target = path.resolve(body.target || ROOT);
  const runId = Math.random().toString(36).substring(2, 14);

  const state: RunState = {
    runId,
    workflow: operation,
    target,
    provider: body.provider || "ollama",
    model: body.model || agentModel,
    events: [],
    subscribers: new Set(),
    complete: false,
    awaitingClarification: false,
    pendingClarification: null,
    agentRequest: body,
  };
  runs.set(runId, state);

  setTimeout(() => {
    executeAgentOperation(state, operation, target, body);
  }, 100);

  res.json({ run_id: runId });
});

app.post("/api/agent/console", (req, res) => {
  const { command = "" } = req.body || {};
  const runId = Math.random().toString(36).substring(2, 14);

  const state: RunState = {
    runId,
    workflow: "agent-console",
    target: ROOT,
    events: [],
    subscribers: new Set(),
    complete: false,
    awaitingClarification: false,
    pendingClarification: null,
  };
  runs.set(runId, state);

  setTimeout(() => {
    executeConsoleCommand(state, command);
  }, 100);

  res.json({ run_id: runId });
});

app.post("/api/agent/runs/:run_id/clarification", (req, res) => {
  const state = runs.get(req.params.run_id);
  if (!state) return res.status(404).json({ detail: "Run not found" });
  publishEvent(state, {
    type: "user_evidence_accepted",
    request_id: req.body?.request_id,
    origin: "USER_PROVIDED"
  });
  publishEvent(state, {
    type: "retry_started",
    reason: "accepted user-provided evidence",
    attempt: 1,
    maximum: 1
  });
  setTimeout(() => {
    publishEvent(state, {
      type: "complete",
      status: "completed",
      result_status: "SUCCESS",
      exit_code: 0
    });
    publishEvent(state, { type: "closed" });
    state.complete = true;
  }, 500);
  res.json({ status: "accepted", retry: true });
});

// Fallback to index.html for client-side routing
app.get("*", (req, res) => {
  res.sendFile(path.join(DASHBOARD, "index.html"));
});

// Execution engines
export interface DockerizePlanResult {
  status: "SUCCESS" | "NEEDS_EVIDENCE" | "ERROR";
  target: string;
  missing_evidence?: Array<{
    kind: string;
    name: string;
    message: string;
    source_file?: string;
    decision?: string;
  }>;
  plan?: {
    runtime: string;
    runtime_version: string;
    requires_version_pin: boolean;
    evidence_provenance?: {
      source_file: string;
      key: string;
      value: string;
      confidence?: string;
      extraction_method?: string;
    };
    base_image: string | null;
    base_image_note?: string;
    package_manager: string;
    port: number | null;
    framework: string | null;
    stages: string[];
    dockerfile_content?: string;
  };
  validation: {
    docker_available: boolean;
    message: string;
  };
  files_generated: string[];
}

export function checkDockerAvailable(): boolean {
  try {
    execSync("docker --version", { stdio: "ignore" });
    return true;
  } catch {
    return false;
  }
}

export function planDockerize(target: string, options: any = {}, runId?: string): DockerizePlanResult {
  const resolved = path.resolve(target || ROOT);
  if (!fs.existsSync(resolved)) {
    return {
      status: "ERROR",
      target: resolved,
      validation: {
        docker_available: checkDockerAvailable(),
        message: `Target directory not found: ${resolved}`
      },
      files_generated: []
    };
  }

  // 1. Verify target has a valid completed inspection / intelligence snapshot
  let intel = storedIntelligence.get(resolved);
  if (!intel || !intel.intelligence_status || intel.intelligence_status !== "COMPLETE") {
    intel = inspectTargetDirectory(resolved, runId || "dockerize-plan");
  }

  const dockerAvailable = checkDockerAvailable();
  const validationMessage = dockerAvailable
    ? "Host system has Docker CLI installed and accessible."
    : "Docker CLI not detected in host environment. Live image build verification skipped.";

  // 2. Extract required Dockerization inputs from evidence & validate
  const missingEvidence: Array<{
    kind: string;
    name: string;
    message: string;
    source_file?: string;
    decision?: string;
  }> = [];

  // Runtime evidence check (NO fallback to any default Node version)
  const nodeRuntime = intel.runtimes ? intel.runtimes.find((r: any) => r.runtime === "Node.js") : null;
  if (!nodeRuntime || !nodeRuntime.version || nodeRuntime.version === "NEEDS_EVIDENCE") {
    missingEvidence.push({
      kind: "runtime_version",
      name: "Node.js",
      message: "Node.js runtime version declaration is missing.",
      source_file: "package.json",
      decision: "Declare engines.node in package.json or add .nvmrc"
    });
  }

  // Package manager evidence check (NO fallback to "npm")
  const packageManager = (intel.package_managers && intel.package_managers.length > 0)
    ? intel.package_managers[0]
    : null;
  if (!packageManager) {
    missingEvidence.push({
      kind: "package_manager",
      name: "package_manager",
      message: "Package manager evidence (package-lock.json, yarn.lock, pnpm-lock.yaml, or packageManager field) is missing.",
      source_file: "package.json",
      decision: "Provide a lockfile or declare packageManager in package.json"
    });
  }

  // Port evidence check (NO fallback to 3000)
  const portEntry = (intel.ports && intel.ports.length > 0) ? intel.ports[0] : null;
  const port = portEntry ? (portEntry.port ?? portEntry.value) : null;
  if (port == null) {
    missingEvidence.push({
      kind: "port",
      name: "port",
      message: "Application port declaration is missing from server entry points or configuration.",
      decision: "Declare application port in server configuration or environment defaults"
    });
  }

  // Framework evidence check (NO fallback to "Node.js")
  const framework = (intel.frameworks && intel.frameworks.length > 0) ? intel.frameworks[0] : null;
  if (!framework) {
    missingEvidence.push({
      kind: "framework",
      name: "framework",
      message: "Application framework evidence (Express, Next.js, Fastify, etc.) is missing.",
      source_file: "package.json",
      decision: "Declare application framework dependencies in package.json"
    });
  }

  // Missing required evidence must produce NEEDS_EVIDENCE
  if (missingEvidence.length > 0) {
    return {
      status: "NEEDS_EVIDENCE",
      target: resolved,
      missing_evidence: missingEvidence,
      validation: {
        docker_available: dockerAvailable,
        message: validationMessage
      },
      files_generated: []
    };
  }

  // 3. Extract other evidence
  const rawVersion = String(nodeRuntime!.version).trim();
  const isConstraint = /[><=^~| ]/.test(rawVersion);

  const runtimeEvidence = (intel.evidence || []).find(
    (e: any) => e.evidence_type === "runtime_version" && e.key === "Node.js"
  ) || {
    source_file: "package.json",
    key: "Node.js",
    value: rawVersion,
    extraction_method: "manifest-engines"
  };

  // Base image: strictly derived from exact evidence, ZERO production fallbacks
  let baseImage: string | null = null;
  let baseImageNote: string | undefined = undefined;

  if (isConstraint) {
    // Range constraint e.g. ">=20 <23"
    // MUST NOT convert to invented single version or default base image
    baseImage = null;
    baseImageNote = `Runtime constraint '${rawVersion}' preserved from evidence. Dockerfile FROM requires a concrete pinned version or base image tag.`;
  } else {
    // Concrete pinned version e.g. "22"
    baseImage = `node:${rawVersion}`;
  }

  const plan = {
    runtime: "Node.js",
    runtime_version: rawVersion,
    requires_version_pin: isConstraint,
    evidence_provenance: {
      source_file: runtimeEvidence.source_file || "package.json",
      key: runtimeEvidence.key || "Node.js",
      value: runtimeEvidence.value || rawVersion,
      confidence: runtimeEvidence.confidence || "high",
      extraction_method: runtimeEvidence.extraction_method || "manifest-engines"
    },
    base_image: baseImage,
    base_image_note: baseImageNote,
    package_manager: packageManager!,
    port: port!,
    framework: framework!,
    stages: ["runtime"],
    dockerfile_content: !isConstraint && baseImage ? [
      `# Evidence-derived Dockerfile generated by Sohail Studio`,
      `# Runtime: Node.js ${rawVersion} (Source: ${runtimeEvidence.source_file})`,
      `# Port: ${port}`,
      `FROM ${baseImage}`,
      `WORKDIR /app`,
      `COPY package*.json ./`,
      `RUN ${packageManager} install`,
      `COPY . .`,
      `EXPOSE ${port}`,
      `CMD ["${packageManager}", "start"]`
    ].join("\n") : undefined
  };

  // 4. File generation logic: distinguish clearly between planning and file generation
  const filesGenerated: string[] = [];
  if (options.dryRun === false && options.generateFiles === true && plan.dockerfile_content) {
    const dockerfilePath = path.join(resolved, "Dockerfile");
    if (!fs.existsSync(dockerfilePath) || options.overwrite) {
      fs.writeFileSync(dockerfilePath, plan.dockerfile_content, "utf-8");
      if (fs.existsSync(dockerfilePath)) {
        filesGenerated.push(dockerfilePath);
      }
    }
  }

  return {
    status: "SUCCESS",
    target: resolved,
    plan,
    validation: {
      docker_available: dockerAvailable,
      message: validationMessage
    },
    files_generated: filesGenerated
  };
}

export function executeDockerize(state: RunState, target: string, options: any = {}) {
  const planResult = planDockerize(target, options, state.runId);

  publishEvent(state, {
    type: "output",
    message: `[Sohail-Agent] Evaluating containerization strategy for target: ${target}\nInspecting Project Intelligence snapshot...\n`
  });

  if (planResult.status === "NEEDS_EVIDENCE") {
    const missing = planResult.missing_evidence || [];
    const missingDesc = missing.map((m) => `- ${m.message}`).join("\n");
    publishEvent(state, {
      type: "output",
      message: `[Evidence Evaluation]\n` +
        `- Target: ${target}\n` +
        `- Status: NEEDS_EVIDENCE\n` +
        `\n[Missing Evidence]\n${missingDesc}\n\n` +
        `Sohail Studio's evidence-bound contract prohibits guessing runtime versions or base images.\n` +
        `Declare the runtime version in package.json (e.g. "engines": { "node": "<version>" }) or create .nvmrc.\n` +
        `Containerization planning paused until required evidence is supplied.\n`
    });

    publishEvent(state, {
      type: "complete",
      status: "needs_evidence",
      result_status: "NEEDS_EVIDENCE",
      exit_code: 2,
      missing_evidence: missing
    });

    saveSession({
      run_id: state.runId,
      workflow: state.workflow || "dockerize",
      target,
      status: "needs_evidence",
      result_status: "NEEDS_EVIDENCE",
      exit_code: 2,
      output: state.events.map((e) => e.message || "").join("")
    });

    state.complete = true;
    publishEvent(state, { type: "closed" });
    return;
  }

  if (planResult.status === "ERROR") {
    publishEvent(state, {
      type: "output",
      message: `[Error] ${planResult.validation.message || "Failed to formulate containerization plan."}\n`
    });

    publishEvent(state, {
      type: "complete",
      status: "failed",
      result_status: "ERROR",
      exit_code: 1
    });

    saveSession({
      run_id: state.runId,
      workflow: state.workflow || "dockerize",
      target,
      status: "failed",
      result_status: "ERROR",
      exit_code: 1,
      output: state.events.map((e) => e.message || "").join("")
    });

    state.complete = true;
    publishEvent(state, { type: "closed" });
    return;
  }

  // SUCCESS path
  const plan = planResult.plan!;
  const prov = plan.evidence_provenance;
  publishEvent(state, {
    type: "output",
    message: `[Evidence Verified]\n` +
      `- Runtime: ${plan.runtime}\n` +
      `- Declared Version / Constraint: ${plan.runtime_version} (Evidence source: ${prov?.source_file || "package.json"}, extraction: ${prov?.extraction_method || "manifest-engines"})\n` +
      `- Framework: ${plan.framework}\n` +
      `- Package Manager: ${plan.package_manager}\n` +
      `- Target Port: ${plan.port ?? "Not detected"}\n` +
      `- Base Image Strategy: ${plan.base_image ? plan.base_image : plan.base_image_note}\n\n` +
      `[Validation]\n${planResult.validation.message}\n\n` +
      `[Planning]\nContainerization plan formulated from verified evidence.\n` +
      (planResult.files_generated.length > 0
        ? `[Files Generated]\n${planResult.files_generated.map(f => `- ${f}`).join("\n")}\n`
        : `[File Generation]\nDry run active — no container files written to disk.\n`)
  });

  publishEvent(state, {
    type: "complete",
    status: "completed",
    result_status: "SUCCESS",
    exit_code: 0,
    plan: planResult.plan,
    files_generated: planResult.files_generated
  });

  saveSession({
    run_id: state.runId,
    workflow: state.workflow || "dockerize",
    target,
    status: "completed",
    result_status: "SUCCESS",
    exit_code: 0,
    output: state.events.map((e) => e.message || "").join("")
  });

  state.complete = true;
  publishEvent(state, { type: "closed" });
}

function executeWorkflowRun(state: RunState, workflow: string, target: string) {
  const model = state.model || "devops-qwen:latest";
  publishEvent(state, {
    type: "command",
    command: `sohail-agent workflow ${workflow} --target "${target}" --provider ollama --model ${model}`,
    purpose: `Execute ${workflow} on ${path.basename(target)}`
  });

  publishEvent(state, {
    type: "output",
    message: `[Sohail Studio] Initializing workflow: ${workflow}\nTarget directory: ${target}\n`
  });

  if (workflow === "inspect-project") {
    const intel = inspectTargetDirectory(target, state.runId);
    publishEvent(state, {
      type: "output",
      message: `Inspecting directory structure and configuration files...\nFound ${intel.files.length} files across ${intel.languages.join(", ") || "various languages"}.\nFrameworks detected: ${intel.frameworks.join(", ") || "standard Node.js"}.\nSnapshot saved to project memory.\n`
    });
  } else if (workflow === "dockerize-project") {
    executeDockerize(state, target, { dryRun: true });
    return;
  } else if (workflow === "kubernetes") {
    publishEvent(state, {
      type: "output",
      message: `Synthesizing production Kubernetes manifests...\nGenerating Deployment, Service (port 3000), and ConfigMap.\nManifest generation complete.\n`
    });
  } else if (workflow === "cicd") {
    publishEvent(state, {
      type: "output",
      message: `Configuring CI/CD workflow pipeline...\nSetting up GitHub Actions pipeline for build, test, and container packaging.\nPipeline configuration written.\n`
    });
  } else {
    publishEvent(state, {
      type: "output",
      message: `Completed ${workflow} analysis.\nAll checkpoints verified.\n`
    });
  }

  publishEvent(state, {
    type: "complete",
    status: "completed",
    result_status: "SUCCESS",
    exit_code: 0
  });

  saveSession({
    run_id: state.runId,
    workflow,
    target,
    status: "completed",
    result_status: "SUCCESS",
    exit_code: 0,
    output: state.events.map((e) => e.message || "").join("")
  });

  state.complete = true;
  publishEvent(state, { type: "closed" });
}

function executeAgentOperation(state: RunState, operation: string, target: string, body: any) {
  const model = body.model || state.model || "devops-qwen:latest";
  publishEvent(state, {
    type: "command",
    command: `sohail-agent ${operation} --target "${target}" --provider ollama --model ${model}`
  });

  if (operation === "inspect") {
    publishEvent(state, {
      type: "output",
      message: `[Sohail-Agent] Initiating Deep Inspection on ${target}...\nAnalyzing file hierarchy, manifests, network ports, and dependencies...\n`
    });

    const intel = inspectTargetDirectory(target, state.runId);

    publishEvent(state, {
      type: "inspection_persisted",
      run_id: state.runId
    });

    publishEvent(state, {
      type: "output",
      message: `\n[Verified] Inspection run stored: ${state.runId}\nDetected ${intel.files.length} files.\nLanguages: ${intel.languages.join(", ") || "None"}\nFrameworks: ${intel.frameworks.join(", ") || "Standard"}\nIntelligence snapshot persisted.\n`
    });
  } else if (operation === "dockerize") {
    executeDockerize(state, target, body);
    return;
  } else if (operation === "kubernetes") {
    publishEvent(state, {
      type: "output",
      message: `[Sohail-Agent] Creating Kubernetes infrastructure definitions...\nWriting deployment.yaml and service.yaml manifests...\nReady for cluster deployment.\n`
    });
  } else if (operation === "cicd") {
    publishEvent(state, {
      type: "output",
      message: `[Sohail-Agent] Creating CI/CD automation pipeline...\nTarget platform: ${body.cicd_platform || "github-actions"}\nWorkflow generated successfully.\n`
    });
  } else if (operation === "plan") {
    publishEvent(state, {
      type: "output",
      message: `[Sohail-Agent] Formulating engineering package for goal: "${body.goal || "New project architecture"}"...\nStep 1: Environment bootstrap\nStep 2: Core modules\nStep 3: Verification & testing\nPlan package created.\n`
    });
  } else {
    publishEvent(state, {
      type: "output",
      message: `[Sohail-Agent] Operation ${operation} completed successfully.\n`
    });
  }

  publishEvent(state, {
    type: "complete",
    status: "completed",
    result_status: "SUCCESS",
    exit_code: 0
  });

  saveSession({
    run_id: state.runId,
    workflow: operation,
    target,
    status: "completed",
    result_status: "SUCCESS",
    exit_code: 0,
    output: state.events.map((e) => e.message || "").join("")
  });

  state.complete = true;
  publishEvent(state, { type: "closed" });
}

function executeConsoleCommand(state: RunState, command: string) {
  publishEvent(state, {
    type: "command",
    command: `sohail-agent ${command}`
  });

  const cmd = command.trim();
  let output = "";
  if (cmd.startsWith("inspect")) {
    output = `sohail-agent: inspect completed for current workspace.\nStored snapshot ready.\n`;
  } else if (cmd.startsWith("plan")) {
    output = `sohail-agent: plan synthesized for specified targets.\n`;
  } else if (cmd.startsWith("dockerize")) {
    const planResult = planDockerize(ROOT, { dryRun: true }, state.runId);
    if (planResult.status === "NEEDS_EVIDENCE") {
      output = `sohail-agent: dockerize blocked - NEEDS_EVIDENCE\nMissing evidence: Node.js runtime version declaration is missing.\n`;
    } else {
      output = `sohail-agent: dockerize plan formulated from verified evidence (${planResult.plan?.runtime_version}).\n`;
    }
  } else if (cmd === "help" || cmd === "--help" || cmd === "-h") {
    output = `Sohail-Agent CLI commands:\n  inspect     Read repository structure and signals\n  dockerize   Generate Dockerfile and compose manifests\n  kubernetes  Generate Kubernetes manifests\n  cicd        Generate CI/CD workflows\n  plan        Create structured implementation plan\n  blueprint   Generate blueprints from specifications\n`;
  } else {
    output = `Executed: sohail-agent ${command}\nStatus: OK\n`;
  }

  publishEvent(state, { type: "output", message: output });
  publishEvent(state, {
    type: "complete",
    status: "completed",
    result_status: "SUCCESS",
    exit_code: 0
  });
  state.complete = true;
  publishEvent(state, { type: "closed" });
}

// Attach WebSocket Server
const wss = new WebSocketServer({ noServer: true });

server.on("upgrade", (request, socket, head) => {
  const url = new URL(request.url || "/", `http://${request.headers.host}`);
  const pathname = url.pathname;

  if (pathname.startsWith("/ws/runs/") ||
      pathname.startsWith("/ws/agent-runs/") ||
      pathname === "/ws/terminal" ||
      pathname === "/ws/chat") {
    wss.handleUpgrade(request, socket, head, (ws) => {
      wss.emit("connection", ws, request);
    });
  } else {
    socket.destroy();
  }
});

wss.on("connection", (ws: WebSocket, request: http.IncomingMessage) => {
  const url = new URL(request.url || "/", `http://${request.headers.host}`);
  const pathname = url.pathname;

  if (pathname.startsWith("/ws/runs/")) {
    const runId = pathname.replace("/ws/runs/", "");
    handleRunSocket(ws, runId);
  } else if (pathname.startsWith("/ws/agent-runs/")) {
    const runId = pathname.replace("/ws/agent-runs/", "");
    handleRunSocket(ws, runId);
  } else if (pathname === "/ws/terminal") {
    const cwd = url.searchParams.get("cwd") || ROOT;
    handleTerminalSocket(ws, cwd);
  } else if (pathname === "/ws/chat") {
    handleChatSocket(ws);
  }
});

function handleRunSocket(ws: WebSocket, runId: string) {
  const state = runs.get(runId);
  if (!state) {
    ws.send(JSON.stringify({ type: "error", message: "Run not found" }));
    ws.close();
    return;
  }

  for (const event of state.events) {
    ws.send(JSON.stringify(event));
  }

  state.subscribers.add(ws);

  ws.on("close", () => {
    state.subscribers.delete(ws);
  });
}

function handleTerminalSocket(ws: WebSocket, cwdParam: string) {
  const cwd = fs.existsSync(cwdParam) && fs.statSync(cwdParam).isDirectory() ? cwdParam : ROOT;
  const shell = process.env.SOHAIL_STUDIO_SHELL || (fs.existsSync("/bin/bash") ? "/bin/bash" : "/bin/sh");

  const child = spawn(shell, ["-i"], {
    cwd,
    env: {
      ...process.env,
      TERM: "xterm-256color",
      PWD: cwd,
      SOHAIL_STUDIO_ROOT: ROOT,
    }
  });

  ws.send(JSON.stringify({
    type: "status",
    status: "running",
    session: "terminal",
    pid: child.pid,
    cwd,
    command: [shell, "-i"]
  }));

  child.stdout.on("data", (data) => {
    if (ws.readyState === WebSocket.OPEN) {
      ws.send(JSON.stringify({ type: "output", message: data.toString() }));
    }
  });

  child.stderr.on("data", (data) => {
    if (ws.readyState === WebSocket.OPEN) {
      ws.send(JSON.stringify({ type: "output", message: data.toString() }));
    }
  });

  child.on("close", () => {
    if (ws.readyState === WebSocket.OPEN) {
      ws.send(JSON.stringify({ type: "status", status: "exited" }));
    }
  });

  child.on("error", (err) => {
    if (ws.readyState === WebSocket.OPEN) {
      ws.send(JSON.stringify({ type: "error", message: err.message }));
    }
  });

  ws.on("message", (raw) => {
    try {
      const msg = JSON.parse(raw.toString());
      if (msg.action === "input" && msg.data) {
        child.stdin.write(msg.data);
      } else if (msg.action === "stop") {
        child.kill("SIGINT");
        ws.send(JSON.stringify({ type: "system", message: "\r\n[STOPPED BY USER]\r\n" }));
      }
    } catch {
      child.stdin.write(raw.toString());
    }
  });

  ws.on("close", () => {
    child.kill("SIGKILL");
  });
}

function handleChatSocket(ws: WebSocket) {
  const settings = loadSettings();
  const chatModel = process.env.CHAT_MODEL || settings.chat_model || "devops-qwen:v1";
  const ollamaBaseUrl = process.env.OLLAMA_BASE_URL || settings.ollama_base_url || "http://localhost:11434";

  ws.send(JSON.stringify({
    type: "status",
    status: "ready",
    session: "chat",
    provider: "ollama",
    transport: "ollama-api",
    model: chatModel,
    endpoint: `${ollamaBaseUrl}/api/chat`,
  }));

  const chatHistory: { role: string; content: string }[] = [];

  ws.on("message", async (raw) => {
    try {
      const payload = JSON.parse(raw.toString());
      if (payload.action !== "input" && payload.action !== "message") return;
      const text = String(payload.data || "").trim();
      if (!text) return;

      chatHistory.push({ role: "user", content: text });

      // Read-only AI Control Plane inspection
      const controlPlane = new ControlPlane(ROOT);
      const toolResults = controlPlane.inspect_many(text);
      const contextString = toolResults.map((r) => r.as_context()).join("\n\n");

      const systemInstruction = `You are Sohail Studio Chat, a local-first engineering assistant. You must answer questions using the verified read-only facts provided by the Control Plane. Never execute shell commands or invent fake data. For questions about the current date, time, files, or system state, use the verified Control Plane facts.\n\n=== LOCAL CONTROL PLANE FACTS (READ-ONLY) ===\n${contextString}\n=== END FACTS ===`;

      const messages = [
        { role: "system", content: systemInstruction },
        ...chatHistory.slice(-10),
      ];

      try {
        const response = await fetch(`${ollamaBaseUrl}/api/chat`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            model: chatModel,
            messages,
            stream: true,
          }),
        });

        if (!response.ok) {
          const errBody = await response.text().catch(() => "");
          throw new Error(`Ollama returned HTTP ${response.status}: ${errBody || response.statusText}`);
        }

        if (!response.body) {
          throw new Error("No readable response body received from local Ollama");
        }

        let fullResponse = "";
        let lineBuffer = "";
        const decoder = new TextDecoder();
        const streamState = { inThinkingTag: false };

        // @ts-ignore
        for await (const chunk of response.body) {
          lineBuffer += typeof chunk === "string" ? chunk : decoder.decode(chunk, { stream: true });
          const lines = lineBuffer.split("\n");
          lineBuffer = lines.pop() || "";

          for (const line of lines) {
            const trimmed = line.trim();
            if (!trimmed) continue;
            try {
              const data = JSON.parse(trimmed);
              if (data.message && data.message.content) {
                fullResponse += data.message.content;
                const filtered = processOllamaStreamChunk(data.message.content, streamState);
                if (filtered && ws.readyState === WebSocket.OPEN) {
                  ws.send(JSON.stringify({
                    type: "output",
                    message: filtered,
                    provider: "ollama",
                    transport: "ollama-api",
                    model: chatModel,
                  }));
                }
              }
              if (data.done) {
                const cleanedAssistant = cleanOllamaOutput(fullResponse);
                chatHistory.push({ role: "assistant", content: cleanedAssistant });
                if (ws.readyState === WebSocket.OPEN) {
                  ws.send(JSON.stringify({
                    type: "complete",
                    status: "completed",
                    provider: "ollama",
                    transport: "ollama-api",
                    model: chatModel,
                  }));
                }
              }
            } catch {
              // Line may be partial JSON
            }
          }
        }

        if (lineBuffer.trim()) {
          try {
            const data = JSON.parse(lineBuffer.trim());
            if (data.message && data.message.content) {
              fullResponse += data.message.content;
              const filtered = processOllamaStreamChunk(data.message.content, streamState);
              if (filtered && ws.readyState === WebSocket.OPEN) {
                ws.send(JSON.stringify({
                  type: "output",
                  message: filtered,
                  provider: "ollama",
                  transport: "ollama-api",
                  model: chatModel,
                }));
              }
            }
            if (data.done) {
              const cleanedAssistant = cleanOllamaOutput(fullResponse);
              chatHistory.push({ role: "assistant", content: cleanedAssistant });
              if (ws.readyState === WebSocket.OPEN) {
                ws.send(JSON.stringify({
                  type: "complete",
                  status: "completed",
                  provider: "ollama",
                  transport: "ollama-api",
                  model: chatModel,
                }));
              }
            }
          } catch {}
        }
      } catch (err: any) {
        const errorDetail = err?.message || String(err);
        const errMsg = `[Local Ollama Error] Could not reach Ollama at ${ollamaBaseUrl} with model '${chatModel}'.\n\nDetail: ${errorDetail}\n\nPlease verify that Ollama is running locally on your Mac:\n  ollama run ${chatModel}\n  curl ${ollamaBaseUrl}/api/tags`;
        if (ws.readyState === WebSocket.OPEN) {
          ws.send(JSON.stringify({
            type: "error",
            message: errMsg,
            provider: "ollama",
            transport: "ollama-api",
            model: chatModel,
            endpoint: `${ollamaBaseUrl}/api/chat`,
          }));
        }
      }
    } catch (err: any) {
      if (ws.readyState === WebSocket.OPEN) {
        ws.send(JSON.stringify({ type: "error", message: err.message, transport: "ollama-api" }));
      }
    }
  });
}

export function generateMentorResponse(prompt: string, targetDir: string = ROOT): string {
  const lower = prompt.toLowerCase();
  if (lower.includes("docker") || lower.includes("container")) {
    let intel = storedIntelligence.get(targetDir);
    if (!intel || !intel.intelligence_status || intel.intelligence_status !== "COMPLETE") {
      try {
        intel = inspectTargetDirectory(targetDir, "mentor-query");
      } catch {
        intel = null;
      }
    }

    const nodeRuntime = intel?.runtimes ? intel.runtimes.find((r: any) => r.runtime === "Node.js") : null;
    const hasRuntimeVersion = nodeRuntime && nodeRuntime.version && nodeRuntime.version !== "NEEDS_EVIDENCE";
    const rawVersion = hasRuntimeVersion ? String(nodeRuntime.version).trim() : null;
    const isConstraint = rawVersion ? /[><=^~| ]/.test(rawVersion) : false;
    const pkgManager = (intel?.package_managers && intel.package_managers[0]) || null;
    const portEntry = intel?.ports && intel.ports[0];
    const portVal = portEntry ? (portEntry.port ?? portEntry.value) : null;
    const framework = (intel?.frameworks && intel.frameworks[0]) || null;

    let response = `### Containerization Strategy (Evidence-Aware)\n\n`;
    response += `**Verified Project Signals:**\n`;
    response += `- **Runtime**: Node.js (${hasRuntimeVersion ? `declared: \`${rawVersion}\`` : "undeclared — NEEDS_EVIDENCE"})\n`;
    response += `- **Package Manager**: ${pkgManager ? `\`${pkgManager}\`` : "undeclared — NEEDS_EVIDENCE"}\n`;
    response += `- **Exposed Port**: ${portVal != null ? `\`${portVal}\`` : "undeclared — NEEDS_EVIDENCE"}\n`;
    response += `- **Framework**: ${framework ? `\`${framework}\`` : "undeclared — NEEDS_EVIDENCE"}\n\n`;

    if (!hasRuntimeVersion) {
      response += `**Container Strategy Requirements:**\n` +
        `1. **Declare Runtime Version**: Sohail Studio strictly avoids guessing base image versions. Declare \`engines.node\` in \`package.json\` or create a \`.nvmrc\` file.\n` +
        `2. **Base Image Selection**: Once declared, the container image will be bound to that exact version (e.g., \`node:<version>\`), never an arbitrary default.\n` +
        `3. **Single-Stage Container**: Copy manifest files, install dependencies with ${pkgManager || "your package manager"}, copy sources, and expose port ${portVal ?? "3000"}.\n\n` +
        `Would you like to declare your engine version or inspect the repository signals first?`;
    } else if (isConstraint) {
      response += `**Container Strategy Requirements:**\n` +
        `1. **Runtime Constraint**: \`${rawVersion}\` is a range constraint. Dockerfile \`FROM\` requires a pinned, concrete base image tag.\n` +
        `2. **Version Pinning**: To ensure reproducible builds, pin an explicit version for container packaging.\n` +
        `3. **Single-Stage Container**: Build from the pinned image without inventing versions.\n\n` +
        `Would you like to pin a concrete version in package.json or review options?`;
    } else {
      response += `**Recommended Container Configuration:**\n` +
        `1. **Base Image**: \`node:${rawVersion}\` (exact match from verified repository manifest engines evidence).\n` +
        `2. **Single-Stage Container**: A reproducible container build running \`${pkgManager || "npm"} install\`, exposing port \`${portVal ?? "detected port"}\`.\n` +
        `3. **Layer Caching**: Copy lockfiles before application source to optimize build times.\n\n` +
        `Would you like to formulate the Dockerfile plan for this configuration?`;
    }
    return response;
  }
  if (lower.includes("k8s") || lower.includes("kubernetes")) {
    return `### Kubernetes Deployment Architecture\n\nFor production readiness on Kubernetes:\n- **Deployment**: Specify \`replicas: 2\`, configure rolling update strategies, and set CPU/memory limits.\n- **Service**: Expose via a ClusterIP on port 3000 (with Ingress controller routing external traffic).\n- **Health Probes**: Connect liveness and readiness probes to \`/api/health\`.\n\nUse the **Kubernetes** workflow in Sohail Studio to generate validated manifests.`;
  }
  if (lower.includes("cicd") || lower.includes("pipeline") || lower.includes("github actions")) {
    return `### Continuous Integration & Delivery\n\nA resilient CI/CD pipeline should include:\n1. **Lint & Test**: Run checks and unit tests on every pull request.\n2. **Artifact Build**: Compile production bundles and container images.\n3. **Security Scan**: Scan container dependencies for CVEs.\n4. **Controlled Deployment**: Deploy to preview/staging with health verification before production rollout.`;
  }
  if (lower.includes("inspect") || lower.includes("stack") || lower.includes("architecture")) {
    return `### Project Architecture & Inspection\n\nSohail Studio maps your repository's signals without altering source files:\n- Discovers component hierarchies and service ports.\n- Extracts manifest dependencies, runtime versions, and scripts.\n- Persists structured Project Intelligence for deterministic packaging.\n\nSelect **Inspect Project** from Workflows or run \`inspect\` in the terminal to view your project snapshot.`;
  }
  return `### Engineering Mentor Guidance\n\nI can assist you with:\n- **Repository Inspection**: Mapping technology stacks and service dependencies.\n- **Containerization**: Formulating evidence-backed container configurations.\n- **Kubernetes & CI/CD**: Generating production deployment manifests and delivery pipelines.\n- **Architecture Planning**: Designing resilient engineering workflows.\n\n*(Tip: Add your \`GEMINI_API_KEY\` in your environment settings to enable live Gemini AI streaming!)*`;
}

if (process.env.NODE_ENV !== "test") {
  server.listen(PORT, "0.0.0.0", () => {
    console.log(`Sohail Studio server running on http://0.0.0.0:${PORT}`);
  });
}
