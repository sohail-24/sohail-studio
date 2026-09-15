/**
 * AI Control Plane (Node.js/TypeScript)
 * Equivalent to historical core/control_plane.py
 *
 * Provides safe, bounded, READ-ONLY inspection of the local workspace and system clock
 * to supply factual grounding to local Ollama Chat (devops-qwen:v1).
 *
 * Safety Mandate:
 * - The Control Plane is strictly READ-ONLY.
 * - Under NO circumstances may it execute mutating commands (rm, mv, cp, write, delete,
 *   git commit, git push, docker build/run/rm, kubectl apply/delete).
 * - Model output can never become an arbitrary shell command.
 */

import fs from "node:fs";
import path from "node:path";
import { execSync } from "node:child_process";

export const EXCLUDED_DIRS = new Set([
  ".git",
  ".venv",
  "venv",
  "__pycache__",
  "node_modules",
  ".pytest_cache",
  ".next",
  "dist",
  "build",
  ".cache"
]);

export const FORBIDDEN_MUTATING_PATTERNS: RegExp[] = [
  /\brm\b/i,
  /\bmv\b/i,
  /\bcp\b/i,
  /\bmkdir\b/i,
  /\btouch\b/i,
  /\btruncate\b/i,
  /\bchmod\b/i,
  /\bchown\b/i,
  /\bwrite\b/i,
  /\bdelete\b/i,
  /\bgit\s+(commit|push|rebase|reset|merge|checkout|branch\s+-[dD])/i,
  /\bdocker\s+(build|run|rm|rmi|kill|stop|start|push|compose\s+up|compose\s+down)/i,
  /\bkubectl\s+(apply|delete|edit|scale|rollout|create|replace|patch)/i,
  /\b(npm|yarn|pnpm|bun)\s+(install|add|remove|uninstall|update)/i,
  /\b(apt|apk|yum|brew|pip|curl.*\|\s*sh|wget.*\|\s*sh)/i,
];

export function assertReadOnlySafety(actionOrCommand: string): void {
  for (const pattern of FORBIDDEN_MUTATING_PATTERNS) {
    if (pattern.test(actionOrCommand)) {
      throw new Error(
        `Safety Violation: Operation '${actionOrCommand}' is strictly prohibited. The Control Plane is READ-ONLY.`
      );
    }
  }
}

export class ToolResult {
  constructor(
    public tool: string,
    public success: boolean,
    public data: any,
    public error?: string
  ) {}

  as_context(): string {
    if (!this.success) {
      return `[Tool: ${this.tool}] Error: ${this.error || "Execution failed"}`;
    }
    const formatted = typeof this.data === "string" ? this.data : JSON.stringify(this.data, null, 2);
    return `[Tool: ${this.tool}]\n${formatted}`;
  }

  asContext(): string {
    return this.as_context();
  }
}

/**
 * 1. local_time
 * Uses the REAL dynamic local system clock at evaluation time.
 * Never hardcoded, never static in system prompt.
 * Returns: date, time, day, timezone
 */
export function getLocalTime(): ToolResult {
  const now = new Date();

  const year = now.getFullYear();
  const month = String(now.getMonth() + 1).padStart(2, "0");
  const dayOfMonth = String(now.getDate()).padStart(2, "0");
  const dateStr = `${year}-${month}-${dayOfMonth}`;

  const hours = String(now.getHours()).padStart(2, "0");
  const minutes = String(now.getMinutes()).padStart(2, "0");
  const seconds = String(now.getSeconds()).padStart(2, "0");
  const timeStr = `${hours}:${minutes}:${seconds}`;

  const daysOfWeek = ["Sunday", "Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday"];
  const dayStr = daysOfWeek[now.getDay()];

  let timeZone = "UTC";
  try {
    timeZone = Intl.DateTimeFormat().resolvedOptions().timeZone || "UTC";
  } catch {
    timeZone = "UTC";
  }

  const offsetMin = -now.getTimezoneOffset();
  const sign = offsetMin >= 0 ? "+" : "-";
  const absOffset = Math.abs(offsetMin);
  const offHours = String(Math.floor(absOffset / 60)).padStart(2, "0");
  const offMins = String(absOffset % 60).padStart(2, "0");
  const timezoneStr = `${timeZone} (UTC${sign}${offHours}:${offMins})`;

  return new ToolResult("local_time", true, {
    date: dateStr,
    time: timeStr,
    day: dayStr,
    timezone: timezoneStr,
    iso: now.toISOString(),
  });
}

/**
 * 2. workspace_pwd
 * Returns the current workspace working directory path.
 * Read-only.
 */
