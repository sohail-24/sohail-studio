import test, { describe, it } from "node:test";
import assert from "node:assert/strict";
import path from "node:path";
import fs from "node:fs";
import {
  ReadOnlyControlPlane,
  READ_ONLY_TOOLS,
  FORBIDDEN_OPERATIONS,
} from "../core/control_plane.js";

describe("ReadOnlyControlPlane - 7 Tools & Read-Only Evidence", () => {
  const root = process.cwd();
  const cp = new ReadOnlyControlPlane(root);

  it("1. local_time: uses dynamic system clock and returns date, time, day, timezone", () => {
    const timeBefore = Date.now();
    const evidence = cp.getLocalTime();
    const timeAfter = Date.now();

    assert.ok(evidence.date.match(/^\d{4}-\d{2}-\d{2}$/), "Date must match YYYY-MM-DD");
    assert.ok(evidence.time.match(/^\d{2}:\d{2}:\d{2}$/), "Time must match HH:MM:SS");
    assert.ok(typeof evidence.day === "string" && evidence.day.length > 0, "Day must be non-empty string");
    assert.ok(typeof evidence.timezone === "string", "Timezone must be string");
    assert.ok(evidence.timestamp >= timeBefore && evidence.timestamp <= timeAfter, "Timestamp must reflect actual clock");
    assert.ok(new Date(evidence.iso).getTime() > 0, "ISO string must be valid");
  });

  it("2. workspace_pwd: returns factual workspace root", () => {
    const evidence = cp.getWorkspacePwd();
    assert.equal(evidence.pwd, path.resolve(root));
    assert.equal(evidence.root, path.resolve(root));
    assert.equal(evidence.basename, path.basename(root));
  });

  it("3. workspace_ls: lists entries safely within workspace boundaries", () => {
    const evidence = cp.getWorkspaceLs(".");
    assert.equal(evidence.exists, true);
    assert.equal(evidence.is_directory, true);
    assert.ok(evidence.entries.length > 0, "Workspace entries must not be empty");

    const packageJson = evidence.entries.find((e) => e.name === "package.json");
    assert.ok(packageJson, "package.json must be listed");
    assert.equal(packageJson?.type, "file");

    // Path traversal outside workspace boundary must be blocked
    const traversal = cp.getWorkspaceLs("../../../etc");
    assert.equal(traversal.exists, false);
    assert.ok(traversal.error?.includes("Access denied"), "Path traversal must be denied");
  });

  it("4. project_files: searches files and handles missing file/folder without hallucination", () => {
    // Search for an existing file
    const searchExisting = cp.searchProjectFiles("package.json");
    assert.equal(searchExisting.found, true);
    assert.ok(searchExisting.matches.some((m) => m.name === "package.json"));

    // Search for non-existent folder/file (e.g., 'sms', 'new-wedding')
    const searchMissing = cp.searchProjectFiles("sms");
    assert.equal(searchMissing.found, false);
    assert.equal(searchMissing.count, 0);
    assert.deepEqual(searchMissing.matches, []);
    assert.ok(
      searchMissing.message.includes("No file or folder matching 'sms' exists in workspace"),
      "Must report factually without hallucinating paths"
    );
    assert.ok(
      searchMissing.message.includes("Only the configured workspace was searched"),
      "Must confirm workspace search boundary"
    );

    // Search for missing folder 'new-wedding'
    const searchNewWedding = cp.searchProjectFiles("new-wedding");
    assert.equal(searchNewWedding.found, false);
    assert.equal(searchNewWedding.count, 0);
    assert.deepEqual(searchNewWedding.matches, []);
    assert.ok(searchNewWedding.message.includes("new-wedding"));
    assert.ok(searchNewWedding.message.includes("Only the configured workspace was searched"));

    // Path outside workspace boundary is blocked
    const searchOutside = cp.searchProjectFiles("../../../etc/passwd");
    assert.equal(searchOutside.found, false);
    assert.ok(searchOutside.message.includes("outside the configured workspace boundary"));
  });

  it("5. docker_read: performs read-only docker inspection", async () => {
    const evidence = await cp.getDockerRead();
    assert.ok(Array.isArray(evidence.docker_files));
    assert.ok(typeof evidence.docker_cli_available === "boolean");
    assert.ok(typeof evidence.message === "string");
  });

  it("6. git_read: performs read-only git queries and handles missing .git factually", async () => {
    const evidence = await cp.getGitRead();
    assert.ok(typeof evidence.is_git_repository === "boolean");
    if (!evidence.is_git_repository) {
      assert.equal(evidence.branch, null);
      assert.ok(evidence.message.includes("Not a git repository"));
    } else {
      assert.ok(typeof evidence.branch === "string");
    }
  });

  it("7. kubernetes_read: performs read-only inspection of manifests", async () => {
    const evidence = await cp.getKubernetesRead();
    assert.ok(Array.isArray(evidence.manifests_found));
    assert.ok(typeof evidence.kubectl_available === "boolean");
    assert.ok(typeof evidence.message === "string");
  });

  describe("Safety & Read-Only Boundaries", () => {
    it("rejects unknown or arbitrary commands", async () => {
      const result = await cp.executeReadOnlyTool("arbitrary_bash" as any, { cmd: "whoami" });
      assert.equal(result.status, "error");
      assert.ok(result.error?.includes("SecurityException"));
      assert.ok(result.error?.includes("rejected"));
    });

    it("blocks modifying operations (rm, mv, cp, mkdir, delete, git commit, docker run, kubectl apply, etc.)", async () => {
      for (const op of FORBIDDEN_OPERATIONS) {
        const result = await cp.executeReadOnlyTool("workspace_ls", { subpath: `.${op}` });
        assert.equal(result.status, "error", `Forbidden operation '${op}' must be blocked`);
        assert.ok(result.error?.includes("SecurityException"));
      }
    });

    it("verifies exact whitelist of permitted tools", () => {
      assert.deepEqual([...READ_ONLY_TOOLS], [
        "local_time",
        "workspace_pwd",
        "workspace_ls",
        "project_files",
        "docker_read",
        "git_read",
        "kubernetes_read",
      ]);
    });

    it("distinguishes general engineering questions from local evidence queries", () => {
      // General engineering questions MUST NOT require Control Plane evidence
      assert.equal(cp.detectEvidenceRequirement("Tell me 5 Docker commands").required, false);
      assert.equal(cp.detectEvidenceRequirement("Explain Docker volumes").required, false);
      assert.equal(cp.detectEvidenceRequirement("What is Kubernetes?").required, false);
      assert.equal(cp.detectEvidenceRequirement("Explain CI/CD").required, false);
      assert.equal(cp.detectEvidenceRequirement("How does Terraform state work?").required, false);
      assert.equal(cp.detectEvidenceRequirement("Explain Kubernetes Deployment").required, false);
      assert.equal(cp.detectEvidenceRequirement("Give me a Dockerfile example").required, false);
      assert.equal(cp.detectEvidenceRequirement("How do I learn DevOps?").required, false);

      // Local evidence questions MUST require Control Plane evidence
      const timePlan = cp.detectEvidenceRequirement("What is today's date?");
      assert.equal(timePlan.required, true);
      assert.ok(timePlan.tools.includes("local_time"));

      const pwdPlan = cp.detectEvidenceRequirement("What is my current workspace?");
      assert.equal(pwdPlan.required, true);
      assert.ok(pwdPlan.tools.includes("workspace_pwd"));

      const lsPlan = cp.detectEvidenceRequirement("List files");
      assert.equal(lsPlan.required, true);
      assert.ok(lsPlan.tools.includes("workspace_ls"));

      const findPlan = cp.detectEvidenceRequirement("Find folder new-wedding");
      assert.equal(findPlan.required, true);
      assert.ok(findPlan.tools.includes("project_files"));
      assert.equal(findPlan.searchParams?.query, "new-wedding");

      const gitPlan = cp.detectEvidenceRequirement("What Git branch am I on?");
      assert.equal(gitPlan.required, true);
      assert.ok(gitPlan.tools.includes("git_read"));

      const dockerPlan = cp.detectEvidenceRequirement("What Docker information is available?");
      assert.equal(dockerPlan.required, true);
      assert.ok(dockerPlan.tools.includes("docker_read"));

      const k8sPlan = cp.detectEvidenceRequirement("Do I have Kubernetes configuration?");
      assert.equal(k8sPlan.required, true);
      assert.ok(k8sPlan.tools.includes("kubernetes_read"));

      const mixedPlan = cp.detectEvidenceRequirement("What Docker setup should I use for this project?");
      assert.equal(mixedPlan.required, true);
      assert.ok(mixedPlan.tools.includes("docker_read"));
      assert.ok(mixedPlan.tools.includes("workspace_ls"));
    });

    it("gatherEvidenceForQuery returns empty for general engineering queries", async () => {
      const generalEvidence = await cp.gatherEvidenceForQuery("Tell me 5 Docker commands");
      assert.deepEqual(generalEvidence, {}, "Must not inject fake local context for general questions");
    });
  });
});
