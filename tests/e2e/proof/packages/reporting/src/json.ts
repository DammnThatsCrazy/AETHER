import { ProofResult, ProofStepResult } from "@aether/proof-runner";

/**
 * JsonReportGenerator — generates a structured JSON report from a ProofResult.
 */
export class JsonReportGenerator {
  generate(result: ProofResult): string {
    const report: Record<string, unknown> = {
      report_version: "1.0.0",
      generated_at: new Date().toISOString(),
      proof: {
        proof_id: result.proofId,
        status: result.status,
        started_at: result.startedAt,
        completed_at: result.completedAt,
        total_duration_ms: result.totalDurationMs,
        summary: result.summary,
      },
      steps: result.steps.map((step: ProofStepResult) => ({
        step_id: step.stepId,
        status: step.status,
        reason: step.reason,
        duration_ms: step.durationMs,
        details: step.details,
      })),
    };

    return JSON.stringify(report, null, 2);
  }

  /**
   * Generates and writes the JSON report to a file.
   */
  async generateToFile(
    result: ProofResult,
    filePath: string
  ): Promise<void> {
    const content = this.generate(result);
    const fs = await import("fs");
    fs.writeFileSync(filePath, content, "utf-8");
  }
}
