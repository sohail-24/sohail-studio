import fs from "fs";
import path from "path";
import { execFile } from "child_process";
import { promisify } from "util";

const execFileAsync = promisify(execFile);

export const READ_ONLY_TOOLS = [
  "local_time",
  "workspace_pwd",
  "workspace_ls",
  "project_files",
  "docker_read",
  "git_read",
  "kubernetes_read",
] as const;

export type ReadOnlyToolName = typeof READ_ONLY_TOOLS[number];

export const FORBIDDEN_OPERATIONS = [
  "rm", "mv", "cp", "mkdir", "touch", "write", "delete", "unlink", "truncate",
  "git commit", "git push", "git checkout", "git reset", "git rebase", "git merge",
  "docker build", "docker run", "docker rm", "docker rmi", "docker stop",
  "kubectl apply", "kubectl delete", "kubectl create", "kubectl patch",
  "npm install", "yarn add", "pnpm add", "bun add"
] as const;

export interface LocalTimeEvidence {
  date: string;
  time: string;
  day: string;
  timezone: string;
  iso: string;
  timestamp: number;
}

export interface WorkspacePwdEvidence {
  pwd: string;
  root: string;
  basename: string;
}

export interface WorkspaceLsEntry {
  name: string;
  type: "file" | "directory" | "other";
  size?: number;
}

export interface WorkspaceLsEvidence {
  target_path: string;
  relative_path: string;
  exists: boolean;
  is_directory: boolean;
  entries: WorkspaceLsEntry[];
  error?: string;
}

export interface ProjectFileMatch {
  path: string;
  name: string;
  type: "file" | "directory";
  size?: number;
}

export interface ProjectFilesEvidence {
  query: string;
  found: boolean;
  count: number;
  matches: ProjectFileMatch[];
  searched_in: string;
  message: string;
}

export interface DockerReadEvidence {
  docker_files: Array<{
    name: string;
    path: string;
    exists: boolean;
    size?: number;
  }>;
  docker_cli_available: boolean;
  cli_readings?: {
    version?: string;
    containers?: string;
  };
  message: string;
}

export interface GitReadEvidence {
  is_git_repository: boolean;
  branch: string | null;
  status: string | null;
  recent_commits: string[] | null;
  remotes: string[] | null;
  message: string;
}

export interface KubernetesReadEvidence {
  manifests_found: Array<{
    path: string;
    kind?: string;
    apiVersion?: string;
  }>;
  kubectl_available: boolean;
  cluster_info?: string | null;
  message: string;
}

export interface ControlPlaneEvidence {
  tool: ReadOnlyToolName;
  status: "success" | "error";
  data?: any;
  error?: string;
}

export interface EvidenceRequirementPlan {
  required: boolean;
  tools: ReadOnlyToolName[];
  searchParams?: Record<string, any>;
}

export class ReadOnlyControlPlane {
  private workspaceRoot: string;

  constructor(workspaceRoot?: string) {
    this.workspaceRoot = path.resolve(workspaceRoot || process.cwd());
  }

  public getWorkspaceRoot(): string {
    return this.workspaceRoot;
  }

  /**
   * Tool 1: local_time
   * Returns current dynamic system clock data. Never hardcoded.
   */
  public getLocalTime(): LocalTimeEvidence {
    const now = new Date();
    const dayNames = ["Sunday", "Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday"];
    const day = dayNames[now.getDay()];

    const year = now.getFullYear();
    const month = String(now.getMonth() + 1).padStart(2, "0");
    const dateStr = String(now.getDate()).padStart(2, "0");
    const date = `${year}-${month}-${dateStr}`;

    const hours = String(now.getHours()).padStart(2, "0");
    const minutes = String(now.getMinutes()).padStart(2, "0");
    const seconds = String(now.getSeconds()).padStart(2, "0");
    const time = `${hours}:${minutes}:${seconds}`;

    let timezone = "UTC";
    try {
      timezone = Intl.DateTimeFormat().resolvedOptions().timeZone || "UTC";
    } catch {
      // fallback
    }

    return {
      date,
      time,
      day,
      timezone,
      iso: now.toISOString(),
      timestamp: now.getTime(),
    };
  }

