import assert from "node:assert/strict";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import {
  server,
  inspectTargetDirectory,
  planDockerize,
  checkDockerAvailable,
  generateMentorResponse,
  storedIntelligence
} from "./server.js";

process.env.NODE_ENV = "test";

console.log("=== Running Project Intelligence Runtime Evidence & Dockerize Tests ===");

// -------------------------------------------------------------
// PART 1: INSPECTOR RUNTIME EVIDENCE
// -------------------------------------------------------------

// TEST A: Current Sohail Studio Repository
console.log("\n[INSPECTOR TEST A] Current Sohail Studio repository (no engines.node)");
const repoIntel = inspectTargetDirectory(".", "run-test-a");

const hasHardcoded22Runtime = repoIntel.runtimes.some(
  (r: any) => r.runtime === "Node.js" && r.version === "22"
);
assert.equal(hasHardcoded22Runtime, false, "Must NOT report hard-coded Node.js 22 in runtimes");

const hasHardcoded22Evidence = repoIntel.evidence.some(
  (e: any) => e.evidence_type === "runtime_version" && e.value === "22"
);
assert.equal(hasHardcoded22Evidence, false, "Must NOT claim Node.js 22 in verified evidence list");

const nodeRuntime = repoIntel.runtimes.find((r: any) => r.runtime === "Node.js");
assert.ok(nodeRuntime, "Node.js runtime should still be detected");
assert.equal(nodeRuntime.version, "NEEDS_EVIDENCE", "Node.js version should be NEEDS_EVIDENCE");

const runtimeGap = repoIntel.evidence_gaps.find(
  (g: any) => g.kind === "runtime_version" && g.status === "NEEDS_EVIDENCE"
);
assert.ok(runtimeGap, "evidence_gaps should record a NEEDS_EVIDENCE finding for runtime_version");
assert.ok(repoIntel.languages.includes("TypeScript"), "TypeScript must remain detected");
assert.ok(repoIntel.languages.includes("JavaScript"), "JavaScript must remain detected");
assert.ok(repoIntel.package_managers.includes("npm"), "npm must remain detected");
assert.ok(repoIntel.frameworks.includes("Express"), "Express must remain detected");
assert.ok(repoIntel.components.some((c: any) => c.name === "studio-service"), "studio-service component preserved");
assert.ok(repoIntel.components.some((c: any) => c.name === "dashboard-ui"), "dashboard-ui component preserved");

const port3000 = repoIntel.ports.find((p: any) => p.port === 3000 || p.value === 3000);
assert.ok(port3000, "Port 3000 must remain detected from server.ts");
console.log("✓ INSPECTOR TEST A passed.");

// TEST B: Synthetic fixture with engines.node: "22"
console.log("\n[INSPECTOR TEST B] Synthetic fixture with engines.node = '22'");
const tmpB = fs.mkdtempSync(path.join(os.tmpdir(), "sohail-test-b-"));
fs.writeFileSync(
  path.join(tmpB, "package.json"),
  JSON.stringify({
    name: "fixture-b",
    engines: {
      node: "22"
    },
    dependencies: {
      express: "^4.21.0"
    }
  })
);

const intelB = inspectTargetDirectory(tmpB, "run-test-b");
const runtimeB = intelB.runtimes.find((r: any) => r.runtime === "Node.js");
assert.ok(runtimeB, "Node.js runtime must be detected");
assert.equal(runtimeB.version, "22", "Node.js 22 should be reported when explicitly declared");

const evidenceB = intelB.evidence.find(
  (e: any) => e.evidence_type === "runtime_version" && e.key === "Node.js"
);
assert.ok(evidenceB, "Evidence entry for Node.js runtime version must exist");
assert.equal(evidenceB.value, "22", "Evidence value must be 22");
assert.equal(evidenceB.source_file, "package.json", "Evidence must point to package.json");
assert.equal(evidenceB.extraction_method, "manifest-engines", "Extraction method should be manifest-engines");
assert.equal(evidenceB.confidence, "high", "Confidence must be high");
console.log("✓ INSPECTOR TEST B passed.");

// TEST C: Synthetic fixture with constraint engines.node: ">=20 <23"
console.log("\n[INSPECTOR TEST C] Synthetic fixture with engines.node = '>=20 <23'");
const tmpC = fs.mkdtempSync(path.join(os.tmpdir(), "sohail-test-c-"));
fs.writeFileSync(
  path.join(tmpC, "package.json"),
  JSON.stringify({
    name: "fixture-c",
    engines: {
      node: ">=20 <23"
    },
    dependencies: {
      express: "^4.21.0"
    }
  })
);