export function getWorkspacePwd(root: string = process.cwd()): ToolResult {
  return new ToolResult("workspace_pwd", true, {
    cwd: path.resolve(root),
  });
}

/**
 * 3. workspace_ls
 * Lists entries in the workspace root or safe relative subpath within the workspace.
 * Bounded inspection: strictly excludes .git, .venv, node_modules, etc.
 * Read-only.
 */
export function getWorkspaceLs(root: string = process.cwd(), subDir: string = ""): ToolResult {
  const resolvedRoot = path.resolve(root);
  const targetDir = subDir ? path.resolve(resolvedRoot, subDir) : resolvedRoot;

  // Boundary check: target must be within workspace
  const relative = path.relative(resolvedRoot, targetDir);
  if (relative.startsWith("..") || path.isAbsolute(relative)) {
    return new ToolResult("workspace_ls", false, null, "Access denied: Path outside workspace boundary");
  }

  if (!fs.existsSync(targetDir)) {
    return new ToolResult("workspace_ls", false, null, `Directory not found: ${subDir || "."}`);
  }

  try {
    const entries = fs.readdirSync(targetDir, { withFileTypes: true });
    const items = entries
      .filter((e) => !EXCLUDED_DIRS.has(e.name))
      .map((e) => ({
        name: e.name,
        type: e.isDirectory() ? "directory" : "file",
      }))
      .sort((a, b) => {
        if (a.type === b.type) return a.name.localeCompare(b.name);
        return a.type === "directory" ? -1 : 1;
      });

    return new ToolResult("workspace_ls", true, {
      path: relative || ".",
      count: items.length,
      items,
    });
  } catch (err: any) {
    return new ToolResult("workspace_ls", false, null, err?.message || String(err));
  }
}

/**
 * 4. project_files
 * Bounded file discovery within the workspace.
 * Skips .git, .venv, node_modules, etc.
 * If searching for a specific file/folder and it is missing, produces a factual error.
 */
export function getProjectFiles(root: string = process.cwd(), query?: string): ToolResult {
  const resolvedRoot = path.resolve(root);
  const foundFiles: { path: string; type: "file" | "directory" }[] = [];
  const maxDepth = 4;
  const maxFiles = 250;

  function traverse(dir: string, depth: number) {
    if (depth > maxDepth || foundFiles.length >= maxFiles) return;
    try {
      const entries = fs.readdirSync(dir, { withFileTypes: true });
      for (const entry of entries) {
        if (EXCLUDED_DIRS.has(entry.name)) continue;
        const fullPath = path.join(dir, entry.name);
        const relPath = path.relative(resolvedRoot, fullPath);
        foundFiles.push({
          path: relPath,
          type: entry.isDirectory() ? "directory" : "file",
        });
        if (entry.isDirectory()) {
          traverse(fullPath, depth + 1);
        }
        if (foundFiles.length >= maxFiles) break;
      }
    } catch {
      // safe ignore unreadable entries
    }
  }

  traverse(resolvedRoot, 1);

  if (query && query.trim()) {
    const rawQuery = query.trim();
    const stopWords = new Set([
      "find", "my", "folder", "directory", "dir", "file", "files", "where",
      "is", "the", "search", "locate", "for", "please", "can", "you", "show", "me"
    ]);
    const terms = rawQuery
      .toLowerCase()
      .replace(/[^a-z0-9_.-]/g, " ")
      .split(/\s+/)
      .filter((w) => w.length > 0 && !stopWords.has(w));

    const searchTerm = terms.length > 0 ? terms[0] : rawQuery.toLowerCase();

    const matched = foundFiles.filter((f) => {
      const p = f.path.toLowerCase();
      const base = path.basename(f.path).toLowerCase();
      if (base === searchTerm || base.startsWith(searchTerm)) return true;
      if (p.includes(searchTerm)) return true;
      return terms.some((t) => p.includes(t));
    });

    if (matched.length === 0) {
      const missingName = terms.join(" ") || rawQuery;
      return new ToolResult(
        "project_files",
        false,
        null,
        `File or directory '${missingName}' not found in workspace`
      );
    }

    return new ToolResult("project_files", true, {
      query: rawQuery,
      matched_count: matched.length,
      files: matched.slice(0, 50),
    });
  }

  return new ToolResult("project_files", true, {
    total_files: foundFiles.length,
    files: foundFiles.slice(0, 100),
  });
}

/**
 * 5. docker_read
 * Safe read-only inspection of Docker artifacts and daemon status.
 * Never runs docker build, docker run, docker rm, etc.
 */
