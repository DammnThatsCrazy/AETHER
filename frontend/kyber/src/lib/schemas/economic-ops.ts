/**
 * KYBER schemas — economic & interoperability intelligence ops surfaces.
 *
 * The backend admin routers (/v1/admin/kyber/{stablecoins,derivatives,interop})
 * return raw `{items, count}` payloads (no APIResponse envelope). Rows are
 * loosely typed with passthrough: the operator surfaces render observed
 * facts verbatim and must not drop provider-specific fields.
 */
import { z } from 'zod';

export const opsRowSchema = z.record(z.string(), z.unknown());

export const opsListSchema = z.object({
  items: z.array(opsRowSchema),
  count: z.number(),
});

export const adapterDescriptorSchema = z.object({
  implementation_status: z.string(),
}).passthrough();

export const adapterFleetSchema = z.object({
  items: z.array(adapterDescriptorSchema),
  count: z.number(),
});

export const stablecoinRegistryStatusSchema = z.object({
  asset_count: z.number(),
  deployment_count: z.number(),
}).passthrough();

export const interopCorrelationHealthSchema = z.object({
  message_count: z.number(),
  out_of_order_discoveries: z.number(),
  uncorrelated_messages: z.number(),
  by_status: z.record(z.string(), z.number()),
}).passthrough();

export type OpsRow = z.infer<typeof opsRowSchema>;
