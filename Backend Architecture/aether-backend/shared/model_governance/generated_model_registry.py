# DO NOT EDIT — generated from packages/shared/contracts/model-registry.json
# Run: python scripts/generate_platform_contracts.py
"""Generated model-harness catalog (providers, capabilities, cost, aliases, models)."""

from __future__ import annotations

from typing import Any

MODEL_REGISTRY_VERSION = "1.0.0"

# Providers registered with the harness.
MODEL_REGISTRY_PROVIDERS: tuple[str, ...] = ("anthropic", "openai", "kimi", "deepseek", "qwen")

# Capability flags that drive adapter behavior.
MODEL_REGISTRY_CAPABILITIES: tuple[str, ...] = (
    "chat",
    "tool_use",
    "streaming",
    "structured_outputs",
    "vision",
    "thinking",
)

# Thinking modes a model may support.
MODEL_REGISTRY_THINKING_MODES: tuple[str, ...] = ("adaptive", "enabled", "disabled")

# Effort ladder a model may support.
MODEL_REGISTRY_EFFORT_LEVELS: tuple[str, ...] = ("low", "medium", "high", "xhigh", "max")

# Lifecycle status of a registered model.
MODEL_REGISTRY_MODEL_STATUSES: tuple[str, ...] = (
    "recommended",
    "stable",
    "beta",
    "deprecated",
    "experimental",
)

# Alias -> canonical modelId.
MODEL_REGISTRY_ALIASES: dict[str, str] = {
    "claude-haiku-4-5": "claude-haiku-4-5-20251001",
}