const intelC = inspectTargetDirectory(tmpC, "run-test-c");
const runtimeC = intelC.runtimes.find((r: any) => r.runtime === "Node.js");
assert.ok(runtimeC, "Node.js runtime must be detected");
assert.equal(runtimeC.version, ">=20 <23", "Constraint '>=20 <23' must be accurately preserved");

const evidenceC = intelC.evidence.find(
  (e: any) => e.evidence_type === "runtime_version" && e.key === "Node.js"
);
assert.ok(evidenceC, "Evidence entry must exist");
assert.equal(evidenceC.value, ">=20 <23", "Constraint must not be converted to an invented single version");
assert.equal(evidenceC.source_file, "package.json", "Evidence must point to package.json");
console.log("✓ INSPECTOR TEST C passed.");

// TEST D: No Node runtime declaration (pure JS project without engines)
console.log("\n[INSPECTOR TEST D] Pure JS fixture with no runtime declaration");
const tmpD = fs.mkdtempSync(path.join(os.tmpdir(), "sohail-test-d-"));
fs.writeFileSync(path.join(tmpD, "index.js"), "console.log('hello');");
fs.writeFileSync(path.join(tmpD, "package.json"), JSON.stringify({ name: "fixture-d" }));

const intelD = inspectTargetDirectory(tmpD, "run-test-d");
const runtimeD = intelD.runtimes.find((r: any) => r.runtime === "Node.js");
assert.ok(runtimeD, "Node.js runtime must be detected from JS/package.json");
assert.equal(runtimeD.version, "NEEDS_EVIDENCE", "Runtime version must be NEEDS_EVIDENCE");
assert.notEqual(runtimeD.version, process.version, "Must not infer machine process.version");
assert.notEqual(runtimeD.version, "22", "Must not infer hardcoded 22");

const runtimeGapD = intelD.evidence_gaps.find(
  (g: any) => g.kind === "runtime_version" && g.status === "NEEDS_EVIDENCE"
);
assert.ok(runtimeGapD, "Must flag evidence gap for missing runtime version declaration");
console.log("✓ INSPECTOR TEST D passed.");

// -------------------------------------------------------------
// PART 2: EVIDENCE-BOUND DOCKERIZE TESTS
// -------------------------------------------------------------
console.log("\n=== DOCKERIZE VERIFICATION TESTS ===");

// DOCKERIZE TEST A: Current Sohail Studio Repository
console.log("\n[DOCKERIZE TEST A] Current Sohail Studio repo must return NEEDS_EVIDENCE, no invented Node 22 image");
const dockerResA = planDockerize(".", { dryRun: true }, "docker-test-a");
assert.equal(dockerResA.status, "NEEDS_EVIDENCE", "Must return NEEDS_EVIDENCE when node version lacks evidence");
assert.ok(dockerResA.missing_evidence && dockerResA.missing_evidence.length > 0, "Must report missing evidence");
const missingA = dockerResA.missing_evidence.find((m: any) => m.name === "Node.js" || m.kind === "runtime_version");
assert.ok(missingA, "Must identify missing Node.js runtime version declaration");
assert.equal(missingA.message, "Node.js runtime version declaration is missing.");
assert.equal(dockerResA.plan, undefined, "Must NOT generate a plan or base image when evidence is missing");
assert.equal(dockerResA.files_generated.length, 0, "Must not claim any files generated");
console.log("✓ DOCKERIZE TEST A passed: Correctly blocked with NEEDS_EVIDENCE without inventing Node 22.");

// DOCKERIZE TEST B: Synthetic project with explicit engines.node = "22"
console.log("\n[DOCKERIZE TEST B] Synthetic project with explicit engines.node: '22'");
const dockerResB = planDockerize(tmpB, { dryRun: true }, "docker-test-b");
assert.equal(dockerResB.status, "SUCCESS", "Must succeed when valid explicit runtime evidence exists");
assert.ok(dockerResB.plan, "Plan must be formulated");
assert.equal(dockerResB.plan.runtime, "Node.js");
assert.equal(dockerResB.plan.runtime_version, "22");
assert.equal(dockerResB.plan.base_image, "node:22");
assert.equal(dockerResB.plan.evidence_provenance.source_file, "package.json");
assert.equal(dockerResB.plan.evidence_provenance.value, "22");
assert.equal(dockerResB.plan.evidence_provenance.extraction_method, "manifest-engines");
assert.equal(dockerResB.files_generated.length, 0, "Dry run must generate 0 files on disk");
console.log("✓ DOCKERIZE TEST B passed: Exact evidence provenance and node:22 preserved.");

