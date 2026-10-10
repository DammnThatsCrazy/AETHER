"""Real transport adapters for the model-runtime (provider SDKs stay here)."""
from intelligence.model_runtime.adapters.anthropic import AnthropicModelProvider
from intelligence.model_runtime.adapters.openai import OpenAIModelProvider

__all__ = ["AnthropicModelProvider", "OpenAIModelProvider"]