  /**
   * Tool 2: workspace_pwd
   * Returns factual workspace path.
   */
  public getWorkspacePwd(): WorkspacePwdEvidence {
    return {
      pwd: this.workspaceRoot,
      root: this.workspaceRoot,
      basename: path.basename(this.workspaceRoot),
    };
  }

  /**
   * Tool 3: workspace_ls
   * Lists entries in the workspace or safe relative directory.
   */
  public getWorkspaceLs(subpath: string = "."): WorkspaceLsEvidence {
    const target = path.resolve(this.workspaceRoot, subpath);

    // Prevent directory traversal outside workspace root
    if (!target.startsWith(this.workspaceRoot)) {
      return {
        target_path: target,
        relative_path: subpath,
        exists: false,
        is_directory: false,
        entries: [],
        error: "Access denied: requested path resolves outside the workspace boundary.",
      };
    }

    if (!fs.existsSync(target)) {
      return {
        target_path: target,
        relative_path: path.relative(this.workspaceRoot, target) || ".",
        exists: false,
        is_directory: false,
        entries: [],
        error: `Path does not exist: ${subpath}`,
      };
    }

    const stat = fs.statSync(target);
    if (!stat.isDirectory()) {
      return {
        target_path: target,
        relative_path: path.relative(this.workspaceRoot, target),
        exists: true,
        is_directory: false,
        entries: [
          {
            name: path.basename(target),
            type: "file",
            size: stat.size,
          },
        ],
      };
    }

    const rawNames = fs.readdirSync(target);
    const entries: WorkspaceLsEntry[] = [];

    for (const name of rawNames) {
      const full = path.join(target, name);
      try {
        const entryStat = fs.statSync(full);
        entries.push({
          name,
          type: entryStat.isDirectory() ? "directory" : entryStat.isFile() ? "file" : "other",
          size: entryStat.isFile() ? entryStat.size : undefined,
        });
      } catch {
        entries.push({ name, type: "other" });
      }
    }

    return {
      target_path: target,
      relative_path: path.relative(this.workspaceRoot, target) || ".",
      exists: true,
      is_directory: true,
      entries,
    };
  }

  /**
   * Tool 4: project_files
   * Searches for files or folders matching a query within the configured workspace.
   * Reports factually: if no matches, reports found: false and no hallucinated paths.
   */
  public searchProjectFiles(query: string = ""): ProjectFilesEvidence {
    const trimmed = query.trim();
    if (!trimmed) {
      return {
        query: "",
        found: false,
        count: 0,
        matches: [],
        searched_in: this.workspaceRoot,
        message: "No search term provided.",
      };
    }

    // Check if query is an explicit path that resolves outside workspace boundary
    const isExplicitPath = trimmed.startsWith("/") || trimmed.startsWith("..") || trimmed.includes(path.sep);
    if (isExplicitPath) {
      const resolved = path.resolve(this.workspaceRoot, trimmed);
      if (!resolved.startsWith(this.workspaceRoot)) {
        return {
          query: trimmed,
          found: false,
          count: 0,
          matches: [],
          searched_in: this.workspaceRoot,
          message: `The requested path '${trimmed}' is outside the configured workspace boundary (${this.workspaceRoot}). Only the configured workspace was searched.`,
        };
      }
    }

    const queryLower = trimmed.toLowerCase();
    const matches: ProjectFileMatch[] = [];
    const ignoredDirs = new Set(["node_modules", ".git", "dist", ".cache"]);

    const walk = (dir: string, depth: number) => {
      if (depth > 10) return;
      let entries: string[] = [];
      try {
        entries = fs.readdirSync(dir);
      } catch {
        return;
      }

      for (const entry of entries) {
        if (ignoredDirs.has(entry)) continue;
        const fullPath = path.join(dir, entry);
        const relPath = path.relative(this.workspaceRoot, fullPath);

        let stat: fs.Stats;
        try {
          stat = fs.statSync(fullPath);
        } catch {
          continue;
        }

        const isDir = stat.isDirectory();
        const entryLower = entry.toLowerCase();
        const relLower = relPath.toLowerCase();

        const isMatch = entryLower === queryLower || entryLower.includes(queryLower) || relLower.includes(queryLower);

        if (isMatch) {
          matches.push({
            path: relPath,
            name: entry,
            type: isDir ? "directory" : "file",
            size: isDir ? undefined : stat.size,
          });
        }

        if (isDir) {
          walk(fullPath, depth + 1);
        }
      }
    };

    walk(this.workspaceRoot, 0);

    const found = matches.length > 0;
    const message = found
      ? `Found ${matches.length} match(es) for '${trimmed}' in workspace (${this.workspaceRoot}).`
      : `No file or folder matching '${trimmed}' exists in workspace (${this.workspaceRoot}). Only the configured workspace was searched.`;

    return {
      query: trimmed,
      found,
      count: matches.length,
      matches,
      searched_in: this.workspaceRoot,
      message,
    };
  }