// DOCKERIZE TEST C: Synthetic project with engines.node = ">=20 <23"
console.log("\n[DOCKERIZE TEST C] Synthetic project with constraint engines.node: '>=20 <23'");
const dockerResC = planDockerize(tmpC, { dryRun: true }, "docker-test-c");
assert.equal(dockerResC.status, "SUCCESS", "Must succeed formulating plan with constraint");
assert.ok(dockerResC.plan, "Plan must be formulated");
assert.equal(dockerResC.plan.runtime_version, ">=20 <23", "Must preserve exact constraint without inventing a single version");
assert.notEqual(dockerResC.plan.runtime_version, "20", "Must not invent version 20");
assert.notEqual(dockerResC.plan.runtime_version, "22", "Must not invent version 22");
assert.equal(dockerResC.plan.requires_version_pin, true, "Must flag that concrete version pin is required for FROM instruction");
assert.equal(dockerResC.plan.base_image, null, "Must not generate an arbitrary base image tag for a range constraint");
console.log("✓ DOCKERIZE TEST C passed: Constraint '>=20 <23' preserved accurately, no invented single version.");

// DOCKERIZE TEST D: Missing required Dockerization evidence
console.log("\n[DOCKERIZE TEST D] Missing required Dockerization evidence produces NEEDS_EVIDENCE");
const dockerResD = planDockerize(tmpD, { dryRun: true }, "docker-test-d");
assert.equal(dockerResD.status, "NEEDS_EVIDENCE");
assert.ok(dockerResD.missing_evidence && dockerResD.missing_evidence.length > 0);
assert.equal(dockerResD.missing_evidence[0].message, "Node.js runtime version declaration is missing.");
console.log("✓ DOCKERIZE TEST D passed: Missing evidence returned correctly.");

// DOCKERIZE TEST E: Verify approved:false cannot execute Dockerize
console.log("\n[DOCKERIZE TEST E] Verify approved:false cannot execute Dockerize via API");
async function testApprovalGates() {
  let testPort = 3000;
  let testServer: any = null;

  if (!server.listening) {
    await new Promise<void>((resolve) => {
      testServer = server.listen(0, "127.0.0.1", () => {
        testPort = (server.address() as any).port;
        resolve();
      });
    });
  }

  const endpoint = `http://127.0.0.1:${testPort}/api/agent/runs`;
  const workflowEndpoint = `http://127.0.0.1:${testPort}/api/runs`;

  try {
    // Test 1: Agent runs without approved: true
    const resUnapprovedAgent = await fetch(endpoint, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ operation: "dockerize", target: ".", approved: false })
    });
    assert.equal(resUnapprovedAgent.status, 400, "Unapproved agent run must return HTTP 400");
    const unapprovedAgentJson = await resUnapprovedAgent.json();
    assert.equal(unapprovedAgentJson.detail, "Approval required");

    // Test 2: Workflow runs without approved: true
    const resUnapprovedWorkflow = await fetch(workflowEndpoint, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ workflow: "dockerize-project", target: ".", approved: false })
    });
    assert.equal(resUnapprovedWorkflow.status, 400, "Unapproved workflow run must return HTTP 400");
    const unapprovedWorkflowJson = await resUnapprovedWorkflow.json();
    assert.equal(unapprovedWorkflowJson.detail, "Approval required");
    console.log("✓ DOCKERIZE TEST E passed: Both /api/agent/runs and /api/runs strictly enforce approved === true.");

    // DOCKERIZE TEST F: Verify approved:true reaches the Dockerize planning/validation path
    console.log("\n[DOCKERIZE TEST F] Verify approved:true reaches Dockerize path");
    const resApprovedAgent = await fetch(endpoint, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ operation: "dockerize", target: ".", approved: true })
    });
    assert.equal(resApprovedAgent.status, 200, "Approved agent run must return HTTP 200");
    const approvedAgentJson = await resApprovedAgent.json();
    assert.ok(approvedAgentJson.run_id, "Approved agent run returns run_id");
    console.log("✓ DOCKERIZE TEST F passed: approved:true accepted and launched run " + approvedAgentJson.run_id);
  } finally {
    if (testServer) {
      testServer.close();
    }
  }
}

await testApprovalGates();

