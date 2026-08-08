/**
 * DO NOT EDIT — generated from packages/shared/contracts/model-registry.json
 * Run: python scripts/generate_platform_contracts.py
 */

export const modelRegistryVersion = '1.0.0' as const;

/** Providers registered with the harness. */
export const modelRegistryProviders = ['anthropic', 'openai'] as const;
export type ModelRegistryProvider = typeof modelRegistryProviders[number];

/** Capability flags that drive adapter behavior. */
export const modelRegistryCapabilities = [
  'chat',
  'tool_use',
  'streaming',
  'structured_outputs',
  'vision',
  'thinking',
] as const;
export type ModelRegistryCapability = typeof modelRegistryCapabilities[number];

/** Thinking modes a model may support. */
export const modelRegistryThinkingModes = ['adaptive', 'enabled', 'disabled'] as const;
export type ModelRegistryThinkingMode = typeof modelRegistryThinkingModes[number];

/** Effort ladder a model may support. */
export const modelRegistryEffortLevels = ['low', 'medium', 'high', 'xhigh', 'max'] as const;
export type ModelRegistryEffortLevel = typeof modelRegistryEffortLevels[number];

/** Lifecycle status of a registered model. */
export const modelRegistryModelStatuses = ['recommended', 'stable', 'beta', 'deprecated'] as const;
export type ModelRegistryModelStatus = typeof modelRegistryModelStatuses[number];

/** Alias → canonical modelId. */
export const modelRegistryAliases: Record<string, string> = {
  'claude-haiku-4-5': 'claude-haiku-4-5-20251001',
};