  /**
   * Tool 5: docker_read
   * Read-only inspection of Docker artifacts in the workspace and read-only CLI check.
   */
  public async getDockerRead(): Promise<DockerReadEvidence> {
    const commonDockerFiles = [
      "Dockerfile",
      "Dockerfile.dev",
      "docker-compose.yml",
      "docker-compose.yaml",
      "compose.yml",
      "compose.yaml",
      ".dockerignore",
    ];

    const dockerFilesFound: Array<{ name: string; path: string; exists: boolean; size?: number }> = [];

    for (const file of commonDockerFiles) {
      const fullPath = path.join(this.workspaceRoot, file);
      if (fs.existsSync(fullPath)) {
        try {
          const stat = fs.statSync(fullPath);
          dockerFilesFound.push({
            name: file,
            path: file,
            exists: true,
            size: stat.size,
          });
        } catch {
          dockerFilesFound.push({ name: file, path: file, exists: true });
        }
      }
    }

    let dockerCliAvailable = false;
    let cliReadings: { version?: string; containers?: string } | undefined;

    try {
      // Strictly read-only query
      const { stdout: versionOut } = await execFileAsync("docker", ["--version"]);
      dockerCliAvailable = true;
      cliReadings = {
        version: versionOut.trim(),
      };
      try {
        const { stdout: psOut } = await execFileAsync("docker", ["ps", "--format", "{{.ID}}\t{{.Image}}\t{{.Status}}"]);
        cliReadings.containers = psOut.trim();
      } catch {
        // Docker daemon may not be running
      }
    } catch {
      dockerCliAvailable = false;
    }

    const message = dockerFilesFound.length > 0
      ? `Discovered ${dockerFilesFound.length} Docker configuration file(s) in workspace.`
      : "No Dockerfile or compose configuration found in workspace root.";

    return {
      docker_files: dockerFilesFound,
      docker_cli_available: dockerCliAvailable,
      cli_readings: cliReadings,
      message,
    };
  }

