import assert from "node:assert/strict";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { inspectTargetDirectory, planDockerize, checkDockerAvailable } from "./server.js";

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
  const endpoint = "http://127.0.0.1:3000/api/agent/runs";
  const workflowEndpoint = "http://127.0.0.1:3000/api/runs";

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
}

await testApprovalGates();

// DOCKERIZE TEST G: Verify Dockerize does not claim files were generated unless files actually exist
console.log("\n[DOCKERIZE TEST G] Verify file generation claims match disk reality");
// In dry run:
assert.equal(fs.existsSync(path.join(tmpB, "Dockerfile")), false, "No Dockerfile should exist in dry-run mode");
assert.equal(dockerResB.files_generated.length, 0, "No files should be reported as generated");

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

// Clean up temporary fixtures
fs.rmSync(tmpB, { recursive: true, force: true });
fs.rmSync(tmpC, { recursive: true, force: true });
fs.rmSync(tmpD, { recursive: true, force: true });

console.log("\n=== ALL INSPECTION & DOCKERIZE TESTS PASSED SUCCESSFULLY! ===");
