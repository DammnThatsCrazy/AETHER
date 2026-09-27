import { beforeEach, describe, expect, it } from "vitest";
import {
  parseSelfServePlan,
  readPostAuthDestination,
  rememberPostAuthDestination,
} from "./post-auth-redirect";

describe("parseSelfServePlan", () => {
  it("accepts the four self-serve plans, case-insensitively", () => {
    expect(parseSelfServePlan("alpha")).toBe("alpha");
    expect(parseSelfServePlan(" Beta ")).toBe("beta");
    expect(parseSelfServePlan("DELTA")).toBe("delta");
  });

  it("rejects anything else", () => {
    expect(parseSelfServePlan(null)).toBeNull();
    expect(parseSelfServePlan("")).toBeNull();
    expect(parseSelfServePlan("enterprise")).toBeNull();
    expect(parseSelfServePlan("P2")).toBeNull();
  });
});

describe("post-auth destination across the Auth0 round trip", () => {
  beforeEach(() => sessionStorage.clear());

  it("returns the remembered destination, and again on a repeated read", () => {
    rememberPostAuthDestination("/billing?plan=beta", 1_000);
    expect(readPostAuthDestination(2_000)).toBe("/billing?plan=beta");
    expect(readPostAuthDestination(3_000)).toBe("/billing?plan=beta");
  });

  it("falls back to the tenant home when nothing was remembered", () => {
    expect(readPostAuthDestination()).toBe("/settings");
  });

  it("never stores or returns an off-site destination", () => {
    rememberPostAuthDestination("//evil.example/x", 1_000);
    expect(readPostAuthDestination(2_000)).toBe("/settings");
    sessionStorage.setItem(
      "aether:post-auth-destination",
      JSON.stringify({ path: "https://evil.example", at: 1_000 }),
    );
    expect(readPostAuthDestination(2_000)).toBe("/settings");
  });

  it("ignores an expired or malformed entry", () => {
    rememberPostAuthDestination("/billing?plan=gamma", 0);
    expect(readPostAuthDestination(31 * 60 * 1000)).toBe("/settings");
    sessionStorage.setItem("aether:post-auth-destination", "not json");
    expect(readPostAuthDestination()).toBe("/settings");
  });

  it("a later hand-off overwrites the earlier one", () => {
    rememberPostAuthDestination("/billing?plan=beta", 1_000);
    rememberPostAuthDestination("/graph", 2_000);
    expect(readPostAuthDestination(3_000)).toBe("/graph");
  });
});
