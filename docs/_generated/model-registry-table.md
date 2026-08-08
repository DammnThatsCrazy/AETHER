<!-- DO NOT EDIT — generated from packages/shared/contracts/model-registry.json -->
<!-- Run: python scripts/generate_platform_contracts.py -->

# Model Registry

Contract version: `1.0.0`

Canonical catalog of harness LLM models — availability, capability flags, cost, and lifecycle status.

| Model | Provider | Context | Max output | Input $/MTok | Output $/MTok | Status | Capabilities |
|---|---|---|---|---|---|---|---|
| `claude-opus-5` | anthropic | 1000000 | 128000 | 5.0 | 25.0 | recommended | `chat`, `tool_use`, `streaming`, `structured_outputs`, `vision`, `thinking` |
| `claude-sonnet-5` | anthropic | 1000000 | 128000 | 3.0 | 15.0 | recommended | `chat`, `tool_use`, `streaming`, `structured_outputs`, `vision`, `thinking` |
| `claude-haiku-4-5-20251001` | anthropic | 200000 | 64000 | 1.0 | 5.0 | recommended | `chat`, `tool_use`, `streaming`, `structured_outputs`, `vision`, `thinking` |
| `claude-fable-5` | anthropic | 1000000 | 128000 | 10.0 | 50.0 | stable | `chat`, `tool_use`, `streaming`, `structured_outputs`, `vision`, `thinking` |
| `claude-opus-4-8` | anthropic | 1000000 | 128000 | 5.0 | 25.0 | stable | `chat`, `tool_use`, `streaming`, `structured_outputs`, `vision`, `thinking` |
| `claude-sonnet-4-6` | anthropic | 1000000 | 128000 | 3.0 | 15.0 | stable | `chat`, `tool_use`, `streaming`, `structured_outputs`, `vision`, `thinking` |
| `gpt-4o-mini` | openai | 128000 | 16384 | 0.15 | 0.6 | recommended | `chat`, `tool_use`, `streaming`, `structured_outputs`, `vision` |
| `gpt-4o` | openai | 128000 | 16384 | 2.5 | 10.0 | stable | `chat`, `tool_use`, `streaming`, `structured_outputs`, `vision` |
| `gpt-4.1` | openai | 1000000 | 32768 | 2.0 | 8.0 | stable | `chat`, `tool_use`, `streaming`, `structured_outputs` |
| `gpt-4.1-mini` | openai | 1000000 | 32768 | 0.4 | 1.6 | stable | `chat`, `tool_use`, `streaming`, `structured_outputs` |
| `kimi-k2` | kimi | 262144 | 32768 | 0.6 | 2.5 | experimental | `chat`, `tool_use`, `streaming`, `structured_outputs`, `vision` |
| `deepseek-chat` | deepseek | 131072 | 8192 | 0.27 | 1.1 | experimental | `chat`, `streaming`, `tool_use`, `structured_outputs` |
| `qwen2.5-72b-instruct` | qwen | 131072 | 8192 | 0.0 | 0.0 | experimental | `chat`, `streaming`, `tool_use` |

## Aliases

- `claude-haiku-4-5` → `claude-haiku-4-5-20251001`