/** Canonical model catalog (JSON file order). */
export const modelRegistryModels = [
  {
    modelId: 'claude-opus-5',
    provider: 'anthropic',
    family: 'claude',
    contextWindowTokens: 1000000,
    maxOutputTokens: 128000,
    capabilities: ['chat', 'tool_use', 'streaming', 'structured_outputs', 'vision', 'thinking'],
    thinkingModes: ['adaptive', 'disabled'],
    effortLevels: ['low', 'medium', 'high', 'xhigh', 'max'],
    samplingParamsSupported: false,
    inputCostPerMTok: 5.0,
    outputCostPerMTok: 25.0,
    status: 'recommended',
    notes: 'adaptive thinking default; sampling params rejected (400); effort ladder low–max; structured outputs; use output_config.effort.',
  },
  {
    modelId: 'claude-sonnet-5',
    provider: 'anthropic',
    family: 'claude',
    contextWindowTokens: 1000000,
    maxOutputTokens: 128000,
    capabilities: ['chat', 'tool_use', 'streaming', 'structured_outputs', 'vision', 'thinking'],
    thinkingModes: ['adaptive', 'disabled'],
    effortLevels: ['low', 'medium', 'high', 'xhigh', 'max'],
    samplingParamsSupported: false,
    inputCostPerMTok: 3.0,
    outputCostPerMTok: 15.0,
    status: 'recommended',
    notes: 'adaptive default; intro pricing $2/$10 through 2026-08-31; sampling params rejected.',
  },
  {
    modelId: 'claude-haiku-4-5-20251001',
    provider: 'anthropic',
    family: 'claude',
    contextWindowTokens: 200000,
    maxOutputTokens: 64000,
    capabilities: ['chat', 'tool_use', 'streaming', 'structured_outputs', 'vision', 'thinking'],
    thinkingModes: ['adaptive', 'enabled', 'disabled'],
    effortLevels: ['low', 'medium', 'high'],
    samplingParamsSupported: true,
    inputCostPerMTok: 1.0,
    outputCostPerMTok: 5.0,
    status: 'recommended',
    notes: 'legacy sampling params accepted; full dated ID (alias claude-haiku-4-5 -> this ID). This is the current Noesis default model.',
  },
  {
    modelId: 'claude-fable-5',
    provider: 'anthropic',
    family: 'claude',
    contextWindowTokens: 1000000,
    maxOutputTokens: 128000,
    capabilities: ['chat', 'tool_use', 'streaming', 'structured_outputs', 'vision', 'thinking'],
    thinkingModes: ['adaptive', 'disabled'],
    effortLevels: ['low', 'medium', 'high', 'xhigh', 'max'],
    samplingParamsSupported: false,
    inputCostPerMTok: 10.0,
    outputCostPerMTok: 50.0,
    status: 'stable',
    notes: 'adaptive default; sampling params rejected.',
  },
  {
    modelId: 'claude-opus-4-8',
    provider: 'anthropic',
    family: 'claude',
    contextWindowTokens: 1000000,
    maxOutputTokens: 128000,
    capabilities: ['chat', 'tool_use', 'streaming', 'structured_outputs', 'vision', 'thinking'],
    thinkingModes: ['adaptive', 'disabled'],
    effortLevels: ['low', 'medium', 'high'],
    samplingParamsSupported: false,
    inputCostPerMTok: 5.0,
    outputCostPerMTok: 25.0,
    status: 'stable',
    notes: 'adaptive default; sampling params rejected.',
  },
  {
    modelId: 'claude-sonnet-4-6',
    provider: 'anthropic',
    family: 'claude',
    contextWindowTokens: 1000000,
    maxOutputTokens: 128000,
    capabilities: ['chat', 'tool_use', 'streaming', 'structured_outputs', 'vision', 'thinking'],
    thinkingModes: ['adaptive', 'disabled'],
    effortLevels: ['low', 'medium', 'high'],
    samplingParamsSupported: false,
    inputCostPerMTok: 3.0,
    outputCostPerMTok: 15.0,
    status: 'stable',
    notes: 'adaptive default; sampling params rejected.',
  },
  {
    modelId: 'gpt-4o-mini',
    provider: 'openai',
    family: 'gpt',
    contextWindowTokens: 128000,
    maxOutputTokens: 16384,
    capabilities: ['chat', 'tool_use', 'streaming', 'structured_outputs', 'vision'],
    thinkingModes: [],
    effortLevels: [],
    samplingParamsSupported: true,
    inputCostPerMTok: 0.15,
    outputCostPerMTok: 0.6,
    status: 'recommended',
    notes: 'current Noesis OpenAI default model.',
  },
  {
    modelId: 'gpt-4o',
    provider: 'openai',
    family: 'gpt',
    contextWindowTokens: 128000,
    maxOutputTokens: 16384,
    capabilities: ['chat', 'tool_use', 'streaming', 'structured_outputs', 'vision'],
    thinkingModes: [],
    effortLevels: [],
    samplingParamsSupported: true,
    inputCostPerMTok: 2.5,
    outputCostPerMTok: 10.0,
    status: 'stable',
    notes: 'no thinking mode; sampling params supported.',
  },
  {
    modelId: 'gpt-4.1',
    provider: 'openai',
    family: 'gpt',
    contextWindowTokens: 1000000,
    maxOutputTokens: 32768,
    capabilities: ['chat', 'tool_use', 'streaming', 'structured_outputs'],
    thinkingModes: [],
    effortLevels: [],
    samplingParamsSupported: true,
    inputCostPerMTok: 2.0,
    outputCostPerMTok: 8.0,
    status: 'stable',
    notes: 'no thinking mode; sampling params supported.',
  },
  {
    modelId: 'gpt-4.1-mini',
    provider: 'openai',
    family: 'gpt',
    contextWindowTokens: 1000000,
    maxOutputTokens: 32768,
    capabilities: ['chat', 'tool_use', 'streaming', 'structured_outputs'],
    thinkingModes: [],
    effortLevels: [],
    samplingParamsSupported: true,
    inputCostPerMTok: 0.4,
    outputCostPerMTok: 1.6,
    status: 'stable',
    notes: 'no thinking mode; sampling params supported.',
  },
] as const;
