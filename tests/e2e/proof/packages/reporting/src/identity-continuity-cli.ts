#!/usr/bin/env node
import { readFileSync, writeFileSync } from "fs";
import { buildIdentityContinuityPack, validateIdentityContinuityPack } from "./identity-continuity-pack";
import { collectIdentityContinuityEvidence } from "./identity-continuity-collector";

function usage(): never {
  process.stderr.write("Usage: aether-identity-proof-pack collect <staging-capture.json> <output-directory>\n       aether-identity-proof-pack build <evidence-manifest.json> <output-pack.json>\n       aether-identity-proof-pack validate <pack.json>\n");
  process.exit(2);
}

const [command, inputPath, outputPath] = process.argv.slice(2);
if (command === "collect" && inputPath && outputPath) {
  const result = collectIdentityContinuityEvidence(inputPath, outputPath);
  if (!result.collected) {
    process.stderr.write(`Identity continuity staging capture incomplete; no proof pack emitted:\n${result.errors.map((error) => `- ${error}`).join("\n")}\n`);
    process.exit(1);
  }
  process.stdout.write(`Collected and validated identity continuity staging proof pack: ${result.packPath}\n`);
} else if (command === "build" && inputPath && outputPath) {
  const result = buildIdentityContinuityPack(inputPath, outputPath);
  if (!result.valid) {
    process.stderr.write(`Identity continuity proof pack rejected:\n${result.errors.map((error) => `- ${error}`).join("\n")}\n`);
    process.exit(1);
  }
  process.stdout.write(`Validated identity continuity proof pack: ${outputPath}\n`);
} else if (command === "validate" && inputPath && !outputPath) {
  let pack: unknown;
  try { pack = JSON.parse(readFileSync(inputPath, "utf8")); }
  catch (error) {
    process.stderr.write(`Cannot read pack: ${String(error)}\n`);
    process.exit(1);
  }
  const result = validateIdentityContinuityPack(pack, inputPath);
  if (!result.valid) {
    process.stderr.write(`Identity continuity proof pack rejected:\n${result.errors.map((error) => `- ${error}`).join("\n")}\n`);
    process.exit(1);
  }
  process.stdout.write(`Identity continuity proof pack valid: ${inputPath}\n`);
} else usage();
