import { GlyphIcon } from './glyph-icon';

export interface DemoTenantBannerProps {
  readonly tenantName?: string | null;
  readonly datasetVersion?: string | null;
}

/**
 * Non-dismissable disclosure for backend-owned synthetic tenant data.
 *
 * Callers must render this component only after the authenticated backend
 * reports both `seeded` and `is_demo_tenant`. Frontend environment variables
 * are intentionally not accepted as inputs.
 */
export function DemoTenantBanner({
  tenantName,
  datasetVersion,
}: DemoTenantBannerProps) {
  return (
    <div
      role="status"
      aria-label="Synthetic demo data"
      className="border-b border-warning/30 bg-warning/10 px-4 py-2 text-xs font-mono text-warning"
    >
      <GlyphIcon glyph="[!]" className="mr-1" />
      Demo tenant{tenantName ? `: ${tenantName}` : ''} — synthetic records were seeded into the
      backend{datasetVersion ? ` (${datasetVersion})` : ''}.
    </div>
  );
}