  /**
   * Tool 6: git_read
   * Read-only inspection of Git status, branch, and recent commits.
   */
  public async getGitRead(): Promise<GitReadEvidence> {
    const gitDir = path.join(this.workspaceRoot, ".git");
    const hasGitDir = fs.existsSync(gitDir);

    if (!hasGitDir) {
      return {
        is_git_repository: false,
        branch: null,
        status: null,
        recent_commits: null,
        remotes: null,
        message: "Not a git repository: '.git' directory was not found in workspace.",
      };
    }

    try {
      // Strictly read-only git queries
      const [branchRes, statusRes, logRes, remoteRes] = await Promise.allSettled([
        execFileAsync("git", ["branch", "--show-current"], { cwd: this.workspaceRoot }),
        execFileAsync("git", ["status", "--short"], { cwd: this.workspaceRoot }),
        execFileAsync("git", ["log", "-n", "5", "--oneline"], { cwd: this.workspaceRoot }),
        execFileAsync("git", ["remote", "-v"], { cwd: this.workspaceRoot }),
      ]);

      const branch = branchRes.status === "fulfilled" ? branchRes.value.stdout.trim() : null;
      const status = statusRes.status === "fulfilled" ? statusRes.value.stdout.trim() : null;
      const recent_commits = logRes.status === "fulfilled"
        ? logRes.value.stdout.trim().split("\n").filter(Boolean)
        : null;
      const remotes = remoteRes.status === "fulfilled"
        ? remoteRes.value.stdout.trim().split("\n").filter(Boolean)
        : null;

      return {
        is_git_repository: true,
        branch: branch || "HEAD (detached)",
        status: status || "clean",
        recent_commits,
        remotes,
        message: `Git repository active on branch '${branch || "detached"}'.`,
      };
    } catch (err: any) {
      return {
        is_git_repository: true,
        branch: null,
        status: null,
        recent_commits: null,
        remotes: null,
        message: `Git directory present, but query failed: ${err.message}`,
      };
    }
  }

  /**
   * Tool 7: kubernetes_read
   * Read-only inspection of Kubernetes manifest files and kubectl environment.
   */
  public async getKubernetesRead(): Promise<KubernetesReadEvidence> {
    const candidateDirs = [this.workspaceRoot, path.join(this.workspaceRoot, "k8s"), path.join(this.workspaceRoot, "kubernetes")];
    const manifestsFound: Array<{ path: string; kind?: string; apiVersion?: string }> = [];

    for (const dir of candidateDirs) {
      if (!fs.existsSync(dir)) continue;
      try {
        const files = fs.readdirSync(dir);
        for (const f of files) {
          if (f.endsWith(".yaml") || f.endsWith(".yml")) {
            const fullPath = path.join(dir, f);
            try {
              const content = fs.readFileSync(fullPath, "utf-8").slice(0, 1000);
              const kindMatch = content.match(/^kind:\s*(\w+)/m);
              const apiMatch = content.match(/^apiVersion:\s*([^\s]+)/m);
              if (kindMatch || apiMatch) {
                manifestsFound.push({
                  path: path.relative(this.workspaceRoot, fullPath),
                  kind: kindMatch ? kindMatch[1] : undefined,
                  apiVersion: apiMatch ? apiMatch[1] : undefined,
                });
              }
            } catch {
              // ignore read errors
            }
          }
        }
      } catch {
        // ignore
      }
    }

    let kubectlAvailable = false;
    let clusterInfo: string | null = null;

    try {
      const { stdout } = await execFileAsync("kubectl", ["version", "--client", "--output=yaml"]);
      kubectlAvailable = true;
      clusterInfo = stdout.trim();
    } catch {
      kubectlAvailable = false;
    }

    const message = manifestsFound.length > 0
      ? `Found ${manifestsFound.length} Kubernetes manifest(s) in workspace.`
      : "No Kubernetes manifest files detected in workspace.";

    return {
      manifests_found: manifestsFound,
      kubectl_available: kubectlAvailable,
      cluster_info: clusterInfo,
      message,
    };
  }

