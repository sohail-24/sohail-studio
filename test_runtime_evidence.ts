import assert from "node:assert/strict";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { inspectTargetDirectory } from "./server.js";

process.env.NODE_ENV = "test";

console.log("=== Running Project Intelligence Runtime Evidence Tests ===");

// -------------------------------------------------------------
// TEST A: Current Sohail Studio Repository
// -------------------------------------------------------------
console.log("\n[TEST A] Current Sohail Studio repository (no engines.node)");
const repoIntel = inspectTargetDirectory(".", "run-test-a");

// 1. Must NOT claim Node.js 22 as verified project runtime evidence
const hasHardcoded22Runtime = repoIntel.runtimes.some(
  (r: any) => r.runtime === "Node.js" && r.version === "22"
);
assert.equal(hasHardcoded22Runtime, false, "Must NOT report hard-coded Node.js 22 in runtimes");

const hasHardcoded22Evidence = repoIntel.evidence.some(
  (e: any) => e.evidence_type === "runtime_version" && e.value === "22"
);
assert.equal(hasHardcoded22Evidence, false, "Must NOT claim Node.js 22 in verified evidence list");

// 2. Runtime version must be unknown / needs evidence
const nodeRuntime = repoIntel.runtimes.find((r: any) => r.runtime === "Node.js");
assert.ok(nodeRuntime, "Node.js runtime should still be detected");
assert.equal(nodeRuntime.version, "NEEDS_EVIDENCE", "Node.js version should be NEEDS_EVIDENCE");

// 3. Evidence gaps must record the missing runtime version declaration
const runtimeGap = repoIntel.evidence_gaps.find(
  (g: any) => g.kind === "runtime_version" && g.status === "NEEDS_EVIDENCE"
);
assert.ok(runtimeGap, "evidence_gaps should record a NEEDS_EVIDENCE finding for runtime_version");

// 4. Valid existing detection preserved
assert.ok(repoIntel.languages.includes("TypeScript"), "TypeScript must remain detected");
assert.ok(repoIntel.languages.includes("JavaScript"), "JavaScript must remain detected");
assert.ok(repoIntel.package_managers.includes("npm"), "npm must remain detected");
assert.ok(repoIntel.frameworks.includes("Express"), "Express must remain detected");
assert.ok(repoIntel.components.some((c: any) => c.name === "studio-service"), "studio-service component preserved");
assert.ok(repoIntel.components.some((c: any) => c.name === "dashboard-ui"), "dashboard-ui component preserved");

// 5. Port 3000 must remain detected
const port3000 = repoIntel.ports.find((p: any) => p.port === 3000 || p.value === 3000);
assert.ok(port3000, "Port 3000 must remain detected from server.ts");

console.log("✓ TEST A passed: No Node 22 fabricated; JS/TS/npm/Express/port 3000 preserved; NEEDS_EVIDENCE reported.");

// -------------------------------------------------------------
// TEST B: Synthetic fixture with engines.node: "22"
// -------------------------------------------------------------
console.log("\n[TEST B] Synthetic fixture with engines.node = '22'");
const tmpB = fs.mkdtempSync(path.join(os.tmpdir(), "sohail-test-b-"));
try {
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

  console.log("✓ TEST B passed: Explicit engines.node='22' correctly reported with package.json provenance.");
} finally {
  fs.rmSync(tmpB, { recursive: true, force: true });
}

// -------------------------------------------------------------
// TEST C: Synthetic fixture with constraint engines.node: ">=20 <23"
// -------------------------------------------------------------
console.log("\n[TEST C] Synthetic fixture with engines.node = '>=20 <23'");
const tmpC = fs.mkdtempSync(path.join(os.tmpdir(), "sohail-test-c-"));
try {
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

  console.log("✓ TEST C passed: Constraint '>=20 <23' preserved accurately without conversion.");
} finally {
  fs.rmSync(tmpC, { recursive: true, force: true });
}

// -------------------------------------------------------------
// TEST D: No Node runtime declaration (pure JS project without engines)
// -------------------------------------------------------------
console.log("\n[TEST D] Pure JS fixture with no runtime declaration");
const tmpD = fs.mkdtempSync(path.join(os.tmpdir(), "sohail-test-d-"));
try {
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

  console.log("✓ TEST D passed: Reported NEEDS_EVIDENCE; zero machine-version or hard-coded inference.");
} finally {
  fs.rmSync(tmpD, { recursive: true, force: true });
}

console.log("\n=== ALL 4 TESTS PASSED SUCCESSFULLY! ===");
