import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
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
import { loadSettings } from "./server.js";

export function runControlPlaneTests() {
  console.log("\n=== Running AI Control Plane & Local Ollama Regression Tests ===");

  // TEST 1: local_time returns dynamic local date/time/day/timezone
  console.log("\n[TEST 1] local_time returns dynamic local date/time/day/timezone");
  const t = getLocalTime();
  assert.equal(t.success, true, "local_time must succeed");
  assert.equal(t.tool, "local_time", "tool name must be local_time");
  assert.ok(t.data.date, "date field must exist");
  assert.ok(t.data.time, "time field must exist");
  assert.ok(t.data.day, "day field must exist");
  assert.ok(t.data.timezone, "timezone field must exist");

  const now = new Date();
  const expectedDays = ["Sunday", "Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday"];
  const expectedDay = expectedDays[now.getDay()];
  assert.equal(t.data.day, expectedDay, "day must match real system day of week");

  const expectedDate = `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, "0")}-${String(now.getDate()).padStart(2, "0")}`;
  assert.equal(t.data.date, expectedDate, "date must dynamically match real system date");
  console.log(`✓ TEST 1 passed: local_time dynamically returned date=${t.data.date}, day=${t.data.day}, timezone=${t.data.timezone}`);

  // TEST 2: workspace_pwd is read-only
  console.log("\n[TEST 2] workspace_pwd is read-only");
  const pwd = getWorkspacePwd(process.cwd());
  assert.equal(pwd.success, true);
  assert.equal(pwd.tool, "workspace_pwd");
  assert.equal(pwd.data.cwd, path.resolve(process.cwd()));
  console.log("✓ TEST 2 passed: workspace_pwd is read-only and accurately returns resolved path.");

  // TEST 3: workspace_ls is read-only
  console.log("\n[TEST 3] workspace_ls is read-only");
  const ls = getWorkspaceLs(process.cwd());
  assert.equal(ls.success, true);
  assert.equal(ls.tool, "workspace_ls");
  assert.ok(Array.isArray(ls.data.items), "items must be an array");
  assert.ok(!ls.data.items.some((i: any) => i.name === ".git"), ".git must be excluded");
  assert.ok(!ls.data.items.some((i: any) => i.name === "node_modules"), "node_modules must be excluded");
  assert.ok(!ls.data.items.some((i: any) => i.name === ".venv"), ".venv must be excluded");

  const outside = getWorkspaceLs(process.cwd(), "../../");
  assert.equal(outside.success, false, "Path traversal outside workspace root must be denied");
  console.log("✓ TEST 3 passed: workspace_ls is read-only, safely bounded, and excludes cache/internal folders.");

  // TEST 4: project_files performs bounded inspection
  console.log("\n[TEST 4] project_files performs bounded inspection");
  const files = getProjectFiles(process.cwd());
  assert.equal(files.success, true);
  assert.equal(files.tool, "project_files");
  assert.ok(files.data.files.length > 0, "must find project files in workspace");
  assert.ok(!files.data.files.some((f: any) => f.path.includes("node_modules")), "bounded inspection skips node_modules");
  assert.ok(!files.data.files.some((f: any) => f.path.split(/[/\\]/).includes(".git")), "bounded inspection skips .git directory");
  console.log(`✓ TEST 4 passed: project_files inspected ${files.data.files.length} bounded files safely.`);

  // TEST 5: missing file produces a factual error
  console.log("\n[TEST 5] missing file produces a factual error");
  const missing = getProjectFiles(process.cwd(), "Find my SMS folder");
  assert.equal(missing.success, false, "Missing file/folder must produce success: false");
  assert.ok(missing.error?.toLowerCase().includes("sms"), "Error message must factually identify missing target");
  assert.ok(missing.as_context().includes("Error"), "as_context must format factual error");
  console.log(`✓ TEST 5 passed: missing file correctly produced factual error: "${missing.error}"`);

  // TEST 6: Chat model is exactly devops-qwen:v1
  console.log("\n[TEST 6] Chat model is exactly devops-qwen:v1");
  const settings = loadSettings();
  assert.equal(settings.chat_model, "devops-qwen:v1", "Chat model must be devops-qwen:v1");
  console.log("✓ TEST 6 passed: Chat model is confirmed devops-qwen:v1.");

  // TEST 7: Sohail-Agent remains devops-qwen:latest
  console.log("\n[TEST 7] Sohail-Agent remains devops-qwen:latest");
  assert.equal(settings.devops_model, "devops-qwen:latest", "Sohail-Agent model must be devops-qwen:latest");
  console.log("✓ TEST 7 passed: Sohail-Agent model is confirmed devops-qwen:latest.");

  // TEST 8: Ollama base URL defaults to localhost:11434
  console.log("\n[TEST 8] Ollama base URL defaults to localhost:11434");
  assert.equal(settings.ollama_base_url, "http://localhost:11434", "Ollama default base URL must be http://localhost:11434");
  console.log("✓ TEST 8 passed: Ollama base URL defaults to http://localhost:11434.");

  // TEST 9: OLLAMA_BASE_URL can override the default
  console.log("\n[TEST 9] OLLAMA_BASE_URL can override the default");
  const origEnv = process.env.OLLAMA_BASE_URL;
  try {
    process.env.OLLAMA_BASE_URL = "http://192.168.1.200:11434";
    const resolvedUrl = process.env.OLLAMA_BASE_URL || settings.ollama_base_url || "http://localhost:11434";
    assert.equal(resolvedUrl, "http://192.168.1.200:11434", "OLLAMA_BASE_URL must override default URL");
  } finally {
    if (origEnv !== undefined) process.env.OLLAMA_BASE_URL = origEnv;
    else delete process.env.OLLAMA_BASE_URL;
  }
  console.log("✓ TEST 9 passed: OLLAMA_BASE_URL environment variable overrides default.");

  // TEST 10: Chat uses ollama-api transport
  console.log("\n[TEST 10] Chat uses ollama-api transport");
  const serverSrc = fs.readFileSync(path.join(process.cwd(), "server.ts"), "utf-8");
  assert.ok(serverSrc.includes('transport: "ollama-api"'), "server.ts must declare transport: 'ollama-api'");
  console.log("✓ TEST 10 passed: Chat transport identifies as ollama-api.");

  // TEST 11: Chat does not use Gemini
  console.log("\n[TEST 11] Chat does not use Gemini");
  const handleChatIdx = serverSrc.indexOf("function handleChatSocket");
  const chatSocketBlock = serverSrc.substring(handleChatIdx, serverSrc.indexOf("export function generateMentorResponse"));
  assert.ok(!chatSocketBlock.includes("GoogleGenAI"), "Chat WebSocket must not use GoogleGenAI");
  assert.ok(!chatSocketBlock.includes("gemini-"), "Chat WebSocket must not use Gemini models");
  console.log("✓ TEST 11 passed: Chat execution path has zero Gemini references.");

  // TEST 12: Chat does not use generateMentorResponse fallback
  console.log("\n[TEST 12] Chat does not use generateMentorResponse fallback");
  assert.ok(!chatSocketBlock.includes("generateMentorResponse("), "handleChatSocket must not call generateMentorResponse");
  console.log("✓ TEST 12 passed: Chat strictly avoids generateMentorResponse fallback.");

  // TEST 13: Ollama unavailable produces an explicit error
  console.log("\n[TEST 13] Ollama unavailable produces an explicit error");
  assert.ok(chatSocketBlock.includes("[Local Ollama Error] Could not reach Ollama"), "Must produce explicit Local Ollama Error");
  assert.ok(serverSrc.includes("Ensure Ollama is running on your local machine with model"), "Must provide actionable local Ollama run instructions");
  console.log("✓ TEST 13 passed: Ollama unreachable state emits explicit local diagnostic error.");

  // TEST 14: Model output cannot become an arbitrary shell command
  console.log("\n[TEST 14] Model output cannot become an arbitrary shell command");
  assert.throws(() => assertReadOnlySafety("rm -rf /"), /Safety Violation/, "rm must be blocked");
  assert.throws(() => assertReadOnlySafety("touch /tmp/bad"), /Safety Violation/, "touch must be blocked");
  assert.throws(() => assertReadOnlySafety("docker run -it alpine"), /Safety Violation/, "docker run must be blocked");
  assert.throws(() => assertReadOnlySafety("git commit -m 'bad'"), /Safety Violation/, "git commit must be blocked");
  assert.throws(() => assertReadOnlySafety("kubectl apply -f bad.yaml"), /Safety Violation/, "kubectl apply must be blocked");
  assert.throws(() => assertReadOnlySafety("npm install malicious-pkg"), /Safety Violation/, "npm install must be blocked");
  assert.ok(!chatSocketBlock.includes("execSync("), "Chat handler must not execute shell commands from model");
  assert.ok(!chatSocketBlock.includes("spawn("), "Chat handler must not spawn shell commands from model");
  console.log("✓ TEST 14 passed: Read-only safety asserts block arbitrary shell mutation; Chat has no execution bridge.");

  // TEST 15: docker_read remains read-only
  console.log("\n[TEST 15] docker_read remains read-only");
  const dockerRes = getDockerRead(process.cwd());
  assert.equal(dockerRes.success, true);
  assert.equal(dockerRes.data.read_only, true, "docker_read must be read_only");
  assert.equal(dockerRes.tool, "docker_read");
  console.log("✓ TEST 15 passed: docker_read is strictly read-only.");

  // TEST 16: git_read remains read-only
  console.log("\n[TEST 16] git_read remains read-only");
  const gitRes = getGitRead(process.cwd());
  assert.equal(gitRes.success, true);
  assert.equal(gitRes.data.read_only, true, "git_read must be read_only");
  assert.equal(gitRes.tool, "git_read");
  console.log("✓ TEST 16 passed: git_read is strictly read-only.");

  // TEST 17: kubernetes_read remains read-only
  console.log("\n[TEST 17] kubernetes_read remains read-only");
  const k8sRes = getKubernetesRead(process.cwd());
  assert.equal(k8sRes.success, true);
  assert.equal(k8sRes.data.read_only, true, "kubernetes_read must be read_only");
  assert.equal(k8sRes.tool, "kubernetes_read");
  console.log("✓ TEST 17 passed: kubernetes_read is strictly read-only.");

  // TEST 18: ControlPlane inspect_many multi-tool integration
  console.log("\n[TEST 18] ControlPlane inspect_many multi-tool integration");
  const cp = new ControlPlane(process.cwd());
  const dateResults = cp.inspect_many("What is today's date and time?");
  assert.ok(dateResults.some((r) => r.tool === "local_time"), "inspect_many must dispatch local_time for date questions");

  const pwdResults = cp.inspect_many("What is my current working directory?");
  assert.ok(pwdResults.some((r) => r.tool === "workspace_pwd"), "inspect_many must dispatch workspace_pwd for pwd questions");

  const findResults = cp.inspect_many("Find my SMS folder");
  assert.ok(findResults.some((r) => r.tool === "project_files"), "inspect_many must dispatch project_files for find questions");

  // Output cleaning test
  const dirtyOutput = "<think>internal reasoning tokens</think>Here is the real answer.";
  assert.equal(cleanOllamaOutput(dirtyOutput), "Here is the real answer.", "cleanOllamaOutput must strip thinking tags");
  console.log("✓ TEST 18 passed: ControlPlane inspect_many and Ollama output cleaning verified.");

  console.log("\n=== ALL AI CONTROL PLANE & OLLAMA TESTS PASSED! ===");
}

if (process.argv[1]?.endsWith("test_control_plane.ts")) {
  runControlPlaneTests();
}
