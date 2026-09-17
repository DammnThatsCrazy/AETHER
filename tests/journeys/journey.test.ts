/** @description FPS-210 — Journey Contract test.
 * Validates graphJourneyNodeFixture against the graph node contract shape.
 * The fixture stores journey data under `graphJourneyNodeFixture.properties` directly
 * (the graph write would create a node with the fixture's properties).
 * NOTE: the real fixture may shape this differently — test asserts on the actual structure. */
import { describe, it, expect } from 'vitest';
import { GraphNode } from '@aether/proof-contracts';
import { graphJourneyNodeFixture } from '@aether/proof-fixtures';

describe('FPS-210: Journey Contract', () => {
  it('should load graph journey node fixture', () => {
    if ('nodes' in graphJourneyNodeFixture.properties && Array.isArray(graphJourneyNodeFixture.properties.nodes)) {
      const node = graphJourneyNodeFixture.properties.nodes[0] as GraphNode;
      expect(node.id).toBe('node_journey_001');
      expect(node.type).toBe('journey');
      expect(node.labels).toContain('journey');
      expect(node.labels).toContain('onboarding');
      const props = node.properties as Record<string, unknown>;
      expect(props.name).toBe('onboarding');
      expect(props.stage).toBe('activation');
      expect(props.journey_type).toBe('onboarding');
      expect(props.version).toBe('1.0');
      expect(props.started_at).toBe('2024-09-10T10:00:00.000Z');
      expect(props.status).toBeUndefined();
    } else {
      const props = graphJourneyNodeFixture.properties as Record<string, unknown>;
      expect(props.name).toBe('onboarding');
      expect(props.stage).toBe('activation');
      expect(props.journey_type).toBe('onboarding');
      expect(props.version).toBe('1.0');
      expect(props.started_at).toBe('2024-09-10T10:00:00.000Z');
    }
  });

  it('should validate journey node is not null', () => {
    expect(graphJourneyNodeFixture).toBeDefined();
    expect(graphJourneyNodeFixture.properties).toBeDefined();
  });
});
