// =============================================================================
// AETHER SDK — FUNNEL MODULE (Tier 2 Thin Client)
// Tags events with funnel metadata from server config.
// No client-side funnel matching, no step tracking, no drop-off analysis.
// =============================================================================

export interface FunnelDefinition {
  id: string;
  name: string;
  steps: { id: string; name: string; event?: string; page?: string }[];
}

export interface FunnelCallbacks {
  onTrack: (event: string, properties: Record<string, unknown>) => void;
}

export class FunnelModule {
  private callbacks: FunnelCallbacks;
  private funnels: Map<string, FunnelDefinition> = new Map();

  constructor(callbacks: FunnelCallbacks, config?: { definitions?: FunnelDefinition[] }) {
    this.callbacks = callbacks;
    if (config?.definitions) {
      for (const def of config.definitions) {
        this.funnels.set(def.id, def);
      }
    }
  }

  /** Load funnel definitions from backend config */
  loadDefinitions(definitions: FunnelDefinition[]): void {
    this.funnels.clear();
    for (const def of definitions) {
      this.funnels.set(def.id, def);
    }
  }

  /** Tag an event with matching funnel metadata and ship to backend */
  tagEvent(eventName: string, properties?: Record<string, unknown>): void {
    this.funnels.forEach((funnel) => {
      const matchingStep = funnel.steps.find((s) => s.event === eventName);
      if (matchingStep) {
        this.callbacks.onTrack('funnel_event', {
          funnelId: funnel.id,
          funnelName: funnel.name,
          stepId: matchingStep.id,
          stepName: matchingStep.name,
          originalEvent: eventName,
          ...properties,
        });
      }
    });
  }

  /** Clean up */
  destroy(): void {
    this.funnels.clear();
  }
}
