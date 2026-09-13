"""Aether Identity Resolution Service — deterministic + probabilistic identity matching."""
from .engine import IdentityResolutionEngine
from .rules import ResolutionRulesEngine, ResolutionConfig
from .signals import ResolutionSignal

__all__ = ["IdentityResolutionEngine", "ResolutionRulesEngine", "ResolutionConfig", "ResolutionSignal"]
