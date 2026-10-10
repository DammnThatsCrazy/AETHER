// @aether/proof-runner — reporters: Console, JSON, Markdown
import type { ProofResult, ProofStepResult } from "./runner";
import { generateReport, generateMinimalReport } from "./reporting";

// ---------------------------------------------------------------------------
// ConsoleReporter — real-time console output
// ---------------------------------------------------------------------------

export class ConsoleReporter {
  readonly verbose: boolean;

  constructor(verbose = false) {
    this.verbose = verbose;
  }

  /** Print a step result as soon as it completes. */
  reportStep(result: ProofStepResult): void {
    const icon =
      result.status === "passed"
        ? "✓"
        : result.status === "skipped"
        ? "○"
        : "✗";
    const msg = `${icon} [${result.status.toUpperCase()}] ${result.stepId}`;
    if (this.verbose && result.reason) {
      console.log(`${msg} — ${result.reason}`);
    } else {
      console.log(msg);
    }
    if (this.verbose && result.details) {
      console.log(`    details: ${JSON.stringify(result.details)}`);
    }
  }

  /** Print the full proof result summary. */
  report(result: ProofResult): void {
    console.log("══════════════════════════════════════════════════════");
    console.log(`  Proof: ${result.proofId}`);
    console.log(`  Status: ${result.status.toUpperCase()}`);
    console.log(`  Started: ${result.startedAt}`);
    console.log(`  Completed: ${result.completedAt}`);
    if (result.totalDurationMs != null) {
      console.log(`  Duration: ${result.totalDurationMs}ms`);
    }
    console.log("──────────────────────────────────────────────────────────");
    console.log("  Steps:");
    for (const step of result.steps) {
      this.reportStep(step);
    }
    console.log("──────────────────────────────────────────────────────────");
    if (result.summary) {
      console.log(`  Summary: ${result.summary}`);
    }
    console.log("══════════════════════════════════════════════════════");
  }
}

// ---------------------------------------------------------------------------
// JsonReporter — JSON output
// ---------------------------------------------------------------------------

export class JsonReporter {
  private readonly chunks: string[] = [];

  /** Capture a step result as a JSON line. */
  reportStep(result: ProofStepResult): void {
    this.chunks.push(JSON.stringify(result));
  }

  /** Return all captured JSON lines as a single string (newline-delimited). */
  getJsonLines(): string {
    return this.chunks.join("\n");
  }

  /** Return all captured step results as a JSON array. */
  getJsonArray(): string {
    return JSON.stringify(this.chunks.map((line) => JSON.parse(line)), null, 2);
  }

  /** Emit all captured JSON to stdout. */
  emit(): void {
    for (const chunk of this.chunks) {
      console.log(chunk);
    }
  }

  /** Clear captured output. */
  clear(): void {
    this.chunks.length = 0;
  }
}

// ---------------------------------------------------------------------------
// MarkdownReporter — 24-line markdown report
// ---------------------------------------------------------------------------

export class MarkdownReporter {
  private readonly results: ProofStepResult[] = [];
  private title?: string;
  private generatedAt?: string;

  /** Set an optional report title. */
  setTitle(title: string): this {
    this.title = title;
    return this;
  }

  /** Capture a step result for inclusion in the final report. */
  reportStep(result: ProofStepResult): void {
    this.results.push(result);
  }

  /** Generate the full markdown report string. */
  getReport(): string {
    return generateReport(this.results, {
      title: this.title,
      generatedAt: this.generatedAt ?? new Date().toISOString(),
    });
  }

  /** Generate the minimal 24-line markdown report. */
  getMinimalReport(): string {
    return generateMinimalReport(this.results);
  }

  /** Write the report to a file path. */
  async writeReport(filePath: string): Promise<void> {
    const fs = await import("fs/promises");
    const report = this.getReport();
    await fs.writeFile(filePath, report, "utf-8");
  }
}