export function getDockerRead(root: string = process.cwd()): ToolResult {
  const resolvedRoot = path.resolve(root);
  const dockerFiles: string[] = [];
  const candidates = [
    "Dockerfile",
    "docker-compose.yml",
    "docker-compose.yaml",
    "compose.yaml",
    "compose.yml",
    ".dockerignore"
  ];

  for (const f of candidates) {
    if (fs.existsSync(path.join(resolvedRoot, f))) {
      dockerFiles.push(f);
    }
  }

  let daemonStatus = "not running or not accessible";
  let dockerVersion = "unknown";

  try {
    const ver = execSync("docker version --format '{{.Server.Version}}'", {
      timeout: 1500,
      stdio: ["pipe", "pipe", "pipe"],
      encoding: "utf-8",
    });
    if (ver && ver.trim()) {
      daemonStatus = "running";
      dockerVersion = ver.trim();
    }
  } catch {
    daemonStatus = "docker daemon not running or docker CLI not found in PATH";
  }

  return new ToolResult("docker_read", true, {
    read_only: true,
    docker_files_found: dockerFiles,
    has_dockerfile: dockerFiles.includes("Dockerfile"),
    docker_daemon: daemonStatus,
    docker_version: dockerVersion,
  });
}

/**
 * 6. git_read
 * Safe read-only inspection of Git repository status.
 * Never runs git commit, git push, git checkout, git rebase, etc.
 */
export function getGitRead(root: string = process.cwd()): ToolResult {
  const resolvedRoot = path.resolve(root);
  const gitDir = path.join(resolvedRoot, ".git");

  if (!fs.existsSync(gitDir)) {
    return new ToolResult("git_read", true, {
      read_only: true,
      is_git_repo: false,
      status: "Not a git repository (no .git directory present in workspace root)",
    });
  }

  let branch = "unknown";
  let statusSummary = "clean";
  let recentCommits: string[] = [];

  try {
    branch = execSync("git branch --show-current", {
      cwd: resolvedRoot,
      timeout: 1500,
      stdio: ["pipe", "pipe", "pipe"],
      encoding: "utf-8",
    }).trim();
  } catch {
    // ignore
  }

  try {
    const rawStatus = execSync("git status --short", {
      cwd: resolvedRoot,
      timeout: 1500,
      stdio: ["pipe", "pipe", "pipe"],
      encoding: "utf-8",
    }).trim();
    statusSummary = rawStatus ? rawStatus : "working tree clean";
  } catch {
    // ignore
  }

  try {
    const log = execSync("git log -n 5 --oneline", {
      cwd: resolvedRoot,
      timeout: 1500,
      stdio: ["pipe", "pipe", "pipe"],
      encoding: "utf-8",
    }).trim();
    recentCommits = log ? log.split("\n") : [];
  } catch {
    // ignore
  }

  return new ToolResult("git_read", true, {
    read_only: true,
    is_git_repo: true,
    branch,
    status: statusSummary,
    recent_commits: recentCommits,
  });
}

/**
 * 7. kubernetes_read
 * Safe read-only inspection of Kubernetes manifests and kubectl client status.
 * Never runs kubectl apply, kubectl delete, kubectl edit, etc.
 */
export function getKubernetesRead(root: string = process.cwd()): ToolResult {
  const resolvedRoot = path.resolve(root);
  const k8sManifests: string[] = [];

  const candidateDirs = ["k8s", "kubernetes", "manifests", "deploy"];
  for (const d of candidateDirs) {
    const p = path.join(resolvedRoot, d);
    if (fs.existsSync(p) && fs.statSync(p).isDirectory()) {
      try {
        const files = fs.readdirSync(p).filter((f) => f.endsWith(".yaml") || f.endsWith(".yml"));
        k8sManifests.push(...files.map((f) => path.join(d, f)));
      } catch {}
    }
  }

  // Also check top-level yaml files for apiVersion/kind
  try {
    const topFiles = fs.readdirSync(resolvedRoot).filter((f) => f.endsWith(".yaml") || f.endsWith(".yml"));
    for (const f of topFiles) {
      try {
        const content = fs.readFileSync(path.join(resolvedRoot, f), "utf-8").slice(0, 500);
        if (content.includes("apiVersion:") && content.includes("kind:")) {
          k8sManifests.push(f);
        }
      } catch {}
    }
  } catch {}

  let kubectlStatus = "kubectl not found or cluster not connected";
  try {
    const ver = execSync("kubectl version --client --output=json", {
      timeout: 1500,
      stdio: ["pipe", "pipe", "pipe"],
      encoding: "utf-8",
    });
    if (ver) {
      kubectlStatus = "kubectl client available (read-only)";
    }
  } catch {
    kubectlStatus = "No active Kubernetes cluster connection or kubectl not found in PATH";
  }

  return new ToolResult("kubernetes_read", true, {
    read_only: true,
    manifests_found: k8sManifests,
    kubectl_status: kubectlStatus,
  });
}

