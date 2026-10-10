"""Versioned, safety-checked system-prompt loading for task profiles.

ADR-008: task profiles bind a model role (planning / reasoning /
classification / synthesis / summarization / extraction) to a system prompt.
This module loads those prompts versioned, validates them against
prompt-injection and secret-leak patterns, and renders them with an
allowlist-only placeholder substitution.

Security contract — the last line of defense against prompt-injection via
templates:

* :class:`PromptCatalog` serves versioned prompt text keyed
  ``role -> version -> text``.
* :class:`PromptSafety.validate` rejects system-override tokens, embedded
  ``<script>``, and secret placeholders (``{api_key}`` / ``{secret}`` /
  ``{credential}`` / ``{token}``), and requires a non-empty prompt.
* :class:`PromptRenderer.render` refuses ANY placeholder outside
  ``ALLOWED_PLACEHOLDERS`` (``{tenant}`` / ``{task}`` / ``{instructions}``),
  raising :class:`PromptInjectionError`, so callers can never interpolate
  credentials or PII into a rendered prompt.

Prompts must never embed tenant PII, credentials, or instructions that would
let a model bypass guardrails.
"""

from __future__ import annotations

import re
from collections.abc import Mapping

ALLOWED_PLACEHOLDERS: tuple[str, ...] = ("{tenant}", "{task}", "{instructions}")

# System-override / guardrail-bypass tokens that must never appear verbatim in
# a system prompt (matched case-insensitively).
_FORBIDDEN_SYSTEM_OVERRIDE_TOKENS: tuple[str, ...] = (
    "ignore previous instructions",
    "<|sys|>",
    "system prompt:",
    "jailbreak",
)

_FORBIDDEN_SCRIPT_TAG = "<script>"

# Placeholder patterns a caller could use to leak a secret into a rendered
# prompt (matched case-insensitively).
_FORBIDDEN_SECRET_PLACEHOLDERS: tuple[str, ...] = (
    "{api_key}",
    "{secret}",
    "{credential}",
    "{token}",
)

# Any "{...}" placeholder in a prompt template (used by the renderer to reject
# non-allowlisted placeholders).
_PLACEHOLDER_RE = re.compile(r"\{[^{}]*\}")


class PromptCatalog:
    """Versioned system-prompt catalog keyed ``role -> version -> text``.

    The default catalog ships a baseline prompt (version 1) for each of the
    six ADR-008 model roles. A custom catalog may be supplied as a mapping of
    ``role -> {version: prompt_text}``; it is copied so later mutation of the
    caller's mapping cannot change this catalog.
    """

    _DEFAULT_PROMPTS: Mapping[str, Mapping[int, str]] = {
        "planning": {
            1: (
                "You plan read-only queries against governed data sources. You "
                "never write, mutate, or deploy changes; you propose a safe, "
                "allowlisted query plan and stop before executing anything."
            ),
        },
        "reasoning": {
            1: (
                "You reason step by step from the provided evidence only, state "
                "assumptions explicitly, and mark any conclusion you cannot "
                "support from the evidence as uncertain."
            ),
        },
        "classification": {
            1: (
                "You classify the input into one of the predefined categories, "
                "using only the category definitions provided, and return the "
                "category label with a one-line justification."
            ),
        },
        "synthesis": {
            1: (
                "You synthesize the provided evidence into a coherent, grounded "
                "answer, cite the evidence you rely on, and clearly separate "
                "established facts from interpretation."
            ),
        },
        "summarization": {
            1: (
                "You summarize the source material faithfully, preserving key "
                "facts and figures, keeping the author's intent, and omitting "
                "no information that materially changes the meaning."
            ),
        },
        "extraction": {
            1: (
                "You extract structured facts from the provided text into the "
                "requested schema, quoting source text verbatim where required, "
                "and skipping fields that are absent rather than inventing "
                "values."
            ),
        },
    }

    def __init__(
        self, prompts: Mapping[str, Mapping[str, str]] | None = None
    ) -> None:
        source = prompts if prompts is not None else self._DEFAULT_PROMPTS
        self._prompts: dict[str, dict[str, str]] = {
            role: dict(versions) for role, versions in source.items()
        }

    def get(self, role: str, version: int = 1) -> str:
        """Return the prompt text for ``role`` at ``version``.

        Raises :class:`KeyError` when the role is unknown or the version is not
        present for that role.
        """
        if role not in self._prompts:
            raise KeyError(role)
        versions = self._prompts[role]
        if version not in versions:
            raise KeyError((role, version))
        return versions[version]

    def roles(self) -> tuple[str, ...]:
        """Return the catalog's role names in insertion order."""
        return tuple(self._prompts)


class PromptSafety:
    """Static checks for dangerous or leak-prone prompt templates."""

    @staticmethod
    def validate(prompt: str) -> list[str]:
        """Return the list of violation reasons; empty list means safe.

        Rejects: system-override tokens, embedded ``<script>``, secret
        placeholders, and empty prompts.
        """
        violations: list[str] = []
        lowered = prompt.lower()
        for token in _FORBIDDEN_SYSTEM_OVERRIDE_TOKENS:
            if token in lowered:
                violations.append(f"forbidden system-override token: {token!r}")
        if _FORBIDDEN_SCRIPT_TAG in lowered:
            violations.append("forbidden embedded script tag: '<script>'")
        for placeholder in _FORBIDDEN_SECRET_PLACEHOLDERS:
            if placeholder in lowered:
                violations.append(f"forbidden secret placeholder: {placeholder}")
        if not prompt.strip():
            violations.append("empty prompt")
        return violations


class PromptInjectionError(Exception):
    """Raised when a prompt template contains a placeholder outside the allowlist.

    Raised by :meth:`PromptRenderer.render` so callers can never interpolate
    credentials, PII, or arbitrary content into a rendered system prompt.
    """


class PromptRenderer:
    """Renders prompt templates with allowlist-only placeholder substitution.

    Only ``ALLOWED_PLACEHOLDERS`` (``{tenant}`` / ``{task}`` /
    ``{instructions}``) may appear in a template. Any other ``{...}``
    placeholder raises :class:`PromptInjectionError` before any substitution
    happens, so a template can never smuggle a secret placeholder (for
    example ``{api_key}``) into a rendered prompt even when the render
    arguments are otherwise safe.
    """

    @staticmethod
    def render(
        prompt: str,
        *,
        tenant: str | None = None,
        task: str | None = None,
        instructions: str | None = None,
    ) -> str:
        """Substitute the allowed placeholders, leaving unprovided ones intact.

        Raises :class:`PromptInjectionError` if the prompt contains any
        ``{...}`` placeholder outside ``ALLOWED_PLACEHOLDERS``.
        """
        for match in _PLACEHOLDER_RE.finditer(prompt):
            if match.group(0) not in ALLOWED_PLACEHOLDERS:
                raise PromptInjectionError(
                    f"forbidden placeholder {match.group(0)!r} in prompt template"
                )
        rendered = prompt
        if tenant is not None:
            rendered = rendered.replace("{tenant}", tenant)
        if task is not None:
            rendered = rendered.replace("{task}", task)
        if instructions is not None:
            rendered = rendered.replace("{instructions}", instructions)
        return rendered


__all__ = [
    "ALLOWED_PLACEHOLDERS",
    "PromptCatalog",
    "PromptInjectionError",
    "PromptRenderer",
    "PromptSafety",
]
