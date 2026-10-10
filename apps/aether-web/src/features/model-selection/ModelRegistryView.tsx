import type { ModelRegistryModel } from './types';

export type ModelStatus = ModelRegistryModel['status'];

/**
 * Read-only tenant view of the model registry (ADR-008 D9).
 *
 * Purely informational: which models exist, their provider, status,
 * capabilities, and display-only cost. This component never mutates the
 * registry and never renders credentials — only plain display strings.
 */
export const MODEL_STATUS_CLASS: Record<ModelStatus, string> = {
  recommended: 'bg-emerald-100 text-emerald-800 border-emerald-200',
  stable: 'bg-blue-100 text-blue-800 border-blue-200',
  beta: 'bg-amber-100 text-amber-800 border-amber-200',
  deprecated: 'bg-gray-200 text-gray-600 border-gray-300',
  experimental: 'bg-purple-100 text-purple-800 border-purple-200',
};

export interface ModelRegistryViewProps {
  models: ModelRegistryModel[];
}

/** Display-only cost: cost per 1M tokens, rendered as currency. */
function formatCost(costPerMTok: number): string {
  return `$${costPerMTok.toFixed(2)}/MTok`;
}

export function ModelRegistryView({ models }: ModelRegistryViewProps) {
  if (models.length === 0) {
    return (
      <div
        className="py-12 text-center text-sm text-text-muted"
        data-testid="model-registry-empty"
      >
        No models registered
      </div>
    );
  }

  // Group by provider, preserving first-seen order.
  const byProvider = new Map<string, ModelRegistryModel[]>();
  for (const model of models) {
    const group = byProvider.get(model.provider) ?? [];
    group.push(model);
    byProvider.set(model.provider, group);
  }

  return (
    <div className="space-y-6" data-testid="model-registry">
      {Array.from(byProvider.entries()).map(([provider, providerModels]) => (
        <section
          key={provider}
          className="model-registry-group"
          data-testid={`provider-group-${provider}`}
        >
          <h2 className="mb-2 text-sm font-semibold uppercase tracking-wide text-text-muted">
            {provider}
          </h2>
          <table className="w-full text-sm">
            <thead>
              <tr className="text-left text-text-muted">
                <th className="py-2 pr-3">Model</th>
                <th className="py-2 pr-3">Provider</th>
                <th className="py-2 pr-3">Status</th>
                <th className="py-2 pr-3">Capabilities</th>
                <th className="py-2">Cost</th>
              </tr>
            </thead>
            <tbody>
              {providerModels.map((model) => (
                <tr
                  key={model.modelId}
                  className="border-t border-border"
                  data-testid={`model-row-${model.modelId}`}
                >
                  <td className="py-2 pr-3 font-mono">{model.modelId}</td>
                  <td className="py-2 pr-3">{model.provider}</td>
                  <td className="py-2 pr-3">
                    <span
                      className={`status-badge status-badge--${model.status} inline-block rounded-full border px-2 py-0.5 text-xs ${
                        MODEL_STATUS_CLASS[model.status] ?? ''
                      }`}
                      data-testid={`status-badge--${model.status}`}
                    >
                      {model.status}
                    </span>
                  </td>
                  <td className="py-2 pr-3">
                    <ul className="flex flex-wrap gap-1">
                      {model.capabilities.map((capability) => (
                        <li
                          key={capability}
                          className="rounded bg-surface-secondary px-2 py-0.5 text-xs"
                          data-testid={`capability-${capability}`}
                        >
                          {capability}
                        </li>
                      ))}
                    </ul>
                  </td>
                  <td className="py-2 font-mono">
                    <div className="flex items-center gap-1">
                      <span>{formatCost(model.inputCostPerMTok)}</span>
                      <span className="text-xs text-text-muted">in</span>
                    </div>
                    <div className="flex items-center gap-1">
                      <span>{formatCost(model.outputCostPerMTok)}</span>
                      <span className="text-xs text-text-muted">out</span>
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </section>
      ))}
    </div>
  );
}

export default ModelRegistryView;