# Canonical model catalog (JSON file order).
MODEL_REGISTRY_MODELS: tuple[dict[str, Any], ...] = (
    {
        "modelId": "claude-opus-5",
        "provider": "anthropic",
        "family": "claude",
        "contextWindowTokens": 1000000,
        "maxOutputTokens": 128000,
        "capabilities": ("chat", "tool_use", "streaming", "structured_outputs", "vision", "thinking"),
        "thinkingModes": ("adaptive", "disabled"),
        "effortLevels": ("low", "medium", "high", "xhigh", "max"),
        "samplingParamsSupported": False,
        "inputCostPerMTok": 5.0,
        "outputCostPerMTok": 25.0,
        "status": "recommended",
        "notes": "adaptive thinking default; sampling params rejected (400); effort ladder low–max; structured outputs; use output_config.effort.",
    },
    {
        "modelId": "claude-sonnet-5",
        "provider": "anthropic",
        "family": "claude",
        "contextWindowTokens": 1000000,
        "maxOutputTokens": 128000,
        "capabilities": ("chat", "tool_use", "streaming", "structured_outputs", "vision", "thinking"),
        "thinkingModes": ("adaptive", "disabled"),
        "effortLevels": ("low", "medium", "high", "xhigh", "max"),
        "samplingParamsSupported": False,
        "inputCostPerMTok": 3.0,
        "outputCostPerMTok": 15.0,
        "status": "recommended",
        "notes": "adaptive default; intro pricing $2/$10 through 2026-08-31; sampling params rejected.",
    },
    {
        "modelId": "claude-haiku-4-5-20251001",
        "provider": "anthropic",
        "family": "claude",
        "contextWindowTokens": 200000,
        "maxOutputTokens": 64000,
        "capabilities": ("chat", "tool_use", "streaming", "structured_outputs", "vision", "thinking"),
        "thinkingModes": ("adaptive", "enabled", "disabled"),
        "effortLevels": ("low", "medium", "high"),
        "samplingParamsSupported": True,
        "inputCostPerMTok": 1.0,
        "outputCostPerMTok": 5.0,
        "status": "recommended",
        "notes": "legacy sampling params accepted; full dated ID (alias claude-haiku-4-5 -> this ID). This is the current Noesis default model.",
    },
    {
        "modelId": "claude-fable-5",
        "provider": "anthropic",
        "family": "claude",
        "contextWindowTokens": 1000000,
        "maxOutputTokens": 128000,
        "capabilities": ("chat", "tool_use", "streaming", "structured_outputs", "vision", "thinking"),
        "thinkingModes": ("adaptive", "disabled"),
        "effortLevels": ("low", "medium", "high", "xhigh", "max"),
        "samplingParamsSupported": False,
        "inputCostPerMTok": 10.0,
        "outputCostPerMTok": 50.0,
        "status": "stable",
        "notes": "adaptive default; sampling params rejected.",
    },
    {
        "modelId": "claude-opus-4-8",
        "provider": "anthropic",
        "family": "claude",
        "contextWindowTokens": 1000000,
        "maxOutputTokens": 128000,
        "capabilities": ("chat", "tool_use", "streaming", "structured_outputs", "vision", "thinking"),
        "thinkingModes": ("adaptive", "disabled"),
        "effortLevels": ("low", "medium", "high"),
        "samplingParamsSupported": False,
        "inputCostPerMTok": 5.0,
        "outputCostPerMTok": 25.0,
        "status": "stable",
        "notes": "adaptive default; sampling params rejected.",
    },
    {
        "modelId": "claude-sonnet-4-6",
        "provider": "anthropic",
        "family": "claude",
        "contextWindowTokens": 1000000,
        "maxOutputTokens": 128000,
        "capabilities": ("chat", "tool_use", "streaming", "structured_outputs", "vision", "thinking"),
        "thinkingModes": ("adaptive", "disabled"),
        "effortLevels": ("low", "medium", "high"),
        "samplingParamsSupported": False,
        "inputCostPerMTok": 3.0,
        "outputCostPerMTok": 15.0,
        "status": "stable",
        "notes": "adaptive default; sampling params rejected.",
    },
    {
        "modelId": "gpt-4o-mini",
        "provider": "openai",
        "family": "gpt",
        "contextWindowTokens": 128000,
        "maxOutputTokens": 16384,
        "capabilities": ("chat", "tool_use", "streaming", "structured_outputs", "vision"),
        "thinkingModes": (),
        "effortLevels": (),
        "samplingParamsSupported": True,
        "inputCostPerMTok": 0.15,
        "outputCostPerMTok": 0.6,
        "status": "recommended",
        "notes": "current Noesis OpenAI default model.",
    },
    {
        "modelId": "gpt-4o",
        "provider": "openai",
        "family": "gpt",
        "contextWindowTokens": 128000,
        "maxOutputTokens": 16384,
        "capabilities": ("chat", "tool_use", "streaming", "structured_outputs", "vision"),
        "thinkingModes": (),
        "effortLevels": (),
        "samplingParamsSupported": True,
        "inputCostPerMTok": 2.5,
        "outputCostPerMTok": 10.0,
        "status": "stable",
        "notes": "no thinking mode; sampling params supported.",
    },
    {
        "modelId": "gpt-4.1",
        "provider": "openai",
        "family": "gpt",
        "contextWindowTokens": 1000000,
        "maxOutputTokens": 32768,
        "capabilities": ("chat", "tool_use", "streaming", "structured_outputs"),
        "thinkingModes": (),
        "effortLevels": (),
        "samplingParamsSupported": True,
        "inputCostPerMTok": 2.0,
        "outputCostPerMTok": 8.0,
        "status": "stable",
        "notes": "no thinking mode; sampling params supported.",
    },
    {
        "modelId": "gpt-4.1-mini",
        "provider": "openai",
        "family": "gpt",
        "contextWindowTokens": 1000000,
        "maxOutputTokens": 32768,
        "capabilities": ("chat", "tool_use", "streaming", "structured_outputs"),
        "thinkingModes": (),
        "effortLevels": (),
        "samplingParamsSupported": True,
        "inputCostPerMTok": 0.4,
        "outputCostPerMTok": 1.6,
        "status": "stable",
        "notes": "no thinking mode; sampling params supported.",
    },
    {
        "modelId": "kimi-k2",
        "provider": "kimi",
        "family": "kimi",
        "contextWindowTokens": 262144,
        "maxOutputTokens": 32768,
        "capabilities": ("chat", "tool_use", "streaming", "structured_outputs", "vision"),
        "thinkingModes": ("disabled",),
        "effortLevels": (),
        "samplingParamsSupported": True,
        "inputCostPerMTok": 0.6,
        "outputCostPerMTok": 2.5,
        "status": "experimental",
        "notes": "OpenAI-compatible; runs via OpenAICompatibleModelProvider (MODEL_RUNTIME_COMPAT_*).",
    },
    {
        "modelId": "deepseek-chat",
        "provider": "deepseek",
        "family": "deepseek",
        "contextWindowTokens": 131072,
        "maxOutputTokens": 8192,
        "capabilities": ("chat", "streaming", "tool_use", "structured_outputs"),
        "thinkingModes": ("disabled",),
        "effortLevels": (),
        "samplingParamsSupported": True,
        "inputCostPerMTok": 0.27,
        "outputCostPerMTok": 1.1,
        "status": "experimental",
        "notes": "OpenAI-compatible chat API; via OpenAICompatibleModelProvider.",
    },
    {
        "modelId": "qwen2.5-72b-instruct",
        "provider": "qwen",
        "family": "qwen",
        "contextWindowTokens": 131072,
        "maxOutputTokens": 8192,
        "capabilities": ("chat", "streaming", "tool_use"),
        "thinkingModes": ("disabled",),
        "effortLevels": (),
        "samplingParamsSupported": True,
        "inputCostPerMTok": 0.0,
        "outputCostPerMTok": 0.0,
        "status": "experimental",
        "notes": "Open-weight; self-host via vLLM/TGI OpenAI-compatible server; cost 0 is self-host.",
    },
)

__all__ = [
    "MODEL_REGISTRY_VERSION",
    "MODEL_REGISTRY_PROVIDERS",
    "MODEL_REGISTRY_CAPABILITIES",
    "MODEL_REGISTRY_THINKING_MODES",
    "MODEL_REGISTRY_EFFORT_LEVELS",
    "MODEL_REGISTRY_MODEL_STATUSES",
    "MODEL_REGISTRY_ALIASES",
    "MODEL_REGISTRY_MODELS",
]