// DOCKERIZE TEST G: Verify Dockerize does not claim files were generated unless files actually exist
console.log("\n[DOCKERIZE TEST G] Verify file generation claims match disk reality");
// In dry run:
assert.equal(fs.existsSync(path.join(tmpB, "Dockerfile")), false, "No Dockerfile should exist in dry-run mode");
assert.equal(dockerResB.files_generated.length, 0, "No files should be reported as generated");
assert.deepEqual(dockerResB.plan?.stages, ["runtime"], "Single FROM Dockerfile must be reported with single stage ['runtime']");
assert.equal(dockerResB.plan?.dockerfile_content?.includes("AS base"), false, "1-FROM Dockerfile must not pretend to be multi-stage");

// In active file generation with verified evidence:
const dockerResBGenerate = planDockerize(tmpB, { dryRun: false, generateFiles: true }, "docker-test-b-gen");
assert.equal(dockerResBGenerate.status, "SUCCESS");
assert.equal(dockerResBGenerate.files_generated.length, 1);
const generatedPath = dockerResBGenerate.files_generated[0];
assert.equal(fs.existsSync(generatedPath), true, "File claimed as generated MUST actually exist on disk");
const content = fs.readFileSync(generatedPath, "utf-8");
assert.ok(content.includes("FROM node:22"), "Dockerfile content must use verified base image");
assert.ok(content.includes("package.json"), "Dockerfile must reference evidence source");
console.log("✓ DOCKERIZE TEST G passed: Files only claimed when verified to exist on disk.");

// -------------------------------------------------------------
// PART 3: MENTOR CONTAINERIZATION GUIDANCE
// -------------------------------------------------------------
console.log("\n=== MENTOR GUIDANCE TESTS ===");

console.log("\n[MENTOR TEST 1] Verify mentor guidance never references node:22-alpine");
const mentorQuery1 = generateMentorResponse("How do I dockerize my project?");
assert.equal(mentorQuery1.includes("node:22-alpine"), false, "Mentor guidance must NEVER use node:22-alpine");
assert.equal(mentorQuery1.includes("multi-stage"), false, "Mentor guidance must NOT describe 1-FROM container as multi-stage");
assert.ok(mentorQuery1.includes("NEEDS_EVIDENCE") || mentorQuery1.includes("Declare Runtime Version"), "Mentor guidance must be evidence-aware and flag missing declarations");
console.log("✓ MENTOR TEST 1 passed: Mentor container guidance is evidence-aware with zero node:22-alpine.");

console.log("\n[MENTOR TEST 2] Verify mentor guidance for project with declared engines.node");
const mentorQuery2 = generateMentorResponse("How should I containerize this?", tmpB);
assert.equal(mentorQuery2.includes("node:22-alpine"), false, "Must not use node:22-alpine even on pinned project");
assert.ok(mentorQuery2.includes("node:22"), "Mentor should reflect detected node:22 from evidence");
assert.equal(mentorQuery2.includes("multi-stage"), false, "Must not claim multi-stage");
console.log("✓ MENTOR TEST 2 passed: Mentor guidance reflects explicit project intelligence.");

// -------------------------------------------------------------
// PART 4: REGRESSION TESTS FOR ALL EVIDENCE GAPS (ZERO FALLBACKS)
// -------------------------------------------------------------
console.log("\n=== REGRESSION TESTS: EVIDENCE GAPS & ZERO PRODUCTION FALLBACKS ===");

// GAP 1: Missing Framework (package.json has engines.node 22, but NO framework dependency)
console.log("\n[GAP TEST 1] Missing framework evidence produces NEEDS_EVIDENCE (no fallback to Node.js)");
const tmpNoFramework = fs.mkdtempSync(path.join(os.tmpdir(), "sohail-test-no-framework-"));
fs.writeFileSync(
  path.join(tmpNoFramework, "package.json"),
  JSON.stringify({ name: "no-framework", engines: { node: "22" } })
);
const resNoFramework = planDockerize(tmpNoFramework, { dryRun: true }, "gap-framework");
assert.equal(resNoFramework.status, "NEEDS_EVIDENCE");
assert.ok(resNoFramework.missing_evidence?.some((m) => m.kind === "framework"), "Must report missing framework evidence");
assert.equal(resNoFramework.plan, undefined, "No plan when framework is missing");
console.log("✓ GAP TEST 1 passed: Missing framework strictly produces NEEDS_EVIDENCE.");
fs.rmSync(tmpNoFramework, { recursive: true, force: true });