  /**
   * Secure Read-Only Gatekeeper
   * Executes ONLY approved read-only tools. Blocks any modifying or unknown commands.
   */
  public async executeReadOnlyTool(name: string, args: Record<string, any> = {}): Promise<ControlPlaneEvidence> {
    // 1. Whitelist validation
    if (!READ_ONLY_TOOLS.includes(name as ReadOnlyToolName)) {
      return {
        tool: name as ReadOnlyToolName,
        status: "error",
        error: `SecurityException: Tool '${name}' is rejected. The Control Plane is strictly READ-ONLY and permits only: ${READ_ONLY_TOOLS.join(", ")}.`,
      };
    }

    // 2. Extra safety checks against mutation keywords in arguments
    const argsStr = JSON.stringify(args).toLowerCase();
    for (const forbidden of FORBIDDEN_OPERATIONS) {
      if (argsStr.includes(forbidden.toLowerCase())) {
        return {
          tool: name as ReadOnlyToolName,
          status: "error",
          error: `SecurityException: Operation containing '${forbidden}' is strictly blocked. Modifying commands and filesystem mutations are prohibited in Chat.`,
        };
      }
    }

    try {
      switch (name as ReadOnlyToolName) {
        case "local_time":
          return {
            tool: "local_time",
            status: "success",
            data: this.getLocalTime(),
          };

        case "workspace_pwd":
          return {
            tool: "workspace_pwd",
            status: "success",
            data: this.getWorkspacePwd(),
          };

        case "workspace_ls":
          return {
            tool: "workspace_ls",
            status: "success",
            data: this.getWorkspaceLs(args.subpath || "."),
          };

        case "project_files":
          return {
            tool: "project_files",
            status: "success",
            data: this.searchProjectFiles(args.query || ""),
          };

        case "docker_read":
          return {
            tool: "docker_read",
            status: "success",
            data: await this.getDockerRead(),
          };

        case "git_read":
          return {
            tool: "git_read",
            status: "success",
            data: await this.getGitRead(),
          };

        case "kubernetes_read":
          return {
            tool: "kubernetes_read",
            status: "success",
            data: await this.getKubernetesRead(),
          };

        default:
          return {
            tool: name as ReadOnlyToolName,
            status: "error",
            error: `Unsupported tool: ${name}`,
          };
      }
    } catch (err: any) {
      return {
        tool: name as ReadOnlyToolName,
        status: "error",
        error: `Tool execution failed: ${err.message}`,
      };
    }
  }

