import { describe, it, expect } from "vitest";
import {
  buildAgentEvent,
  buildMCPObservation,
  buildToolInvocation,
  buildRiskSignal,
} from "./agentic";

const _base = {
  tenant_id: "tenant-x",
  event_name: "agent_activity_observed",
  source: { provider: "custom" as const },
  actor: { actor_type: "agent" as const, actor_id: "agent-1" },
  object: { object_type: "task", object_id: "task-1" },
  action: { name: "observe", status: "observed" as const },
};

describe("buildAgentEvent", () => {
  it("builds a valid envelope with execution_by_aether=false", () => {
    const evt = buildAgentEvent(_base);
    expect(evt.tenant_id).toBe("tenant-x");
    expect(evt.execution_by_aether).toBe(false);
  });

  it("rejects execution_by_aether=true", () => {
    expect(() =>
      buildAgentEvent({ ..._base, execution_by_aether: true as any })
    ).toThrow("execution_by_aether must be false");
  });

  it("rejects economics.is_execution_by_aether=true", () => {
    expect(() =>
      buildAgentEvent({
        ..._base,
        economics: { is_execution_by_aether: true as any },
      })
    ).toThrow("economics.is_execution_by_aether must be false");
  });

  it("forces economics.is_execution_by_aether to false", () => {
    const evt = buildAgentEvent({
      ..._base,
      economics: { is_execution_by_aether: false, amount: 10, currency: "USD" },
    });
    expect(evt.economics?.is_execution_by_aether).toBe(false);
    expect(evt.economics?.amount).toBe(10);
  });

  it("passes through v2 runtime context field", () => {
    const evt = buildAgentEvent({
      ..._base,
      runtime: { runtime_id: "rt-1", environment: "production" },
    });
    expect(evt.runtime?.runtime_id).toBe("rt-1");
    expect(evt.runtime?.environment).toBe("production");
  });

  it("passes through v2 correlation context field", () => {
    const evt = buildAgentEvent({ ..._base, correlation: { trace_id: "tr-abc" } });
    expect(evt.correlation?.trace_id).toBe("tr-abc");
  });

  it("passes through v2 mcp context field", () => {
    const evt = buildAgentEvent({
      ..._base,
      mcp: { server_name: "my-mcp", tool_name: "bash" },
    });
    expect(evt.mcp?.server_name).toBe("my-mcp");
    expect(evt.mcp?.tool_name).toBe("bash");
  });

  it("passes through v2 authorization context field", () => {
    const evt = buildAgentEvent({
      ..._base,
      authorization: { grant_id: "g-1", scope: ["read"] },
    });
    expect(evt.authorization?.grant_id).toBe("g-1");
  });

  it("passes through v2 verification context field", () => {
    const evt = buildAgentEvent({
      ..._base,
      verification: { verification_status: "confirmed" },
    });
    expect(evt.verification?.verification_status).toBe("confirmed");
  });

  it("passes through v2 privacy context field", () => {
    const evt = buildAgentEvent({
      ..._base,
      privacy: { privacy_class: "sensitive", dsr_applicable: true },
    });
    expect(evt.privacy?.dsr_applicable).toBe(true);
  });
});

describe("buildMCPObservation", () => {
  it("creates a valid MCP observation", () => {
    const obs = buildMCPObservation({
      tenant_id: "t-1",
      server_name: "test-mcp",
      tools: ["bash", "read"],
    });
    expect(obs.execution_by_aether).toBe(false);
    expect(obs.tools).toEqual(["bash", "read"]);
    expect(obs.server_name).toBe("test-mcp");
  });

  it("defaults tools to empty array", () => {
    const obs = buildMCPObservation({ tenant_id: "t-1", server_name: "mcp" });
    expect(obs.tools).toEqual([]);
  });
});

describe("buildToolInvocation", () => {
  it("creates a valid tool invocation", () => {
    const inv = buildToolInvocation({
      tenant_id: "t-1",
      tool_name: "write_file",
      agent_id: "agent-2",
      duration_ms: 42,
    });
    expect(inv.execution_by_aether).toBe(false);
    expect(inv.tool_name).toBe("write_file");
    expect(inv.status).toBe("observed");
    expect(inv.duration_ms).toBe(42);
  });

  it("uses provided status", () => {
    const inv = buildToolInvocation({
      tenant_id: "t-1",
      tool_name: "read_file",
      status: "succeeded_observed",
    });
    expect(inv.status).toBe("succeeded_observed");
  });
});

describe("buildRiskSignal", () => {
  it("creates a valid risk signal", () => {
    const sig = buildRiskSignal({
      tenant_id: "t-1",
      risk_level: "high",
      reason_codes: ["exceeded_tool_budget"],
    });
    expect(sig.risk_level).toBe("high");
    expect(sig.reason_codes).toContain("exceeded_tool_budget");
    expect(sig.policy_flags).toEqual([]);
  });

  it("defaults reason_codes and policy_flags to empty arrays", () => {
    const sig = buildRiskSignal({ tenant_id: "t-1", risk_level: "low" });
    expect(sig.reason_codes).toEqual([]);
    expect(sig.policy_flags).toEqual([]);
  });
});
