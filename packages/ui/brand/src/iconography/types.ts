/**
 * Semantic icon names are renderer-agnostic. `@olympus/brand` does not ship SVG
 * geometry or a component; `@aether/ui` maps these names to its approved SVG
 * primitives while retaining the semantic label and decorative policy.
 */
export interface IconDescriptor {
  readonly icon: string;
  readonly label: string;
  readonly decorativeByDefault: boolean;
  readonly description: string;
}