/**
 * ControlPlane Class
 * Direct Node.js/TypeScript equivalent to historical ControlPlane(ROOT)
 */
export class ControlPlane {
  public root: string;

  constructor(root: string = process.cwd()) {
    this.root = path.resolve(root);
  }

  local_time(): ToolResult {
    return getLocalTime();
  }

  workspace_pwd(): ToolResult {
    return getWorkspacePwd(this.root);
  }

  workspace_ls(subDir?: string): ToolResult {
    return getWorkspaceLs(this.root, subDir);
  }

  project_files(query?: string): ToolResult {
    return getProjectFiles(this.root, query);
  }

  docker_read(): ToolResult {
    return getDockerRead(this.root);
  }

  git_read(): ToolResult {
    return getGitRead(this.root);
  }

  kubernetes_read(): ToolResult {
    return getKubernetesRead(this.root);
  }

  /**
   * inspect_many(message, explicitTools)
   * Dispatches relevant read-only tools based on user prompt or explicit tool list.
   */
  inspect_many(message: string, explicitTools?: string[]): ToolResult[] {
    const lower = (message || "").toLowerCase();
    const results: ToolResult[] = [];
    const toolsToRun = new Set<string>(explicitTools || []);

    if (!explicitTools || explicitTools.length === 0) {
      // 1. local_time
      if (
        lower.includes("date") ||
        lower.includes("today") ||
        lower.includes("time") ||
        lower.includes("clock") ||
        lower.includes("day") ||
        lower.includes("now") ||
        lower.includes("timezone")
      ) {
        toolsToRun.add("local_time");
      }

      // 2. workspace_pwd
      if (
        lower.includes("pwd") ||
        lower.includes("working directory") ||
        lower.includes("where am i") ||
        lower.includes("current dir") ||
        lower.includes("location") ||
        lower.includes("what directory")
      ) {
        toolsToRun.add("workspace_pwd");
      }

      // 3. workspace_ls
      if (
        lower.includes("ls") ||
        lower.includes("list") ||
        lower.includes("show files") ||
        lower.includes("what files") ||
        lower.includes("dir ") ||
        lower.includes("directory contents")
      ) {
        toolsToRun.add("workspace_ls");
      }

      // 4. project_files
      if (
        lower.includes("find") ||
        lower.includes("search") ||
        lower.includes("locate") ||
        lower.includes("sms") ||
        lower.includes("file") ||
        lower.includes("folder") ||
        lower.includes("where is")
      ) {
        toolsToRun.add("project_files");
      }

      // 5. docker_read
      if (
        lower.includes("docker") ||
        lower.includes("container") ||
        lower.includes("dockerfile") ||
        lower.includes("compose")
      ) {
        toolsToRun.add("docker_read");
      }

      // 6. git_read
      if (
        lower.includes("git") ||
        lower.includes("branch") ||
        lower.includes("commit") ||
        lower.includes("repo") ||
        lower.includes("remote")
      ) {
        toolsToRun.add("git_read");
      }

      // 7. kubernetes_read
      if (
        lower.includes("k8s") ||
        lower.includes("kubernetes") ||
        lower.includes("kubectl") ||
        lower.includes("cluster") ||
        lower.includes("pod") ||
        lower.includes("deployment")
      ) {
        toolsToRun.add("kubernetes_read");
      }

      // Default baseline: if general message, provide basic workspace context
      if (toolsToRun.size === 0) {
        toolsToRun.add("local_time");
        toolsToRun.add("workspace_pwd");
        toolsToRun.add("workspace_ls");
      }
    }

    if (toolsToRun.has("local_time")) results.push(this.local_time());
    if (toolsToRun.has("workspace_pwd")) results.push(this.workspace_pwd());
    if (toolsToRun.has("workspace_ls")) results.push(this.workspace_ls());
    if (toolsToRun.has("project_files")) results.push(this.project_files(message));
    if (toolsToRun.has("docker_read")) results.push(this.docker_read());
    if (toolsToRun.has("git_read")) results.push(this.git_read());
    if (toolsToRun.has("kubernetes_read")) results.push(this.kubernetes_read());

    return results;
  }
}
