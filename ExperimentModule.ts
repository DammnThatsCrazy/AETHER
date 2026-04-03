// =============================================================================
// AETHER SDK — EXPERIMENTS MODULE
// Deterministic A/B testing with variant assignment and exposure tracking
// =============================================================================

import type { ExperimentConfig, ExperimentAssignment } from './WebSDKTypes(CoreTypeDefinitions)';
import { storage } from './SDKUtilityFunctions';

const ASSIGNMENTS_KEY = 'experiments';

export interface ExperimentCallbacks {
  onExposure: (experimentId: string, variantId: string) => void;
}

export class ExperimentsModule {
  private assignments: Map<string, ExperimentAssignment>;
  private callbacks: ExperimentCallbacks;
  private anonymousId: string;

  constructor(anonymousId: string, callbacks: ExperimentCallbacks) {
    this.anonymousId = anonymousId;
    this.callbacks = callbacks;
    this.assignments = this.loadAssignments();
  }

  /** Run an experiment — returns assigned variant ID and executes its callback */
  run(config: ExperimentConfig): string {
    const existing = this.assignments.get(config.id);
    if (existing) {
      // Execute the variant callback
      config.variants[existing.variantId]?.();
      this.callbacks.onExposure(config.id, existing.variantId);
      return existing.variantId;
    }

    // Deterministic assignment based on user ID + experiment ID
    const variantId = this.assignVariant(config);
    const assignment: ExperimentAssignment = {
      experimentId: config.id,
      variantId,
      assignedAt: new Date().toISOString(),
    };

    this.assignments.set(config.id, assignment);
    this.persistAssignments();

    // Execute variant callback
    config.variants[variantId]?.();
    this.callbacks.onExposure(config.id, variantId);

    return variantId;
  }

  /** Get existing assignment for an experiment */
  getAssignment(experimentId: string): ExperimentAssignment | null {
    return this.assignments.get(experimentId) ?? null;
  }

  /** Get all active assignments */
  getAllAssignments(): ExperimentAssignment[] {
    return Array.from(this.assignments.values());
  }

  /** Clear all experiment assignments */
  reset(): void {
    this.assignments.clear();
    storage.remove(ASSIGNMENTS_KEY);
  }

  /** Update anonymous ID (e.g., after identity merge) */
  setAnonymousId(id: string): void {
    this.anonymousId = id;
  }

  // ===========================================================================
  // PRIVATE
  // ===========================================================================

  /** Deterministic variant assignment using consistent hashing */
  private assignVariant(config: ExperimentConfig): string {
    const variantIds = Object.keys(config.variants);
    const weights = config.weights;

    if (weights) {
      // Weighted assignment
      const hash = this.hash(`${this.anonymousId}:${config.id}`);
      const normalizedHash = hash / 0xFFFFFFFF; // Normalize to 0-1
      let cumulative = 0;
      for (const [id, weight] of Object.entries(weights)) {
        cumulative += weight;
        if (normalizedHash <= cumulative) return id;
      }
      return variantIds[variantIds.length - 1];
    }

    // Equal weight assignment
    const hash = this.hash(`${this.anonymousId}:${config.id}`);
    const index = hash % variantIds.length;
    return variantIds[index];
  }

  /** Simple but deterministic hash function (FNV-1a 32-bit) */
  private hash(str: string): number {
    let h = 0x811c9dc5;
    for (let i = 0; i < str.length; i++) {
      h ^= str.charCodeAt(i);
      h = Math.imul(h, 0x01000193);
    }
    return h >>> 0;
  }

  private loadAssignments(): Map<string, ExperimentAssignment> {
    const stored = storage.get<Record<string, ExperimentAssignment>>(ASSIGNMENTS_KEY);
    if (stored) {
      return new Map(Object.entries(stored));
    }
    return new Map();
  }

  private persistAssignments(): void {
    const obj: Record<string, ExperimentAssignment> = {};
    this.assignments.forEach((v, k) => { obj[k] = v; });
    storage.set(ASSIGNMENTS_KEY, obj);
  }
}