  /**
   * Evidence Requirement Detector:
   * Distinguishes normal engineering questions from questions requiring real local/system/workspace evidence.
   * Normal engineering questions (e.g. "Tell me 5 Docker commands", "Explain Kubernetes") return required: false.
   * Local questions (e.g. "What is today's date?", "What is my current workspace?", "Find folder new-wedding") return required: true with specific tools.
   */
  public detectEvidenceRequirement(query: string): EvidenceRequirementPlan {
    const trimmed = query.trim();
    const lower = trimmed.toLowerCase();

    const tools: ReadOnlyToolName[] = [];
    let searchParams: Record<string, any> | undefined;

    // 1. local_time: asks for dynamic local/system clock/date/time
    const isTimeQuery =
      /\b(?:what(?:'s|\s+is)?\s+(?:the\s+)?(?:current\s+)?(?:date|time|day|clock|timezone)|today(?:'s)?\s+date|date\s+today|what\s+time\s+is\s+it|time\s+now|current\s+time|current\s+date|local\s+time)\b/i.test(trimmed);
    if (isTimeQuery) {
      tools.push("local_time");
    }

    // 2. workspace_pwd: asks for current workspace, directory, or pwd
    const isPwdQuery =
      /^(?:pwd)$/i.test(trimmed) ||
      /\b(?:what(?:'s|\s+is)?\s+(?:my\s+|the\s+)?(?:current\s+)?workspace|workspace\s+path|where\s+am\s+i|current\s+(?:working\s+)?directory|what\s+folder\s+am\s+i\s+in)\b/i.test(trimmed);
    if (isPwdQuery) {
      tools.push("workspace_pwd");
    }

    // 3. workspace_ls: asks to list files or directory contents
    const isLsQuery =
      /^(?:ls|dir)(?:\s+.*)?$/i.test(trimmed) ||
      /\b(?:list\s+(?:the\s+)?(?:files|directory|folder|workspace)|show\s+(?:the\s+)?(?:files|directory\s+contents|workspace\s+files)|what\s+files\s+(?:are\s+in|exist|do\s+we\s+have))\b/i.test(trimmed);
    if (isLsQuery && !tools.includes("workspace_ls")) {
      tools.push("workspace_ls");
    }

    // 4. project_files: asks to find / search / locate a specific file or folder
    // e.g. "find folder new-wedding", "find file package.json", "where is index.html", "search for server.ts", "do we have a new-wedding folder"
    let fileSearchTerm: string | null = null;
    const findMatch = trimmed.match(
      /\b(?:find|locate|search(?:\s+for)?|where\s+is)\s+(?:(?:the|a|an)\s+)?(?:(?:folder|directory|dir|file)\s+)?([a-zA-Z0-9_\-./]+)/i
    );
    if (findMatch && findMatch[1]) {
      const candidate = findMatch[1].trim();
      if (!/^(?:how|what|why|who|a|an|the|me|my|your|this|that|some)$/i.test(candidate)) {
        fileSearchTerm = candidate;
      }
    }
    if (!fileSearchTerm) {
      const existMatch = trimmed.match(
        /\b(?:do\s+(?:we|i)\s+have|is\s+there)\s+(?:(?:a|an|the)\s+)?([a-zA-Z0-9_\-./]+)\s+(?:folder|directory|dir|file)\b/i
      );
      if (existMatch && existMatch[1]) {
        fileSearchTerm = existMatch[1].trim();
      }
    }
    if (fileSearchTerm) {
      tools.push("project_files");
      searchParams = { query: fileSearchTerm };
    }

    // 5. git_read: asks about the local Git repository state / branch / status
    const isGitLocalQuery =
      /^(?:git\s+(?:status|branch|log))$/i.test(trimmed) ||
      /\b(?:what\s+git\s+branch|what\s+branch\s+am\s+i|what\s+is\s+my\s+git\s+branch|current\s+git\s+branch|show\s+git\s+branch|check\s+git\s+status|is\s+this\s+a\s+git\s+repo(?:sitory)?|what\s+branch\s+are\s+we\s+on)\b/i.test(trimmed);
    if (isGitLocalQuery) {
      tools.push("git_read");
    }

    // 6. docker_read: asks about local Docker status / Docker in this project
    const isDockerLocalQuery =
      /\b(?:what\s+docker\s+information|is\s+docker\s+(?:installed|running|available)|check\s+docker|do\s+i\s+have\s+(?:a\s+)?dockerfile|docker\s+status)\b/i.test(trimmed);
    if (isDockerLocalQuery && !tools.includes("docker_read")) {
      tools.push("docker_read");
    }

    // 7. kubernetes_read: asks about local Kubernetes configuration / manifests in this project
    const isK8sLocalQuery =
      /\b(?:do\s+(?:i|we)\s+have\s+(?:a\s+)?kubernetes\s+config(?:uration)?|do\s+(?:i|we)\s+have\s+k8s\s+manifests|is\s+kubectl\s+(?:installed|running|available)|check\s+kubernetes\s+setup|kubernetes\s+configuration\s+available)\b/i.test(trimmed);
    if (isK8sLocalQuery && !tools.includes("kubernetes_read")) {
      tools.push("kubernetes_read");
    }

    // 8. Mixed / Project-specific questions (e.g. "What Docker setup should I use for this project?")
    const isProjectContext = /\b(?:for\s+this\s+project|in\s+this\s+project|for\s+this\s+repo(?:sitory)?|in\s+this\s+repo(?:sitory)?|this\s+project|this\s+workspace)\b/i.test(trimmed);
    if (isProjectContext) {
      if (lower.includes("docker") && !tools.includes("docker_read")) {
        tools.push("docker_read");
        if (!tools.includes("workspace_ls")) tools.push("workspace_ls");
      }
      if ((lower.includes("k8s") || lower.includes("kubernetes")) && !tools.includes("kubernetes_read")) {
        tools.push("kubernetes_read");
        if (!tools.includes("workspace_ls")) tools.push("workspace_ls");
      }
    }

    return {
      required: tools.length > 0,
      tools,
      searchParams,
    };
  }

  /**
   * Gather evidence strictly according to the detected plan.
   */
  public async gatherEvidenceByPlan(plan: EvidenceRequirementPlan): Promise<Record<string, any>> {
    const evidence: Record<string, any> = {};

    for (const tool of plan.tools) {
      switch (tool) {
        case "local_time":
          evidence.local_time = this.getLocalTime();
          break;
        case "workspace_pwd":
          evidence.workspace_pwd = this.getWorkspacePwd();
          break;
        case "workspace_ls":
          evidence.workspace_ls = this.getWorkspaceLs(".");
          break;
        case "project_files":
          evidence.file_search = this.searchProjectFiles(plan.searchParams?.query || "");
          break;
        case "docker_read":
          evidence.docker = await this.getDockerRead();
          break;
        case "git_read":
          evidence.git = await this.getGitRead();
          break;
        case "kubernetes_read":
          evidence.kubernetes = await this.getKubernetesRead();
          break;
      }
    }

    return evidence;
  }

  /**
   * Proactive Evidence Gatherer:
   * Inspects user prompt and gathers factual evidence ONLY when required.
   * For normal engineering questions, returns an empty object without injecting fake baseline context.
   */
  public async gatherEvidenceForQuery(query: string): Promise<Record<string, any>> {
    const plan = this.detectEvidenceRequirement(query);
    if (!plan.required) {
      return {};
    }
    return this.gatherEvidenceByPlan(plan);
  }

  /**
   * Tool definitions schema for Ollama /api/chat tool calling.
   */
  public getOllamaToolDefinitions(): any[] {
    return [
      {
        type: "function",
        function: {
          name: "local_time",
          description: "Get dynamic system clock evidence: current date, time, day, timezone, and timestamp.",
          parameters: {
            type: "object",
            properties: {},
            required: [],
          },
        },
      },
      {
        type: "function",
        function: {
          name: "workspace_pwd",
          description: "Get the current verified workspace directory path.",
          parameters: {
            type: "object",
            properties: {},
            required: [],
          },
        },
      },
      {
        type: "function",
        function: {
          name: "workspace_ls",
          description: "List files and subdirectories within a safe workspace directory path.",
          parameters: {
            type: "object",
            properties: {
              subpath: {
                type: "string",
                description: "Relative directory path to inspect, defaults to '.'",
              },
            },
            required: [],
          },
        },
      },
      {
        type: "function",
        function: {
          name: "project_files",
          description: "Search workspace for files or directories by name. Reports factual matches or explicit not-found without hallucination.",
          parameters: {
            type: "object",
            properties: {
              query: {
                type: "string",
                description: "Name or keyword of file/folder to search for.",
              },
            },
            required: ["query"],
          },
        },
      },
      {
        type: "function",
        function: {
          name: "docker_read",
          description: "Inspect workspace Dockerfile, compose manifests, and read-only Docker state.",
          parameters: {
            type: "object",
            properties: {},
            required: [],
          },
        },
      },
      {
        type: "function",
        function: {
          name: "git_read",
          description: "Inspect current Git branch, status, recent commits, and repository state.",
          parameters: {
            type: "object",
            properties: {},
            required: [],
          },
        },
      },
      {
        type: "function",
        function: {
          name: "kubernetes_read",
          description: "Inspect workspace Kubernetes manifests and read-only cluster context.",
          parameters: {
            type: "object",
            properties: {},
            required: [],
          },
        },
      },
    ];
  }
}
