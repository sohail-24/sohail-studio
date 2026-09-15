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
   * Searches for files or folders matching a query.
   * Reports factually: if no matches, reports found: false and no hallucinated paths.
   */
  public searchProjectFiles(query: string = ""): ProjectFilesEvidence {
    const trimmed = query.trim().toLowerCase();
    const matches: ProjectFileMatch[] = [];
    const ignoredDirs = new Set(["node_modules", ".git", "dist", ".cache"]);

    const walk = (dir: string, depth: number) => {
      if (depth > 6) return;
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

        const isMatch = !trimmed || entryLower.includes(trimmed) || relLower.includes(trimmed);

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
      ? `Found ${matches.length} match(es) for '${query}' in workspace.`
      : `No file or folder matching '${query}' exists in workspace.`;

    return {
      query,
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
   * Proactive Evidence Gatherer:
   * Inspects user prompt and gathers factual evidence before/with inference.
   * Ensures the model receives genuine local evidence for queries about time, git, files, docker, etc.
   */
  public async gatherEvidenceForQuery(query: string): Promise<Record<string, any>> {
    const lower = query.toLowerCase();
    const evidence: Record<string, any> = {};

    // Local time query
    if (lower.includes("time") || lower.includes("date") || lower.includes("clock") || lower.includes("today") || lower.includes("day") || lower.includes("timezone")) {
      evidence.local_time = this.getLocalTime();
    }

    // Git / branch query
    if (lower.includes("git") || lower.includes("branch") || lower.includes("commit") || lower.includes("repo")) {
      evidence.git = await this.getGitRead();
    }

    // Docker query
    if (lower.includes("docker") || lower.includes("container") || lower.includes("dockerfile") || lower.includes("compose")) {
      evidence.docker = await this.getDockerRead();
    }

    // Kubernetes query
    if (lower.includes("k8s") || lower.includes("kubernetes") || lower.includes("pod") || lower.includes("deployment") || lower.includes("service")) {
      evidence.kubernetes = await this.getKubernetesRead();
    }

    // Search or find file/folder query (e.g. "Find the sms folder", "Where is index.html")
    const searchMatch = query.match(/(?:find|search|look for|where is|locate)\s+(?:the\s+)?([a-zA-Z0-9_\-./]+)/i);
    if (searchMatch && searchMatch[1]) {
      const term = searchMatch[1].replace(/folder|directory|file/gi, "").trim();
      if (term) {
        evidence.file_search = this.searchProjectFiles(term);
      }
    } else if (lower.includes("sms")) {
      evidence.file_search = this.searchProjectFiles("sms");
    }

    // Path / PWD / Workspace list
    if (lower.includes("pwd") || lower.includes("path") || lower.includes("workspace") || lower.includes("directory") || lower.includes("files") || lower.includes("ls")) {
      evidence.workspace_pwd = this.getWorkspacePwd();
      evidence.workspace_ls = this.getWorkspaceLs(".");
    }

    // Always provide baseline factual context if nothing specific was matched
    if (Object.keys(evidence).length === 0) {
      evidence.workspace_pwd = this.getWorkspacePwd();
      evidence.local_time = this.getLocalTime();
    }

    return evidence;
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