// GAP 2: Missing Package Manager
console.log("\n[GAP TEST 2] Missing package manager evidence produces NEEDS_EVIDENCE (no fallback to npm)");
const tmpNoPkgManager = fs.mkdtempSync(path.join(os.tmpdir(), "sohail-test-no-pkgmgr-"));
storedIntelligence.set(tmpNoPkgManager, {
  name: "no-pkgmgr",
  root_path: tmpNoPkgManager,
  intelligence_status: "COMPLETE",
  files: ["index.js"],
  components: [],
  languages: ["JavaScript"],
  frameworks: ["Express"],
  runtimes: [{ runtime: "Node.js", version: "22" }],
  package_managers: [], // empty!
  ports: [{ port: 3000, value: 3000 }],
  evidence: [{ evidence_type: "runtime_version", key: "Node.js", value: "22" }]
});
const resNoPkgManager = planDockerize(tmpNoPkgManager, { dryRun: true }, "gap-pkgmgr");
assert.equal(resNoPkgManager.status, "NEEDS_EVIDENCE");
assert.ok(resNoPkgManager.missing_evidence?.some((m) => m.kind === "package_manager"), "Must report missing package manager");
assert.equal(resNoPkgManager.plan, undefined);
console.log("✓ GAP TEST 2 passed: Missing package manager strictly produces NEEDS_EVIDENCE.");
fs.rmSync(tmpNoPkgManager, { recursive: true, force: true });

// GAP 3: Missing Port
console.log("\n[GAP TEST 3] Missing port evidence produces NEEDS_EVIDENCE (no fallback to 3000)");
const tmpNoPort = fs.mkdtempSync(path.join(os.tmpdir(), "sohail-test-no-port-"));
storedIntelligence.set(tmpNoPort, {
  name: "no-port",
  root_path: tmpNoPort,
  intelligence_status: "COMPLETE",
  files: ["server.js"],
  components: [],
  languages: ["JavaScript"],
  frameworks: ["Express"],
  runtimes: [{ runtime: "Node.js", version: "22" }],
  package_managers: ["npm"],
  ports: [], // empty!
  evidence: [{ evidence_type: "runtime_version", key: "Node.js", value: "22" }]
});
const resNoPort = planDockerize(tmpNoPort, { dryRun: true }, "gap-port");
assert.equal(resNoPort.status, "NEEDS_EVIDENCE");
assert.ok(resNoPort.missing_evidence?.some((m) => m.kind === "port"), "Must report missing port declaration");
assert.equal(resNoPort.plan, undefined);
console.log("✓ GAP TEST 3 passed: Missing port strictly produces NEEDS_EVIDENCE.");
fs.rmSync(tmpNoPort, { recursive: true, force: true });

// GAP 4: Missing Runtime Version
console.log("\n[GAP TEST 4] Missing runtime version declaration strictly produces NEEDS_EVIDENCE");
const tmpNoRuntime = fs.mkdtempSync(path.join(os.tmpdir(), "sohail-test-no-runtime-"));
fs.writeFileSync(
  path.join(tmpNoRuntime, "package.json"),
  JSON.stringify({ name: "no-runtime", dependencies: { express: "^4.21.0" } })
);
const resNoRuntime = planDockerize(tmpNoRuntime, { dryRun: true }, "gap-runtime");
assert.equal(resNoRuntime.status, "NEEDS_EVIDENCE");
assert.ok(resNoRuntime.missing_evidence?.some((m) => m.kind === "runtime_version"), "Must report missing runtime version");
assert.equal(resNoRuntime.plan, undefined);
console.log("✓ GAP TEST 4 passed: Missing runtime version strictly produces NEEDS_EVIDENCE.");
fs.rmSync(tmpNoRuntime, { recursive: true, force: true });

// GAP 5: Range Constraint preserves constraint and never invents base image
console.log("\n[GAP TEST 5] Range constraint preserves constraint, requires_version_pin: true, base_image: null");
assert.equal(dockerResC.status, "SUCCESS");
assert.equal(dockerResC.plan?.runtime_version, ">=20 <23");
assert.equal(dockerResC.plan?.requires_version_pin, true);
assert.equal(dockerResC.plan?.base_image, null);
assert.ok(dockerResC.plan?.base_image_note?.includes("Runtime constraint '>=20 <23' preserved"));
console.log("✓ GAP TEST 5 passed: Range constraint preserved without inventing version or base image.");

// Clean up temporary fixtures
fs.rmSync(tmpB, { recursive: true, force: true });
fs.rmSync(tmpC, { recursive: true, force: true });
fs.rmSync(tmpD, { recursive: true, force: true });

console.log("\n=== ALL INSPECTION & DOCKERIZE TESTS PASSED SUCCESSFULLY! ===");
